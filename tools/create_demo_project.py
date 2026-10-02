"""Create a realistic-looking demo hierarchy: one project, one part, several lots.

Unlike ``create_test_fixture.py`` (which is full of deliberate problems), this
one is a clean "happy path" tree shaped like a real engineering folder, for a
manual smoke test. All values are synthetic: a typical-looking base value per
column plus ``unit * 0.02 + file_number * 0.01``. It also writes a small demo
reference workbook with limits (``HRM_Reference_demo.xlsx``).

Optionally one real HRM workbook can be copied into the matching Buildup/side
folder with ``--real-sample``; the original file is only read.

Run:  python tools/create_demo_project.py --output ../test_data
"""

from __future__ import annotations

import argparse
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

import pandas as pd

from create_test_fixture import (
    PAD_HEADERS,
    ROUGHNESS_HEADERS,
    TRACE_HEADERS,
    VIA_HEADERS,
    Block,
    make_block,
    write_workbook,
)

PROJECT = "Chiplet4Future"
PART = "FHR0020"
UNIT_ORDER = (7, 8, 9, 4, 5, 6, 1, 2, 3)  # the order HRM writes units in
COUPON_ORDER = (1, 2, 3)

# lot -> buildup -> process folders -> panels
LAYOUT: dict[str, dict[str, dict[str, tuple[str, ...]]]] = {
    "19197": {
        "BU01": {
            "post DDV_HRM-2026-0088": ("Panel 28", "Panel 30"),
            "post DFS_HRM-2026-0115": ("Panel 28",),
        },
        "BU02": {"post DDV_HRM-2026-0091": ("Panel 28", "Panel 30")},
    },
    "19198": {
        "BU03": {
            "post DDV_HRM-2026-0102": ("Panel 05",),
            "post FET_HRM-2026-0118": ("Panel 05", "Panel 12"),
        },
    },
    "19199": {
        "BU01": {"post DDV_HRM-2026-0130": ("Panel 02",)},
        "BU10": {"post DDV_HRM-2026-0131": ("Panel 02",)},
    },
}
SIDES = ("front", "back", "Coupon front")
OTHER_MACHINES = ("XRF", "AOI")


REFERENCE_NAME = "HRM_Reference_demo.xlsx"

# Typical-looking base value per column; purely illustrative.
PAD_BASE = (16.6, 16.4, 16.5, 42.0, 0.05, 1.8)
SR_PAD_BASE = (15.5, 15.4, 15.45, 251.4)
TRACE_BASE = (16.5, 15.8, 16.2, 21.5, 33.8)
VIA_BASE = (0.6, 1.1)
ROUGHNESS_BASE = (0.74, 0.08, 0.60, 0.95, 0.108, 0.0075, 0.092, 0.125)

# Blank = applies to all. The most specific fitting row wins.
REFERENCE_ROWS: list[dict[str, object]] = [
    {"Part_Number": PART, "Feature_Type": "Pad", "Metric": "Mean_Stepheight",
     "LSL": 13.0, "Target": 16.0, "USL": 18.0, "Comment": "all Buildups, both sides"},
    {"Part_Number": PART, "Feature_Type": "Pad", "Metric": "Radius",
     "LSL": 41.0, "Target": 42.0, "USL": 43.0, "Comment": "general Pad radius"},
    {"Part_Number": PART, "Buildup": "BU-03", "Side": "Back", "Feature_Type": "Pad",
     "Metric": "Radius", "LSL": 41.5, "Target": 42.0, "USL": 42.3,
     "Comment": "tighter on BU-03 back: overrides the general row"},
    {"Part_Number": PART, "Buildup": "BU-03", "Side": "Back", "Feature_Type": "Pad",
     "Feature_Number": 2, "Metric": "Radius", "LSL": 41.0, "Target": 41.6, "USL": 42.0,
     "Comment": "Pad 2 only: most specific row"},
    {"Part_Number": PART, "Feature_Type": "Trace", "Metric": "Width",
     "LSL": 20.0, "Target": 21.5, "USL": 23.0},
    {"Part_Number": PART, "Feature_Type": "Via", "Metric": "Dimple", "USL": 0.9,
     "Comment": "USL only"},
    {"Part_Number": PART, "Feature_Type": "Roughness", "Metric": "Ra_Mean",
     "Target": 110.0, "USL": 150.0, "Comment": "roughness limits are in nm"},
]  # fmt: skip
REFERENCE_COLUMNS = (
    "Part_Number", "Buildup", "Side", "Feature_Type", "Feature_Number", "Metric",
    "LSL", "Target", "USL", "Comment",
)  # fmt: skip


