"""Names of the files the converter writes, so each says what it holds.

    HRM_Long_FHR0020_19198_2026-10-02_1745.xlsx
    HRM_Wide_FHR0020_19198_2026-10-02_1745.xlsx
    HRM_FixFolders_FHR0020_19198_2026-10-02_1745.bat

``{scope}`` is what was selected (project, part, part + lot, or part + lot +
Buildup) and ``{timestamp}`` the minute the run started, shared by all files
of one run. Both are placeholders in ``output.filename`` and ``wide.filename``.
"""

from __future__ import annotations

import os
import re
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from hrm_converter.models import ConfigError, FolderRole, Scope

_UNSAFE = re.compile(r"[^\w.\-]+")
_PLACEHOLDER = re.compile(r"\{[^{}]*\}")
_MAX_PART = 60


def _safe(text: str) -> str:
    return _UNSAFE.sub("-", text.strip()).strip("-")[:_MAX_PART] or "HRM"


def timestamp() -> str:
    return datetime.now().strftime("%Y-%m-%d_%H%M")


def scope_label(scope: Scope) -> str:
    """Project folder -> 'Chiplet4Future'; Lot folder -> 'FHR0020_19198'; and so on."""
    parts = scope.start_path.relative_to(scope.project_path.parent).parts
    names = {
        FolderRole.PROJECT: parts[:1],
        FolderRole.PART_NUMBER: parts[1:2],
        FolderRole.LOT_NUMBER: parts[1:3],
        FolderRole.BUILDUP: parts[1:4],
    }[scope.role]
    return "_".join(_safe(name) for name in names)


def loose_label(file_names: Sequence[str]) -> str:
    """One loose file -> its own name; several -> how many."""
    if len(file_names) == 1:
        return _safe(Path(file_names[0]).stem)
    return f"{len(file_names)}-loose-files"


def render(template: str, scope: str, stamp: str, setting: str) -> str:
    """Fill ``{scope}`` and ``{timestamp}`` into a file-name setting."""
    try:
        name = template.format(scope=scope, timestamp=stamp)
    except (KeyError, IndexError, ValueError) as exc:
        raise ConfigError(
            f"Setting '{setting}' ('{template}') may only use the placeholders {{scope}} and "
            f"{{timestamp}}."
        ) from exc
    if not name.lower().endswith(".xlsx"):
        raise ConfigError(f"Setting '{setting}' must end with .xlsx: {template}")
    return name


def wide_name_for(long_path: Path) -> str:
    """Wide workbook name matching a long workbook: 'HRM_Long_x' -> 'HRM_Wide_x'."""
    stem = long_path.stem
    for long, wide in (("Long", "Wide"), ("long", "wide"), ("LONG", "WIDE")):
        if long in stem:
            return stem.replace(long, wide, 1) + ".xlsx"
    return f"{stem}_wide.xlsx"


def glob_for(template: str) -> str:
    """Glob pattern matching every file a template can produce."""
    return _PLACEHOLDER.sub("*", template)


def fix_script_name(scope: str, stamp: str) -> str:
    extension = "bat" if os.name == "nt" else "sh"
    return f"HRM_FixFolders_{scope}_{stamp}.{extension}"
