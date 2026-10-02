"""HRM-only traversal and workbook candidate rules."""

from __future__ import annotations

from conftest import ConfigFactory
from create_test_fixture import FixtureInfo
from hrm_converter.config import Config
from hrm_converter.discovery import DiscoveryResult, discover
from hrm_converter.hierarchy import detect_scope
from hrm_converter.validation import IssueCollector


def run_discovery(folder: object, config: Config) -> tuple[DiscoveryResult, IssueCollector]:
    issues = IssueCollector()
    scope = detect_scope(folder, config, issues)  # type: ignore[arg-type]
    return discover(scope, config, issues), issues


def categories(issues: IssueCollector) -> list[str]:
    return [issue.category for issue in issues.reportable()]


def test_only_hrm_is_processed(hierarchy: FixtureInfo, config: Config) -> None:
    result, _ = run_discovery(hierarchy.project, config)
    assert result.hrm_folder_count == 5
    assert all("HRM" in candidate.path.parts for candidate in result.candidates)
    assert hierarchy.files["other_machine"] not in [c.path for c in result.candidates]


def test_traversal_order_is_deterministic_and_natural(
    hierarchy: FixtureInfo, config: Config
) -> None:
    first, _ = run_discovery(hierarchy.project, config)
    second, _ = run_discovery(hierarchy.project, config)
    assert [c.path for c in first.candidates] == [c.path for c in second.candidates]

    order = [(c.context.buildup, c.context.process, c.context.panel) for c in first.candidates]
    lot_a1 = [entry for entry in order if entry[0] in ("BU-01", "BU-02", "BU-10")][:11]
    buildups = list(dict.fromkeys(entry[0] for entry in lot_a1))
    assert buildups == ["BU-01", "BU-02", "BU-10"]
    panels = [entry[2] for entry in order if entry[1] == "Post AAA" and entry[0] == "BU-01"][:5]
    assert panels == [2, 2, 2, 2, 10]  # Panel 2 before Panel 10


def test_context_is_built_from_the_folders(hierarchy: FixtureInfo, config: Config) -> None:
    result, _ = run_discovery(hierarchy.project, config)
    by_path = {c.path: c.context for c in result.candidates}
    coupon = by_path[hierarchy.files["trace_only_coupon"]]
    assert (coupon.buildup, coupon.process, coupon.panel) == ("BU-01", "Post AAA", 2)
    assert (coupon.side, coupon.location) == ("Front", "Coupon")
    assert coupon.process_folder == "post AAA_HRM-2099-0001"
    unit = by_path[hierarchy.files["pad_only"]]
    assert (unit.side, unit.location) == ("Back", "Unit")


def test_zero_workbooks_and_temporary_files(hierarchy: FixtureInfo, config: Config) -> None:
    result, issues = run_discovery(hierarchy.buildup_a1_bu01, config)
    assert not any(c.path.name.startswith("~$") for c in result.candidates)
    no_workbook = [i for i in issues.reportable() if i.category == "no_workbook"]
    assert len(no_workbook) == 1
    assert no_workbook[0].relative_path.endswith("Panel 10/back")


def test_multiple_workbooks_are_not_chosen_silently(hierarchy: FixtureInfo, config: Config) -> None:
    result, issues = run_discovery(hierarchy.buildup_a1_bu01, config)
    multiple = [
        c
        for c in result.candidates
        if c.context.process == "Post BBB" and c.context.side == "Front"
    ]
    assert len(multiple) == 2
    assert all(c.skip_reason and "Multiple workbooks" in c.skip_reason for c in multiple)
    errors = [i for i in issues.reportable() if i.category == "multiple_workbooks"]
    assert len(errors) == 1
    assert all(c.path.name in errors[0].message for c in multiple)


def test_newest_policy_must_be_configured_explicitly(
    hierarchy: FixtureInfo, make_config: ConfigFactory
) -> None:
    config = make_config(processing={"multiple_files_policy": "newest"})
    result, _ = run_discovery(hierarchy.buildup_a1_bu01, config)
    multiple = [
        c
        for c in result.candidates
        if c.context.process == "Post BBB" and c.context.side == "Front"
    ]
    assert sorted(c.skip_reason is None for c in multiple) == [False, True]


def test_empty_process_and_panel_folders_are_reported(
    hierarchy: FixtureInfo, config: Config
) -> None:
    _, issues = run_discovery(hierarchy.buildup_a1_bu01, config)
    empty = [i for i in issues.reportable() if i.category == "empty_folder"]
    assert {i.relative_path.rsplit("/", 1)[-1] for i in empty} == {
        "post CCC_HRM-2099-0003",
        "Panel 3",
    }


def test_unparsed_process_falls_back_to_folder_name(hierarchy: FixtureInfo, config: Config) -> None:
    result, issues = run_discovery(hierarchy.buildup_a1_bu01, config)
    assert "Special Run" in {c.context.process for c in result.candidates}
    assert "process_fallback" in categories(issues)


def test_files_not_matching_the_name_pattern_are_reported(
    hierarchy: FixtureInfo, make_config: ConfigFactory
) -> None:
    config = make_config(input={"filename_patterns": ["*_Report.xlsx"]})
    result, issues = run_discovery(hierarchy.lot_a1 / "BU02", config)
    assert result.candidates == ()
    assert {"filename_pattern", "no_workbook"} <= set(categories(issues))


def test_lot_name_comes_from_config(hierarchy: FixtureInfo, make_config: ConfigFactory) -> None:
    config = make_config(metadata={"default_lot_name": "Other", "lot_names": {"90001": "DOE Lot"}})
    result, _ = run_discovery(hierarchy.part_a, config)
    names = {c.context.lot_number: c.context.lot_name for c in result.candidates}
    assert names == {"90001": "DOE Lot", "90002": "Other"}
