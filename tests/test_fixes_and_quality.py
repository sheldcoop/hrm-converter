"""Fix plan, value sanity checks, duplicate workbooks and the app's remembered paths."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pandas as pd
import pytest

from conftest import ConfigFactory
from create_test_fixture import PAD_HEADERS, Block, make_block, write_workbook
from hrm_converter.config import Config
from hrm_converter.fixplan import fix_script, side_folder_name
from hrm_converter.models import FIX_PLAN_COLUMNS
from hrm_converter.pipeline import run_conversion, run_loose_files

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = Path(__file__).resolve().parents[1] / "app.py"
PROCESS = "post AAA_HRM-2099-0001"


def book(path: Path, buildup: str = "BU01", side: str = "Front", seed: float = 10) -> Path:
    return write_workbook(
        path, f"SYN_PN_{buildup}_{side}", [make_block("Pad 1", PAD_HEADERS, seed)]
    )


def messy_tree(root: Path) -> Path:
    """A lot whose folders are wrong in ways that have an unambiguous repair."""
    lot = root / "P" / "PN" / "L1"
    process = lot / "BU01" / "HRM" / PROCESS
    book(process / "Panel 1" / "front" / "a_BU01_Front_Summary.xlsx", seed=10)
    book(process / "Pnl 7" / "front" / "b_BU01_Front_Summary.xlsx", seed=20)  # bad panel name
    book(process / "Panel 2" / "Back (remeasure)" / "c_BU01_Back_Summary.xlsx", "BU01", "Back", 30)
    book(process / "Panel 3" / "d_BU01_Coupon_Back_Summary.xlsx", "BU01", "Back", 40)  # in panel
    book(process / "Panel 4" / "front and back" / "e_BU01_Front_Summary.xlsx", seed=50)  # unclear
    book(
        lot / "Buildup 2" / "HRM" / PROCESS / "Panel 1" / "front" / "f_BU02_Front_Summary.xlsx",
        "BU02",
        seed=60,
    )
    return root / "P"


def test_fix_plan_proposes_only_unambiguous_repairs(tmp_path: Path, config: Config) -> None:
    project = messy_tree(tmp_path)
    result = run_conversion(project, config)
    plan = {(p.action, p.source.name, p.target.name) for p in result.fix_plan}
    assert plan == {
        ("Rename folder", "Pnl 7", "Panel 7"),
        ("Rename folder", "Back (remeasure)", "back"),
        ("Move file", "d_BU01_Coupon_Back_Summary.xlsx", "d_BU01_Coupon_Back_Summary.xlsx"),
        ("Rename folder", "Buildup 2", "BU02"),
    }
    move = next(p for p in result.fix_plan if p.action == "Move file")
    assert move.target.parent.name == "Coupon back"

    assert result.output_path is not None
    sheet = pd.read_excel(result.output_path, sheet_name="Fix_Plan", dtype=object)
    assert tuple(sheet.columns) == FIX_PLAN_COLUMNS and len(sheet) == 4
    assert result.fix_script_path is not None and result.fix_script_path.is_file()
    assert (
        project / "PN" / "L1" / "BU01" / "HRM" / PROCESS / "Pnl 7"
    ).is_dir()  # nothing was touched


@pytest.mark.skipif(os.name == "nt" or shutil.which("sh") is None, reason="needs a POSIX shell")
def test_running_the_fix_script_repairs_the_folders(tmp_path: Path, config: Config) -> None:
    project = messy_tree(tmp_path)
    before = run_conversion(project, config)
    assert before.processed_count == 1 and before.fix_script_path is not None

    done = subprocess.run(["sh", str(before.fix_script_path)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr

    after = run_conversion(project, config)
    assert after.processed_count == 5  # only the ambiguous 'front and back' folder is left
    assert [p for p in after.fix_plan] == [] and after.fix_script_path is None
    assert not before.fix_script_path.exists()  # a stale plan is removed
    assert {r.buildup for r in after.records} == {"BU-01", "BU-02"}
    assert [i.category for i in after.issues if i.category.startswith("invalid")] == [
        "invalid_side_folder"
    ]
    # Running it a second time changes nothing and overwrites nothing.
    again = subprocess.run(
        ["sh", "-c", fix_script(before.fix_plan, windows=False)], capture_output=True, text=True
    )
    assert again.returncode == 0


def test_windows_script_is_plain_single_line_commands() -> None:
    from hrm_converter.models import FixProposal

    proposal = FixProposal(
        "Rename folder", Path("L:/data/100% (new)/Pnl 7"), Path("L:/data/100% (new)/Panel 7"), "why"
    )
    script = fix_script([proposal], windows=True)
    assert script.startswith("@echo off\r\n") and script.rstrip().endswith("pause")
    assert "100%% (new)" in script  # percent signs are escaped for cmd
    move = [
        line for line in script.splitlines() if line.startswith("if not exist") and " move " in line
    ]
    assert len(move) == 1 and move[0].count('"') == 6


def test_side_folder_name_needs_exactly_one_side(config: Config) -> None:
    assert side_folder_name("Back (remeasure)", config) == "back"
    assert side_folder_name("x_BU01_Coupon_Front_Summary", config) == "Coupon front"
    assert side_folder_name("front and back", config) is None
    assert side_folder_name("left", config) is None


def quality_rows(
    tmp_path: Path, config: Config, rows: list[tuple[str, str | None, list[object]]]
) -> list[str]:
    path = write_workbook(
        tmp_path / "q.xlsx",
        "S",
        [Block("Pad 1", PAD_HEADERS, rows)],  # type: ignore[arg-type]
    )
    result = run_loose_files([(path.name, path)], config)
    return [f"{i.category}: {i.message}" for i in result.issues]


def test_value_sanity_checks(tmp_path: Path, config: Config) -> None:
    good = [17.0, 16.0, 16.5, 42.0, 0.0, 1.8]  # Max, Min, Mean, Radius, Dimple, Bump
    issues = quality_rows(
        tmp_path,
        config,
        [
            ("Unit 1", "Pad 1", good),
            ("Unit 2", None, good),
            ("Unit 3", None, good),
            ("Unit 4", None, [16.0, 17.0, 16.5, 42.0, 0.0, 1.8]),  # Min and Max swapped
            ("Unit 5", None, [17.0, 16.0, 16.5, 4200.0, 0.0, -1.8]),  # Radius x100, negative Bump
            ("Unit 6", None, [17.0, 16.0, 16.5, 42.0, 0.0, 0.0]),  # a true zero is not suspicious
        ],
    )
    assert len(issues) == 3
    assert any(
        i.startswith("value_order: Pad 1, unit 4: Stepheight") and "Min (17) > Max (16)" in i
        for i in issues
    )
    assert any(
        i.startswith("negative_value: Pad 1, unit 5: Bump is negative (-1.8)") for i in issues
    )
    assert any(i.startswith("suspicious_value: Pad 1, unit 5: Radius = 4200") for i in issues)


def test_sanity_checks_can_be_switched_off(tmp_path: Path, make_config: ConfigFactory) -> None:
    config = make_config(
        quality={"order_check": False, "negative_check": False, "outlier_factor": None}
    )
    rows = [
        (f"Unit {u}", "Pad 1" if u == 1 else None, [16.0, 17.0, 16.5, radius, 0.0, -1.0])
        for u, radius in ((1, 42.0), (2, 4200.0), (3, 42.0))
    ]
    assert quality_rows(tmp_path, config, rows) == []  # type: ignore[arg-type]


def test_same_workbook_in_two_folders_is_reported(tmp_path: Path, config: Config) -> None:
    panel = tmp_path / "P" / "PN" / "L1" / "BU01" / "HRM" / PROCESS / "Panel 1"
    original = book(panel / "front" / "a_BU01_Front_Summary.xlsx")
    copy = panel.parent / "Panel 2" / "front" / original.name
    copy.parent.mkdir(parents=True)
    shutil.copy2(original, copy)

    result = run_conversion(tmp_path / "P", config)
    duplicates = [i for i in result.issues if i.category == "duplicate_workbook"]
    assert len(duplicates) == 1 and "Panel 1/front" in duplicates[0].message
    assert duplicates[0].relative_path.endswith(f"Panel 2/front/{original.name}")
    assert result.processed_count == 2  # both are converted; the user decides which is the copy


def test_app_remembers_the_last_folder_and_limits_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import hrm_converter.config as config_module

    def load_into_tmp(path: Path | None) -> config_module.Config:
        del path
        return config_module.build_config(
            {
                "output": {"directory": str(tmp_path / "out")},
                "logging": {"directory": str(tmp_path / "logs")},
            }
        )

    monkeypatch.setattr(config_module, "load_config", load_into_tmp)
    project = messy_tree(tmp_path / "data")
    limits = tmp_path / "limits.xlsx"
    pd.DataFrame([{"Feature_Type": "Pad", "Metric": "Radius", "USL": 99}]).to_excel(
        limits, sheet_name="Limits", index=False
    )

    first = AppTest.from_file(str(APP), default_timeout=60).run()
    assert first.text_input(key="folder").value == ""
    first.text_input(key="folder").set_value(f"'{project}'")
    first.text_input(key="reference_path").set_value(str(limits))
    first.button(key="convert").click().run()
    assert not first.exception
    assert [s.value for s in first.subheader][:2] == ["Folder check", "Fix plan"]
    assert "needs fixing in 1 of 1 lot" in first.warning[0].value

    second = AppTest.from_file(str(APP), default_timeout=60).run()  # a new session
    assert second.text_input(key="folder").value == str(project)
    assert second.text_input(key="reference_path").value == str(limits)
