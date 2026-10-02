"""Reference limits (LSL / Target / USL) maintained by the user in one Excel sheet.

Layout of the reference sheet (default sheet name ``Limits``)::

    Part_Number | Buildup | Side | Feature_Type | Feature_Number | Metric | LSL | Target | USL

* ``Feature_Type`` and ``Metric`` are required on every row.
* Every other key column is optional. A **blank cell means "applies to all"**,
  so one row can cover every Buildup, or every Pad number.
* When several rows fit a measurement, the **most specific** row wins (the one
  with the most key cells filled in). Two equally specific rows with different
  limits are a conflict: it is reported and no limit is applied.
* Limits are in the unit of the long table's ``Value`` column (roughness: nm).

Any long-format key column may be used as a key column (``KEY_COLUMNS``).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import IO

import pandas as pd

from hrm_converter.config import Config, normalize_key
from hrm_converter.hierarchy import parse_buildup
from hrm_converter.models import HrmConverterError
from hrm_converter.validation import IssueCollector

KEY_COLUMNS: tuple[str, ...] = (
    "Project_Name",
    "Part_Number",
    "Lot_Number",
    "Buildup",
    "Process",
    "Panel",
    "Side",
    "Location",
    "Feature_Type",
    "Feature_Number",
    "Metric",
)
REQUIRED_KEYS: tuple[str, ...] = ("Feature_Type", "Metric")
LIMIT_COLUMNS: tuple[str, ...] = ("LSL", "Target", "USL")
TEMPLATE_COLUMNS: tuple[str, ...] = (
    "Part_Number",
    "Buildup",
    "Side",
    "Feature_Type",
    "Feature_Number",
    "Metric",
    "LSL",
    "Target",
    "USL",
    "Unit_of_Measurement",
    "Comment",
)


class ReferenceFileError(HrmConverterError):
    """The reference workbook cannot be read or has no usable layout."""


@dataclass(frozen=True)
class Limits:
    lsl: float | None = None
    target: float | None = None
    usl: float | None = None

    def is_empty(self) -> bool:
        return self.lsl is None and self.target is None and self.usl is None


@dataclass(frozen=True)
class LimitRule:
    """One row of the reference sheet; ``keys`` holds only the filled-in cells."""

    excel_row: int
    keys: tuple[tuple[str, str], ...]
    limits: Limits

    @property
    def specificity(self) -> int:
        return len(self.keys)


@dataclass
class Reference:
    source: str
    key_columns: tuple[str, ...]
    rules: list[LimitRule]
    frame: pd.DataFrame
    matched: dict[int, int] = field(default_factory=dict)
    conflicts: set[tuple[int, ...]] = field(default_factory=set)


def is_blank(value: object) -> bool:
    return (
        value is None or (isinstance(value, float) and pd.isna(value)) or str(value).strip() == ""
    )


def normalize_value(column: str, value: object, config: Config) -> str:
    """Comparable form of one key value, so 'BU03' meets 'BU-03' and 'pad' meets 'Pad'."""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    if column == "Buildup":
        text = parse_buildup(text, config) or text
    elif column == "Feature_Type":
        text = config.features.aliases.get(normalize_key(text), text)
    elif column == "Metric":
        text = config.metrics.aliases.get(normalize_key(text), text)
    elif column in ("Feature_Number", "Panel") and text.isdigit():
        text = str(int(text))
    return normalize_key(text)


def _number(value: object) -> float | None:
    if is_blank(value):
        return None
    if isinstance(value, bool):
        raise ValueError(str(value))
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value).strip().replace(",", "."))
    except ValueError:
        raise ValueError(str(value).strip()) from None


def _columns(frame: pd.DataFrame) -> dict[str, str]:
    """Map canonical column names to the headers actually used in the sheet."""
    wanted = {normalize_key(name): name for name in (*KEY_COLUMNS, *LIMIT_COLUMNS)}
    found: dict[str, str] = {}
    for header in frame.columns:
        canonical = wanted.get(normalize_key(header))
        if canonical is not None and canonical not in found:
            found[canonical] = str(header)
    return found


def parse_reference(
    frame: pd.DataFrame, source: str, config: Config, issues: IssueCollector
) -> Reference:
    """Validate a reference table and turn its rows into limit rules."""
    columns = _columns(frame)
    missing = [name for name in REQUIRED_KEYS if name not in columns]
    if missing or not any(name in columns for name in LIMIT_COLUMNS):
        raise ReferenceFileError(
            f"Reference '{source}' needs the columns Feature_Type and Metric and at least one "
            f"of LSL, Target, USL. Found: {', '.join(str(c) for c in frame.columns) or 'none'}."
        )
    key_columns = tuple(name for name in KEY_COLUMNS if name in columns)
    rules: list[LimitRule] = []

    def report(row: int, message: str, column: str = "") -> None:
        issues.error(
            "reference_row", f"Row {row}: {message} Row ignored.", source_file=source, field=column
        )

    for position, (_, raw) in enumerate(frame.iterrows()):
        excel_row = position + 2
        if all(is_blank(raw[header]) for header in columns.values()):
            continue
        blank_required = [name for name in REQUIRED_KEYS if is_blank(raw[columns[name]])]
        if blank_required:
            report(
                excel_row, f"{' and '.join(blank_required)} must be filled in.", blank_required[0]
            )
            continue
        try:
            numbers = {
                name: _number(raw[columns[name]]) if name in columns else None
                for name in LIMIT_COLUMNS
            }
        except ValueError as exc:
            report(excel_row, f"a limit is not a number ('{exc}').")
            continue
        limits = Limits(numbers["LSL"], numbers["Target"], numbers["USL"])
        if limits.is_empty():
            issues.warning(
                "reference_row",
                f"Row {excel_row}: no LSL, Target or USL filled in. Row ignored.",
                source_file=source,
            )
            continue
        if limits.lsl is not None and limits.usl is not None and limits.lsl > limits.usl:
            report(excel_row, f"LSL ({limits.lsl:g}) is greater than USL ({limits.usl:g}).", "LSL")
            continue
        keys = tuple(
            (name, normalize_value(name, raw[columns[name]], config))
            for name in key_columns
            if not is_blank(raw[columns[name]])
        )
        rules.append(LimitRule(excel_row, keys, limits))

    return Reference(source, key_columns, rules, frame)


def load_reference(
    source: Path | IO[bytes], config: Config, issues: IssueCollector, name: str | None = None
) -> Reference:
    """Read the reference workbook (sheet ``wide.reference_sheet``, else the first sheet).

    ``source`` is a path, or an open binary file such as an upload; ``name`` labels it in issues.
    """
    label = name or (source.name if isinstance(source, Path) else "reference")
    try:
        sheets = pd.read_excel(source, sheet_name=None, dtype=object)
    except Exception as exc:
        raise ReferenceFileError(
            f"Reference workbook cannot be read: {label} ({type(exc).__name__}: {exc})"
        ) from exc
    wanted = normalize_key(config.wide.reference_sheet)
    sheet = next((n for n in sheets if normalize_key(n) == wanted), next(iter(sheets)))
    return parse_reference(sheets[sheet], f"{label} [{sheet}]", config, issues)


def find_limits(
    reference: Reference, row: dict[str, str], issues: IssueCollector, label: str
) -> Limits:
    """Limits for one measurement group; ``row`` holds normalised key values."""
    fitting = [
        rule for rule in reference.rules if all(row.get(name) == value for name, value in rule.keys)
    ]
    if not fitting:
        return Limits()
    best = max(rule.specificity for rule in fitting)
    winners = [rule for rule in fitting if rule.specificity == best]
    if len({rule.limits for rule in winners}) > 1:
        conflict = tuple(rule.excel_row for rule in winners)
        if conflict in reference.conflicts:  # report each clash of rows once
            return Limits()
        reference.conflicts.add(conflict)
        rows = ", ".join(str(row) for row in conflict)
        issues.error(
            "reference_conflict",
            f"{label}: reference rows {rows} fit equally well but give different limits; "
            f"no limit applied. Make one of them more specific.",
            source_file=reference.source,
        )
        return Limits()
    for rule in winners:
        reference.matched[rule.excel_row] = reference.matched.get(rule.excel_row, 0) + 1
    return winners[0].limits


def reference_template(long: pd.DataFrame) -> pd.DataFrame:
    """A starter reference: one row per Part Number, feature type and metric found.

    Buildup, Side and Feature_Number are left blank (= applies to all); fill
    them in, or copy a row, where limits differ.
    """
    found = long[["Part_Number", "Feature_Type", "Metric", "Unit_of_Measurement"]].drop_duplicates()
    rows = [
        {
            "Part_Number": item.Part_Number,
            "Feature_Type": item.Feature_Type,
            "Metric": item.Metric,
            "Unit_of_Measurement": item.Unit_of_Measurement,
        }
        for item in found.itertuples(index=False)
    ]
    template: pd.DataFrame = pd.DataFrame(rows, columns=list(TEMPLATE_COLUMNS), dtype=object)
    return template
