"""The stress project: every messy case is handled and reported, none stops the run."""

from __future__ import annotations

from pathlib import Path

from conftest import ConfigFactory
from create_stress_project import KINDS, create_stress_project
from hrm_converter.pipeline import run_conversion
from hrm_converter.reference import load_reference
from hrm_converter.validation import IssueCollector
from hrm_converter.wide import build_wide, read_long

EXPECTED_ISSUES = {
    "invalid_panel_folder", "invalid_side_folder", "metadata_conflict", "multiple_workbooks",
    "unreadable_workbook", "empty_folder", "extra_sheets", "filename_pattern", "header_order",
    "missing_hrm_folder", "no_workbook", "process_fallback",
}  # fmt: skip


def test_stress_project_converts_and_reports_every_problem(
    tmp_path: Path, make_config: ConfigFactory
) -> None:
    info = create_stress_project(tmp_path / "data", size="small")
    config = make_config()
    result = run_conversion(info.project, config)

    assert result.processed_count > 0 and len(result.records) > 0
    assert {issue.category for issue in result.issues} >= EXPECTED_ISSUES
    reasons = " | ".join(r.reason for r in result.file_results)
    for expected in ("Multiple workbooks", "cannot be opened", "No measurement blocks",
                     "Buildup, Side", "Part_Number"):  # fmt: skip
        assert expected in reasons
    assert not any("xrf" in record.source_file for record in result.records)
    assert {record.buildup for record in result.records} >= {"BU-01", "BU-03", "BU-02", "BU-08"}
    assert all(isinstance(record.value, int | float) for record in result.records)

    assert result.output_path is not None
    issues = IssueCollector()
    reference = load_reference(info.reference, config, issues)
    wide = build_wide(read_long(result.output_path, config), reference, config, issues)
    assert {"Pad", "Trace", "Via", "Roughness"} <= set(wide.sheets)
    assert wide.out_of_spec_count > 0
    found = {issue.category for issue in issues.reportable()}
    assert {"reference_row", "reference_unused"} <= found


def test_every_workbook_kind_produces_blocks_the_reader_accepts(tmp_path: Path) -> None:
    import random

    from create_stress_project import Maker
    from create_test_fixture import write_workbook
    from hrm_converter.workbook_reader import read_workbook

    for position, (name, build) in enumerate(KINDS):
        path = write_workbook(
            tmp_path / f"kind_{position}.xlsx", "Sheet", build(Maker(random.Random(position)))
        )
        assert read_workbook(path).blocks, name
    assert len({name for name, _ in KINDS}) >= 14
