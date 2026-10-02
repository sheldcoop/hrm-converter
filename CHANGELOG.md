# Changelog

## 1.2.0 - 2026-10-02

- App: **Loose Excel files** mode for workbooks outside the folder structure.
  Measurements are converted as usual; the metadata columns are left blank.
- Long table: `LSL`, `Target` and `USL` columns after the 16 schema columns,
  filled from the reference workbook for folder runs and loose files alike
  (`--reference` on the command line).
- Long table: `Open_File` column next to `Source_File`, a clickable link that
  opens the source workbook.
- Folder check: Excel files at the wrong folder level and missing process or
  panel folders are now reported instead of being ignored; every issue has a
  `How_To_Fix` instruction; a `Folder_Check` sheet and Summary table give a
  verdict per lot.
- App: both workbooks can be downloaded from the Summary page.
- App runs under any Streamlit installation, accepts pasted paths in quotes,
  and the Browse button uses the operating system's folder dialog.
- README quick start; made-up stress project added under `test_data/`.

## 1.1.0 - 2026-10-02

- Wide format: `python -m hrm_converter.wide` writes one sheet per feature type
  from the long workbook, one column per metric.
- Reference limits: LSL / Target / USL from one Excel sheet, keyed by Part
  Number, Buildup, Side, feature type, feature number and metric. Blank key
  cells apply to all; the most specific row wins; conflicts are reported.
- `Out_of_Spec` column, red cell fill, `Limit_Summary`, `Reference` and
  `Wide_Issues` sheets. `--make-reference` writes a starter reference.
- Streamlit app (`streamlit run app.py`, or `run_app.bat` on Windows) over the
  same engine: Summary, Long, Wide, Issues and Reference pages.
- `tools/create_demo_project.py`: a clean demo tree with realistic-looking
  values and a demo limits workbook.
- App styling shared with the QVM dashboard (dark theme, copper accent);
  out-of-spec cells are tinted red on screen.
- `tools/create_stress_project.py`: a large, deliberately messy project with
  many workbook kinds, one problem case per panel folder and a limits workbook.

## 1.0.0 - 2026-10-02

First version.

- Command-line converter: `python -m hrm_converter --input "<folder>" --config config.yaml`,
  with an optional folder picker when no input is given.
- Accepts a Project, Part Number, Lot Number or Buildup folder; the role is
  detected from the position of the `HRM` folders and validated against the
  Buildup naming pattern.
- Traverses only `HRM` folders: process, panel and side/location folders,
  in deterministic natural order.
- Parses the stacked block layout of HRM summary sheets; features and metrics
  are detected dynamically, with aliases and unit rules in `config.yaml`.
- Roughness metrics are named by column position and converted from µm to nm.
- Writes `Long`, `Processing_Summary` and `Validation_Issues` as Excel tables.
- Strict (default) or permissive handling of hierarchy/workbook conflicts.
- Synthetic fixture generator (`tools/create_test_fixture.py`) and a pytest
  suite with unit and end-to-end tests.

Differences from the earlier `HRM-AutoLot_v3.py` script:

- Output is one long table instead of wide Pad / Trace / Via / Roughness sheets.
- Several workbooks in one folder are an error by default instead of taking
  the newest.
- No derived `Diameter = 2 × Radius`, no QC flags.
- Any folder level can be selected, not only a Lot.
