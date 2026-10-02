"""HRM-only traversal: Buildup -> HRM -> Process -> Panel -> Side -> workbook."""

from __future__ import annotations

import fnmatch
from dataclasses import dataclass
from pathlib import Path

from hrm_converter.config import Config
from hrm_converter.hierarchy import (
    is_machine_folder,
    list_dirs,
    parse_panel,
    parse_process,
    parse_side,
)
from hrm_converter.models import BuildupFolder, Candidate, Scope, WorkbookContext
from hrm_converter.validation import IssueCollector, natural_key


@dataclass(frozen=True)
class DiscoveryResult:
    candidates: tuple[Candidate, ...]
    hrm_folder_count: int


def _lot_name(lot_number: str, config: Config) -> str:
    return config.metadata.lot_names.get(lot_number, config.metadata.default_lot_name)


def _workbooks(folder: Path, config: Config, exclude: Path | None) -> tuple[list[Path], list[str]]:
    """Candidate workbooks in a side folder, plus Excel files not matching the name pattern."""
    matching: list[Path] = []
    not_matching: list[str] = []
    for item in sorted(folder.iterdir(), key=lambda p: (natural_key(p.name), p.name)):
        if not item.is_file() or item.suffix.lower() not in config.input.accepted_extensions:
            continue
        if any(item.name.startswith(prefix) for prefix in config.input.ignore_filename_prefixes):
            continue
        if exclude is not None and item.resolve() == exclude:
            continue
        name = item.name.lower()
        if any(fnmatch.fnmatch(name, p.lower()) for p in config.input.filename_patterns):
            matching.append(item)
        else:
            not_matching.append(item.name)
    return matching, not_matching


def _side_candidates(
    side_dir: Path,
    context: WorkbookContext,
    config: Config,
    issues: IssueCollector,
    exclude: Path | None,
) -> list[Candidate]:
    relative = context.relative_folder
    try:
        files, not_matching = _workbooks(side_dir, config, exclude)
    except OSError as exc:
        issues.error("unreadable_folder", f"Folder cannot be listed: {exc}", relative_path=relative)
        return []
    if not_matching:
        issues.warning(
            "filename_pattern",
            f"Excel file(s) not matching {list(config.input.filename_patterns)} were ignored: "
            f"{', '.join(not_matching)}",
            relative_path=relative,
        )
    if not files:
        issues.warning(
            "no_workbook", "No HRM workbook found in this folder.", relative_path=relative
        )
        return []
    if len(files) == 1:
        return [Candidate(files[0], context)]

    names = ", ".join(f.name for f in files)
    if config.processing.multiple_files_policy == "newest":
        newest = max(files, key=lambda f: (f.stat().st_mtime, f.name))
        issues.warning(
            "multiple_workbooks",
            f"{len(files)} workbooks found ({names}); newest by file date used: {newest.name} "
            f"(multiple_files_policy: newest).",
            relative_path=relative,
        )
        reason = f"Older duplicate; {newest.name} used (multiple_files_policy: newest)"
        return [Candidate(f, context, None if f == newest else reason) for f in files]
    issues.error(
        "multiple_workbooks",
        f"{len(files)} workbooks found in one folder; none was chosen and the folder was "
        f"skipped. Candidates: {names}",
        relative_path=relative,
    )
    reason = f"Multiple workbooks in folder ({len(files)}); folder skipped"
    return [Candidate(f, context, reason) for f in files]


def _buildup_candidates(
    buildup: BuildupFolder,
    hrm_dir: Path,
    base: Path,
    config: Config,
    issues: IssueCollector,
    exclude: Path | None,
) -> list[Candidate]:
    candidates: list[Candidate] = []
    process_dirs = list_dirs(hrm_dir, issues)
    if not process_dirs:
        issues.warning(
            "empty_folder",
            "HRM folder contains no process folders.",
            relative_path=hrm_dir.relative_to(base).as_posix(),
        )
    for process_dir in process_dirs:
        process_rel = process_dir.relative_to(base).as_posix()
        process, parsed = parse_process(process_dir.name, config)
        if not parsed:
            issues.warning(
                "process_fallback",
                f"Process could not be parsed from the folder name; folder name '{process}' "
                f"used as Process.",
                field="Process",
                relative_path=process_rel,
            )
        panel_dirs = list_dirs(process_dir, issues)
        if not panel_dirs:
            issues.warning(
                "empty_folder",
                "Process folder contains no panel folders.",
                relative_path=process_rel,
            )
        for panel_dir in panel_dirs:
            panel_rel = panel_dir.relative_to(base).as_posix()
            panel = parse_panel(panel_dir.name, config)
            if panel is None:
                issues.error(
                    "invalid_panel_folder",
                    f"Folder name '{panel_dir.name}' is not a panel folder; skipped.",
                    field="Panel",
                    relative_path=panel_rel,
                )
                continue
            side_dirs = list_dirs(panel_dir, issues)
            if not side_dirs:
                issues.warning(
                    "empty_folder",
                    "Panel folder contains no side folders.",
                    relative_path=panel_rel,
                )
            for side_dir in side_dirs:
                side_rel = side_dir.relative_to(base).as_posix()
                side = parse_side(side_dir.name, config)
                if side is None:
                    issues.error(
                        "invalid_side_folder",
                        f"Side/location cannot be interpreted from folder name "
                        f"'{side_dir.name}'; skipped.",
                        field="Side",
                        relative_path=side_rel,
                    )
                    continue
                context = WorkbookContext(
                    project_name=buildup.project_name,
                    part_number=buildup.part_number,
                    lot_number=buildup.lot_number,
                    lot_name=_lot_name(buildup.lot_number, config),
                    buildup=buildup.buildup,
                    process=process,
                    process_folder=process_dir.name,
                    panel=panel,
                    side=side[0],
                    location=side[1],
                    folder=side_dir,
                    relative_folder=side_rel,
                )
                candidates.extend(_side_candidates(side_dir, context, config, issues, exclude))
    return candidates


def discover(
    scope: Scope, config: Config, issues: IssueCollector, exclude: Path | None = None
) -> DiscoveryResult:
    """Find every candidate HRM workbook in scope, in deterministic order.

    ``exclude`` is the output workbook path, so a run never reads its own output.
    """
    base = scope.project_path.parent
    candidates: list[Candidate] = []
    hrm_count = 0
    for buildup in scope.buildups:
        hrm_dirs = [d for d in list_dirs(buildup.path, issues) if is_machine_folder(d.name, config)]
        if len(hrm_dirs) > 1:
            issues.error(
                "duplicate_hrm_folder",
                f"Several '{config.scope.machine_folder}' folders found "
                f"({', '.join(d.name for d in hrm_dirs)}); Buildup skipped.",
                relative_path=buildup.path.relative_to(base).as_posix(),
            )
            continue
        for hrm_dir in hrm_dirs:
            hrm_count += 1
            candidates.extend(_buildup_candidates(buildup, hrm_dir, base, config, issues, exclude))
    return DiscoveryResult(tuple(candidates), hrm_count)
