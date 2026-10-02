# Implementation plan

Source of requirements: `HRM_Converter_GitHub_Copilot_Master_Prompt(1).md`,
the sample workbook `2026-08-11_11-02-51_ENG_Chipletz4Future_BU03_Back_Summary.xlsx`
and the earlier script `HRM-AutoLot_v3.py`.

## Decisions taken with the user

| Topic | Decision |
|---|---|
| Workbook layout | One sheet per file, stacked block layout (as in the sample). No structured feature sheets. |
| Output | Long format only for now; wide tables come later as derived views. |
| Roughness header | The operator-typed header can be wrong; metric names follow the column position. |
| Roughness values | Converted to nm (source value × 1000). |
| Other metrics | µm. `Unit_of_Measurement` is kept because the `Value` column mixes nm and µm. |

## Carried over from `HRM-AutoLot_v3.py`

- Block parsing of the first sheet (column A unit, column B label, C.. values).
- `Unit 7` → `7`, coupon → `C7`; `BU03` → `BU-03`; `Panel 05` → `5`.
- Label aliases (`pad pos`, `sr pad`, `via pos`, …) and header names
  (`Max_Stepheight`, `Line` → `Width`).
- `*_Summary.xlsx` file name pattern; `Lot_Name` typed in the settings.

## Deliberately different from the old script

- Multiple workbooks in a folder: error and skip (master prompt, section 4).
- No derived Diameter and no QC flags: the long table holds measured values only.

## Steps

1. Project structure, `pyproject.toml`, dependencies.
2. Typed config (`config.py`) and domain models (`models.py`).
3. Folder-name parsing and selected-folder role detection (`hierarchy.py`).
4. HRM-only traversal and workbook candidate rules (`discovery.py`).
5. Read-only block reader (`workbook_reader.py`).
6. Dynamic feature / metric / unit detection (`schema_detection.py`).
7. Long-format transformation and stable natural sorting (`transformer.py`).
8. Issue collection and hierarchy-vs-workbook cross-checks (`validation.py`).
9. Excel output with three table sheets (`output_writer.py`).
10. Orchestration (`pipeline.py`) and command line (`cli.py`).
11. Synthetic fixture generator (`tools/create_test_fixture.py`).
12. Unit and end-to-end tests; ruff, mypy.
13. README, changelog, Copilot instructions.
