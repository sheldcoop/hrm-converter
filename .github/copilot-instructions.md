# Copilot instructions: HRM converter

Python 3.10+ command-line application that converts HRM Excel summary files in
an engineering folder hierarchy into one long-format Excel workbook. Read
`README.md` for the full behaviour before changing anything.

## Architecture

`src/hrm_converter/`, one responsibility per module:

| Module | Responsibility |
|---|---|
| `models.py` | Dataclasses, enums, exceptions, output column lists |
| `config.py` | Defaults, YAML loading, validation into frozen dataclasses |
| `hierarchy.py` | Folder-name parsing, role detection of the selected folder |
| `discovery.py` | HRM-only traversal, workbook candidate rules |
| `workbook_reader.py` | Read-only parsing of the stacked block layout |
| `schema_detection.py` | Feature, metric, unit-of-measurement and unit-id detection |
| `transformer.py` | Blocks to long records, value policy, sorting |
| `validation.py` | Issue collector, natural sort key, metadata cross-checks |
| `output_writer.py` | The three output sheets and their formatting |
| `pipeline.py` | Orchestration, no user-interface code |
| `cli.py` | Arguments, folder picker, completion summary |
| `quality.py` | Value sanity checks (order, negative, far-off values); report only |
| `fixplan.py` | Proposed folder repairs and the reviewable fix script; never applied |
| `reference.py` | Limits sheet: validation and most-specific-row matching |
| `wide.py` | Per-feature wide workbook from the long table, with limits; its own CLI |

`app.py` (repository root) is a Streamlit screen over `pipeline`, `reference`
and `wide`. Keep it thin: no parsing or matching logic in the app.

Data flow: `detect_scope` → `discover` → `read_workbook` → `find_conflicts` →
`transform` → `sort_records` → `write_output`. Wide step, from the long table
only: `load_reference` → `build_wide` → `write_wide`.

## Domain rules

- Hierarchy: `Project / Part Number / Lot / Buildup / HRM / Process / Panel / Side`.
  Only the folder named `HRM` (case-insensitive, trimmed) is entered.
- The selected folder's role comes from where `HRM` sits below it, validated
  by the Buildup naming pattern and the available parent folders. Never from
  path depth alone.
- Workbook layout: one sheet; a header row has an empty column A; unit rows
  have the unit in column A; the feature label is in column B of the first
  unit row of a block.
- `Feature_Type` and `Feature_Number` come from the block label (`SR Pad 2`).
- Every header cell is a metric. Roughness metric names come from the column
  position (`metrics.positional`).
- Folder hierarchy is authoritative for metadata; the sheet name and file name
  are the cross-check. Strict mode skips a conflicting file.
- Output columns are fixed: `LONG_COLUMNS` in `models.py`, followed in the Long
  sheet by `LSL`, `Target`, `USL` (`LONG_SHEET_COLUMNS`). Do not add `Sample`,
  `Site` or `Point`.
- The long table is the single source. Wide tables are derived from it and
  never read source workbooks.
- Limits: a blank key cell in the reference means "all"; the most specific
  fitting row wins; equally specific rows with different limits are a
  reported conflict and no limit is applied.

## Do not hardcode names

Process names, feature names and metric names must not appear in parsing
code. They belong in `config.py` defaults and `config.yaml` (`features.aliases`,
`metrics.aliases`, `metrics.positional`, `units.*`, `hierarchy.*`). An unknown
feature or metric must flow through to the output and be reported, never
dropped.

## Safety rules

- Never write to, rename, move or delete source folders or files. Open
  workbooks with `read_only=True`.
- Never guess metadata. If something cannot be read reliably, report it.
- Never convert text to zero, never aggregate duplicates, never pick one of
  several workbooks unless `multiple_files_policy` says so.
- One bad workbook must not stop the run: record an issue and continue.
- Do not print or log measurement datasets.
- Keep output ordering deterministic (`sort_records`, `natural_key`).
- Use `pathlib`; no hardcoded drive letters; paths may contain spaces.

## Testing expectations

- `python -m pytest`, `ruff check .`, `ruff format --check .` and `mypy` must
  all pass before a change is complete.
- Tests use only synthetic data from `tools/create_test_fixture.py` in
  temporary folders. Never add real measurement files to the repository.
- A new rule needs a unit test; a new folder or workbook situation needs a
  case in the fixture and an end-to-end assertion.
- The session-scoped `hierarchy` fixture is shared and read-only; build a
  private hierarchy under `tmp_path` when a test needs different files.
- Code is typed (`mypy --strict`), uses small functions and frozen dataclasses.
