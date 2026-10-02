"""Folder-name interpretation and role detection for the selected folder.

Expected hierarchy:
``Project / Part Number / Lot Number / Buildup / HRM / Process / Panel / Side``.

The role of the selected folder is derived from where the machine folder
(``HRM``) sits below it, validated against the Buildup naming pattern and the
number of parent folders available for metadata. It is never taken from the
absolute folder depth alone.
"""

from __future__ import annotations

from pathlib import Path

from hrm_converter.config import Config, normalize_key
from hrm_converter.fixplan import propose_buildup_rename
from hrm_converter.models import BuildupFolder, FolderRole, HierarchyError, Scope
from hrm_converter.validation import IssueCollector, natural_key

LOCATION_UNIT = "Unit"
LOCATION_COUPON = "Coupon"

# Depth of the machine folder below the selected folder -> role of that folder.
_ROLE_BY_DEPTH = {
    1: FolderRole.BUILDUP,
    2: FolderRole.LOT_NUMBER,
    3: FolderRole.PART_NUMBER,
    4: FolderRole.PROJECT,
}
_MAX_DEPTH = max(_ROLE_BY_DEPTH)


def is_machine_folder(name: str, config: Config) -> bool:
    return name.strip().casefold() == config.scope.machine_folder.casefold()


def list_dirs(path: Path, issues: IssueCollector | None = None) -> list[Path]:
    """Visible sub-folders in deterministic natural order."""
    try:
        dirs = [p for p in path.iterdir() if p.is_dir() and not p.name.startswith(".")]
    except OSError as exc:
        if issues is not None:
            issues.error(
                "unreadable_folder", f"Folder cannot be listed: {exc}", relative_path=str(path)
            )
        return []
    return sorted(dirs, key=lambda p: (natural_key(p.name), p.name))


def parse_buildup(name: str, config: Config) -> str | None:
    """'BU03' / 'bu 3' -> 'BU-03'; None when the name is not a Buildup name."""
    match = config.hierarchy.buildup_pattern.match(name.strip())
    if not match:
        return None
    if "number" in match.groupdict() and match.group("number") is not None:
        return config.hierarchy.buildup_format.format(number=int(match.group("number")))
    return name.strip()


def parse_process(name: str, config: Config) -> tuple[str, bool]:
    """'post DDV_HRM-2026-0088' -> ('Post DDV', True); fallback (trimmed name, False)."""
    trimmed = " ".join(name.split())
    match = config.hierarchy.process_pattern.match(trimmed)
    if not match or not match.group("name").strip(" _-"):
        return trimmed, False
    words = match.group("name").strip(" _-").split()
    words[0] = words[0][:1].upper() + words[0][1:]
    return " ".join(words), True


def parse_panel(name: str, config: Config) -> int | None:
    match = config.hierarchy.panel_pattern.match(name.strip())
    return int(match.group("number")) if match else None


def parse_side(name: str, config: Config) -> tuple[str, str] | None:
    """'Coupon_front' -> ('Front', 'Coupon'); 'back' -> ('Back', 'Unit')."""
    key = normalize_key(name)
    location = LOCATION_UNIT
    coupon = config.hierarchy.coupon_keyword
    if coupon and key.startswith(coupon):
        location = LOCATION_COUPON
        key = key[len(coupon) :].strip()
    side = config.hierarchy.sides.get(key)
    return (side, location) if side else None


def _machine_depths(start: Path, config: Config) -> dict[int, list[Path]]:
    """Machine folders below ``start`` grouped by depth (1 = direct child)."""
    found: dict[int, list[Path]] = {}
    level = [start]
    for depth in range(1, _MAX_DEPTH + 1):
        next_level: list[Path] = []
        for folder in level:
            for child in list_dirs(folder):
                if is_machine_folder(child.name, config):
                    found.setdefault(depth, []).append(child)
                else:
                    next_level.append(child)
        level = next_level
    return found


