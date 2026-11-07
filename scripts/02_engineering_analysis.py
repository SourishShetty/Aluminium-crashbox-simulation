"""Analyse the five retained crash-box simulations.

Run from the project root:
    python scripts/02_engineering_analysis.py

Requires NumPy and Matplotlib. Reads Script 1 outputs from
results/processed/<design>/ and solver inventories from data/<design>/.
Writes metrics, figures and a provenance manifest to a new timestamp folder.
"""
from pathlib import Path
from datetime import datetime, timezone
import csv
import hashlib
import json
import re

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parent.parent
DESIGNS = ["Baseline_5mm", "D12_Position15_3mm", "D16_Position15_3mm",
           "D12_Position30_3mm", "D12_Position13_3mm"]
LABELS = ["Baseline (5 mm)", "D12 / Pos15", "D16 / Pos15",
          "D12 / Pos30", "D12 / Pos13"]
STROKE = 80.0  # Common comparison stroke, mm
WINDOW = 11  # Fixed across designs; exploratory moving average, not a standard filter
NATIVE_MASS_TO_KG = 1000.0  # N-mm-s consistent mass unit is tonne
NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[EeDd][-+]?\d+)?"


def write_csv(path, rows):
    keys = list(dict.fromkeys(k for row in rows for k in row))
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=keys)
        writer.writeheader()
        writer.writerows(rows)


def load_csv(path):
    with path.open(newline="", encoding="utf-8-sig") as file:
        rows = list(csv.DictReader(file))
    if len(rows) < 2:
        raise ValueError(f"Insufficient records: {path}")
    data = {k: np.array([float(r[k]) for r in rows]) for k in rows[0]}
    if any(not np.isfinite(v).all() for v in data.values()):
        raise ValueError(f"Non-finite values: {path}")
    if np.any(np.diff(data["time_s"]) <= 0):
        raise ValueError(f"Non-increasing times: {path}")
    return data


def solver_inventory(path):
    text = path.read_text(errors="replace")
    def value(pattern):
        hits = re.findall(pattern, text, re.I)
        if len(hits) != 1:
            raise ValueError(f"Expected one solver inventory value: {pattern}")
        return float(hits[0].replace("D", "E").replace("d", "e"))
    # Restrict mass extraction to the explicitly identified part-1 block.
    part = re.search(r"m a s s\s+p r o p e r t i e s\s+o f\s+p a r t # 1\s+"
                     r"total mass of part\s*=\s*(" + NUM + ")", text, re.I)
    if not part:
        raise ValueError("Cannot identify crash-box part-1 mass")
    box_mass = float(part.group(1).replace("D", "E")) * NATIVE_MASS_TO_KG
    return {
        "box_mass_kg": box_mass,
        "moving_mass_kg": value(r"mass of rigid body\s*=\s*(" + NUM + ")") * NATIVE_MASS_TO_KG,
        "solid_elements": int(value(r"total # of \*ELEMENT_SOLID\.+\s*(\d+)")),
        "shell_elements": int(value(r"total # of \*ELEMENT_SHELL_option\.+\s*(\d+)")),
    }


def integral(y, x):
    return float(np.sum((y[1:] + y[:-1]) * np.diff(x) / 2))


def common_stroke(t, x, f):
    """First forward passage; insert an interpolated endpoint at exactly 80 mm."""
    hits = np.flatnonzero(x >= STROKE)
    if not len(hits) or hits[0] == 0:
        raise ValueError("No usable first crossing of the comparison stroke")
    j = hits[0]
    if np.any(np.diff(x[:j+1]) < -1e-8):
        raise ValueError("Reversal before 80 mm; review before defining work")
    w = (STROKE-x[j-1])/(x[j]-x[j-1])
    return (np.r_[t[:j], t[j-1]+w*(t[j]-t[j-1])],
            np.r_[x[:j], STROKE], np.r_[f[:j], f[j-1]+w*(f[j]-f[j-1])])


