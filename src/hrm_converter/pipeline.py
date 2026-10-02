"""Orchestration: scope detection -> discovery -> read -> transform -> write.

Kept free of any user-interface code so it can be driven by the CLI, by tests
or by another front end.
"""

from __future__ import annotations

import logging
from pathlib import Path

from hrm_converter.config import Config
from hrm_converter.discovery import discover
from hrm_converter.hierarchy import detect_scope
from hrm_converter.models import (
    Candidate,
    FileResult,
    LongRecord,
    RunResult,
    Status,
    WorkbookReadError,
)
from hrm_converter.output_writer import resolve_output_path, write_output
from hrm_converter.transformer import sort_records, transform
from hrm_converter.validation import IssueCollector, find_conflicts
from hrm_converter.workbook_reader import read_workbook

logger = logging.getLogger(__name__)


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

    return transform(sheet, candidate, config, issues), None


def run_conversion(start_path: Path, config: Config) -> RunResult:
    """Run the whole conversion for the selected folder and write the output workbook."""
    issues = IssueCollector()
    output_path = resolve_output_path(config, start_path)
    scope = detect_scope(start_path, config, issues)
    logger.info("Selected folder: %s (detected role: %s)", scope.start_path, scope.role.value)

    discovery = discover(scope, config, issues, exclude=output_path)
    result = RunResult(scope=scope, hrm_folder_count=discovery.hrm_folder_count)
    records: list[LongRecord] = []

    for candidate in discovery.candidates:
        if candidate.skip_reason is not None:
            result.file_results.append(
                FileResult(candidate, Status.SKIPPED, candidate.skip_reason, 0)
            )
            continue
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
    result.issues = issues.reportable()
    result.output_path = write_output(result, config, output_path)
    logger.info(
        "Finished: %d processed, %d skipped, %d rows, %d warnings, %d errors",
        result.processed_count,
        result.skipped_count,
        len(result.records),
        result.warning_count,
        result.error_count,
    )
    return result
