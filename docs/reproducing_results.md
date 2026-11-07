# Reproducing the crash-box analysis

This guide describes how to regenerate the Python metrics and figures from the five retained LS-DYNA output sets. It documents the two-script workflow used for this study. The accompanying [technical report](technical_report.md) explains the model and interpretation; the [README](../README.md) summarises the findings.

## 1. What is being reproduced

Running the Python scripts reprocesses existing simulation outputs. It does not rerun LS-DYNA or validate the simulations against physical tests. You need the retained raw files listed below; the report, screenshots and summary metrics alone are insufficient.

The publication scripts were successfully rerun on Windows with Python 3.13.2, NumPy 2.5.4 and Matplotlib 3.11.2 on 7 November 2026. Both scripts completed for all five designs, and the displayed peak-force and contact-work values matched the retained results. Script 1 uses the Python standard library; Script 2 additionally uses NumPy and Matplotlib. The 11 installed package versions are captured in the project-root `requirements.txt`. This records the successful publication rerun environment, not a recovered environment from the earliest analysis. Byte-identical figure reproduction across platforms is not claimed.

The simulation work used ANSYS 2026 R1 with DesignModeler, Workbench/Mechanical and LS-DYNA. LS-PrePost was used for deformation inspection. These applications are not required for the Python post-processing steps.

## 2. Prepare the project folders

Use `CrashBox_Python_Analysis` as the project root. The scripts locate that root from their own location, so both Python files must be directly inside its `scripts` folder.

| Path relative to the project root | Contents |
|---|---|
| `scripts/01_process_simulation_data.py` | Working parser with corrected solid-element counting |
| `scripts/02_engineering_analysis.py` | Engineering metrics and plotting script |
| `data/Baseline_5mm/` | Unperforated reference, nominal 5 mm shell mesh |
| `data/D12_Position15_3mm/` | 12 mm holes, centres 15 mm from the impacted end |
| `data/D16_Position15_3mm/` | 16 mm holes, centres 15 mm from the impacted end |
| `data/D12_Position30_3mm/` | 12 mm holes, centres 30 mm from the impacted end |
| `data/D12_Position13_3mm/` | 12 mm holes, centres 13 mm from the impacted end |
| `results/` | Generated tables, diagnostics and plots |
| `docs/` | Technical report and this guide |
| `docs/figures/` | Selected analysis plots and deformation screenshots |
| `docs/results/` | Archived result tables, method notes and provenance |
| `requirements.txt` | Pinned packages from the successful publication rerun |

Each of the five design folders must contain these six files from the same simulation run:

| Filename | Purpose |
|---|---|
| `input.k` | Exported model and unit metadata |
| `d3hsp` | Solver diagnostics, masses and element counts |
| `rcforc` | Contact-force history |
| `rbdout` | Rigid-impactor motion |
| `glstat` | Global energy history |
| `sleout` | Sliding/contact-energy history |

Preserve these filenames, including the absence of extensions on the five solver-output files. Do not mix a keyword deck from one run with output histories from another. Neither `d3plot` nor the Workbench project archive is read by the Python scripts.

Use the corrected publication script named `01_process_simulation_data.py`. An alternative generic parser was explored during development and did not match these output layouts; it is not the reference parser for this guide. Do not substitute an older `_og.py` copy for the corrected publication file.

## 3. Set up Python

Open the project root in VS Code and open its PowerShell terminal. If the existing environment already runs both scripts successfully, reuse it. For a fresh environment, run:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

These commands use the environment's interpreter directly and do not require PowerShell activation. Check the interpreter and dependencies:

```powershell
.\.venv\Scripts\python.exe --version
.\.venv\Scripts\python.exe -c "import numpy, matplotlib; print('NumPy:', numpy.__version__); print('Matplotlib:', matplotlib.__version__)"
```

Use Python 3.13.2 to match the recorded interpreter version. The requirements file pins NumPy, Matplotlib and the other packages present in the successful environment; Python itself is installed separately. The confirmed environment has `include-system-site-packages = false`. The pinned installation command is the documented setup route; a second clean installation from this file on another machine has not been demonstrated. Record any platform or dependency changes when reproducing the analysis.

## 4. Process the raw outputs

From the project root, run:

```powershell
.\.venv\Scripts\python.exe scripts/01_process_simulation_data.py
```

The required final success message is:

```text
RESULT: 5/5 datasets processed
```

The script writes `results/validation_report.csv` and the following files inside `results/processed/<design>/`:

- `contact_force.csv`
- `impactor_motion.csv`
- `global_energy.csv`
- `contact_energy.csv`
- `model_diagnostics.json`

Check that all five rows in the validation report have status `OK`. The retained histories contain 1001 samples per design for each of the four history types. Do not continue to engineering analysis after an incomplete processing run: older processed files may still exist.

**Rerun behaviour:** Script 1 replaces the processed outputs at these fixed paths and replaces the validation report. It does not modify the raw input files. Keep a copy of any previous processed results that you need to preserve before rerunning it.

An earlier parser counted solid-element text lines rather than elements. The publication version counts complete solid records, including the two-line format in these decks, and reports 800 solids for each model. In the verification run, the corrected parser preserved all 20 force, motion and energy CSV files byte-for-byte. Script 2 independently obtains element counts and masses from `d3hsp`. The filename “validation report” refers to parsing and consistency checks, not experimental validation or numerical convergence.

## 5. Generate engineering results

After all five datasets have processed successfully, run:

