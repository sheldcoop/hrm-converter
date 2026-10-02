"""Write the consolidated output workbook (Long, Processing_Summary, Validation_Issues)."""

from __future__ import annotations

import os
import re
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

import pandas as pd
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.worksheet.worksheet import Worksheet

from hrm_converter.config import Config
from hrm_converter.hierarchy import is_machine_folder
from hrm_converter.models import (
    FOLDER_CHECK_COLUMNS,
    ISSUE_COLUMNS,
    LONG_SHEET_COLUMNS,
    OPEN_FILE_COLUMN,
    SUMMARY_COLUMNS,
    FileResult,
    Issue,
    LimitValues,
    LongRecord,
    OutputError,
    RunResult,
    Status,
)
from hrm_converter.validation import FOLDER_CATEGORIES, fix_hint, natural_key

EXCEL_MAX_ROWS = 1_048_576
SUMMARY_SHEET = "Processing_Summary"
ISSUES_SHEET = "Validation_Issues"
FOLDER_CHECK_SHEET = "Folder_Check"
_ILLEGAL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_WIDTH_SAMPLE_ROWS = 500
OPEN_FILE_LABEL = "\U0001f4c2 Open"
_LINK_CHUNK = 200
_LINK_FONT = Font(color="0563C1", underline="single")


def resolve_output_path(config: Config, start_path: Path) -> Path:
    """Absolute output path; refuses locations the traversal would read from."""
    path = (Path.cwd() / config.output.directory / config.output.filename).resolve()
    if path.suffix.lower() != ".xlsx":
        raise OutputError(f"Output filename must end with .xlsx: {config.output.filename}")
    start = start_path.resolve()
    if path.is_relative_to(start) and any(
        is_machine_folder(part, config) for part in path.relative_to(start).parts
    ):
        raise OutputError(
            f"Output location '{path}' lies inside a '{config.scope.machine_folder}' source "
            f"folder. Choose an output directory outside the source hierarchy."
        )
    return path


def _clean(value: object) -> object:
    return _ILLEGAL_CHARS.sub(" ", value) if isinstance(value, str) else value


def _frame(rows: Sequence[tuple[object, ...]], columns: tuple[str, ...]) -> pd.DataFrame:
    frame: pd.DataFrame = pd.DataFrame(list(rows), columns=list(columns), dtype=object)
    return frame


def open_file_link(path: str) -> str | None:
    """Excel formula for a clickable cell that opens the source workbook.

    Excel accepts at most 255 characters per text literal, so a long network
    path is passed as several literals joined with ``&``.
    """
    if not path:
        return None
    chunks = [path[i : i + _LINK_CHUNK] for i in range(0, len(path), _LINK_CHUNK)]
    location = "&".join('"' + chunk.replace('"', '""') + '"' for chunk in chunks)
    return f'=HYPERLINK({location},"{OPEN_FILE_LABEL}")'


def long_frame(
    records: list[LongRecord], limits: Sequence[LimitValues] | None = None
) -> pd.DataFrame:
    """The Long sheet: schema columns, Open_File link, then LSL / Target / USL."""
    blank: LimitValues = (None, None, None)
    rows = [
        (
            *record.as_row(),
            open_file_link(record.source_path),
            *(limits[position] if limits else blank),
        )
        for position, record in enumerate(records)
    ]
    return _frame(rows, LONG_SHEET_COLUMNS)


def summary_frame(results: list[FileResult]) -> pd.DataFrame:
    rows = [
        (
            r.candidate.context.project_name,
            r.candidate.context.part_number,
            r.candidate.context.lot_number,
            r.candidate.context.buildup,
            r.candidate.context.process,
            r.candidate.context.panel,
            r.candidate.context.side,
            r.candidate.context.location,
            r.candidate.path.name,
            r.candidate.relative_path,
            r.status.value,
            _clean(r.reason),
            r.row_count,
        )
        for r in results
    ]
    return _frame(rows, SUMMARY_COLUMNS)


def issues_frame(issues: list[Issue]) -> pd.DataFrame:
    rows = [
        (
            i.severity.value,
            i.category,
            i.source_file,
            i.sheet,
            i.field,
            _clean(i.message),
            fix_hint(i.category),
            i.hierarchy_value,
            i.workbook_value,
            i.relative_path,
        )
        for i in issues
    ]
    return _frame(rows, ISSUE_COLUMNS)


