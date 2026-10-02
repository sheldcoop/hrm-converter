"""Block parsing plus dynamic feature, metric and unit detection."""

from __future__ import annotations

import pytest

from conftest import ConfigFactory
from hrm_converter.config import Config
from hrm_converter.schema_detection import (
    detect_feature,
    detect_metrics,
    parse_unit,
    split_label,
)
from hrm_converter.workbook_reader import parse_rows

# The header exactly as an operator typed it in a real file: wrong names, right positions.
OPERATOR_ROUGHNESS = [
    "Rz max",
    "Rz mean",
    "Rz min",
    "Rz max",
    "Ra mean",
    "Ra Std dev",
    "Ra min",
    "Ra max",
]
STANDARD_ROUGHNESS = [
    "Rz_Mean",
    "Rz_Std_dev",
    "Rz_Min",
    "Rz_Max",
    "Ra_Mean",
    "Ra_Std_dev",
    "Ra_Min",
    "Ra_Max",
]


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Pad 1", ("Pad", 1)),
        ("SR Pad 2", ("SR Pad", 2)),
        ("Pad Pos 3", ("Pad Pos", 3)),
        ("via-12", ("via", 12)),
        ("roughness", ("roughness", None)),
        ("  Landing   Pad  4 ", ("Landing Pad", 4)),
        ("7", ("7", None)),
    ],
)
def test_split_label(label: str, expected: tuple[str, int | None]) -> None:
    assert split_label(label) == expected


@pytest.mark.parametrize(
    ("label", "feature_type", "number", "known"),
    [
        ("Pad 1", "Pad", 1, True),
        ("SR Pad 2", "SR Pad", 2, True),
        ("pad pos 3", "Pad", 3, True),
        ("via 2", "Via", 2, True),
        ("Trace 1", "Trace", 1, True),
        ("Landing Pad 5", "Landing_Pad", 5, True),
        ("roughness", "Roughness", 1, True),
        ("Fiducial 4", "Fiducial", 4, False),
        ("Micro Bump", "Micro Bump", 1, False),
    ],
)
def test_feature_type_comes_from_the_label_and_number_from_its_cell(
    config: Config, label: str, feature_type: str, number: int, known: bool
) -> None:
    feature = detect_feature(label, config)
    assert (feature.feature_type, feature.feature_number, feature.known) == (
        feature_type,
        number,
        known,
    )


def test_known_metrics_are_mapped_and_unknown_ones_kept(config: Config) -> None:
    schema = detect_metrics(
        ("Max Stepheight", "Distance 1", " Distance  2", "Angle"), "Pad", config
    )
    assert [c.metric for c in schema.columns] == [
        "Max_Stepheight",
        "Distance 1",
        "Distance 2",
        "Angle",
    ]
    assert [c.unit for c in schema.columns] == ["µm", "", "", ""]
    assert schema.discovered == ("Distance 1", "Distance 2", "Angle")
    assert schema.without_unit == ("Distance 1", "Distance 2", "Angle")


def test_columns_without_header_are_not_metrics(config: Config) -> None:
    schema = detect_metrics(("Dimple", None, "Bump"), "Via", config)
    assert [(c.index, c.metric) for c in schema.columns] == [(0, "Dimple"), (2, "Bump")]


def test_roughness_metrics_are_assigned_by_position(config: Config) -> None:
    schema = detect_metrics(tuple(OPERATOR_ROUGHNESS), "Roughness", config)
    assert [c.metric for c in schema.columns] == STANDARD_ROUGHNESS
    assert schema.positional_mismatch
    assert schema.duplicates == ()
    assert {(c.unit, c.scale) for c in schema.columns} == {("nm", 1000.0)}


def test_correct_roughness_header_raises_no_mismatch(config: Config) -> None:
    header = tuple(name.replace("_", " ") for name in STANDARD_ROUGHNESS)
    assert not detect_metrics(header, "Roughness", config).positional_mismatch


def test_duplicate_headers_are_kept_under_numbered_names(config: Config) -> None:
    schema = detect_metrics(
        ("Width", "Line", "Space"), "Trace", config
    )  # 'Line' is an alias of Width
    assert [c.metric for c in schema.columns] == ["Width", "Width (2)", "Space"]
    assert schema.duplicates == ("Width",)
    assert [c.unit for c in schema.columns] == ["µm", "µm", "µm"]


def test_unit_rules_are_configurable(make_config: ConfigFactory) -> None:
    config = make_config(units={"metric_units": {"Angle": "deg"}, "feature_rules": {}})
    schema = detect_metrics(("Angle", "Radius"), "Roughness", config)
    assert [(c.metric, c.unit, c.scale) for c in schema.columns[:2]] == [
        ("Rz_Mean", "", 1.0),
        ("Rz_Std_dev", "", 1.0),
    ]
    assert detect_metrics(("Angle",), "Pad", config).columns[0].unit == "deg"


@pytest.mark.parametrize(
    ("label", "location", "expected"),
    [
        ("Unit 7", "Unit", 7),
        ("Unit 07", "Unit", 7),
        ("Unit 2", "Coupon", "C2"),
        ("C3", "Coupon", "C3"),
    ],
)
def test_parse_unit(label: str, location: str, expected: int | str) -> None:
    assert parse_unit(label, location) == expected


def test_parse_rows_splits_stacked_blocks() -> None:
    rows: list[tuple[object, ...]] = [
        (None, None, "Max Stepheight", "Radius"),
        ("Unit 7", "Pad 1", 1.0, 2.0),
        ("Unit 8", None, 3.0, 4.0),
        (None, None, "Dimple", "Bump"),
        ("Unit 7", "via 1", 5.0, 6.0),
        (None, None, None, None),
        (None, None, "Dimple", "Bump"),
        ("Unit 7", "via 2", 7.0, 8.0),
    ]
    blocks, stray = parse_rows(rows)
    assert stray == ()
    assert [(b.label, b.header, len(b.rows), b.start_row) for b in blocks] == [
        ("Pad 1", ("Max Stepheight", "Radius"), 2, 2),
        ("via 1", ("Dimple", "Bump"), 1, 5),
        ("via 2", ("Dimple", "Bump"), 1, 8),
    ]
    assert blocks[0].rows[1].values == (3.0, 4.0)


def test_parse_rows_notes_stray_rows_and_missing_header_rows() -> None:
    rows: list[tuple[object, ...]] = [
        ("Measured by synthetic operator", None, None),
        (None, None, "Dimple"),
        ("Unit 1", "via 1", 1.0),
        ("Unit 2", "re-measured", 2.0),  # text on a later row is a note
        ("Unit 1", "via 2", 3.0),  # unit repeats with a label: new block, same header
        (None, "orphan", 9.0),
    ]
    blocks, stray = parse_rows(rows)
    assert stray == (1, 6)
    assert [(b.label, b.header) for b in blocks] == [("via 1", ("Dimple",)), ("via 2", ("Dimple",))]
    assert blocks[0].rows[1].note == "re-measured"
