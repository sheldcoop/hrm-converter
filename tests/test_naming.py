"""Output file names say what was converted and when."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from conftest import ConfigFactory
from create_test_fixture import PAD_HEADERS, FixtureInfo, make_block, write_workbook
from hrm_converter.config import Config
from hrm_converter.models import ConfigError
from hrm_converter.naming import loose_label, render, wide_name_for
from hrm_converter.pipeline import run_conversion, run_loose_files
from hrm_converter.wide import main as wide_main

STAMP = r"\d{4}-\d{2}-\d{2}_\d{4}"


@pytest.mark.parametrize(
    ("level", "scope"),
    [
        ("project", "SYN_Demo_Project"),
        ("part_a", "SYN-PART-A"),
        ("lot_a1", "SYN-PART-A_90001"),
        ("buildup_a1_bu01", "SYN-PART-A_90001_BU01"),
    ],
)
def test_long_workbook_is_named_after_the_selected_folder(
    hierarchy: FixtureInfo, config: Config, level: str, scope: str
) -> None:
    result = run_conversion(getattr(hierarchy, level), config)
    assert result.output_path is not None
    assert re.fullmatch(rf"HRM_Long_{scope}_{STAMP}\.xlsx", result.output_path.name)
    assert result.label == scope


def test_loose_files_are_named_after_the_file_or_their_count(
    tmp_path: Path, config: Config
) -> None:
    one = write_workbook(
        tmp_path / "My panel (5) back.xlsx", "S", [make_block("Pad 1", PAD_HEADERS, 1)]
    )
    result = run_loose_files([(one.name, one)], config)
    assert result.output_path is not None
    assert re.fullmatch(rf"HRM_Long_My-panel-5-back_{STAMP}\.xlsx", result.output_path.name)
    assert loose_label(["a.xlsx", "b.xlsx", "c.xlsx"]) == "3-loose-files"


def test_wide_workbook_and_fix_script_share_the_name(
    tmp_path: Path, make_config: ConfigFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    lot = tmp_path / "P" / "PN" / "L1"
    process = lot / "BU01" / "HRM" / "post AAA_HRM-2099-0001"
    write_workbook(
        process / "Panel 1" / "front" / "a_BU01_Front_Summary.xlsx",
        "S",
        [make_block("Pad 1", PAD_HEADERS, 1)],
    )
    write_workbook(
        process / "Pnl 2" / "front" / "b_BU01_Front_Summary.xlsx",
        "S",
        [make_block("Pad 1", PAD_HEADERS, 2)],
    )
    config = make_config()
    result = run_conversion(lot, config)
    assert result.output_path is not None and result.fix_script_path is not None
    tail = result.output_path.stem.removeprefix("HRM_Long_")
    assert result.fix_script_path.stem == f"HRM_FixFolders_{tail}"

    # The wide command without --input picks the newest long workbook and names its output alike.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("hrm_converter.wide.load_config", lambda path: config)
    assert wide_main([]) == 0
    assert result.output_path.with_name(f"HRM_Wide_{tail}.xlsx").is_file()


def test_wide_name_follows_the_long_name() -> None:
    assert wide_name_for(Path("HRM_Long_FHR0020_19198_2026-10-02_1745.xlsx")) == (
        "HRM_Wide_FHR0020_19198_2026-10-02_1745.xlsx"
    )
    assert wide_name_for(Path("hrm_long_format.xlsx")) == "hrm_wide_format.xlsx"
    assert wide_name_for(Path("results.xlsx")) == "results_wide.xlsx"


def test_fixed_names_and_bad_placeholders(
    hierarchy: FixtureInfo, make_config: ConfigFactory
) -> None:
    fixed = make_config(output={"filename": "always_the_same.xlsx"})
    result = run_conversion(hierarchy.lot_a1 / "BU02", fixed)
    assert result.output_path is not None and result.output_path.name == "always_the_same.xlsx"
    with pytest.raises(ConfigError, match="may only use the placeholders"):
        render("HRM_{lot}.xlsx", "x", "y", "output.filename")
    with pytest.raises(ConfigError, match="must end with .xlsx"):
        render("HRM_{scope}.csv", "x", "y", "output.filename")
