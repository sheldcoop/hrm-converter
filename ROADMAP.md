# Roadmap and open questions

Status on 2026-10-02 (version 1.3.0). This is the list to come back to.

## Still to verify

These are built but have not been checked in the situation they are meant for.

| Item | Why it is open |
|---|---|
| Real `L:\` folder tree | Everything so far ran on one real sample workbook and made-up data. Start with one Buildup, then a Lot, and read `Folder_Check` and `Validation_Issues`. |
| Windows | `run_app.bat`, the `HRM_FixFolders_….bat` script and the Browse button's Windows dialog were written on a Mac and never run on Windows. |
| `Open_File` link in Excel | The links point to the right files; nobody has clicked one inside Excel yet. |
| Real coupon workbooks | Assumed: column A says `Unit n` and the unit is written as `Cn`. No coupon sample was available. |
| Part Number cross-check | Assumed: the second part of the sheet name (`ENG_FHR0020_BU03_Back`) is the Part Number. If other files differ they are skipped in strict mode; switch off with `cross_check.sheet_part_number_pattern: null`. |

## Open questions

1. **Move the data to a SQL database?** Not decided. Rough plan:
   [docs/DATABASE_MIGRATION_PLAN.md](docs/DATABASE_MIGRATION_PLAN.md). Three
   decisions are needed first: which database, what happens on a re-run, and
   whether to keep history.
2. **Should the repository stay public?** It mentions real project and part
   names as examples in `README.md` and `config.yaml`.
3. **Commit author email** is a placeholder, so commits are not linked to a
   GitHub profile.

## Suggested features, not built

| Feature | What it would do | Size |
|---|---|---|
| Pass/fail in the long table | An `Out_of_Spec` column next to LSL / USL, as the wide table has | Small |
| Completeness check | State what each panel should have (sides, features, number of units); list what is missing | Medium |
| What changed since the last run | New, missing and changed workbooks compared with the previous output | Medium |
| One-page lot report | Per lot and feature: count, mean, min, max, share out of spec | Medium |
| `Open_File` link in the wide sheets | Same link as in the long table | Small |
| Type metadata for loose files | Instead of blank columns, enter project, part, lot and so on in the app | Small |

## Done

Long table, wide table with limits, Streamlit app, loose-file mode, folder
check with fix hints, fix plan, value sanity checks, duplicate detection,
descriptive file names. Details in [CHANGELOG.md](CHANGELOG.md).
