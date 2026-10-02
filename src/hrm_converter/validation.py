"""Issue collection, natural sorting and hierarchy-vs-workbook cross-checks."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from hrm_converter.config import Config, normalize_key
from hrm_converter.models import Issue, Severity, WorkbookContext

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
