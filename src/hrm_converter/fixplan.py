"""Fix plan: safe, reviewable repairs of a wrong folder structure.

The converter never changes source folders. For the few problems whose repair
is unambiguous it writes down what it *would* do, as rows of the ``Fix_Plan``
sheet and as a small script the user can read, edit and run:

* a panel folder with exactly one number in its name   -> rename to ``Panel <n>``
* a side folder that names exactly one side             -> rename to ``front`` / ``back`` /
                                                           ``Coupon front`` / ``Coupon back``
* a Buildup folder with exactly one number in its name  -> rename to ``BU<nn>``
* a workbook lying directly in a panel folder whose file name states its side
                                                        -> move into that side folder

A repair is only proposed when its target does not exist yet. Anything
ambiguous (two sides in a name, no number, a target already in use) is left to
the user and only reported.
"""

from __future__ import annotations

import os
import re
import shlex
from collections.abc import Sequence
from pathlib import Path

from hrm_converter.config import Config, normalize_key
from hrm_converter.models import FixProposal
from hrm_converter.validation import IssueCollector

RENAME = "Rename folder"
MOVE = "Move file"
_NUMBER = re.compile(r"\d+")


def _only_number(name: str) -> int | None:
    numbers = _NUMBER.findall(name)
    return int(numbers[0]) if len(numbers) == 1 else None


def side_folder_name(text: str, config: Config) -> str | None:
    """'Back (remeasure)' -> 'back'; 'x_Coupon_Front_Summary' -> 'Coupon front'; else None."""
    key = normalize_key(text)
    sides = [
        side
        for side in config.hierarchy.sides
        if re.search(rf"(?<![a-z]){re.escape(side)}(?![a-z])", key)
    ]
    if len(sides) != 1:
        return None
    coupon = config.hierarchy.coupon_keyword
    return f"Coupon {sides[0]}" if coupon and coupon in key else sides[0]


def _propose(issues: IssueCollector, action: str, source: Path, target: Path, reason: str) -> None:
    taken = {proposal.target for proposal in issues.proposals}
    if source != target and not target.exists() and target not in taken:
        issues.proposals.append(FixProposal(action, source, target, reason))


def propose_panel_rename(folder: Path, issues: IssueCollector) -> None:
    number = _only_number(folder.name)
    if number is not None:
        _propose(issues, RENAME, folder, folder.with_name(f"Panel {number}"),
                 f"'{folder.name}' is not a panel folder name")  # fmt: skip


def propose_side_rename(folder: Path, config: Config, issues: IssueCollector) -> None:
    name = side_folder_name(folder.name, config)
    if name is not None:
        _propose(issues, RENAME, folder, folder.with_name(name),
                 f"'{folder.name}' is not a side folder name")  # fmt: skip


def propose_buildup_rename(folder: Path, issues: IssueCollector) -> None:
    number = _only_number(folder.name)
    if number is not None:
        _propose(issues, RENAME, folder, folder.with_name(f"BU{number:02d}"),
                 f"'{folder.name}' is not a Buildup folder name")  # fmt: skip


def propose_file_moves(
    panel_dir: Path, names: Sequence[str], config: Config, issues: IssueCollector
) -> None:
    """Workbooks lying directly in a panel folder go into the side folder their name states."""
    targets: dict[str, list[str]] = {}
    for name in names:
        side = side_folder_name(Path(name).stem, config)
        if side is not None:
            targets.setdefault(side, []).append(name)
    for side, files in targets.items():
        folder = panel_dir / side
        occupied = folder.is_dir() and any(
            item.suffix.lower() in config.input.accepted_extensions for item in folder.iterdir()
        )
        if len(files) == 1 and not occupied:  # never create a two-workbook side folder
            _propose(issues, MOVE, panel_dir / files[0], folder / files[0],
                     f"workbook lies in the panel folder; its name says '{side}'")  # fmt: skip


def fix_script(proposals: Sequence[FixProposal], windows: bool | None = None) -> str:
    """The proposals as a script: a .bat for Windows, a shell script elsewhere."""
    windows = os.name == "nt" if windows is None else windows
    if windows:

        def quote(path: Path) -> str:
            return '"' + str(path).replace("%", "%%") + '"'

        lines = [
            "@echo off",
            "rem HRM converter - proposed folder fixes.",
            "rem READ every line before running. The converter itself never changes your folders.",
            "rem Delete the lines you do not want.",
            "rem Nothing is overwritten: existing targets are skipped.",
            "",
        ]
        for proposal in proposals:
            source, target, parent = (
                quote(proposal.source),
                quote(proposal.target),
                quote(proposal.target.parent),
            )
            lines += [
                f"rem {proposal.action}: {proposal.reason}",
                f"if not exist {parent} mkdir {parent}",
                f"if exist {target} echo SKIPPED - target already exists: {target}",
                f"if not exist {target} move {source} {target}",
                "",
            ]
        lines.append("pause")
        return "\r\n".join(lines) + "\r\n"

    lines = [
        "#!/bin/sh",
        "# HRM converter - proposed folder fixes.",
        "# READ every line before running. The converter itself never changes your folders.",
        "# Delete the lines you do not want. Nothing is overwritten: existing targets are skipped.",
        "",
    ]
    for proposal in proposals:
        source, target = shlex.quote(str(proposal.source)), shlex.quote(str(proposal.target))
        parent = shlex.quote(str(proposal.target.parent))
        lines += [
            f"# {proposal.action}: {proposal.reason}",
            f"mkdir -p {parent}",
            f"if [ -e {target} ]; then echo SKIPPED - target already exists: {target}; "
            f"else mv {source} {target}; fi",
            "",
        ]
    return "\n".join(lines)


def write_fix_script(proposals: Sequence[FixProposal], path: Path) -> Path | None:
    """Write the script next to the output workbook; None when there is nothing to fix."""
    if not proposals:
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(fix_script(proposals), encoding="utf-8", newline="")
    return path
