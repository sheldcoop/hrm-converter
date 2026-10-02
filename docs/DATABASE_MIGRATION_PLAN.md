# Rough plan: moving the HRM data into a SQL database

Status: **not started, not decided.** Written on 2026-10-02 as a starting
point for a later decision. Nothing in the code depends on it.

## Why it is a small step

The long table already has the shape of a database table: one row per
measurement, fixed columns, no merged cells or layout. The converter builds
that table in memory (`RunResult.records`) before it writes Excel, so a
database writer is one more output next to `output_writer.py`, not a rewrite.

Worth doing when one of these becomes true:

- the long workbook approaches Excel's limit of about one million rows, or
  gets slow to open;
- several people or Power BI need the same data at the same time;
- you want to ask questions across many lots without converting them again.

Until then, Excel and Power Query read the long workbook directly.

## Decisions to take first

| # | Decision | Options | Suggested |
|---|---|---|---|
| 1 | Which database | **SQLite** (one file, nothing to install) / a company server such as SQL Server or PostgreSQL (shared, needs IT) | Start with SQLite; the same code can target a server later |
| 2 | What a re-run does | Add rows again (duplicates) / **replace the rows of each workbook** / refuse | Replace per workbook |
| 3 | History | Latest state only / **keep each import** with a timestamp | Latest state first; add history only if a re-export question comes up |
| 4 | Limits | Copied onto every row (as in Excel) / **own table, joined when querying** | Own table: change a limit once, every query sees it |
| 5 | Who writes | Only the converter / also by hand | Only the converter; the folders stay the source of truth |

## Proposed tables

```text
workbook                       one row per source Excel file
  workbook_id      key
  source_path      full path at import time (unique)
  source_file      file name
  content_hash     SHA-256 of the file, already computed for duplicate detection
  imported_at
  project_name, part_number, lot_number, lot_name,
  buildup, process, panel, side, location

measurement                    one row per value (the long table)
  workbook_id      -> workbook
  unit
  feature_type, feature_number
  metric
  value
  unit_of_measurement

limit_rule                     the reference sheet, one row per rule
  part_number, buildup, side, feature_type, feature_number, metric   (blank = all)
  lsl, target, usl

issue                          Validation_Issues, per import
  workbook_id (optional), severity, category, message, how_to_fix, relative_path
```

Splitting `workbook` from `measurement` avoids repeating nine metadata columns
on every row, and gives decision 2 a natural handle: delete the measurements of
one `workbook_id` and insert the new ones.

A view named `long` that joins `workbook`, `measurement` and the matching limit
would look exactly like today's Long sheet, so existing Power Query steps and
the wide-format code keep working against it.

## Steps

1. **Writer.** New module `database_writer.py` that takes a `RunResult` and
   writes the four tables. SQLite through Python's built-in `sqlite3`, or
   SQLAlchemy if a server is likely. Config section `database:` with `enabled`
   and a connection string. Small.
2. **Re-run handling.** Look up each workbook by `source_path`; if
   `content_hash` is unchanged, skip it; otherwise replace its measurements in
   one transaction. Small to medium. This also makes repeated runs faster.
3. **Limits.** Load the reference sheet into `limit_rule`; move the
   most-specific-row matching into the `long` view or keep it in Python and
   store the result. Small if kept in Python, medium as SQL.
4. **Reading back.** Let the wide step and the app read from the database
   instead of the long workbook (`read_long` is the single place to change).
   Small.
5. **App.** A switch "also write to database" and a line on the Summary page
   saying how many workbooks were added, replaced or unchanged. Small.
6. **Tests.** The existing synthetic fixtures already cover the data; add
   tests for re-run, changed file and removed file. Medium.

Steps 1 and 2 give a usable database. The rest can follow when needed.

## Things to watch

- **Loose files** have blank metadata and no path. They need either typed
  metadata or a rule to keep them out of the database.
- **Mixed-type `Unit`** (`7` and `C7`): store as text.
- **Renamed or moved source files** look like a new workbook plus a missing
  one. The content hash can recognise a move; decide whether to follow it.
- **A deleted source file:** decide whether its rows stay or go. Suggested:
  keep them, and mark the workbook as "not found in the last run".
- **Units:** roughness is stored in nm, everything else in µm, as in the long
  table. Keep `unit_of_measurement` on every row.
- **Access rights and backups** matter once it is a shared server; a SQLite
  file on a network drive is fine for one writer but not for several.

## Not part of this plan

Changing what is measured or how it is parsed. The database would hold the
same rows as the long table; only the storage changes.
