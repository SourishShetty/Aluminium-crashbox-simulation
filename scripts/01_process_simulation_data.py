"""Crash-box Phase 7: Parts 1–6, LS-DYNA ingestion and validation.

Put this file in CrashBox_Python_Analysis/scripts/ and run from the VS Code
project root with: python scripts/01_process_simulation_data.py

The code expects five folders in data/, each with six unchanged LS-DYNA files.
It never modifies raw input. It exports SI-normalized CSV and a QA report.
"""

# PART 1 — Project paths, configuration, file verification
from pathlib import Path
from collections import defaultdict
import csv
import json
import math
import re

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "results" / "processed"
REPORT = ROOT / "results" / "validation_report.csv"

DESIGNS = [
    "Baseline_5mm",
    "D12_Position15_3mm",
    "D16_Position15_3mm",
    "D12_Position30_3mm",
    "D12_Position13_3mm",
]
REQUIRED = ("rcforc", "rbdout", "glstat", "sleout", "d3hsp", "input.k")
# Confirmed for these saved models from the supplied LS-DYNA input decks.
EXPECTED_UNITS = "NMM"  # N, mm, s; energy = N*mm, velocity = mm/s
FORCE_INTERFACE = 48  # frictionless impactor/crash-box contact (not self-contact 38)
IMPACTOR_RIGID_BODY = 2
NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[EeDd][-+]?\d+)?"


def num(text):
    return float(text.replace("D", "E").replace("d", "e"))


