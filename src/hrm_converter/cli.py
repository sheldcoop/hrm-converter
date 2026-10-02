"""Command-line interface. All parsing and transformation logic lives elsewhere."""

from __future__ import annotations

import argparse
import dataclasses
import sys
from collections.abc import Sequence
from pathlib import Path

from hrm_converter import __version__
from hrm_converter.config import Config, load_config
from hrm_converter.logging_setup import close_logging, setup_logging
from hrm_converter.models import HrmConverterError, RunResult
from hrm_converter.output_writer import folder_check_frame
from hrm_converter.pipeline import run_conversion

DEFAULT_CONFIG = Path("config.yaml")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hrm_converter",
        description="Convert HRM Excel summary files below a Project, Part Number, Lot Number "
        "or Buildup folder into one long-format Excel workbook.",
    )
    parser.add_argument(
        "--input", type=Path, help="Folder to process. Omit to pick it in a dialog."
    )
    parser.add_argument(
        "--config", type=Path, help="Path to config.yaml (default: ./config.yaml if present)."
    )
    parser.add_argument("--output-dir", type=Path, help="Overrides output.directory of the config.")
    parser.add_argument(
        "--lot-name", help="Lot_Name written for every lot (overrides metadata.default_lot_name)."
    )
    parser.add_argument(
        "--reference",
        type=Path,
        help="Workbook with LSL / Target / USL; adds limit columns to the long table "
        "(default: wide.reference_path of the config).",
    )
    parser.add_argument(
        "--permissive",
        action="store_true",
        help="On metadata conflicts use the hierarchy value instead of skipping the file.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def pick_folder() -> Path | None:
    """Native folder dialog; None when cancelled or when no display is available."""
    if not sys.stdin.isatty():
        return None
    try:
        import tkinter
        from tkinter import filedialog

        root = tkinter.Tk()
        root.withdraw()
        selected = filedialog.askdirectory(
            title="Select a Project, Part Number, Lot Number or Buildup folder"
        )
        root.destroy()
    except Exception:  # no display, tkinter not installed, ...
        return None
    return Path(selected) if selected else None


def _apply_overrides(config: Config, args: argparse.Namespace) -> Config:
    if args.output_dir is not None:
        config = dataclasses.replace(
            config, output=dataclasses.replace(config.output, directory=args.output_dir)
        )
    if args.lot_name is not None:
        config = dataclasses.replace(
            config, metadata=dataclasses.replace(config.metadata, default_lot_name=args.lot_name)
        )
    if args.permissive:
        config = dataclasses.replace(
            config,
            processing=dataclasses.replace(config.processing, strict_metadata_conflicts=False),
        )
    return config


def format_summary(result: RunResult) -> str:
    """Concise completion summary; never contains measurement records."""
    assert result.scope is not None  # the command line always converts a folder
    check = folder_check_frame(result)
    lines = [
        "",
        "HRM conversion finished",
        f"  Selected scope      : {result.scope.role.value} folder '{result.scope.start_path}'",
        f"  HRM folders found   : {result.hrm_folder_count}",
        f"  Workbooks processed : {result.processed_count}",
        f"  Workbooks skipped   : {result.skipped_count}",
        f"  Output rows         : {len(result.records)}",
        f"  Warnings / errors   : {result.warning_count} / {result.error_count}",
        f"  Lots needing fixes  : {int((check['Verdict'] != 'OK').sum())} of {len(check)}"
        " (folder structure)",
        f"  Output workbook     : {result.output_path}",
        f"  Log file            : {result.log_path}",
    ]
    if result.warning_count or result.error_count:
        lines.append(
            "  See the 'Folder_Check' and 'Validation_Issues' sheets of the output workbook "
            "for what to fix."
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config_path = args.config
        if config_path is None and DEFAULT_CONFIG.is_file():
            config_path = DEFAULT_CONFIG
        config = _apply_overrides(load_config(config_path), args)

        start = args.input or config.input.start_path or pick_folder()
        if start is None:
            print(
                'No folder selected. Pass --input "<folder>" or set input.start_path '
                "in the config.",
                file=sys.stderr,
            )
            return 2

        log_path = setup_logging(config.logging.directory, config.logging.level)
        try:
            result = run_conversion(Path(start), config, reference=args.reference)
        finally:
            close_logging()
        result.log_path = log_path.resolve()
    except HrmConverterError as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        return 1

    print(format_summary(result))
    return 0