# PART 7 — Engineering calculations
def analyse(design):
    folder = ROOT / "results" / "processed" / design
    force = load_csv(folder / "contact_force.csv")
    motion = load_csv(folder / "impactor_motion.csv")
    energy = load_csv(folder / "global_energy.csv")
    contact = load_csv(folder / "contact_energy.csv")
    diagnostic = json.loads((folder / "model_diagnostics.json").read_text())
    inventory = solver_inventory(ROOT / "data" / design / "d3hsp")
    if diagnostic["model_units"] != "NMM" or not diagnostic["normal_termination"]:
        raise ValueError(f"Unexpected units or termination: {design}")
    tf, tm = force["time_s"], motion["time_s"]
    if abs(tm[0]) > 1e-8 or abs(motion["displacement_z_mm"][0]) > 1e-6:
        raise ValueError("Expected motion history starting at zero displacement/time")
    mask = (tf >= tm[0]) & (tf <= tm[-1])
    t = tf[mask]
    f = force["compression_force_N"][mask]
    x = np.interp(t, tm, motion["travel_mm"])
    tc, xc, fc = common_stroke(t, x, f)
    if np.any(np.diff(t) <= 0) or len(t) < WINDOW:
        raise ValueError("Invalid force time base")
    dt = np.diff(t)
    if not np.allclose(dt, np.median(dt), rtol=0.02, atol=1e-9):
        raise ValueError("Irregular force sampling: review moving-average definition")
    smooth = np.convolve(force["compression_force_N"], np.ones(WINDOW)/WINDOW, mode="valid")
    smooth_time = tf[WINDOW//2:len(tf)-WINDOW//2]
    work = integral(fc, xc) / 1000  # N mm to J
    peak = float(np.max(force["compression_force_N"]))
    mean = work*1000/STROKE  # J -> N mm, then divide by mm
    k = int(np.argmax(force["compression_force_N"]))
    row = {
        "design": design, **inventory,
        "raw_PCF_kN": peak/1000, "raw_peak_time_ms": tf[k]*1000,
        "MA11_peak_kN": float(max(smooth))/1000,
        "MA11_span_ms": float(np.median(dt))*(WINDOW-1)*1000,
        "contact_work_80mm_J": work, "mean_contact_force_80mm_kN": mean/1000,
        "CFE_raw_80mm_percent": mean/peak*100,
        "SEA_contact_80mm_kJ_kg": work/inventory["box_mass_kg"]/1000,
        "max_impactor_travel_mm": float(max(motion["travel_mm"])),
        "impulse_to_80mm_Ns": integral(fc, tc),
        "initial_KE_J": energy["kinetic_energy_J"][0],
        "final_KE_J": energy["kinetic_energy_J"][-1],
        "final_internal_energy_J": energy["internal_energy_J"][-1],
        "final_sliding_energy_J": contact["sliding_energy_J"][-1],
        "final_eroded_internal_energy_J": energy["eroded_internal_energy_J"][-1],
        "final_energy_ratio": energy["total_energy_ratio"][-1],
        "max_energy_ratio_deviation_percent": float(max(abs(energy["total_energy_ratio"]-1)))*100,
        "failed_shells": diagnostic["failed_shell_count"],
        "mesh_note": "Unmatched 5 mm reference" if design == DESIGNS[0] else "3 mm variant; element deletion present",
    }
    for key in ("hourglass_energy_J", "eroded_kinetic_energy_J", "external_work_J"):
        if key in energy:
            row["final_"+key] = energy[key][-1]
    et = energy["time_s"]
    support = (et >= contact["time_s"][0]) & (et <= contact["time_s"][-1])
    contact_on_global = np.interp(et[support], contact["time_s"], contact["sliding_energy_J"])
    row["max_contact_global_energy_difference_J"] = float(max(abs(
        contact_on_global-energy["sliding_energy_J"][support])))
    return row, (t, x, f, tc, xc, fc, smooth_time, smooth, energy, contact, diagnostic)


# PART 8 — Compare against D12 / Position15 at the same nominal shell size
def comparisons(rows):
    reference = rows[1]
    columns = ("raw_PCF_kN", "MA11_peak_kN", "contact_work_80mm_J",
               "max_impactor_travel_mm", "SEA_contact_80mm_kJ_kg")
    return [{"design": row["design"], "reference": reference["design"],
             "comparison_scope": row["mesh_note"],
             **{key+"_change_percent": (row[key]/reference[key]-1)*100 for key in columns}}
            for row in rows]


# PART 9 — Engineering figures
def figures(out, histories, rows):
    plt.rcParams.update({"font.size": 10, "axes.grid": True, "grid.alpha": 0.25})
    def finish(fig, name):
        fig.tight_layout()
        fig.savefig(out/(name+".png"), dpi=220)
        fig.savefig(out/(name+".pdf"))
        plt.close(fig)
    fig, axes = plt.subplots(2, 1, figsize=(9, 8))
    for label, h in zip(LABELS, histories):
        t, x, f, tc, xc, fc, ts, fs, *_ = h
        axes[0].plot(t*1000, f/1000, label=label, lw=1)
        axes[1].plot(ts*1000, fs/1000, label=label, lw=1.3)
    for ax in axes:
        ax.set(xlabel="Time [ms]", ylabel="Compression force [kN]")
        ax.legend(fontsize=8)
    axes[0].set_title("Raw force histories")
    axes[1].set_title("11-sample moving average (exploratory; valid windows only)")
    finish(fig, "01_force_time")
    fig, ax = plt.subplots(figsize=(9, 5))
    for label, h in zip(LABELS, histories):
        ax.plot(h[4], h[5]/1000, label=label, lw=1)
    ax.set(xlabel="Impactor travel [mm]", ylabel="Compression force [kN]",
           title="First forward passage to 80 mm")
    ax.legend(fontsize=8)
    finish(fig, "02_force_travel_80mm")
    fig, axes = plt.subplots(5, 1, figsize=(9, 15))
    for ax, label, h in zip(axes, LABELS, histories):
        e = h[8]
        for key in ("kinetic_energy_J", "internal_energy_J", "sliding_energy_J",
                    "eroded_internal_energy_J"):
            ax.plot(e["time_s"]*1000, e[key], label=key.replace("_J", "").replace("_", " "))
        ax.set(title=label, xlabel="Time [ms]", ylabel="Energy [J]")
        ax.legend(fontsize=8, ncol=2)
    finish(fig, "03_energy_histories")
    fig, axes = plt.subplots(2, 2, figsize=(11, 8))
    fields = [("raw_PCF_kN", "Raw PCF [kN]"), ("contact_work_80mm_J", "Contact work at 80 mm [J]"),
              ("max_impactor_travel_mm", "Maximum impactor travel [mm]"), ("failed_shells", "Failed shells [count]")]
    for ax, (key, title) in zip(axes.flat, fields):
        ax.bar(range(5), [r[key] for r in rows], color=["#888888", "#0072B2", "#009E73", "#D55E00", "#CC79A7"])
        ax.set_xticks(range(5), LABELS, rotation=25, ha="right")
        ax.set_title(title)
    finish(fig, "04_design_comparison")


# PART 10 — Reproducible exports and stated limitations
def main():
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S_%fZ")
    out = ROOT / "results" / "engineering_analysis" / stamp
    out.mkdir(parents=True, exist_ok=False)
    rows, histories = [], []
    for design in DESIGNS:
        row, history = analyse(design)
        rows.append(row)
        histories.append(history)
        t, x, f, tc, xc, fc, *_ = history
        write_csv(out/(design+"_aligned.csv"), [
            {"time_s": a, "travel_mm": b, "compression_force_N": c} for a,b,c in zip(t,x,f)])
        cumulative = np.r_[0, np.cumsum((fc[1:]+fc[:-1])*np.diff(xc)/2000)]
        write_csv(out/(design+"_first80mm.csv"), [
            {"time_s": a, "travel_mm": b, "compression_force_N": c, "contact_work_J": d}
            for a,b,c,d in zip(tc,xc,fc,cumulative)])
        print(f"{design}: PCF={row['raw_PCF_kN']:.3f} kN; work80={row['contact_work_80mm_J']:.2f} J")
    write_csv(out/"engineering_metrics.csv", rows)
    write_csv(out/"comparison_vs_D12_Position15.csv", comparisons(rows))
    figures(out, histories, rows)
    sources = [
        ROOT / "scripts" / "01_process_simulation_data.py",
        Path(__file__).resolve(),
    ]
    for design in DESIGNS:
        raw_folder = ROOT / "data" / design
        processed_folder = ROOT / "results" / "processed" / design
        sources.extend(raw_folder / name for name in (
            "input.k", "d3hsp", "rcforc", "rbdout", "glstat", "sleout"
        ))
        sources.extend(processed_folder / name for name in (
            "contact_force.csv", "impactor_motion.csv", "global_energy.csv",
            "contact_energy.csv", "model_diagnostics.json"
        ))

    manifest = []
    for path in sources:
        manifest.append({
            "path": path.relative_to(ROOT).as_posix(),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    (out / "source_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    notes = """METHOD AND LIMITATIONS
Common stroke: first forward passage to 80 mm; interpolated endpoint.
Signed compression force = -SURFA interface 48 Fz; rigid impactor body 2.
Motion interpolated onto force times within overlapping time support only.
Contact work = integral(F dx)/1000 J; it is not pure plastic dissipation.
Mean force = work/80 mm; CFE uses raw full-history peak; SEA uses box mass only.
Masses and element counts come from d3hsp, not Script 1 line counts.
The N-mm-s mass unit is tonne; multiply by 1000 for kg.
11-sample moving average: fixed window, valid windows, no zero padding.
This is exploratory smoothing, not a standards-based crash-test filter.
Raw and smoothed peaks are reported separately. No design-specific filter tuning.
The baseline is 5 mm and the modified designs are 3 mm: no matched-mesh causal claim.
All modified designs contain element failures. No experimental validation or mesh convergence is demonstrated.
Global near-unity energy ratio alone does not establish numerical reliability.
No automatic winner is assigned. Review folding animations and numerical sensitivity.
"""
    (out/"method_and_limitations.txt").write_text(notes, encoding="utf-8")
    print("RESULT: 5/5 designs analysed. Review metrics, figures and limitations.")
    print("Results:", out)


if __name__ == "__main__":
    main()