def demo_block(
    label: str,
    headers: Sequence[str],
    base: Sequence[float],
    file_number: int,
    units: Sequence[int],
) -> Block:
    """A block whose values sit near ``base``, shifted a little per unit and per file."""
    template = make_block(label, headers, 0, units)
    shift = (file_number % 7) * 0.01
    rows = [
        (
            unit_label,
            note,
            [round(value * (1 + unit * 0.002) + shift * value / 16, 4) for value in base],
        )
        for (unit_label, note, _), unit in zip(template.rows, units, strict=True)
    ]
    return Block(label, headers, rows)


def unit_blocks(file_number: int, with_roughness: bool) -> list[Block]:
    blocks = [
        demo_block("Pad 1", PAD_HEADERS, PAD_BASE, file_number, UNIT_ORDER),
        demo_block("Pad 2", PAD_HEADERS, PAD_BASE, file_number + 1, UNIT_ORDER),
        demo_block("SR Pad 1", PAD_HEADERS[:4], SR_PAD_BASE, file_number, UNIT_ORDER),
        demo_block("Trace 1", TRACE_HEADERS, TRACE_BASE, file_number, UNIT_ORDER),
        demo_block("Trace 2", TRACE_HEADERS, TRACE_BASE, file_number + 2, UNIT_ORDER),
        demo_block("via 1", VIA_HEADERS, VIA_BASE, file_number, UNIT_ORDER),
    ]
    if with_roughness:
        blocks.append(
            demo_block("roughness", ROUGHNESS_HEADERS, ROUGHNESS_BASE, file_number, UNIT_ORDER)
        )
    return blocks


def coupon_blocks(file_number: int) -> list[Block]:
    return [
        demo_block("Pad 1", PAD_HEADERS, PAD_BASE, file_number, COUPON_ORDER),
        demo_block("Trace 1", TRACE_HEADERS, TRACE_BASE, file_number, COUPON_ORDER),
    ]


def write_demo_reference(path: Path) -> Path:
    """Write the demo limits workbook (sheet ``Limits``)."""
    frame = pd.DataFrame(REFERENCE_ROWS, columns=list(REFERENCE_COLUMNS), dtype=object)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_excel(path, sheet_name="Limits", index=False)
    return path


def create_demo_project(root: Path, real_sample: Path | None = None) -> Path:
    """Create the demo tree below ``root`` and return the project folder."""
    project = root / PROJECT
    if project.exists():
        raise FileExistsError(f"Demo project already exists: {project}")

    file_number = 0
    for lot, buildups in LAYOUT.items():
        for buildup, processes in buildups.items():
            buildup_dir = project / PART / lot / buildup
            for machine in OTHER_MACHINES:  # must be ignored by the converter
                write_workbook(
                    buildup_dir / machine / "Panel 01" / "front" / "other_machine_Summary.xlsx",
                    "Sheet1",
                    [make_block("Pad 1", PAD_HEADERS, 999, COUPON_ORDER)],
                )
            for process, panels in processes.items():
                for panel in panels:
                    for side in SIDES:
                        file_number += 1
                        tag = side.title().replace(" ", "_")  # Front / Back / Coupon_Front
                        coupon = side.lower().startswith("coupon")
                        write_workbook(
                            buildup_dir
                            / "HRM"
                            / process
                            / panel
                            / side
                            / f"2026-01-01_00-00-00_ENG_{PROJECT}_{buildup}_{tag}_Summary.xlsx",
                            f"ENG_{PART}_{buildup}_{tag}"[:31],
                            coupon_blocks(file_number)
                            if coupon
                            else unit_blocks(file_number, side == "front"),
                        )

    if real_sample is not None:
        # The sample is a BU03 / Back workbook: replace the synthetic file in that slot.
        target = project / PART / "19198" / "BU03" / "HRM" / "post DDV_HRM-2026-0102"
        target = target / "Panel 05" / "back"
        for synthetic in target.glob("*.xlsx"):
            synthetic.unlink()
        shutil.copy2(real_sample, target / real_sample.name)
    write_demo_reference(root / REFERENCE_NAME)
    return project


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a clean demo HRM project tree.")
    parser.add_argument("--output", type=Path, default=Path("test_data"), help="Target folder.")
    parser.add_argument("--real-sample", type=Path, help="Real BU03/Back workbook to copy in.")
    args = parser.parse_args(argv)
    try:
        project = create_demo_project(args.output, args.real_sample)
    except FileExistsError as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        return 1
    print(f"Demo project created: {project.resolve()}")
    print(f"Demo reference      : {(args.output / REFERENCE_NAME).resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