def write_csv(destination, rows):
    if not rows:
        raise ValueError(f"No data parsed for {destination.name}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def validate_times(rows, label):
    times = [r["time_s"] for r in rows]
    if not times or any(not math.isfinite(t) or t < 0 for t in times):
        raise ValueError(f"{label}: missing/invalid times")
    if any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError(f"{label}: non-increasing/duplicated time entries")
    if not 0.028 <= times[-1] <= 0.031:
        raise ValueError(f"{label}: unexpected ending time {times[-1]:.7g} s")
    for row in rows:
        if any(isinstance(v, float) and not math.isfinite(v) for v in row.values()):
            raise ValueError(f"{label}: NaN or infinity encountered")
    return len(times)


# PART 2 — Contact-force history: rcforc (force N, time seconds)
# SURFA at interface 48 has negative Fz during compression.
RCFORC = re.compile(
    rf"^\s*SURFA\s+(\d+)\s+time\s+({NUM})\s+x\s+({NUM})"
    rf"\s+y\s+({NUM})\s+z\s+({NUM})", re.I
)


def read_rcforc(path):
    rows = []
    with path.open(errors="replace") as stream:
        for line in stream:
            match = RCFORC.search(line)
            if match and int(match.group(1)) == FORCE_INTERFACE:
                t, fx, fy, fz = (num(s) for s in match.groups()[1:])
                rows.append({
                    "time_s": t, "force_x_N": fx, "force_y_N": fy,
                    "force_z_N": fz, "compression_force_N": -fz,
                })
    validate_times(rows, "rcforc")
    if max(r["compression_force_N"] for r in rows) < 1000:
        raise ValueError("rcforc: unexpected contact force; check interface/axis")
    return rows


# PART 3 — Impactor motion: rbdout (displacement mm; velocity mm/s)
RBD_TIME = re.compile(rf"r\s*i\s*g\s*i\s*d\s+b\s*o\s*d\s*y\s+m\s*o\s*t\s*i\s*o\s*n.*?time\s*=\s*({NUM})", re.I)
RBD_BODY = re.compile(r"^\s*rigid body\s+(\d+)\s*$", re.I)


def read_rbdout(path):
    rows = []
    time = None
    body = None
    in_global = False
    disp = None
    vel = None
    with path.open(errors="replace") as stream:
        for line in stream:
            tm = RBD_TIME.search(line)
            if tm:
                if time is not None and disp is not None and vel is not None:
                    rows.append({"time_s": time, "displacement_z_mm": disp,
                                 "travel_mm": -disp, "velocity_z_mm_s": vel})
                time, body, in_global, disp, vel = num(tm.group(1)), None, False, None, None
                continue
            bm = RBD_BODY.match(line)
            if bm:
                body = int(bm.group(1))
                in_global = False
                continue
            if body != IMPACTOR_RIGID_BODY:
                continue
            if re.match(r"\s*global\s+x\s+y\s+z", line, re.I):
                in_global = True
                continue
            if "principal or user defined local" in line.lower():
                in_global = False
            if in_global and ("displacements:" in line or "velocities:" in line):
                values = re.findall(NUM, line.split(":", 1)[1])
                if len(values) >= 3:
                    if "displacements:" in line:
                        disp = num(values[2])
                    else:
                        vel = num(values[2])
    if time is not None and disp is not None and vel is not None:
        rows.append({"time_s": time, "displacement_z_mm": disp,
                     "travel_mm": -disp, "velocity_z_mm_s": vel})
    validate_times(rows, "rbdout")
    if abs(rows[0]["velocity_z_mm_s"] + 10000) > 100:
        raise ValueError("rbdout: impactor velocity not near -10,000 mm/s")
    return rows


# PART 4 — Energy histories: glstat and sleout (N*mm -> J)
GLSTAT_FIELDS = {
    "kinetic energy": "kinetic_energy_J",
    "internal energy": "internal_energy_J",
    "hourglass energy": "hourglass_energy_J",
    "sliding interface energy": "sliding_energy_J",
    "eroded internal energy": "eroded_internal_energy_J",
    "eroded kinetic energy": "eroded_kinetic_energy_J",
    "total energy": "total_energy_J",
    "external work": "external_work_J",
    "total energy / initial energy": "total_energy_ratio",
}
GL_PAIR = re.compile(rf"^\s*(.+?)\.{{2,}}\s*({NUM})\s*$")


def read_glstat(path):
    rows = []
    record = None
    with path.open(errors="replace") as stream:
        for line in stream:
            match = GL_PAIR.match(line)
            if not match:
                continue
            key = match.group(1).strip().lower()
            value = num(match.group(2))
            if key == "time":
                if record is not None:
                    rows.append(record)
                record = {"time_s": value}
            elif record is not None and key in GLSTAT_FIELDS:
                column = GLSTAT_FIELDS[key]
                record[column] = value if column == "total_energy_ratio" else value / 1000.0
    if record is not None:
        rows.append(record)
    required = {"time_s", "kinetic_energy_J", "internal_energy_J",
                "sliding_energy_J", "total_energy_J", "total_energy_ratio",
                "eroded_internal_energy_J"}
    if not rows or any(not required <= row.keys() for row in rows):
        raise ValueError("glstat: missing required energy fields")
    validate_times(rows, "glstat")
    if not 4500 <= rows[0]["kinetic_energy_J"] <= 5500:
        raise ValueError("glstat: initial KE not near 5000 J; verify units and mass")
    return rows


SLE_TIME = re.compile(rf"contact interface energy file,\s*time\s*=\s*({NUM})", re.I)
SLE_TOTAL = re.compile(rf"^\s*total energy\s*=\s*({NUM})", re.I)
SLE_FRICTION = re.compile(rf"friction energy\s*=\s*({NUM})", re.I)


def read_sleout(path):
    rows = []
    current = None
    with path.open(errors="replace") as stream:
        for line in stream:
            match = SLE_TIME.search(line)
            if match:
                if current is not None:
                    rows.append(current)
                current = {"time_s": num(match.group(1))}
                continue
            if current is None:
                continue
            match = SLE_TOTAL.search(line)
            if match:
                current["sliding_energy_J"] = num(match.group(1)) / 1000
            match = SLE_FRICTION.search(line)
            if match:
                current["friction_energy_J"] = num(match.group(1)) / 1000
    if current is not None:
        rows.append(current)
    if not rows or any("sliding_energy_J" not in r for r in rows):
        raise ValueError("sleout: missing sliding-interface energy summary")
    validate_times(rows, "sleout")
    return rows


# PART 5 — Diagnostic and model validation: d3hsp and input.k
FAIL = re.compile(rf"shell element\s+(\d+)\s+failed at time\s+({NUM})", re.I)


def read_d3hsp(path):
    text = path.read_text(errors="replace")
    failures = {}
    for element_id, failure_time in FAIL.findall(text):
        failures[int(element_id)] = min(failures.get(int(element_id), float("inf")),
                                        num(failure_time))
    if "*** termination time reached ***" not in text.lower():
        raise ValueError("d3hsp: expected normal end-time termination not found")
    return {
        "normal_termination": True,
        "failed_shell_count": len(failures),
        "failed_shell_elements": [
            {"element_id": eid, "failure_time_s": t}
            for eid, t in sorted(failures.items(), key=lambda item: item[1])
        ],
    }


def read_input_k(path):
    """Read mesh counts from the retained Workbench keyword format."""
    units_seen = False
    counts = defaultdict(int)
    active = None
    solid_connectivity_pending = False

    with path.open(errors="replace") as stream:
        for line_number, raw_line in enumerate(stream, start=1):
            if "data in consistent nmm units" in raw_line.lower():
                units_seen = True
            line = raw_line.strip()

            if not line or line.startswith("$"):
                continue
            if line.startswith("*"):
                if solid_connectivity_pending:
                    raise ValueError(
                        f"input.k: missing solid connectivity before line {line_number}"
                    )
                active = line.upper().split()[0]
                continue

            if active in ("*NODE", "*ELEMENT_SHELL"):
                counts[active] += 1
            elif active == "*ELEMENT_SOLID":
                # Retained decks use a two-integer ID/part header followed
                # by eight node IDs. Also accept a complete ten-field record.
                fields = line.replace(",", " ").split()
                try:
                    values = [int(field) for field in fields]
                except ValueError as exc:
                    raise ValueError(
                        f"input.k: invalid solid record at line {line_number}"
                    ) from exc

                if solid_connectivity_pending:
                    if len(values) != 8:
                        raise ValueError(
                            f"input.k: expected eight solid node IDs at line {line_number}"
                        )
                    counts[active] += 1
                    solid_connectivity_pending = False
                elif len(values) == 2:
                    solid_connectivity_pending = True
                elif len(values) == 10:
                    counts[active] += 1
                else:
                    raise ValueError(
                        f"input.k: unsupported solid record at line {line_number}"
                    )

    if solid_connectivity_pending:
        raise ValueError("input.k: incomplete solid element at end of file")
    if not units_seen:
        raise ValueError("input.k: NMM unit statement missing; stop and verify units manually")
    if counts["*ELEMENT_SHELL"] < 500 or counts["*ELEMENT_SOLID"] < 100:
        raise ValueError("input.k: implausible mesh entity counts")
    return {
        "model_units": EXPECTED_UNITS,
        "nodes": counts["*NODE"],
        "shell_elements": counts["*ELEMENT_SHELL"],
        "solid_elements": counts["*ELEMENT_SOLID"],
    }



# PART 6 — Consistency, QA report, standardized data export
# IMPORTANT: file-type validation above occurs immediately after each import.
# Histories are left at original sampling times; script 2 will interpolate
# motion onto force timestamps before work/force-displacement integration.
def process_design(name):
    folder = DATA / name
    missing = [f for f in REQUIRED if not (folder / f).is_file()]
    if missing:
        raise FileNotFoundError(f"Missing files: {', '.join(missing)}")

    out = OUT / name
    deck = read_input_k(folder / "input.k")  # units checked before conversion
    print("  [OK] input.k: NMM model units and mesh metadata")
    force = read_rcforc(folder / "rcforc")
    print(f"  [OK] rcforc: {len(force)} contact-force samples")
    motion = read_rbdout(folder / "rbdout")
    print(f"  [OK] rbdout: {len(motion)} impactor-motion samples")
    glstat = read_glstat(folder / "glstat")
    print(f"  [OK] glstat: {len(glstat)} energy samples, Nmm -> J")
    sleout = read_sleout(folder / "sleout")
    print(f"  [OK] sleout: {len(sleout)} sliding-energy samples, Nmm -> J")
    diagnostic = read_d3hsp(folder / "d3hsp")
    print(f"  [OK] d3hsp: {diagnostic['failed_shell_count']} failed shells")

    write_csv(out / "contact_force.csv", force)
    write_csv(out / "impactor_motion.csv", motion)
    write_csv(out / "global_energy.csv", glstat)
    write_csv(out / "contact_energy.csv", sleout)
    with (out / "model_diagnostics.json").open("w", encoding="utf-8") as fh:
        json.dump({**deck, **diagnostic}, fh, indent=2)

    end_times = [sequence[-1]["time_s"] for sequence in
                 (force, motion, glstat, sleout)]
    if max(end_times) - min(end_times) > 0.00015:
        raise ValueError("Different final times across output files; inspect source run")

    return {
        "design": name, "status": "OK",
        "model_units": deck["model_units"],
        "shell_elements": deck["shell_elements"],
        "solid_elements": deck["solid_elements"],
        "rcforc_samples": len(force), "rbdout_samples": len(motion),
        "glstat_samples": len(glstat), "sleout_samples": len(sleout),
        "final_time_s": round(max(end_times), 7),
        "failed_shell_count": diagnostic["failed_shell_count"],
        "final_total_energy_ratio": glstat[-1]["total_energy_ratio"],
        "final_sliding_energy_J": sleout[-1]["sliding_energy_J"],
        "final_eroded_internal_energy_J": glstat[-1]["eroded_internal_energy_J"],
        "note": "Numerical reliability requires independent engineering judgment",
    }


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    summaries = []
    for name in DESIGNS:
        print(f"\nPROCESSING: {name}")
        try:
            row = process_design(name)
            print("  COMPLETE")
        except (OSError, ValueError) as exc:
            row = {"design": name, "status": "ERROR", "note": str(exc)}
            print(f"  ERROR: {exc}")
        summaries.append(row)

    # Unified column list includes information present in successful runs.
    columns = list(dict.fromkeys(key for row in summaries for key in row))
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    with REPORT.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        writer.writerows(summaries)

    success = sum(row["status"] == "OK" for row in summaries)
    print(f"\nRESULT: {success}/{len(DESIGNS)} datasets processed")
    print(f"Validation report: {REPORT}")
    print(f"Normalized data: {OUT}")
    if success != len(DESIGNS):
        raise SystemExit("Some datasets failed. Review validation_report.csv")


if __name__ == "__main__":
    main()
