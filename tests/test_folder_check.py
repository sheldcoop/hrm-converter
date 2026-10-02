"""Folder-structure problems are found, explained and summarised per lot."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from create_test_fixture import PAD_HEADERS, FixtureInfo, make_block, write_workbook
from hrm_converter.config import Config
from hrm_converter.models import FOLDER_CHECK_COLUMNS
from hrm_converter.output_writer import folder_check_frame, issues_frame
from hrm_converter.pipeline import run_conversion
from hrm_converter.validation import FIX_HINTS, FOLDER_CATEGORIES


def book(path: Path, buildup: str = "BU01", side: str = "Front") -> Path:
    return write_workbook(path, f"SYN_PN_{buildup}_{side}", [make_block("Pad 1", PAD_HEADERS, 10)])


def test_wrongly_built_folders_are_explained(tmp_path: Path, config: Config) -> None:
    lot = tmp_path / "P" / "PN" / "L1"
    hrm = lot / "BU01" / "HRM"
    process = hrm / "post AAA_HRM-2099-0001"
    good = book(process / "Panel 1" / "front" / "a_BU01_Front_Summary.xlsx")
    book(hrm / "in_hrm_Summary.xlsx")  # directly in HRM
    book(process / "in_process_Summary.xlsx")  # directly in the process folder
    book(process / "Panel 1" / "in_panel_Summary.xlsx")  # directly in the panel folder
    book(process / "Panel 1" / "front" / "old" / "copy_Summary.xlsx")  # one level too deep
    book(hrm / "Panel 7" / "front" / "x_BU01_Front_Summary.xlsx")  # process folder missing
    book(process / "back" / "y_BU01_Back_Summary.xlsx", side="Back")  # panel folder missing
    book(
        lot
        / "BU02"
        / "HRM"
        / "post AAA_HRM-2099-0002"
        / "Panel 1"
        / "front"
        / "b_BU02_Front_Summary.xlsx",
        "BU02",
    )

    result = run_conversion(tmp_path / "P", config)
    assert [r.candidate.path for r in result.file_results if r.row_count] != []
    assert result.processed_count == 2 and good.is_file()

    found = {(i.category, i.relative_path.rsplit("/", 1)[-1]) for i in result.issues}
    assert {
        ("misplaced_workbook", "HRM"),
        ("misplaced_workbook", "post AAA_HRM-2099-0001"),
        ("misplaced_workbook", "Panel 1"),
        ("misplaced_workbook", "front"),
        ("missing_process_folder", "Panel 7"),
        ("missing_panel_folder", "back"),
    } <= found

    issues = issues_frame(result.issues)
    assert (issues["How_To_Fix"] != "").all()
    hint = issues[issues["Category"] == "missing_process_folder"].iloc[0]["How_To_Fix"]
    assert "Add a process folder between HRM and the panel folder" in hint

    check = folder_check_frame(result)
    assert tuple(check.columns) == FOLDER_CHECK_COLUMNS and len(check) == 1
    row = check.iloc[0]
    assert (row["Part_Number"], row["Lot_Number"], row["Buildups"]) == ("PN", "L1", 2)
    assert (row["Workbooks_Processed"], row["Folder_Problems"], row["Verdict"]) == (
        2,
        6,
        "Needs fixing",
    )
    assert "4 x misplaced_workbook" in row["Problems"]


def test_folder_check_per_lot_in_the_output_workbook(
    hierarchy: FixtureInfo, config: Config
) -> None:
    result = run_conversion(hierarchy.project, config)
    assert result.output_path is not None
    check = pd.read_excel(result.output_path, sheet_name="Folder_Check", dtype=object)
    verdicts = dict(zip(check["Lot_Number"], check["Verdict"], strict=True))
    assert verdicts == {"90001": "Needs fixing", "90002": "OK", "80001": "OK"}
    first = check[check["Lot_Number"] == "90001"].iloc[0]
    assert first["Buildups"] == 3 and "1 x missing_hrm_folder" in first["Problems"]
    assert "1 x multiple_workbooks" in first["Problems"]


def test_every_folder_problem_has_a_fix_hint() -> None:
    assert set(FIX_HINTS) >= FOLDER_CATEGORIES