```powershell
.\.venv\Scripts\python.exe scripts/02_engineering_analysis.py
```

The script prints one result line per design, followed by:

```text
RESULT: 5/5 designs analysed. Review metrics, figures and limitations.
```

Each execution creates a new UTC timestamp folder under `results/engineering_analysis/`. Use the path printed by that execution; do not accidentally review an older folder.

| Output | Contents |
|---|---|
| `engineering_metrics.csv` | All five designs and their engineering metrics |
| `comparison_vs_D12_Position15.csv` | Comparisons using D12/Pos15 as the reference |
| `<design>_aligned.csv` | Force and interpolated motion on a common time base |
| `<design>_first80mm.csv` | First forward passage to 80 mm and cumulative contact work |
| `01_force_time.png` and `.pdf` | Raw and exploratory smoothed force histories |
| `02_force_travel_80mm.png` and `.pdf` | Force versus impactor travel to 80 mm |
| `03_energy_histories.png` and `.pdf` | Energy histories |
| `04_design_comparison.png` and `.pdf` | Peak force, work, travel and failed-shell counts |
| `method_and_limitations.txt` | Analysis definitions and cautions |
| `source_manifest.json` | Script/input paths and SHA-256 hashes |

The script saves figures directly; a plot window need not appear. If it stops with an error, the new timestamp folder may contain partial outputs and must not be treated as a completed run.

## 6. Compare against the retained results

With the same retained data and analysis definitions, the values should round to the following:

| Design | Raw PCF (kN) | Contact work at 80 mm (J) | Failed shells |
|---|---:|---:|---:|
| Baseline_5mm | 187.876 | 4080.34 | 0 |
| D12_Position15_3mm | 174.984 | 4588.31 | 4 |
| D16_Position15_3mm | 168.462 | 4422.56 | 4 |
| D12_Position30_3mm | 175.726 | 3506.52 | 8 |
| D12_Position13_3mm | 174.031 | 4543.58 | 4 |

Matching this table verifies reproduction of the numerical analysis, not physical accuracy. A different raw run, force interface, sign convention or comparison endpoint can change the results. Timestamp names and figure metadata can differ between executions even when numerical values agree.

The publication script writes project-relative paths with SHA-256 hashes for both Python scripts, the six raw files per design and the five processed files per design: 57 entries in total. Earlier manifests used absolute paths; use the newly generated manifest for publication. The manifest records files present at analysis time, so rerun Script 1 before Script 2 after changing the parser to keep processed outputs and script provenance consistent. Package versions are recorded separately in `requirements.txt`.

## 7. Assumptions built into the scripts

The parser is specific to these retained output formats and model identifiers. It expects N–mm–s units, force interface 48, rigid impactor body 2, approximately 5 kJ initial kinetic energy and approximately 30 ms of output. Script 2 obtains crash-box mass from part 1 and evaluates the first forward passage to 80 mm using an 11-sample exploratory moving average for the separate smoothed curve.

Do not reuse it unchanged for arbitrary LS-DYNA models. Check units, part/body/interface IDs, output layout, duration and comparison distance when adapting it. Do not simply disable a failed check to force a new model through the workflow.

| Symptom | Check |
|---|---|
| `ModuleNotFoundError` | Install dependencies using the same interpreter used to run Script 2. |
| Missing input file | Confirm exact design-folder names and the six required filenames. |
| Unexpected units, force, velocity or initial energy | Confirm the output belongs to the intended model and run; review the parser's assumptions. |
| No normal termination detected | Inspect `d3hsp` before treating the output as a complete simulation. |
| No crossing of 80 mm or reversal before it | Review the motion history; the common-stroke definition may not apply. |
| Non-increasing times or irregular sampling | Inspect the source history and any file concatenation or manual edits. |
| Results disagree with the table | First confirm all raw files come from the retained runs and Script 1 completed successfully. Then compare hashes and analysis definitions. |

## 8. Rerunning the simulations

A solver rerun is a separate reproduction level. It requires an appropriate LS-DYNA installation, the complete model and any referenced files, and a recorded solver configuration. The Python commands above do not launch or configure the solver.

The technical report records the verified setup, but this guide does not claim a tested clean solver rerun on another machine or prescribe an unverified solver command. A future solver reproduction should retain the solver version/build, execution settings, termination diagnostics and output files before comparison with the archived results. For animation review, open the corresponding `d3plot` result family in LS-PrePost; those binary results are separate from the six ASCII inputs used here.

## 9. Archived publication evidence

The project-root `results/` directory contains generated working outputs and is excluded from Git. Selected copies are preserved under `docs/results/`:

- [Engineering metrics](results/engineering_metrics.csv)
- [Comparison against D12/Pos15](results/comparison_vs_D12_Position15.csv)
- [Parser consistency report](results/validation_report.csv)
- [Method and limitations](results/method_and_limitations.txt)
- [Source manifest](results/source_manifest.json)

The publication copies are snapshots. Running the scripts does not overwrite them; compare newly generated outputs with these snapshots before deliberately updating the publication evidence. The timestamped analysis folder and its archived metrics/manifest should come from the same successful run. The consistency report comes from Script 1 immediately preceding that analysis.

Manifest paths are relative to the project root, not to the folder containing the copied manifest. Entries beginning `results/processed/` refer to regenerated files: run Script 1 before trying to verify those entries in a fresh checkout. The manifest hashes both scripts, 30 raw input files and 25 processed files. It does not hash the final figures or engineering-metrics CSV, and should not be described as a checksum inventory of every published artifact.