def folder_check_frame(result: RunResult) -> pd.DataFrame:
    """One row per lot: is its folder structure usable, and what is wrong with it?"""
    lots: dict[tuple[str, str], dict[str, object]] = {}

    def lot(part: str, number: str) -> dict[str, object]:
        return lots.setdefault(
            (part, number), {"buildups": set(), "processed": 0, "skipped": 0, "problems": Counter()}
        )

    if result.scope is not None:
        for buildup in result.scope.buildups:
            entry = lot(buildup.part_number, buildup.lot_number)
            entry["buildups"].add(buildup.buildup)  # type: ignore[attr-defined]
        for file in result.file_results:
            context = file.candidate.context
            key = "processed" if file.status is Status.PROCESSED else "skipped"
            entry = lot(context.part_number, context.lot_number)
            entry[key] += 1  # type: ignore[operator]
        for issue in result.issues:
            parts = issue.relative_path.split("/")
            if issue.category in FOLDER_CATEGORIES and len(parts) >= 3:
                lot(parts[1], parts[2])["problems"][issue.category] += 1  # type: ignore[index]

    rows = []
    for (part, number), entry in sorted(lots.items(), key=lambda i: tuple(map(natural_key, i[0]))):
        problems: Counter[str] = entry["problems"]  # type: ignore[assignment]
        count = sum(problems.values())
        rows.append(
            (
                part,
                number,
                len(entry["buildups"]),  # type: ignore[arg-type]
                entry["processed"],
                entry["skipped"],
                count,
                "Needs fixing" if count else "OK",
                "; ".join(f"{n} x {category}" for category, n in sorted(problems.items())),
            )
        )
    return _frame(rows, FOLDER_CHECK_COLUMNS)


def format_sheet(sheet: Worksheet, frame: pd.DataFrame, table_name: str) -> None:
    sheet.freeze_panes = "A2"
    last_column = get_column_letter(len(frame.columns))
    reference = f"A1:{last_column}{len(frame) + 1}"
    if len(frame) > 0:
        # An Excel table brings its own header filter.
        table = Table(displayName=table_name, ref=reference)
        table.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
        sheet.add_table(table)
    else:
        sheet.auto_filter.ref = reference
    sample = frame.head(_WIDTH_SAMPLE_ROWS)
    for position, column in enumerate(frame.columns, start=1):
        longest = max([len(str(column))] + [len(str(v)) for v in sample[column] if v is not None])
        sheet.column_dimensions[get_column_letter(position)].width = min(max(longest + 4, 10), 70)


def _style_links(sheet: Worksheet, column: int) -> None:
    """Make the Open_File cells look like links, and keep the column narrow."""
    letter = get_column_letter(column + 1)
    sheet.column_dimensions[letter].width = 12
    for (cell,) in sheet.iter_rows(min_row=2, min_col=column + 1, max_col=column + 1):
        if cell.value:
            cell.font = _LINK_FONT


def write_output(result: RunResult, config: Config, path: Path) -> Path:
    """Write the three sheets as static values and return the workbook path."""
    frames = [
        (config.output.sheet_name, long_frame(result.records, result.record_limits), "tblLong"),
        (SUMMARY_SHEET, summary_frame(result.file_results), "tblProcessingSummary"),
        (ISSUES_SHEET, issues_frame(result.issues), "tblValidationIssues"),
        (FOLDER_CHECK_SHEET, folder_check_frame(result), "tblFolderCheck"),
    ]
    names = [name for name, _, _ in frames]
    if len(set(names)) != len(names) or not 0 < len(config.output.sheet_name) <= 31:
        raise OutputError(
            f"output.sheet_name '{config.output.sheet_name}' must be 1-31 characters and differ "
            f"from '{SUMMARY_SHEET}' and '{ISSUES_SHEET}'."
        )
    if len(result.records) + 1 > EXCEL_MAX_ROWS:
        raise OutputError(
            f"{len(result.records)} rows exceed the Excel limit of {EXCEL_MAX_ROWS - 1} data rows. "
            f"Select a smaller scope (for example one Part Number or Lot)."
        )

    temporary = path.with_name(f".{path.stem}.tmp.xlsx")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with pd.ExcelWriter(temporary, engine="openpyxl") as writer:
            for name, frame, table_name in frames:
                frame.to_excel(writer, sheet_name=name, index=False)
                format_sheet(writer.sheets[name], frame, table_name)
                if OPEN_FILE_COLUMN in frame.columns:
                    _style_links(writer.sheets[name], list(frame.columns).index(OPEN_FILE_COLUMN))
        os.replace(temporary, path)
    except OSError as exc:
        temporary.unlink(missing_ok=True)
        raise OutputError(
            f"Output workbook cannot be written: {path} ({exc}). "
            f"Close the file if it is open in Excel and run again."
        ) from exc
    return path
