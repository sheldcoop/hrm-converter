"""Issue collection, natural sorting and hierarchy-vs-workbook cross-checks."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from hrm_converter.config import Config, normalize_key
from hrm_converter.models import FixProposal, Issue, Severity, WorkbookContext

logger = logging.getLogger(__name__)

_BUILDUP_TOKEN = re.compile(r"(?<![A-Za-z0-9])BU[\s\-_]?0*(\d+)(?!\d)", re.IGNORECASE)
_DIGITS = re.compile(r"(\d+)")

NaturalKey = tuple[tuple[int, int, str], ...]


def natural_key(value: object) -> NaturalKey:
    """Sort key where 'BU-2' precedes 'BU-10' and numbers precede text."""
    if isinstance(value, bool):
        value = str(value)
    if isinstance(value, int):
        return ((0, value, ""),)
    parts = _DIGITS.split(str(value).strip().lower())
    return tuple((0, int(p), "") if p.isdigit() else (1, 0, p) for p in parts if p != "")


class IssueCollector:
    """Collects structured issues and mirrors them to the log file."""

    def __init__(self) -> None:
        self._issues: list[Issue] = []
        self.proposals: list[FixProposal] = []  # safe folder repairs, for the fix plan

    def add(self, issue: Issue) -> None:
        self._issues.append(issue)
        level = {
            Severity.INFO: logging.INFO,
            Severity.WARNING: logging.WARNING,
            Severity.ERROR: logging.ERROR,
        }[issue.severity]
        where = " | ".join(p for p in (issue.relative_path, issue.sheet, issue.field) if p)
        logger.log(
            level, "[%s] %s%s", issue.category, f"{where} | " if where else "", issue.message
        )

    def info(self, category: str, message: str, **details: str) -> None:
        self.add(Issue(Severity.INFO, category, message, **details))

    def warning(self, category: str, message: str, **details: str) -> None:
        self.add(Issue(Severity.WARNING, category, message, **details))

    def error(self, category: str, message: str, **details: str) -> None:
        self.add(Issue(Severity.ERROR, category, message, **details))

    def count(self, severity: Severity) -> int:
        return sum(1 for issue in self._issues if issue.severity is severity)

    def reportable(self) -> list[Issue]:
        """Warnings and errors, in the order they occurred (INFO stays in the log)."""
        return [i for i in self._issues if i.severity is not Severity.INFO]

    def all(self) -> list[Issue]:
        return list(self._issues)


@dataclass(frozen=True)
class Conflict:
    field: str
    hierarchy_value: str
    workbook_value: str
    source: str


def _buildup_numbers(text: str) -> set[int]:
    return {int(m.group(1)) for m in _BUILDUP_TOKEN.finditer(text)}


def _sides(text: str, config: Config) -> set[str]:
    found: set[str] = set()
    for key, side in config.hierarchy.sides.items():
        if re.search(rf"(?<![A-Za-z]){re.escape(key)}(?![A-Za-z])", text, re.IGNORECASE):
            found.add(side)
    return found


def find_conflicts(
    context: WorkbookContext, sheet_name: str, file_name: str, config: Config
) -> list[Conflict]:
    """Compare hierarchy metadata with what the sheet name and file name state.

    HRM summary sheets carry no metadata columns, so the sheet name and the
    file name are the only independent workbook-side evidence. A field is only
    compared when the name states it unambiguously.
    """
    conflicts: list[Conflict] = []
    hierarchy_buildup = _buildup_numbers(context.buildup)

    for source, text in (("sheet name", sheet_name), ("file name", file_name)):
        numbers = _buildup_numbers(text)
        if len(numbers) == 1 and hierarchy_buildup and numbers != hierarchy_buildup:
            conflicts.append(
                Conflict("Buildup", context.buildup, f"BU{next(iter(numbers)):02d}", source)
            )
        sides = _sides(text, config)
        if len(sides) == 1 and context.side not in sides:
            conflicts.append(Conflict("Side", context.side, next(iter(sides)), source))

    pattern = config.cross_check.sheet_part_number_pattern
    if pattern is not None:
        match = pattern.search(sheet_name)
        if match:
            stated = match.group("part_number").strip()
            if normalize_key(stated) != normalize_key(context.part_number):
                conflicts.append(Conflict("Part_Number", context.part_number, stated, "sheet name"))
    return conflicts


EXPECTED_LAYOUT = "<Buildup>/HRM/<process>/Panel <n>/front|back|Coupon front|Coupon back/<file>"

# Plain-language repair advice per issue category (the How_To_Fix column).
FIX_HINTS: dict[str, str] = {
    "missing_hrm_folder": "Create an 'HRM' folder inside this Buildup folder and move the HRM "
    "process folders into it. Ignore this if the Buildup has no HRM measurements yet.",
    "invalid_buildup_name": "Rename the folder that contains 'HRM' to a Buildup name such as "
    "BU01 or BU-03.",
    "duplicate_hrm_folder": "Keep one 'HRM' folder in this Buildup and merge the others into it.",
    "empty_folder": "Add the missing sub-folders and workbooks, or delete the empty folder.",
    "missing_process_folder": "Add a process folder between HRM and the panel folder, for "
    "example HRM/post DDV_HRM-2026-0088/Panel 5.",
    "missing_panel_folder": "Add a panel folder between the process folder and the side "
    "folder, for example post DDV_HRM-2026-0088/Panel 5/front.",
    "invalid_panel_folder": "Rename the folder to 'Panel <number>', for example 'Panel 5'.",
    "invalid_side_folder": "Rename the folder to front, back, Coupon front or Coupon back.",
    "misplaced_workbook": "Move the Excel file into its side folder: " + EXPECTED_LAYOUT + ".",
    "no_workbook": "Put the HRM *_Summary.xlsx file into this side folder, or delete the folder.",
    "multiple_workbooks": "Leave exactly one workbook in this side folder; move the others out.",
    "filename_pattern": "Rename the file so it ends with _Summary.xlsx if it is the HRM summary; "
    "otherwise leave it, it is ignored.",
    "process_fallback": "Rename the process folder like 'post DDV_HRM-2026-0088' for a clean "
    "Process name. Optional: the folder name is used as it is.",
    "metadata_conflict": "The file name or sheet name contradicts the folder. Move the file to "
    "the folder it belongs to, or rename the folder; if the folder is right, untick the "
    "skip option (permissive mode).",
    "unreadable_workbook": "Open the file in Excel and save it again as .xlsx, or export it "
    "again from HRM. Remove any password.",
    "unreadable_folder": "Check that you have permission to open this folder.",
    "missing_feature_label": "Type the feature label (for example 'Pad 1') in column B of the "
    "first row of the block.",
    "new_feature_type": "Nothing to fix if the label is right. Add it to features.aliases in "
    "config.yaml to stop this warning; correct a typo in the workbook otherwise.",
    "header_order": "Nothing to fix in the data: names were assigned by position. Correct the "
    "roughness header in the HRM template to stop this warning.",
    "duplicate_metric_column": "Remove or rename the repeated column header in the block.",
    "duplicate_measurement": "The same block label appears twice. Renumber one block "
    "(for example Pad 1 and Pad 2) or delete the repeat.",
    "value_without_header": "Add a header above the extra value column, or delete the values.",
    "unrecognised_rows": "Remove title or comment rows, or ignore: they are not read.",
    "unit_note": "Nothing to fix: the operator's note is only reported.",
    "text_value": "Replace the text with a number, or empty the cell if it was not measured.",
    "numeric_text": "Format the cell as a number (use a decimal point). The value was still read.",
    "invalid_unit": "Write the unit in column A as 'Unit <number>'.",
    "extra_sheets": "Only the first sheet is read. Move the summary to the first sheet if it "
    "is not there.",
    "duplicate_file_name": "Rename one of the files so every uploaded file has its own name.",
    "value_order": "Check the Min, Mean and Max cells of this unit in the workbook: they are "
    "out of order (often two columns swapped or a typing mistake).",
    "negative_value": "Check this value in the workbook. If negative values are normal for this "
    "metric, set quality.negative_check to false in config.yaml.",
    "suspicious_value": "Check this value in the workbook: a decimal point, a unit or a column "
    "may be wrong. If it is real, nothing needs fixing.",
    "duplicate_workbook": "The same workbook content is stored in two places. Delete the copy "
    "that is in the wrong folder; both were converted in the meantime.",
    "reference_row": "Correct this row in the limits workbook.",
    "reference_conflict": "Fill in one more key cell on one of the clashing limit rows so it "
    "becomes the more specific one.",
    "reference_unused": "Check the spelling of Feature_Type, Metric, Part_Number, Buildup and "
    "Side on these limit rows.",
}

# Categories that mean "the folders or files are not laid out as expected".
FOLDER_CATEGORIES = frozenset(
    {
        "missing_hrm_folder",
        "invalid_buildup_name",
        "duplicate_hrm_folder",
        "empty_folder",
        "missing_process_folder",
        "missing_panel_folder",
        "invalid_panel_folder",
        "invalid_side_folder",
        "misplaced_workbook",
        "no_workbook",
        "multiple_workbooks",
        "metadata_conflict",
        "unreadable_folder",
        "duplicate_workbook",
    }
)


def fix_hint(category: str) -> str:
    return FIX_HINTS.get(category, "")