def _choose_depth(start: Path, found: dict[int, list[Path]], config: Config) -> int:
    machine = config.scope.machine_folder
    if not found:
        raise HierarchyError(
            f"No '{machine}' folder was found within {_MAX_DEPTH} levels below '{start}'. "
            f"Select a Project, Part Number, Lot Number or Buildup folder."
        )
    if len(found) == 1:
        return next(iter(found))
    # HRM folders at several depths: only accept a depth whose parents look like Buildups.
    plausible = [
        depth
        for depth, folders in found.items()
        if any(parse_buildup(f.parent.name, config) for f in folders)
    ]
    if len(plausible) == 1:
        return plausible[0]
    examples = "; ".join(
        f"level {depth}: {folders[0].relative_to(start)}"
        for depth, folders in sorted(found.items())
    )
    raise HierarchyError(
        f"The role of '{start}' cannot be determined reliably: '{machine}' folders were found "
        f"at different levels below it ({examples}). Select a folder with a consistent structure."
    )


def _in_filter(allowed: frozenset[str] | None, *names: str) -> bool:
    return allowed is None or any(normalize_key(n) in allowed for n in names)


def detect_scope(start: Path, config: Config, issues: IssueCollector) -> Scope:
    """Detect the role of the selected folder and list the Buildups in scope."""
    start = start.expanduser().resolve()
    machine = config.scope.machine_folder
    if not start.is_dir():
        raise HierarchyError(f"The selected folder does not exist or is not a folder: {start}")
    if any(is_machine_folder(part, config) for part in start.parts):
        raise HierarchyError(
            f"The selected folder '{start}' is the '{machine}' folder or lies inside it. "
            f"Select a Project, Part Number, Lot Number or Buildup folder instead."
        )

    depth = _choose_depth(start, _machine_depths(start, config), config)
    role = _ROLE_BY_DEPTH[depth]
    parents_needed = _MAX_DEPTH - depth
    if len(start.parents) <= parents_needed:
        raise HierarchyError(
            f"'{start}' looks like a {role.value} folder ('{machine}' is {depth} level(s) below "
            f"it), but it has too few parent folders to reconstruct Project, Part Number and Lot."
        )
    project_path = start if parents_needed == 0 else start.parents[parents_needed - 1]

    # Collect every folder at Buildup level, walking down from the selected folder.
    level = [start]
    for _ in range(depth - 1):
        level = [child for folder in level for child in list_dirs(folder, issues)]

    buildup_filter = config.scope.buildups
    if buildup_filter is not None:
        buildup_filter = frozenset(
            normalize_key(parse_buildup(entry, config) or entry) for entry in buildup_filter
        )

    buildups: list[BuildupFolder] = []
    unmatched: list[str] = []
    for folder in level:
        relative = folder.relative_to(project_path.parent).as_posix()
        project, part, lot = (
            p.name.strip() for p in (folder.parents[2], folder.parents[1], folder.parent)
        )
        has_machine = any(is_machine_folder(c.name, config) for c in list_dirs(folder))
        buildup = parse_buildup(folder.name, config)
        if not has_machine:
            if buildup:
                issues.warning(
                    "missing_hrm_folder",
                    f"Buildup folder has no '{machine}' folder; nothing to process.",
                    relative_path=relative,
                )
            else:
                issues.info(
                    "ignored_folder", "Folder is not a Buildup; ignored.", relative_path=relative
                )
            continue
        if buildup is None:
            if config.hierarchy.require_buildup_pattern:
                unmatched.append(folder.name)
                issues.error(
                    "invalid_buildup_name",
                    f"Folder contains '{machine}' but its name does not match the Buildup "
                    f"naming pattern; skipped.",
                    field="Buildup",
                    relative_path=relative,
                )
                propose_buildup_rename(folder, issues)
                continue
            buildup = folder.name.strip()
        if not (
            _in_filter(config.scope.part_numbers, part)
            and _in_filter(config.scope.lot_numbers, lot)
            and _in_filter(buildup_filter, buildup, folder.name)
        ):
            issues.info(
                "filtered_out", "Buildup excluded by scope filters.", relative_path=relative
            )
            continue
        buildups.append(
            BuildupFolder(
                path=folder,
                project_name=project,
                part_number=part,
                lot_number=lot,
                buildup=buildup,
                buildup_folder=folder.name,
            )
        )

    if unmatched and not buildups:
        raise HierarchyError(
            f"'{start}' looks like a {role.value} folder, but validation failed: the folder(s) "
            f"containing '{machine}' ({', '.join(unmatched)}) do not match the Buildup naming "
            f"pattern '{config.hierarchy.buildup_pattern.pattern}'. Adjust "
            f"'hierarchy.buildup_pattern' in the config or select a different folder."
        )
    return Scope(start_path=start, role=role, project_path=project_path, buildups=tuple(buildups))
