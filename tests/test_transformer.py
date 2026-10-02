"""Long-format transformation: unpivoting, value policy and ordering."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import ConfigFactory
from hrm_converter.config import Config
from hrm_converter.models import (
    Candidate,
    CellValue,
    LongRecord,
    RawSheet,
    Severity,
    WorkbookContext,
    WorkbookReadError,
)
from hrm_converter.transformer import sort_records, transform
from hrm_converter.validation import IssueCollector
from hrm_converter.workbook_reader import parse_rows

Rows = list[tuple[object, ...]]


def candidate(location: str = "Unit", panel: int = 2) -> Candidate:
    context = WorkbookContext(
        project_name="SYN_Project",
        part_number="SYN-PART",
        lot_number="90001",
        lot_name="Synthetic Lot",
        buildup="BU-01",
        process="Post AAA",
        process_folder="post AAA_HRM-2099-0001",
        panel=panel,
        side="Front",
        location=location,
        folder=Path("front"),
        relative_folder="SYN_Project/SYN-PART/90001/BU01/HRM/post AAA_HRM-2099-0001/Panel 2/front",
    )
    return Candidate(Path("front/synthetic_Summary.xlsx"), context)


def run(
    rows: Rows, config: Config, location: str = "Unit"
) -> tuple[list[LongRecord], IssueCollector]:
    blocks, stray = parse_rows(rows)
    issues = IssueCollector()
    records = transform(
        RawSheet("SYN_Sheet", blocks, stray, ()), candidate(location), config, issues
    )
    return records, issues


def values(records: list[LongRecord]) -> dict[tuple[object, str], CellValue]:
    return {(r.unit, r.metric): r.value for r in records}


def test_one_row_per_metric_value(config: Config) -> None:
    records, issues = run(
        [(None, None, "Width", "Space"), ("Unit 1", "Trace 2", 25.3, 15.5)], config
    )
    assert [(r.feature_type, r.feature_number, r.metric, r.value) for r in records] == [
        ("Trace", 2, "Width", 25.3),
        ("Trace", 2, "Space", 15.5),
    ]
    first = records[0]
    assert (first.project_name, first.part_number, first.lot_number, first.lot_name) == (
        "SYN_Project",
        "SYN-PART",
        "90001",
        "Synthetic Lot",
    )
    assert (first.buildup, first.process, first.panel, first.side, first.location) == (
        "BU-01",
        "Post AAA",
        2,
        "Front",
        "Unit",
    )
    assert (first.unit, first.unit_of_measurement, first.source_file) == (
        1,
        "µm",
        "synthetic_Summary.xlsx",
    )
    assert issues.reportable() == []


def test_new_metric_columns_are_unpivoted_automatically(config: Config) -> None:
    records, issues = run(
        [
            (None, None, "Distance 1", "Distance 2", "Angle", "Area"),
            ("Unit 3", "Fiducial 1", 1, 2, 3, 4),
        ],
        config,
    )
    assert [r.metric for r in records] == ["Distance 1", "Distance 2", "Angle", "Area"]
    assert {r.feature_type for r in records} == {"Fiducial"}
    assert {r.unit_of_measurement for r in records} == {""}
    assert [i.category for i in issues.reportable()] == ["new_feature_type"]


def test_blank_cells_give_no_rows_and_zero_is_preserved(config: Config) -> None:
    records, _ = run(
        [
            (None, None, "Dimple", "Bump"),
            ("Unit 1", "via 1", None, 0),
            ("Unit 2", None, "   ", 0.0),
        ],
        config,
    )
    assert values(records) == {(1, "Bump"): 0, (2, "Bump"): 0.0}


def test_text_is_never_converted_to_zero(config: Config) -> None:
    records, issues = run([(None, None, "Dimple", "Bump"), ("Unit 1", "via 1", "n/a", 1.5)], config)
    assert values(records) == {(1, "Bump"): 1.5}
    errors = [i for i in issues.reportable() if i.severity is Severity.ERROR]
    assert [(i.category, i.field) for i in errors] == [("text_value", "Dimple")]
    assert "'n/a'" in errors[0].message


def test_text_can_be_kept_when_configured(make_config: ConfigFactory) -> None:
    config = make_config(processing={"text_value_policy": "keep_as_text"})
    records, issues = run([(None, None, "Dimple"), ("Unit 1", "via 1", "n/a")], config)
    assert values(records) == {(1, "Dimple"): "n/a"}
    assert [i.severity for i in issues.reportable()] == [Severity.WARNING]


def test_numeric_text_is_converted_with_a_warning(config: Config) -> None:
    records, issues = run(
        [(None, None, "Dimple", "Bump"), ("Unit 1", "via 1", "12,5", "3.25")], config
    )
    assert values(records) == {(1, "Dimple"): 12.5, (1, "Bump"): 3.25}
    assert [i.category for i in issues.reportable()] == ["numeric_text", "numeric_text"]


def test_roughness_is_converted_to_nm_by_position(config: Config) -> None:
    operator_header = [
        "Rz max",
        "Rz mean",
        "Rz min",
        "Rz max",
        "Ra mean",
        "Ra Std dev",
        "Ra min",
        "Ra max",
    ]
    header = (None, None, *operator_header)
    records, issues = run(
        [header, ("Unit 7", "roughness", 0.75, 0.07, 0.5, 0.9, 0.125, 0.007, 0.09, 0.12)], config
    )
    assert values(records)[(7, "Rz_Mean")] == pytest.approx(750.0)
    assert values(records)[(7, "Rz_Std_dev")] == pytest.approx(70.0)
    assert values(records)[(7, "Rz_Max")] == pytest.approx(900.0)
    assert values(records)[(7, "Ra_Mean")] == pytest.approx(125.0)
    assert {r.unit_of_measurement for r in records} == {"nm"}
    assert {(r.feature_type, r.feature_number) for r in records} == {("Roughness", 1)}
    assert [i.category for i in issues.reportable()] == ["header_order"]


def test_coupon_units_get_a_c_prefix(config: Config) -> None:
    records, _ = run(
        [(None, None, "Dimple"), ("Unit 1", "via 1", 1.0), ("Unit 2", None, 2.0)], config, "Coupon"
    )
    assert [r.unit for r in records] == ["C1", "C2"]
    assert {r.location for r in records} == {"Coupon"}


def test_duplicate_measurements_are_kept_not_aggregated(config: Config) -> None:
    records, issues = run(
        [
            (None, None, "Dimple"),
            ("Unit 1", "via 1", 1.0),
            (None, None, "Dimple"),
            ("Unit 1", "via 1", 2.0),
        ],
        config,
    )
    assert [r.value for r in records] == [1.0, 2.0]
    assert [i.category for i in issues.reportable()] == ["duplicate_measurement"]


def test_block_without_label_is_reported_not_guessed(config: Config) -> None:
    records, issues = run(
        [
            (None, None, "Dimple"),
            ("Unit 1", None, 1.0),
            (None, None, "Dimple"),
            ("Unit 1", "via 1", 2.0),
        ],
        config,
    )
    assert [r.value for r in records] == [2.0]
    assert [i.category for i in issues.reportable()] == ["missing_feature_label"]


def test_values_without_header_and_notes_are_reported(config: Config) -> None:
    records, issues = run(
        [(None, None, "Dimple"), ("Unit 1", "via 1", 1.0, 99.0), ("Unit 2", "scratched", None)],
        config,
    )
    assert values(records) == {(1, "Dimple"): 1.0}
    assert [i.category for i in issues.reportable()] == ["value_without_header", "unit_note"]


def test_sheet_without_blocks_is_an_error(config: Config) -> None:
    with pytest.raises(WorkbookReadError, match="No measurement blocks"):
        run([("just text", None, None)], config)


def test_sorting_is_natural_and_stable(config: Config) -> None:
    rows: Rows = [(None, None, "Dimple")]
    rows += [(f"Unit {u}", "via 1" if i == 0 else None, float(u)) for i, u in enumerate((10, 2, 1))]
    unit_records, _ = run(rows, config)
    coupon_records, _ = run(rows, config, "Coupon")
    ordered = sort_records(coupon_records + unit_records)
    assert [r.unit for r in ordered] == ["C1", "C2", "C10", 1, 2, 10]  # Location: Coupon < Unit
    assert sort_records(list(reversed(ordered))) == ordered
