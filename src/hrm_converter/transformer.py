"""Turn the raw blocks of one workbook into long-format records.

Value policy (see README, "Error and warning behaviour"):

* blank cell            -> no output row (``skip_blank_metric_values``)
* zero                  -> kept as 0 (``preserve_zero_values``)
* number                -> kept numeric, multiplied by the unit rule's scale
* numeric-looking text  -> converted to a number and reported as a warning
* any other text        -> never converted; not written and reported as an
                           error (``text_value_policy: skip_and_report``) or
                           written unchanged as text (``keep_as_text``)
"""

from __future__ import annotations

from hrm_converter.config import Config
from hrm_converter.models import (
    Candidate,
    CellValue,
    LongRecord,
    RawBlock,
    RawSheet,
    WorkbookReadError,
)
from hrm_converter.schema_detection import (
    Feature,
    MetricColumn,
    detect_feature,
    detect_metrics,
    parse_unit,
)
from hrm_converter.validation import IssueCollector, natural_key


def _to_number(text: str) -> float | None:
    try:
        return float(text.replace(",", "."))
    except ValueError:
        return None


class _FileTransformer:
    def __init__(
        self, sheet: RawSheet, candidate: Candidate, config: Config, issues: IssueCollector
    ) -> None:
        self.sheet = sheet
        self.candidate = candidate
        self.context = candidate.context
        self.config = config
        self.issues = issues
        self.records: list[LongRecord] = []
        self._seen: set[tuple[object, ...]] = set()
        self._reported_duplicates: set[tuple[str, int]] = set()
        self._discovered_features: set[str] = set()
        self._zeros_dropped = 0

    def _details(self, field: str = "") -> dict[str, str]:
        return {
            "source_file": self.candidate.path.name,
            "sheet": self.sheet.sheet_name,
            "field": field,
            "relative_path": self.candidate.relative_path,
        }

    def run(self) -> list[LongRecord]:
        if not self.sheet.blocks:
            raise WorkbookReadError(
                f"No measurement blocks found in sheet '{self.sheet.sheet_name}'."
            )
        if self.sheet.other_sheets:
            self.issues.warning(
                "extra_sheets",
                f"Only the first sheet is processed; ignored sheet(s): "
                f"{', '.join(self.sheet.other_sheets)}",
                **self._details(),
            )
        if self.sheet.stray_rows:
            rows = ", ".join(str(r) for r in self.sheet.stray_rows)
            self.issues.warning(
                "unrecognised_rows",
                f"Row(s) {rows} are neither a header row nor a unit row; ignored.",
                **self._details(),
            )
        for block in self.sheet.blocks:
            self._block(block)
        if self._zeros_dropped:
            self.issues.warning(
                "zero_values_dropped",
                f"{self._zeros_dropped} zero value(s) not written (preserve_zero_values: false).",
                **self._details(),
            )
        return self.records

    def _block(self, block: RawBlock) -> None:
        if block.label is None:
            self.issues.error(
                "missing_feature_label",
                f"Block starting at row {block.start_row} has no feature label in column B; "
                f"block skipped ({len(block.rows)} unit row(s)).",
                **self._details("Feature_Type"),
            )
            return
        feature = detect_feature(block.label, self.config)
        label = f"{feature.feature_type} {feature.feature_number}"
        if not feature.known and feature.feature_type not in self._discovered_features:
            self._discovered_features.add(feature.feature_type)
            self.issues.warning(
                "new_feature_type",
                f"New feature type '{feature.feature_type}' discovered (block label "
                f"'{block.label}'); kept as written. Add it to features.aliases to confirm it.",
                **self._details("Feature_Type"),
            )
        if all(v is None for row in block.rows for v in row.values):
            self.issues.info(
                "empty_block",
                f"Block '{block.label}' has no values; nothing written.",
                **self._details(),
            )
            return

        schema = detect_metrics(block.header, feature.feature_type, self.config)
        if schema.positional_mismatch:
            self.issues.warning(
                "header_order",
                f"Block '{block.label}': header {[h for h in block.header if h]} differs from the "
                f"standard column order; metric names were assigned by position: "
                f"{[c.metric for c in schema.columns]}",
                **self._details("Metric"),
            )
        if schema.duplicates:
            self.issues.warning(
                "duplicate_metric_column",
                f"Block '{block.label}': column(s) {list(schema.duplicates)} appear more than "
                f"once; "
                f"every column was kept under a numbered name.",
                **self._details("Metric"),
            )
        if schema.without_unit:
            self.issues.info(
                "unit_of_measurement",
                f"Block '{block.label}': no unit rule for metric(s) {list(schema.without_unit)}; "
                f"Unit_of_Measurement left blank.",
                **self._details("Unit_of_Measurement"),
            )
        if schema.discovered:
            self.issues.info(
                "new_metric",
                f"Block '{block.label}': metric(s) {list(schema.discovered)} have no alias; "
                f"written under their source names.",
                **self._details("Metric"),
            )

        mapped = {column.index for column in schema.columns}
        orphan_rows = [
            row.excel_row
            for row in block.rows
            if any(v is not None and i not in mapped for i, v in enumerate(row.values))
        ]
        if orphan_rows:
            self.issues.warning(
                "value_without_header",
                f"Block '{block.label}': value(s) in a column without a header in row(s) "
                f"{', '.join(str(r) for r in orphan_rows)}; not written.",
                **self._details("Metric"),
            )

        for row in block.rows:
            unit = parse_unit(row.unit_label, self.context.location)
            if unit is None:
                self.issues.error(
                    "invalid_unit",
                    f"Row {row.excel_row}: unit '{row.unit_label}' cannot be interpreted; "
                    f"row skipped.",
                    **self._details("Unit"),
                )
                continue
            if row.note:
                self.issues.warning(
                    "unit_note",
                    f"Row {row.excel_row} ({label}, unit {unit}): note in column B: '{row.note}'.",
                    **self._details(),
                )
            for column in schema.columns:
                raw = row.values[column.index] if column.index < len(row.values) else None
                self._value(raw, unit, feature, column, row.excel_row)

    def _value(
        self,
        raw: CellValue,
        unit: int | str,
        feature: Feature,
        column: MetricColumn,
        excel_row: int,
    ) -> None:
        processing = self.config.processing
        where = f"Row {excel_row} ({feature.feature_type} {feature.feature_number}, unit {unit})"
        value: CellValue = raw
        if isinstance(raw, str):
            number = _to_number(raw) if processing.coerce_numeric_text else None
            if number is not None:
                self.issues.warning(
                    "numeric_text",
                    f"{where}: '{column.metric}' is stored as text ('{raw}'); "
                    f"converted to a number.",
                    **self._details(column.metric),
                )
                value = number
            elif processing.text_value_policy == "keep_as_text":
                self.issues.warning(
                    "text_value",
                    f"{where}: '{column.metric}' is not a number ('{raw}'); written as text.",
                    **self._details(column.metric),
                )
            else:
                self.issues.error(
                    "text_value",
                    f"{where}: '{column.metric}' is not a number ('{raw}'); value not written.",
                    **self._details(column.metric),
                )
                return
        if value is None and processing.skip_blank_metric_values:
            return
        if isinstance(value, int | float):
            if value == 0 and not processing.preserve_zero_values:
                self._zeros_dropped += 1
                return
            if column.scale != 1.0:
                value = value * column.scale

        key = (unit, feature.feature_type, feature.feature_number, column.metric)
        if key in self._seen:
            block_key = (feature.feature_type, feature.feature_number)
            if block_key not in self._reported_duplicates:
                self._reported_duplicates.add(block_key)
                self.issues.warning(
                    "duplicate_measurement",
                    f"{feature.feature_type} {feature.feature_number} has more than one value for "
                    f"the same unit and metric; all values were kept and none was aggregated.",
                    **self._details(column.metric),
                )
        self._seen.add(key)

        ctx = self.context
        self.records.append(
            LongRecord(
                project_name=ctx.project_name,
                part_number=ctx.part_number,
                lot_number=ctx.lot_number,
                lot_name=ctx.lot_name,
                buildup=ctx.buildup,
                process=ctx.process,
                panel=ctx.panel,
                side=ctx.side,
                location=ctx.location,
                unit=unit,
                feature_type=feature.feature_type,
                feature_number=feature.feature_number,
                metric=column.metric,
                value=value,
                unit_of_measurement=column.unit,
                source_file=self.candidate.path.name,
            )
        )


def transform(
    sheet: RawSheet, candidate: Candidate, config: Config, issues: IssueCollector
) -> list[LongRecord]:
    """Unpivot every block of one workbook into long-format records."""
    return _FileTransformer(sheet, candidate, config, issues).run()


def sort_records(records: list[LongRecord]) -> list[LongRecord]:
    """Stable natural-order sort; ties keep their source order."""
    return sorted(
        records,
        key=lambda r: tuple(
            natural_key(v)
            for v in (
                r.project_name,
                r.part_number,
                r.lot_number,
                r.buildup,
                r.process,
                r.panel,
                r.side,
                r.location,
                r.unit,
                r.feature_type,
                r.feature_number,
                r.metric,
                r.source_file,
            )
        ),
    )
