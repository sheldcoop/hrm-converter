"""Loose Excel files: no folder hierarchy, so the metadata columns stay blank."""

from __future__ import annotations

import importlib.util
import io
import sys
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from conftest import ConfigFactory
from create_test_fixture import PAD_HEADERS, VIA_HEADERS, make_block, write_workbook
from hrm_converter.config import Config
from hrm_converter.models import LONG_COLUMNS, LONG_SHEET_COLUMNS
from hrm_converter.pipeline import run_loose_files
from hrm_converter.validation import IssueCollector
from hrm_converter.wide import build_wide, read_long

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = Path(__file__).resolve().parents[1] / "app.py"
METADATA = LONG_COLUMNS[:9]  # Project_Name .. Location


def workbook(path: Path, seed: float) -> Path:
    blocks = [make_block("Pad 1", PAD_HEADERS, seed), make_block("via 2", VIA_HEADERS, seed + 50)]
    return write_workbook(path, "ENG_PART_BU03_Back", blocks)


def test_metadata_is_blank_and_measurements_are_complete(tmp_path: Path, config: Config) -> None:
    first = workbook(tmp_path / "in" / "a_BU03_Back_Summary.xlsx", 100)
    second = workbook(tmp_path / "in" / "any name at all.xlsx", 200)
    before = first.read_bytes()

    result = run_loose_files(
        [(first.name, first), (second.name, io.BytesIO(second.read_bytes()))], config
    )
    assert first.read_bytes() == before
    assert result.scope is None
    assert (result.processed_count, result.skipped_count, len(result.records)) == (2, 0, 48)

    assert result.output_path is not None
    long = read_long(result.output_path, config)
    assert tuple(long.columns) == LONG_SHEET_COLUMNS
    for column in METADATA:
        assert set(long[column]) == {""}, column  # nothing is guessed from the file name
    assert set(long["Unit"]) == {1, 2, 3}
    assert set(zip(long["Feature_Type"], long["Feature_Number"], strict=True)) == {
        ("Pad", 1),
        ("Via", 2),
    }
    assert set(long["Source_File"]) == {first.name, second.name}
    assert long["Value"].map(lambda v: isinstance(v, int | float)).all()

    wide = build_wide(long, None, config, IssueCollector())
    pad = wide.sheets["Pad"]
    assert len(pad) == 6 and list(pad["Source_File"]).count(first.name) == 3  # files stay apart


def test_bad_and_duplicate_files_are_reported_not_fatal(tmp_path: Path, config: Config) -> None:
    good = workbook(tmp_path / "good.xlsx", 100)
    result = run_loose_files(
        [(good.name, good), ("broken.xlsx", io.BytesIO(b"not excel")), (good.name, good)], config
    )
    assert (result.processed_count, result.skipped_count) == (1, 2)
    # (The synthetic values are not physically ordered, so value_order warnings are expected.)
    found = [issue.category for issue in result.issues if issue.category != "value_order"]
    assert found == ["unreadable_workbook", "duplicate_file_name"]
    assert len(result.records) == 24


def test_app_convert_with_uploaded_loose_files(
    tmp_path: Path, make_config: ConfigFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    spec = importlib.util.spec_from_file_location("hrm_app", APP)
    assert spec is not None and spec.loader is not None
    app = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, app)  # dataclasses look the module up
    spec.loader.exec_module(app)
    monkeypatch.setattr(app, "base_config", lambda: make_config())

    source = workbook(tmp_path / "loose.xlsx", 100)
    upload = SimpleNamespace(name="loose.xlsx", getvalue=source.read_bytes)
    run = app.convert("", "ignored lot name", True, None, "", [upload])

    assert run.result.scope is None and len(run.long) == 24
    assert set(run.long["Lot_Name"]) == {""}
    assert run.result.output_path.is_file() and run.wide_path.is_file()
    assert set(pd.read_excel(run.wide_path, sheet_name=None)) >= {"Pad", "Via"}


def test_app_loose_mode_needs_a_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    app = AppTest.from_file(str(APP), default_timeout=60).run()
    app.radio(key="mode").set_value("Loose Excel files").run()
    assert not app.exception
    assert not [w for w in app.text_input if w.key == "folder"]  # folder box is replaced
    app.button(key="convert").click().run()
    assert not app.exception
    assert "Upload at least one Excel file first" in app.error[0].value


def limits_file(path: Path, rows: list[dict[str, object]]) -> Path:
    pd.DataFrame(rows).to_excel(path, sheet_name="Limits", index=False)
    return path


def test_loose_files_get_limits_in_the_long_table(tmp_path: Path, config: Config) -> None:
    source = workbook(tmp_path / "loose.xlsx", 100)
    reference = limits_file(
        tmp_path / "limits.xlsx",
        [
            {
                "Part_Number": None,
                "Feature_Type": "Pad",
                "Metric": "Radius",
                "LSL": 100,
                "USL": 100.25,
            },
            # Needs a Part Number, which a loose file does not have: cannot match.
            {"Part_Number": "SYN-PART", "Feature_Type": "Via", "Metric": "Dimple", "USL": 1},
        ],
    )
    result = run_loose_files([(source.name, source)], config, reference)
    assert result.output_path is not None
    long = read_long(result.output_path, config)
    radius = long[(long["Feature_Type"] == "Pad") & (long["Metric"] == "Radius")]
    assert set(radius["LSL"]) == {100} and set(radius["USL"]) == {100.25}
    assert set(radius["Target"]) == {""}
    others = long[long["Metric"] != "Radius"]
    assert set(others["LSL"]) == {""} and set(others["USL"]) == {""}
