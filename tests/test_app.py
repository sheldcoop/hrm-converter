"""Smoke test of the Streamlit app, run headless with Streamlit's own test harness."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from create_test_fixture import FixtureInfo

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

APP = Path(__file__).resolve().parents[1] / "app.py"


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> AppTest:
    """The app with its output and logs redirected to the test's temporary folder."""
    import hrm_converter.config as config_module

    def load_into_tmp(path: Path | None) -> config_module.Config:
        del path  # the app's own config.yaml is replaced by test settings
        return config_module.build_config(
            {
                "output": {"directory": str(tmp_path / "out")},
                "logging": {"directory": str(tmp_path / "logs")},
            }
        )

    monkeypatch.setattr(config_module, "load_config", load_into_tmp)
    return AppTest.from_file(str(APP), default_timeout=60)


def metrics(app: AppTest) -> dict[str, str]:
    return {metric.label: metric.value for metric in app.metric}


def test_app_starts_and_asks_for_a_folder(app: AppTest) -> None:
    app.run()
    assert not app.exception
    assert "Choose a folder" in app.info[0].value

    app.button(key="convert").click().run()
    assert not app.exception
    assert "Enter or browse to a folder first" in app.error[0].value


def test_app_converts_and_shows_every_page(
    app: AppTest, hierarchy: FixtureInfo, tmp_path: Path
) -> None:
    app.run()
    app.text_input(key="folder").set_value(str(hierarchy.lot_a1))
    app.button(key="convert").click().run()
    assert not app.exception
    assert metrics(app)["Processed"] == "8"
    assert metrics(app)["Long rows"] == "244"
    names = sorted(path.name[:28] for path in (tmp_path / "out").glob("*.xlsx"))
    assert names == ["HRM_Long_SYN-PART-A_90001_20", "HRM_Wide_SYN-PART-A_90001_20"]

    for view in ("Long", "Wide", "Issues", "Reference", "Summary"):
        app.button(key=f"view_{view}").click().run()
        assert not app.exception, view
    app.button(key="view_Wide").click().run()
    assert metrics(app)["Out of spec"] == "0"
    assert "No reference workbook loaded" in app.info[0].value


def test_app_reports_a_bad_folder(app: AppTest, tmp_path: Path) -> None:
    (tmp_path / "empty").mkdir()
    app.run()
    app.text_input(key="folder").set_value(str(tmp_path / "empty"))
    app.button(key="convert").click().run()
    assert not app.exception
    assert "No 'HRM' folder was found" in app.error[0].value


def test_app_applies_limits_from_a_reference_path(
    app: AppTest, hierarchy: FixtureInfo, tmp_path: Path
) -> None:
    reference = tmp_path / "limits.xlsx"
    pd.DataFrame(
        [{"Buildup": "BU-01", "Feature_Type": "Pad", "Metric": "Radius", "LSL": 100, "USL": 100.25}]
    ).to_excel(reference, sheet_name="Limits", index=False)

    app.run()
    app.text_input(key="folder").set_value(str(hierarchy.buildup_a1_bu01))
    app.text_input(key="reference_path").set_value(str(reference))
    app.button(key="convert").click().run()
    assert not app.exception
    app.button(key="view_Wide").click().run()
    assert not app.exception
    shown = metrics(app)
    assert shown["With limits (of 208)"] == "17"
    assert shown["Out of spec"] == "15"
    app.button(key="view_Reference").click().run()
    assert not app.exception and app.dataframe[0].value["Matched_Groups"].tolist() == [1]


def test_app_reports_an_unreadable_reference(app: AppTest, hierarchy: FixtureInfo) -> None:
    app.run()
    app.text_input(key="folder").set_value(str(hierarchy.buildup_a1_bu01))
    app.text_input(key="reference_path").set_value(str(hierarchy.root / "missing.xlsx"))
    app.button(key="convert").click().run()
    assert not app.exception
    assert "Reference workbook cannot be read" in app.error[0].value
