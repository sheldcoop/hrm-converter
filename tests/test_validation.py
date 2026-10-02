"""Natural sorting, issue collection, metadata cross-checks and config validation."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from conftest import ConfigFactory
from hrm_converter.config import Config, build_config, load_config
from hrm_converter.models import ConfigError, Severity, WorkbookContext
from hrm_converter.validation import IssueCollector, find_conflicts, natural_key

CONTEXT = WorkbookContext(
    project_name="Chiplet4Future",
    part_number="FHR0020",
    lot_number="19198",
    lot_name="",
    buildup="BU-03",
    process="Post DDV",
    process_folder="post DDV_HRM-2026-0088",
    panel=5,
    side="Back",
    location="Unit",
    folder=Path("back"),
    relative_folder="back",
)
SHEET = "ENG_FHR0020_BU03_Back"
FILE = "2026-08-11_11-02-51_ENG_Chipletz4Future_BU03_Back_Summary.xlsx"


def test_natural_key_orders_numbers_inside_text() -> None:
    names = ["BU-10", "BU-2", "Panel 10", "Panel 2", "bu-1"]
    assert sorted(names, key=natural_key) == ["bu-1", "BU-2", "BU-10", "Panel 2", "Panel 10"]
    assert sorted([10, "C2", 2, "C10", 1], key=natural_key) == [1, 2, 10, "C2", "C10"]


def test_issue_collector_separates_info_from_reportable_issues() -> None:
    issues = IssueCollector()
    issues.info("a", "info")
    issues.warning("b", "warning", field="Side")
    issues.error("c", "error", source_file="x.xlsx")
    assert [i.severity for i in issues.reportable()] == [Severity.WARNING, Severity.ERROR]
    assert len(issues.all()) == 3
    assert issues.count(Severity.ERROR) == 1


def test_agreeing_metadata_gives_no_conflict(config: Config) -> None:
    assert find_conflicts(CONTEXT, SHEET, FILE, config) == []


def test_buildup_side_and_part_number_conflicts_are_found(config: Config) -> None:
    conflicts = find_conflicts(CONTEXT, "ENG_FHR0099_BU07_Front", FILE, config)
    assert [(c.field, c.hierarchy_value, c.workbook_value, c.source) for c in conflicts] == [
        ("Buildup", "BU-03", "BU07", "sheet name"),
        ("Side", "Back", "Front", "sheet name"),
        ("Part_Number", "FHR0020", "FHR0099", "sheet name"),
    ]
    from_file = find_conflicts(CONTEXT, "Sheet1", "x_BU04_Front_Summary.xlsx", config)
    assert [(c.field, c.source) for c in from_file] == [
        ("Buildup", "file name"),
        ("Side", "file name"),
    ]


def test_names_without_metadata_are_not_guessed(config: Config) -> None:
    assert find_conflicts(CONTEXT, "Sheet1", "summary.xlsx", config) == []
    # Both sides named: ambiguous, so no Side comparison is made.
    assert find_conflicts(CONTEXT, "Front_and_Back", "summary.xlsx", config) == []


def test_coupon_names_are_checked_on_their_side(config: Config) -> None:
    coupon = replace(CONTEXT, location="Coupon", side="Front")
    assert (
        find_conflicts(
            coupon, "ENG_FHR0020_BU03_Coupon_Front", FILE.replace("Back", "Coupon_Front"), config
        )
        == []
    )


def test_part_number_check_can_be_switched_off(make_config: ConfigFactory) -> None:
    config = make_config(cross_check={"sheet_part_number_pattern": None})
    assert find_conflicts(CONTEXT, "ENG_FHR0099_BU03_Back", FILE, config) == []


def test_unknown_settings_are_rejected() -> None:
    with pytest.raises(ConfigError, match="Unknown setting 'processing.strict'"):
        build_config({"processing": {"strict": True}})
    with pytest.raises(ConfigError, match="Unknown setting 'outputs'"):
        build_config({"outputs": {}})


def test_invalid_setting_values_are_rejected() -> None:
    with pytest.raises(ConfigError, match="multiple_files_policy"):
        build_config({"processing": {"multiple_files_policy": "first"}})
    with pytest.raises(ConfigError, match="not a valid regular expression"):
        build_config({"hierarchy": {"panel_pattern": "("}})
    with pytest.raises(ConfigError, match="named group"):
        build_config({"hierarchy": {"panel_pattern": r"^Panel (\d+)$"}})


def test_shipped_config_file_equals_the_defaults() -> None:
    shipped = Path(__file__).resolve().parents[1] / "config.yaml"
    assert load_config(shipped) == build_config()


def test_missing_config_file_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="cannot be read"):
        load_config(tmp_path / "missing.yaml")
