"""Orchestration: scope detection -> discovery -> read -> transform -> write.

Kept free of any user-interface code so it can be driven by the CLI, by tests
or by another front end.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Sequence
from pathlib import Path
from typing import IO

from hrm_converter.config import Config
from hrm_converter.discovery import discover
from hrm_converter.fixplan import write_fix_script
from hrm_converter.hierarchy import detect_scope
from hrm_converter.models import (
    LONG_COLUMNS,
    Candidate,
    FileResult,
    LimitValues,
    LongRecord,
    RunResult,
    Status,
    WorkbookContext,
    WorkbookReadError,
)
from hrm_converter.naming import (
    fix_script_name,
    loose_label,
    render,
    scope_label,
    timestamp,
)
from hrm_converter.output_writer import resolve_output_path, write_output
from hrm_converter.quality import check_values
from hrm_converter.reference import LimitMatcher, load_reference
from hrm_converter.transformer import sort_records, transform
from hrm_converter.validation import IssueCollector, find_conflicts
from hrm_converter.workbook_reader import read_workbook

logger = logging.getLogger(__name__)
_NAME = "output.filename"


def _process(
    candidate: Candidate, config: Config, issues: IssueCollector
) -> tuple[list[LongRecord], str | None]:
    """Convert one workbook; returns (records, skip reason or None)."""
    name = candidate.path.name
    sheet = read_workbook(candidate.path)
    details = {
        "source_file": name,
        "sheet": sheet.sheet_name,
        "relative_path": candidate.relative_path,
    }

    conflicts = find_conflicts(candidate.context, sheet.sheet_name, name, config)
    strict = config.processing.strict_metadata_conflicts
    for conflict in conflicts:
        message = (
            f"{conflict.field} from the folder hierarchy ('{conflict.hierarchy_value}') disagrees "
            f"with the workbook {conflict.source} ('{conflict.workbook_value}'). "
            + (
                "File skipped (strict mode)."
                if strict
                else "Hierarchy value used (permissive mode)."
            )
        )
        report = issues.error if strict else issues.warning
        report(
            "metadata_conflict",
            message,
            field=conflict.field,
            hierarchy_value=conflict.hierarchy_value,
            workbook_value=conflict.workbook_value,
            **details,
        )
    if conflicts and strict:
        fields = ", ".join(dict.fromkeys(c.field for c in conflicts))
        return [], f"Metadata conflict between hierarchy and workbook: {fields}"

    rows = transform(sheet, candidate, config, issues)
    check_values(rows, candidate, config, issues)
    return rows, None


class _DuplicateFinder:
    """Reports a workbook whose content is identical to one already seen in this run."""

    def __init__(self, config: Config, issues: IssueCollector) -> None:
        self.enabled = config.quality.duplicate_file_check
        self.issues = issues
        self._seen: dict[str, str] = {}

    def check(self, candidate: Candidate, source: Path | IO[bytes]) -> None:
        if not self.enabled:
            return
        try:
            if isinstance(source, Path):
                data = source.read_bytes()
            else:
                position = source.tell()
                data = source.read()
                source.seek(position)
        except OSError:
            return  # unreadable files are reported by the reader
        digest = hashlib.sha256(data).hexdigest()
        first = self._seen.setdefault(digest, candidate.relative_path)
        if first != candidate.relative_path:
            self.issues.error(
                "duplicate_workbook",
                f"This workbook has exactly the same content as '{first}'. Both were "
                f"converted; one of them is probably a copy in the wrong place.",
                source_file=candidate.path.name,
                relative_path=candidate.relative_path,
            )


ReferenceSource = Path | IO[bytes] | None


def _load_limits(
    source: ReferenceSource, name: str | None, config: Config, issues: IssueCollector
) -> LimitMatcher | None:
    """The reference workbook given for this run, else the configured one, else none."""
    chosen = source if source is not None else config.wide.reference_path
    if chosen is None:
        return None
    return LimitMatcher(load_reference(chosen, config, issues, name=name), config, issues)


def _record_limits(records: list[LongRecord], matcher: LimitMatcher | None) -> list[LimitValues]:
    if matcher is None:
        return []
    found = (matcher.limits(dict(zip(LONG_COLUMNS, r.as_row(), strict=True))) for r in records)
    return [(limits.lsl, limits.target, limits.usl) for limits in found]


def run_conversion(
    start_path: Path,
    config: Config,
    reference: ReferenceSource = None,
    reference_name: str | None = None,
) -> RunResult:
    """Run the whole conversion for the selected folder and write the output workbook.

    With a reference workbook, the Long sheet also carries LSL / Target / USL per row.
    """
    issues = IssueCollector()
    stamp = timestamp()
    # Checked with a placeholder name first, so a bad output location stops the run early.
    resolve_output_path(config, start_path, render(config.output.filename, "x", stamp, _NAME))
    matcher = _load_limits(reference, reference_name, config, issues)
    scope = detect_scope(start_path, config, issues)
    label = scope_label(scope)
    output_path = resolve_output_path(
        config, start_path, render(config.output.filename, label, stamp, _NAME)
    )
    logger.info("Selected folder: %s (detected role: %s)", scope.start_path, scope.role.value)

    discovery = discover(scope, config, issues, exclude=output_path)
    result = RunResult(
        scope=scope, hrm_folder_count=discovery.hrm_folder_count, label=label, timestamp=stamp
    )
    records: list[LongRecord] = []

    duplicates = _DuplicateFinder(config, issues)
    for candidate in discovery.candidates:
        if candidate.skip_reason is not None:
            result.file_results.append(
                FileResult(candidate, Status.SKIPPED, candidate.skip_reason, 0)
            )
            continue
        duplicates.check(candidate, candidate.path)
        try:
            rows, skip_reason = _process(candidate, config, issues)
        except WorkbookReadError as exc:
            issues.error(
                "unreadable_workbook",
                str(exc),
                source_file=candidate.path.name,
                relative_path=candidate.relative_path,
            )
            result.file_results.append(FileResult(candidate, Status.SKIPPED, str(exc), 0))
            continue
        except Exception as exc:  # one malformed workbook must never stop the run
            logger.exception("Unexpected problem in %s", candidate.path)
            reason = f"Unexpected problem: {type(exc).__name__}: {exc}"
            issues.error(
                "unexpected_error",
                reason,
                source_file=candidate.path.name,
                relative_path=candidate.relative_path,
            )
            result.file_results.append(FileResult(candidate, Status.SKIPPED, reason, 0))
            continue
        if skip_reason is not None:
            result.file_results.append(FileResult(candidate, Status.SKIPPED, skip_reason, 0))
            continue
        records.extend(rows)
        logger.info("Processed %s: %d rows", candidate.relative_path, len(rows))
        result.file_results.append(FileResult(candidate, Status.PROCESSED, "", len(rows)))

    result.records = sort_records(records)
    result.record_limits = _record_limits(result.records, matcher)
    result.issues = issues.reportable()
    result.fix_plan = list(issues.proposals)
    result.output_path = write_output(result, config, output_path)
    result.fix_script_path = write_fix_script(
        result.fix_plan, output_path.parent / fix_script_name(label, stamp)
    )
    logger.info(
        "Finished: %d processed, %d skipped, %d rows, %d warnings, %d errors",
        result.processed_count,
        result.skipped_count,
        len(result.records),
        result.warning_count,
        result.error_count,
    )
    return result


LOOSE_FOLDER = "(loose file)"


def run_loose_files(
    files: Sequence[tuple[str, Path | IO[bytes]]],
    config: Config,
    reference: ReferenceSource = None,
    reference_name: str | None = None,
) -> RunResult:
    """Convert workbooks that are not in a folder hierarchy.

    ``files`` holds (file name, path or open binary file). There are no folders
    to read metadata from and nothing is guessed from the file name, so every
    metadata column (Project_Name .. Location) is left blank for the user to
    fill in. Unit, feature, metric, value and Source_File are filled as usual.
    """
    issues = IssueCollector()
    stamp, label = timestamp(), loose_label([name for name, _ in files])
    filename = render(config.output.filename, label, stamp, _NAME)
    output_path = (Path.cwd() / config.output.directory / filename).resolve()
    matcher = _load_limits(reference, reference_name, config, issues)
    blank = WorkbookContext(
        project_name="",
        part_number="",
        lot_number="",
        lot_name="",
        buildup="",
        process="",
        process_folder="",
        panel="",
        side="",
        location="",
        folder=Path("."),
        relative_folder=LOOSE_FOLDER,
    )
    result = RunResult(scope=None, label=label, timestamp=stamp)
    records: list[LongRecord] = []
    seen: set[str] = set()
    duplicates = _DuplicateFinder(config, issues)

    for name, source in files:
        on_disk = isinstance(source, Path) and source.name == name
        candidate = Candidate(source.resolve() if on_disk else Path(name), blank)  # type: ignore[union-attr]
        details = {"source_file": name, "relative_path": candidate.relative_path}
        if name in seen:
            reason = "Another file with the same name was already given; skipped."
            issues.error("duplicate_file_name", reason, **details)
            result.file_results.append(FileResult(candidate, Status.SKIPPED, reason, 0))
            continue
        seen.add(name)
        duplicates.check(candidate, source)
        try:
            rows = transform(read_workbook(source), candidate, config, issues)
            check_values(rows, candidate, config, issues)
        except WorkbookReadError as exc:
            issues.error("unreadable_workbook", str(exc), **details)
            result.file_results.append(FileResult(candidate, Status.SKIPPED, str(exc), 0))
            continue
        except Exception as exc:  # one malformed workbook must never stop the run
            logger.exception("Unexpected problem in %s", name)
            reason = f"Unexpected problem: {type(exc).__name__}: {exc}"
            issues.error("unexpected_error", reason, **details)
            result.file_results.append(FileResult(candidate, Status.SKIPPED, reason, 0))
            continue
        records.extend(rows)
        result.file_results.append(FileResult(candidate, Status.PROCESSED, "", len(rows)))

    result.records = sort_records(records)
    result.record_limits = _record_limits(result.records, matcher)
    result.issues = issues.reportable()
    result.output_path = write_output(result, config, output_path)
    logger.info(
        "Finished loose files: %d processed, %d skipped, %d rows",
        result.processed_count,
        result.skipped_count,
        len(result.records),
    )
    return result
