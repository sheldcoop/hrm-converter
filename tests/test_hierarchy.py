"""Folder-name interpretation and role detection of the selected folder."""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import ConfigFactory
from create_test_fixture import LOT_A1, PART_A, PROJECT, FixtureInfo
from hrm_converter.config import Config
from hrm_converter.hierarchy import (
    detect_scope,
    parse_buildup,
    parse_panel,
    parse_process,
    parse_side,
)
from hrm_converter.models import FolderRole, HierarchyError
from hrm_converter.validation import IssueCollector


@pytest.mark.parametrize(
    ("name", "expected"),
    [("BU03", "BU-03"), ("bu 3", "BU-03"), ("BU-10", "BU-10"), (" BU_1 ", "BU-01"), ("XRF", None)],
)
def test_parse_buildup(config: Config, name: str, expected: str | None) -> None:
    assert parse_buildup(name, config) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("post DDV_HRM-2026-0088", ("Post DDV", True)),
        ("post DFS_HRM-2026-0115", ("Post DFS", True)),
        ("pre  XYZ9 HRM 2030-0001", ("Pre XYZ9", True)),
        ("  Special   Run ", ("Special Run", False)),
    ],
)
def test_parse_process_is_not_hardcoded(
    config: Config, name: str, expected: tuple[str, bool]
) -> None:
    assert parse_process(name, config) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [("Panel 05", 5), ("panel_12", 12), ("Panel-3", 3), ("Panel", None), ("Board 3", None)],
)
def test_parse_panel(config: Config, name: str, expected: int | None) -> None:
    assert parse_panel(name, config) == expected


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("front", ("Front", "Unit")),
        ("BACK", ("Back", "Unit")),
        ("Coupon front", ("Front", "Coupon")),
        ("coupon_back", ("Back", "Coupon")),
        ("Coupon-Front ", ("Front", "Coupon")),
        ("sideways", None),
        ("Coupon", None),
    ],
)
def test_parse_side(config: Config, name: str, expected: tuple[str, str] | None) -> None:
    assert parse_side(name, config) == expected


def test_role_detection_at_every_level(hierarchy: FixtureInfo, config: Config) -> None:
    expected = {
        hierarchy.project: FolderRole.PROJECT,
        hierarchy.part_a: FolderRole.PART_NUMBER,
        hierarchy.lot_a1: FolderRole.LOT_NUMBER,
        hierarchy.buildup_a1_bu01: FolderRole.BUILDUP,
    }
    for folder, role in expected.items():
        assert detect_scope(folder, config, IssueCollector()).role is role


def test_project_scope_lists_all_buildups_in_natural_order(
    hierarchy: FixtureInfo, config: Config
) -> None:
    scope = detect_scope(hierarchy.project, config, IssueCollector())
    found = [(b.part_number, b.lot_number, b.buildup) for b in scope.buildups]
    assert found == [
        ("SYN-PART-A", "90001", "BU-01"),
        ("SYN-PART-A", "90001", "BU-02"),
        ("SYN-PART-A", "90001", "BU-10"),
        ("SYN-PART-A", "90002", "BU-01"),
        ("SYN-PART-B", "80001", "BU-01"),
    ]


def test_parent_metadata_is_recovered_for_lot_and_buildup(
    hierarchy: FixtureInfo, config: Config
) -> None:
    for folder in (hierarchy.lot_a1, hierarchy.buildup_a1_bu01):
        scope = detect_scope(folder, config, IssueCollector())
        assert scope.project_path == hierarchy.project
        for buildup in scope.buildups:
            assert (buildup.project_name, buildup.part_number, buildup.lot_number) == (
                PROJECT,
                PART_A,
                LOT_A1,
            )


