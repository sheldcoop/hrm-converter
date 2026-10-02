# HRM converter

Finds HRM Excel summary files in an engineering folder hierarchy and converts
their measurements into one consolidated long-format Excel workbook.

## Quick start (app)

1. **Start the app.** In a terminal, inside this folder:

   ```bash
   streamlit run app.py
   ```

   On Windows you can double-click `run_app.bat` instead. The app opens in
   your browser at `http://localhost:8502`.

2. **Choose the folder.** In the sidebar, paste the path of a Project, Part
   Number, Lot or Buildup folder into the first box, or press **Browse…**.
   Quotes around a pasted path are fine.

3. **Add limits (optional).** The limits file is an Excel workbook that *you*
   keep, anywhere you like (for example next to your data). It is not part of
   the source folders and the app never changes it. Give it to the app in one
   of two ways, both in the sidebar under **Limits**:
   - **Upload** it with the *Reference workbook* box, or
   - type its path in *…or path of the reference workbook* (handy when the
     file always stays in the same place; you can also set it once in
     `config.yaml` under `wide.reference_path`).

   No limits file yet? Convert once without it, open the **Reference** page and
   press **Download a template for this data**. Fill in LSL / Target / USL in
   Excel, save it, and give it to the app as above. The layout and rules are in
   [Wide format and limits](#wide-format-and-limits).

4. **Press Convert**, then look at the pages:

   | Page | What you see |
   |---|---|
   | Summary | How many folders and workbooks were found, processed and skipped, and why |
   | Long | The long table, with filters and a download button |
   | Wide | One feature at a time, with limits and out-of-spec values in red |
   | Issues | Every warning and error from the conversion and from the limits file |
   | Reference | The limits that were used, and the template download |

5. **Find the results.** Both workbooks are saved in the `output` folder next
   to the app (`hrm_long_format.xlsx`, `hrm_wide_format.xlsx`) and can be
   downloaded from the Long and Wide pages. Logs are in `logs`.

To try it without real data, see
[Demo project](#demo-project-for-a-manual-smoke-test) and
[Stress project](#stress-project-many-files-many-problems).

## Purpose and non-goals

**Purpose.** You select a Project, Part Number, Lot Number or Buildup folder.
The converter walks only the `HRM` folders below it, reads every HRM summary
workbook, and writes one table with one row per measured value. That long
table is the master analytical source.

**Non-goals.**

- It never modifies, renames, moves or deletes a source folder or file.
  Workbooks are opened read-only.
- The converter itself writes only the long table. Wide per-feature tables with
  limits are a separate, derived step (see
  [Wide format and limits](#wide-format-and-limits)).
- It does not calculate values. There is no `Diameter = 2 × Radius` and no
  averaging. The only arithmetic is the configured unit conversion for
  roughness (µm to nm).
- It does not read machine folders other than `HRM`.

## Supported hierarchy

```text
<Project_Name>/
└── <Part_Number>/
    └── <Lot_Number>/
        ├── <Buildup>/                     e.g. BU03
        │   ├── HRM/                       the only machine folder that is entered
        │   │   ├── <Process folder>/      e.g. post DDV_HRM-2026-0088
        │   │   │   └── Panel <n>/
        │   │   │       ├── front/         one *_Summary.xlsx
        │   │   │       ├── back/
        │   │   │       ├── Coupon front/
        │   │   │       └── Coupon back/
        │   └── <other machine>/           ignored
        └── <Buildup>/...
```

### Supported starting folders

| You select | What is processed |
|---|---|
| Project | every Part Number, Lot and Buildup below it |
| Part Number | every Lot and Buildup below it |
| Lot Number | that Lot and all its Buildups |
| Buildup | that Buildup only |

Project, Part Number and Lot Number are always reconstructed from the parent
folders, also when a Lot or Buildup is selected.

## Installation

Python 3.10 or newer.

Windows:

```bash
py -m venv .venv
```

```bash
.venv\Scripts\activate
```

```bash
pip install -e ".[dev]"
```

macOS / Linux:

```bash
python3 -m venv .venv
```

```bash
source .venv/bin/activate
```

```bash
pip install -e ".[dev]"
```

Use `".[app]"` instead of `".[dev]"` if you only want to run the converter and
the app (no tests, lint or type checks). Leave the brackets out for the
command line only.

## Running

```bash
python -m hrm_converter --input "L:\...\Chiplet4Future\FHR0020\19198" --config config.yaml
```

| Option | Meaning |
|---|---|
| `--input` | Folder to process. If omitted, `input.start_path` of the config is used; if that is empty too, a folder picker opens. |
| `--config` | Settings file. Default: `config.yaml` in the current folder if present, otherwise built-in defaults. |
| `--output-dir` | Overrides `output.directory`. |
| `--lot-name` | `Lot_Name` written for every lot in this run. |
| `--permissive` | On a metadata conflict, use the folder value instead of skipping the file. |

At the end a short summary is printed: detected scope, HRM folders found,
workbooks processed and skipped, output rows, warnings and errors, and the
paths of the output workbook and the log file. Measurement values are never
printed.

Relative `output.directory` and `logging.directory` are resolved against the
folder you run the command from.

## Wide format and limits

A second command turns the long workbook into a wide one. It only reshapes the
long table; it never reads the source folders.

```bash
python -m hrm_converter.wide --input output/hrm_long_format.xlsx --reference HRM_Reference.xlsx
```

| Option | Meaning |
|---|---|
| `--input` | Long workbook. Default: the converter's output from the config. |
| `--reference` | Workbook with limits. Default: `wide.reference_path` of the config; without one, no limit columns are written. |
| `--output` | Wide workbook. Default: `hrm_wide_format.xlsx` next to the long workbook. |
| `--make-reference FILE` | Write a starter reference workbook from the long data and stop. Never overwrites an existing file. |

**Wide workbook.**

- One sheet per `Feature_Type` (`Pad`, `SR Pad`, `Trace`, `Via`, `Roughness`;
  a new feature type gets its own sheet automatically).
- One row per unit and feature number. The feature number is in a column named
  after the feature (`Pad`, `Trace`, …).
- One column per metric, with the unit in the header (`Radius (µm)`,
  `Ra_Mean (nm)`). Metrics follow the order in the config; unknown ones come
  last.
- Next to a metric that has limits: `Radius_LSL`, `Radius_Target`,
  `Radius_USL`. Only the limit kinds actually used get a column.
- `Out_of_Spec` lists what is outside its limits (`Radius > USL; Dimple < LSL`);
  those cells are filled red.
- `Repeat` appears only when the same unit, feature and metric was measured
  more than once in a file; every value is kept on its own row.
- `Limit_Summary`: per feature and metric, how many values exist, how many have
  limits and how many are out of spec.
- `Reference`: a copy of the limits used, with `Matched_Groups` showing how
  often each row was applied. `Wide_Issues`: problems in the reference.

**Reference workbook.** One sheet (default name `Limits`), one row per limit:

| Part_Number | Buildup | Side | Feature_Type | Feature_Number | Metric | LSL | Target | USL |
|---|---|---|---|---|---|---|---|---|
| FHR0020 | | | Pad | | Radius | 41 | 42 | 43 |
| FHR0020 | BU-03 | Back | Pad | | Radius | 41.5 | 42 | 42.3 |
| FHR0020 | BU-03 | Back | Pad | 2 | Radius | 41 | 41.6 | 42 |

- `Feature_Type` and `Metric` are required. `LSL`, `Target` and `USL` are each
  optional, but a row needs at least one.
- A **blank** key cell means "applies to all". The first row above covers every
  Buildup and side.
- When several rows fit a measurement, the **most specific** one wins (the row
  with the most key cells filled in). Above, BU-03 Back uses the second row,
  and Pad 2 on BU-03 Back uses the third.
- Two equally specific rows with different limits are a conflict: it is
  reported once and no limit is applied, rather than picking one.
- Spelling is forgiving: `BU03` matches `BU-03`, `pad` matches `Pad`,
  `Max Stepheight` matches `Max_Stepheight`, and header case does not matter.
- Limits are in the unit of the long table: µm, and **nm for roughness**.
- Any other long-table column (`Lot_Number`, `Process`, `Panel`, `Location`,
  `Project_Name`) may be added as a further key column.
- Extra columns such as `Comment` are ignored.

Rows with a missing key, a non-numeric limit or `LSL > USL` are reported and
ignored; rows that match nothing are reported so a typo does not go unnoticed.

## App

The same engine with a screen on top (Streamlit):

```bash
streamlit run app.py
```

On Windows you can double-click `run_app.bat` instead; on first use it creates
the environment and installs what is needed.

1. Enter the folder path, or press **Browse…**.
2. Optionally set the Lot name, and give a reference workbook (upload it, or
   type its path so it does not need uploading each time).
3. Press **Convert**.

Pages: **Summary** (counts and the list of workbooks), **Long** (filter by
feature and Buildup, download), **Wide** (one feature at a time, optionally
only out-of-spec rows, download), **Issues** (conversion and limit problems)
and **Reference** (the limits used, and a template for the current data).

Both workbooks are also saved in `output/` next to the app.

The look follows the QVM dashboard: dark theme with the copper accent, filled
buttons for the selected page and the main action, outlined buttons for the
rest. Colours are set in `.streamlit/config.toml` and `assets/styles.css`.

## Configuration

All rules that may change live in [config.yaml](config.yaml); every section is
optional. Unknown setting names are rejected, so a typo is reported instead of
being ignored.

Common changes:

```yaml
# Lot names (not available from folders or workbooks)
metadata:
  default_lot_name: ''
  lot_names: {'19197': 'DOE Lot', '19198': 'Reference Lot'}

# Process only some of what is below the selected folder
scope:
  part_numbers: all
  lot_numbers: ['19198']
  buildups: [BU-03, BU-04]

# A new block label in column B
features:
  aliases:
    fiducial: Fiducial        # 'Fiducial 3' -> Feature_Type Fiducial, Feature_Number 3

# A unit for a new metric
units:
  metric_units:
    Angle: deg
```

`features.aliases`, `metrics.aliases`, `metrics.positional`,
`units.metric_units`, `units.feature_rules`, `metadata.lot_names` and
`hierarchy.sides` are replaced as a whole when you set them: list every entry
you want, as the shipped `config.yaml` does.

## Long-format schema

Sheet `Long`, exactly these columns in this order. One row is one metric value
of one feature on one unit or coupon.

| Column | Source |
|---|---|
| `Project_Name` | Project folder name |
| `Part_Number` | Part Number folder name; cross-checked against the sheet name |
| `Lot_Number` | Lot folder name, written as text |
| `Lot_Name` | `metadata.lot_names` / `metadata.default_lot_name` / `--lot-name`; otherwise blank |
| `Buildup` | Buildup folder, normalised (`BU03` → `BU-03`); cross-checked against sheet and file name |
| `Process` | Process folder (`post DDV_HRM-2026-0088` → `Post DDV`) |
| `Panel` | Panel folder as a number (`Panel 05` → `5`) |
| `Side` | Final folder: `Front` or `Back`; cross-checked against sheet and file name |
| `Location` | Final folder: `Unit`, or `Coupon` when the folder name starts with "Coupon" |
| `Unit` | Column A of the block: `Unit 7` → `7`; on a Coupon folder → `C7` |
| `Feature_Type` | Block label in column B without its number: `SR Pad 2` → `SR Pad` |
| `Feature_Number` | Number of the block label: `SR Pad 2` → `2`; `1` when the label has none |
| `Metric` | Header of the value column |
| `Value` | The cell value, numeric |
| `Unit_of_Measurement` | From the unit rules in the config; blank when no rule exists |
| `Source_File` | Workbook file name only |

Rows are sorted naturally (so `BU-2` precedes `BU-10` and `Panel 2` precedes
`Panel 10`) by Project_Name, Part_Number, Lot_Number, Buildup, Process, Panel,
Side, Location, Unit, Feature_Type, Feature_Number, Metric, Source_File. Equal
keys keep their source order, so the output is identical from run to run.

## Workbook and sheet detection

An HRM summary workbook has **one sheet** with measurement blocks stacked on
top of each other:

```text
A        B          C                D                E ...
                    Max Stepheight   Min Stepheight   Radius      <- header row
Unit 7   Pad 1      16.62            16.49            42.25       <- first unit row carries the label
Unit 8              17.56            17.47            42.37
                    Width            Space                        <- next block
Unit 7   Trace 1    21.52            33.35
```

Rules (implemented in `workbook_reader.py` and `schema_detection.py`):

1. Only the **first sheet** is read. Further sheets are reported and ignored.
2. A row with an empty column A and text from column C onward is a **header
   row** and starts a new block.
3. A row whose column A is a unit (`Unit 7`, `7`, `C3`) is a **unit row**.
4. The **feature label** is column B of the first unit row of a block. If a
   later labelled row repeats a unit already seen in the block, a new block
   starts and reuses the previous header (operator left out the header row).
   Any other text in column B of a later row is reported as a unit note.
5. **Feature**: the label's trailing number is `Feature_Number`, the text
   before it is `Feature_Type`. Known labels are mapped through
   `features.aliases`; an unknown label is kept as written and reported as a
   new feature type. Nothing is dropped.
6. **Metrics**: every header cell becomes a `Metric`. Names are kept after
   whitespace normalisation unless `metrics.aliases` maps them explicitly
   (`Max Stepheight` → `Max_Stepheight`, `Line` → `Width`). New columns such as
   `Distance 1` or `Angle` appear automatically.
7. **Roughness** takes its eight metric names from the **column position**
   (`metrics.positional`), because operators type that header by hand and it
   can be wrong. A header that differs from the standard order is reported.
8. **Units of measurement**: `units.feature_rules` first (Roughness: nm, value
   × 1000 because HRM stores it in µm), then `units.metric_units` (µm for the
   known metrics), otherwise blank.

Workbooks are matched by file name (`input.filename_patterns`, default
`*_Summary.xlsx`). Files starting with `~$` are ignored.

## Folder metadata extraction

The role of the selected folder is detected from **where the `HRM` folders sit
below it**, not from the folder depth of the path:

| `HRM` found | Selected folder is |
|---|---|
| 1 level down | Buildup |
| 2 levels down | Lot Number |
| 3 levels down | Part Number |
| 4 levels down | Project |

This is then validated: the folder directly above `HRM` must match the Buildup
naming pattern (`hierarchy.buildup_pattern`), and the selected folder must have
enough parent folders to supply Project, Part Number and Lot. If `HRM` folders
appear at several levels, the level whose parents look like Buildups is used;
if that is not unique the run stops with a message naming what was found. A
folder that is `HRM` itself, or lies inside it, is rejected.

`HRM` is matched by exact name, ignoring case and surrounding spaces.

**Hierarchy versus workbook.** HRM summary sheets contain no metadata columns,
so the only workbook-side evidence is the sheet name (for example
`ENG_FHR0020_BU03_Back`) and the file name. Buildup and Side are compared with
both; Part Number is compared with the sheet name. A field is only compared
when the name states it unambiguously. Project, Lot, Process and Panel cannot
be cross-checked because the workbook does not state them.

## Error and warning behaviour

One problem file never stops the run. Everything below is written to the
`Validation_Issues` sheet and to the log file.

| Situation | Result |
|---|---|
| Selected folder role cannot be determined | Run stops with an explanation |
| Buildup folder without `HRM` | Warning |
| Empty process or panel folder | Warning |
| Folder name is not a panel / side folder | Error, folder skipped |
| Process name cannot be parsed | Warning, trimmed folder name used |
| No workbook in a side folder | Warning |
| More than one workbook in a side folder | Error, folder skipped, candidates listed (`multiple_files_policy: newest` opts into taking the newest) |
| Excel file not matching the file name pattern | Warning, ignored |
| Corrupted / password-protected / unreadable workbook | Error, file skipped |
| Hierarchy and sheet/file name disagree | Strict (default): error, file skipped. Permissive: warning, folder value used |
| Block without a label | Error, block skipped |
| Unknown feature label | Warning, written as-is |
| Roughness header differs from standard order | Warning, names assigned by position |
| Same header twice in a block | Warning, both kept (`Width`, `Width (2)`) |
| Same unit, feature and metric twice in a file | Warning, both rows kept, nothing aggregated |
| Blank cell | No row |
| Zero | Row with `0` |
| Number stored as text (`12,5`) | Converted, warning |
| Other text (`n/a`) | Error, no row; never converted to zero (`text_value_policy: keep_as_text` writes the text instead) |
| Value in a column without a header | Warning, not written |

## Output workbook

Written to `output/hrm_long_format.xlsx` by default, as static values:

1. `Long` – the consolidated table.
2. `Processing_Summary` – one row per candidate workbook: status
   (`Processed` / `Skipped`), reason and row count.
3. `Validation_Issues` – severity, category, source file, sheet, field,
   message, hierarchy value, workbook value and relative path.

Each sheet is an Excel table with a frozen header row, filters and sized
columns. The converter refuses to write into an `HRM` source folder and never
reads its own output.

## Testing

```bash
python -m pytest
```

```bash
ruff check .
```

```bash
ruff format --check .
```

```bash
mypy
```

Tests use only synthetic data created in temporary folders; no network drive
or company file is needed. The app is tested headless with Streamlit's own
test harness (those tests are skipped if Streamlit is not installed).

### Synthetic fixture

```bash
python tools/create_test_fixture.py --output test_fixture
```

This creates a complete artificial hierarchy (`SYN_Demo_Project`, two Part
Numbers, three Lots, several Buildups, coupons, empty folders, a corrupt file,
a metadata conflict, duplicate workbooks and so on) and prints ready-to-run
commands for each starting level. All values follow
`seed + unit / 10 + column / 100`.

### Demo project for a manual smoke test

```bash
python tools/create_demo_project.py --output ../test_data
```

This creates a clean tree shaped like a real one (`Chiplet4Future / FHR0020 /
19197, 19198, 19199`, five Buildups, three processes, front / back / Coupon
front, plus `XRF` and `AOI` folders that must be ignored) and a small limits
workbook, `HRM_Reference_demo.xlsx`. Add `--real-sample "<BU03 Back workbook>"`
to copy one real file into the matching folder. Then run the converter on the
project, a lot or a Buildup, and the wide command with the demo reference.

### Stress project: many files, many problems

```bash
python tools/create_stress_project.py --output ../test_data
```

A large made-up project (`Orion_Stress_Demo`: two Part Numbers, five Lots, 17
Buildups, about 330 workbooks) with inconsistently spelled folders and many
kinds of workbook: annular pads, `Line` instead of `Width`, `Pad Pos 3` labels,
unknown features and metrics, blank / zero / text values, operator notes,
missing header rows, duplicate and unlabelled blocks, 36-unit panels. Buildup
`BU08` of the first lot holds one problem case per panel folder (several
workbooks in a folder, corrupt and empty files, wrong file names, metadata
conflicts, bad folder names); the command prints the list. It also writes
`Stress_Reference.xlsx`, a limits workbook with a few deliberately bad rows.

## Known limitations

- Only the stacked block layout on the first sheet is supported. Workbooks
  with separate structured `Pad` / `Trace` / `Via` sheets are not parsed.
- `Lot_Name` cannot be derived; it comes from the config or `--lot-name`.
- Project, Lot, Process and Panel cannot be cross-checked against the
  workbook, because the workbook does not state them.
- `.xls` and `.xlsm` files are not read unless added to
  `input.accepted_extensions` (`.xls` is not supported by the reader).
- Excel allows 1,048,575 data rows per sheet. A larger scope stops with a
  message; select a smaller folder.
- `Lot_Number` is written as text, so leading zeros survive.
- The wide workbook checks values against LSL and USL only. It does no
  statistics (Cpk, averages) and `Target` is shown but not evaluated.
- In the app, out-of-spec cells are tinted red for tables up to 5,000 rows;
  larger tables are shown plain and rely on the `Out_of_Spec` column.

## Downstream use with Power Query

`python -m hrm_converter.wide` already builds per-feature wide sheets. If you
prefer to stay inside Excel, treat `Long` as the single source and build wide
tables there as derived views, so they never drift from the data:

1. *Data → Get Data → From File → From Workbook* and pick the `tblLong` table.
2. Filter `Feature_Type` (for example `Pad` and `SR Pad`).
3. Remove `Unit_of_Measurement` (or merge it into `Metric`).
4. Select `Metric`, choose *Transform → Pivot Column*, values column `Value`,
   aggregation *Don't Aggregate*.

The result has one row per unit and feature with one column per metric
(`Max_Stepheight`, `Radius`, …). Repeat with a different filter for Trace, Via
or Roughness. When new workbooks arrive, rerun the converter and refresh.
