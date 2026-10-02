"""Typed domain models shared by all modules."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

CellValue = int | float | str | None

LONG_COLUMNS: tuple[str, ...] = (
    "Project_Name",
    "Part_Number",
    "Lot_Number",
    "Lot_Name",
    "Buildup",
    "Process",
    "Panel",
    "Side",
    "Location",
    "Unit",
    "Feature_Type",
    "Feature_Number",
    "Metric",
    "Value",
    "Unit_of_Measurement",
    "Source_File",
)

# The Long sheet: the schema columns with the limits placed right after the value
# (LSL / Target / USL; blank when no reference workbook was given or no row of it fits),
# and Source_File plus a clickable link that opens the source workbook at the very end.
OPEN_FILE_COLUMN = "Open_File"
LONG_LIMIT_COLUMNS: tuple[str, ...] = ("LSL", "Target", "USL")
LONG_SHEET_COLUMNS: tuple[str, ...] = (
    *LONG_COLUMNS[:-1],
    *LONG_LIMIT_COLUMNS,
    LONG_COLUMNS[-1],
    OPEN_FILE_COLUMN,
)

FIX_PLAN_COLUMNS: tuple[str, ...] = ("Action", "From", "To", "Reason")
LimitValues = tuple[float | None, float | None, float | None]

SUMMARY_COLUMNS: tuple[str, ...] = (
    "Project_Name",
    "Part_Number",
    "Lot_Number",
    "Buildup",
    "Process",
    "Panel",
    "Side",
    "Location",
    "Source_File",
    "Relative_Path",
    "Status",
    "Reason",
    "Row_Count",
)

ISSUE_COLUMNS: tuple[str, ...] = (
    "Severity",
    "Category",
    "Source_File",
    "Sheet",
    "Field",
    "Message",
    "How_To_Fix",
    "Hierarchy_Value",
    "Workbook_Value",
    "Relative_Path",
)


FOLDER_CHECK_COLUMNS: tuple[str, ...] = (
    "Part_Number",
    "Lot_Number",
    "Buildups",
    "Workbooks_Processed",
    "Workbooks_Skipped",
    "Folder_Problems",
    "Verdict",
    "Problems",
)


class HrmConverterError(Exception):
    """Base class for errors that stop the whole run with a clear message."""


class ConfigError(HrmConverterError):
    """The configuration file is missing, unreadable or invalid."""


class HierarchyError(HrmConverterError):
    """The selected folder does not fit the expected engineering hierarchy."""


class OutputError(HrmConverterError):
    """The output workbook cannot be written safely."""


class WorkbookReadError(Exception):
    """One workbook cannot be opened or contains no readable measurement blocks."""


@dataclass(frozen=True)
class FixProposal:
    """One safe, reviewable repair of the folder structure (never applied by the app)."""

    action: str  # "Rename folder" or "Move file"
    source: Path
    target: Path
    reason: str


class FolderRole(str, Enum):
    PROJECT = "Project"
    PART_NUMBER = "Part Number"
    LOT_NUMBER = "Lot Number"
    BUILDUP = "Buildup"


class Severity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


class Status(str, Enum):
    PROCESSED = "Processed"
    SKIPPED = "Skipped"


@dataclass(frozen=True)
class Issue:
    """One structured warning or error (a row of the Validation_Issues sheet)."""

    severity: Severity
    category: str
    message: str
    source_file: str = ""
    sheet: str = ""
    field: str = ""
    hierarchy_value: str = ""
    workbook_value: str = ""
    relative_path: str = ""


@dataclass(frozen=True)
class BuildupFolder:
    """A Buildup folder inside the selected scope, with its reconstructed parents."""

    path: Path
    project_name: str
    part_number: str
    lot_number: str
    buildup: str
    buildup_folder: str


@dataclass(frozen=True)
class Scope:
    """Result of role detection for the folder selected by the user."""

    start_path: Path
    role: FolderRole
    project_path: Path
    buildups: tuple[BuildupFolder, ...]


@dataclass(frozen=True)
class WorkbookContext:
    """All hierarchy-derived metadata for one side/location folder."""

    project_name: str
    part_number: str
    lot_number: str
    lot_name: str
    buildup: str
    process: str
    process_folder: str
    panel: int | str  # '' for loose files without a folder hierarchy
    side: str
    location: str
    folder: Path
    relative_folder: str


@dataclass(frozen=True)
class Candidate:
    """One candidate HRM workbook found during traversal."""

    path: Path
    context: WorkbookContext
    skip_reason: str | None = None

    @property
    def relative_path(self) -> str:
        return f"{self.context.relative_folder}/{self.path.name}"


@dataclass(frozen=True)
class RawRow:
    """One unit row of a block, exactly as stored in the sheet."""

    excel_row: int
    unit_label: str
    note: str | None
    values: tuple[CellValue, ...]


@dataclass(frozen=True)
class RawBlock:
    """One stacked measurement block of the HRM summary sheet."""

    start_row: int
    label: str | None
    header: tuple[str | None, ...]
    rows: tuple[RawRow, ...]


@dataclass(frozen=True)
class RawSheet:
    sheet_name: str
    blocks: tuple[RawBlock, ...]
    stray_rows: tuple[int, ...]
    other_sheets: tuple[str, ...]


@dataclass(frozen=True)
class LongRecord:
    """One output row: one metric value of one feature on one unit."""

    project_name: str
    part_number: str
    lot_number: str
    lot_name: str
    buildup: str
    process: str
    panel: int | str  # '' for loose files without a folder hierarchy
    side: str
    location: str
    unit: int | str
    feature_type: str
    feature_number: int
    metric: str
    value: CellValue
    unit_of_measurement: str
    source_file: str
    source_path: str = ""  # full path for the Open_File link; '' for uploads

    def as_row(self) -> tuple[CellValue, ...]:
        return (
            self.project_name,
            self.part_number,
            self.lot_number,
            self.lot_name,
            self.buildup,
            self.process,
            self.panel,
            self.side,
            self.location,
            self.unit,
            self.feature_type,
            self.feature_number,
            self.metric,
            self.value,
            self.unit_of_measurement,
            self.source_file,
        )


@dataclass(frozen=True)
class FileResult:
    """One row of the Processing_Summary sheet."""

    candidate: Candidate
    status: Status
    reason: str
    row_count: int


@dataclass
class RunResult:
    """Everything a run produced; consumed by the output writer and the CLI."""

    scope: Scope | None  # None for loose files without a folder hierarchy
    records: list[LongRecord] = field(default_factory=list)
    record_limits: list[LimitValues] = field(default_factory=list)  # parallel to records
    fix_plan: list[FixProposal] = field(default_factory=list)
    fix_script_path: Path | None = None
    file_results: list[FileResult] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    hrm_folder_count: int = 0
    output_path: Path | None = None
    log_path: Path | None = None

    @property
    def processed_count(self) -> int:
        return sum(1 for r in self.file_results if r.status is Status.PROCESSED)

    @property
    def skipped_count(self) -> int:
        return sum(1 for r in self.file_results if r.status is Status.SKIPPED)

    @property
    def warning_count(self) -> int:
        return sum(1 for i in self.issues if i.severity is Severity.WARNING)

    @property
    def error_count(self) -> int:
        return sum(1 for i in self.issues if i.severity is Severity.ERROR)