def test_selection_scope_is_respected(hierarchy: FixtureInfo, config: Config) -> None:
    lot = detect_scope(hierarchy.lot_a1, config, IssueCollector())
    assert {b.lot_number for b in lot.buildups} == {LOT_A1}
    assert [b.buildup for b in lot.buildups] == ["BU-01", "BU-02", "BU-10"]
    buildup = detect_scope(hierarchy.buildup_a1_bu01, config, IssueCollector())
    assert [b.buildup for b in buildup.buildups] == ["BU-01"]


def test_buildup_without_hrm_is_reported(hierarchy: FixtureInfo, config: Config) -> None:
    issues = IssueCollector()
    detect_scope(hierarchy.lot_a1, config, issues)
    missing = [i for i in issues.reportable() if i.category == "missing_hrm_folder"]
    assert len(missing) == 1
    assert missing[0].relative_path.endswith("90001/BU03")


def test_scope_filters(hierarchy: FixtureInfo, make_config: ConfigFactory) -> None:
    config = make_config(scope={"part_numbers": ["syn-part-a"], "buildups": ["BU10", "bu 2"]})
    scope = detect_scope(hierarchy.project, config, IssueCollector())
    assert [(b.part_number, b.buildup) for b in scope.buildups] == [
        ("SYN-PART-A", "BU-02"),
        ("SYN-PART-A", "BU-10"),
    ]


def test_selecting_hrm_or_below_is_rejected(hierarchy: FixtureInfo, config: Config) -> None:
    hrm = hierarchy.buildup_a1_bu01 / "HRM"
    for folder in (hrm, hrm / "post AAA_HRM-2099-0001"):
        with pytest.raises(HierarchyError, match="'HRM' folder or lies inside it"):
            detect_scope(folder, config, IssueCollector())


def test_folder_without_hrm_is_rejected(tmp_path: Path, config: Config) -> None:
    (tmp_path / "A" / "B").mkdir(parents=True)
    with pytest.raises(HierarchyError, match="No 'HRM' folder was found"):
        detect_scope(tmp_path, config, IssueCollector())


def test_missing_folder_is_rejected(tmp_path: Path, config: Config) -> None:
    with pytest.raises(HierarchyError, match="does not exist"):
        detect_scope(tmp_path / "nope", config, IssueCollector())


def test_role_is_not_guessed_from_depth_alone(tmp_path: Path, config: Config) -> None:
    # HRM sits one level down, but the folder is not named like a Buildup.
    (tmp_path / "P" / "PN" / "L" / "Misc" / "HRM").mkdir(parents=True)
    with pytest.raises(HierarchyError, match="do not match the Buildup naming pattern"):
        detect_scope(tmp_path / "P" / "PN" / "L" / "Misc", config, IssueCollector())


def test_inconsistent_hrm_levels_are_rejected(tmp_path: Path, config: Config) -> None:
    (tmp_path / "P" / "X1" / "HRM").mkdir(parents=True)
    (tmp_path / "P" / "X2" / "Y" / "HRM").mkdir(parents=True)
    with pytest.raises(HierarchyError, match="cannot be determined reliably"):
        detect_scope(tmp_path / "P", config, IssueCollector())


def test_buildup_pattern_resolves_mixed_levels(tmp_path: Path, config: Config) -> None:
    lot = tmp_path / "P" / "PN" / "L"
    (lot / "BU01" / "HRM").mkdir(parents=True)
    (lot / "archive" / "old" / "HRM").mkdir(parents=True)
    scope = detect_scope(lot, config, IssueCollector())
    assert scope.role is FolderRole.LOT_NUMBER
    assert [b.buildup for b in scope.buildups] == ["BU-01"]


def test_hrm_folder_name_is_case_insensitive_and_trimmed(tmp_path: Path, config: Config) -> None:
    (tmp_path / "P" / "PN" / "L" / "BU01" / "hrm ").mkdir(parents=True)
    scope = detect_scope(tmp_path / "P" / "PN" / "L", config, IssueCollector())
    assert scope.role is FolderRole.LOT_NUMBER
