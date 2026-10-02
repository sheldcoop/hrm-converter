"""Create a large, deliberately messy HRM project to watch the converter cope.

Everything is made up: project, part and lot names are invented and the values
are random numbers around typical-looking levels (fixed seed, so every run
produces the same files).

What it contains:

* two Part Numbers, five Lots, many Buildups with differently spelled folder
  names (``BU01``, ``BU 03``, ``bu-04``, ``BU_05``), several processes, panels
  and all four side folders in mixed spellings (``front``, ``BACK``,
  ``coupon_back``, ``Coupon-Front``);
* many kinds of workbook, rotated over the tree (see ``KINDS``): annular pads,
  ``Line`` instead of ``Width``, ``Pad Pos 3`` labels, unknown features and
  metrics, blank / zero / text values, operator notes, missing header rows,
  duplicate and unlabelled blocks, extra sheets, 36-unit panels, ...;
* one Buildup, ``BU08`` in the first lot, that holds one **problem case per
  panel folder** (see ``PROBLEM_CASES``): several workbooks in a folder,
  corrupt and empty files, wrong file names, metadata conflicts, bad folder
  names (three of which have a proposed repair in the fix plan) and so on;
* a limits workbook, ``Stress_Reference.xlsx``, with good rows and a few
  deliberately bad ones.

Run:  python tools/create_stress_project.py --output ../test_data
"""

from __future__ import annotations

import argparse
import random
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import openpyxl
import pandas as pd

from create_test_fixture import (
    PAD_HEADERS,
    ROUGHNESS_HEADERS,
    TRACE_HEADERS,
    VIA_HEADERS,
    Block,
    Cell,
    write_workbook,
)

PROJECT = "Orion_Stress_Demo"
REFERENCE_NAME = "Stress_Reference.xlsx"
PROBLEM_BUILDUP = "BU08"
SEED = 20260101

# part -> lot -> Buildup folder names (spelled inconsistently on purpose)
FULL_LAYOUT: dict[str, dict[str, tuple[str, ...]]] = {
    "PN-ALPHA-01": {
        "30101": ("BU01", "BU02", "BU 03", "bu-04", "BU_05", "BU10"),
        "30102": ("BU01", "BU02", "BU12"),
        "30103": ("BU01",),
    },
    "PN-BETA-02": {
        "40201": ("BU01", "BU02", "BU03", "BU04"),
        "40202": ("BU02", "BU07"),
    },
}
SMALL_LAYOUT: dict[str, dict[str, tuple[str, ...]]] = {
    "PN-ALPHA-01": {"30101": ("BU01", "BU 03")},
    "PN-BETA-02": {"40201": ("BU02",)},
}
PROCESSES = (
    "post DDV_HRM-2031-{n:04d}",
    "post DFS_HRM-2031-{n:04d}",
    "post FET_HRM-2031-{n:04d}",
    "pre LAM_HRM-2031-{n:04d}",
)
PANELS = ("Panel 02", "Panel 7", "panel_11", "Panel-28")
# folder spelling variants -> (tag used in sheet / file names, is coupon)
SIDE_SETS: tuple[tuple[tuple[str, str, bool], ...], ...] = (
    (("front", "Front", False), ("back", "Back", False),
     ("Coupon front", "Coupon_Front", True), ("Coupon back", "Coupon_Back", True)),
    (("Front", "Front", False), ("BACK", "Back", False),
     ("Coupon-Front", "Coupon_Front", True), ("coupon_back", "Coupon_Back", True)),
)  # fmt: skip

PAD_BASE = (16.6, 16.4, 16.5, 42.0, 0.05, 1.8)
SR_PAD_BASE = (15.5, 15.4, 15.45, 251.4)
TRACE_BASE = (16.5, 15.8, 16.2, 21.5, 33.8)
VIA_BASE = (0.6, 1.1)
ROUGHNESS_BASE = (0.74, 0.08, 0.60, 0.95, 0.108, 0.0075, 0.092, 0.125)
ANNULAR_HEADERS = (
    "Max Stepheight", "Min Stepheight", "Mean Stepheight", "Outer Radius", "Inner Radius",
    "Diameter", "Dimple", "Bump",
)  # fmt: skip
ANNULAR_BASE = (16.6, 16.4, 16.5, 55.0, 42.0, 84.0, 0.05, 1.8)
UNITS_9 = (7, 8, 9, 4, 5, 6, 1, 2, 3)  # the order HRM writes them in
UNITS_36 = tuple(range(1, 37))
COUPONS = (1, 2, 3)


@dataclass
class Maker:
    """Builds blocks with seeded random values around a base level."""

    rng: random.Random
    level: float = 1.0  # per-Buildup shift, so Buildups differ visibly

    def values(self, base: Sequence[float], ordered: bool = False) -> list[Cell]:
        """Random values around ``base``; ``ordered`` keeps Max >= Mean >= Min in columns 0-2."""
        made = [round(value * self.level * (1 + self.rng.gauss(0, 0.012)), 5) for value in base]
        if ordered:
            high, middle, low = sorted(made[:3], reverse=True)
            made[:3] = [high, low, middle]  # column order is Max, Min, Mean
        return list(made)

    def block(
        self,
        label: str | None,
        headers: Sequence[str | None],
        base: Sequence[float],
        units: Sequence[int] = UNITS_9,
        with_header_row: bool = True,
    ) -> Block:
        ordered = [str(h) for h in headers[:3]] == list(PAD_HEADERS[:3])
        rows = [
            (f"Unit {unit}", label if position == 0 else None, self.values(base, ordered))
            for position, unit in enumerate(units)
        ]
        return Block(label, headers, rows, with_header_row)

    def roughness(self, correct_header: bool = False) -> Block:
        header = (
            ("Rz mean", "Rz Std dev", "Rz min", "Rz max",
             "Ra mean", "Ra Std dev", "Ra min", "Ra max")
            if correct_header
            else ROUGHNESS_HEADERS
        )  # fmt: skip
        return self.block("roughness", header, ROUGHNESS_BASE)


def with_cells(block: Block, changes: dict[tuple[int, int], Cell]) -> Block:
    """Copy of a block with single cells replaced: {(row, column): value}."""
    rows = [(unit, note, list(values)) for unit, note, values in block.rows]
    for (row, column), value in changes.items():
        rows[row][2][column] = value
    return Block(block.label, block.headers, rows, block.with_header_row)


def with_note(block: Block, row: int, note: str, blank_values: bool) -> Block:
    rows = [(unit, label, list(values)) for unit, label, values in block.rows]
    unit, _, values = rows[row]
    rows[row] = (unit, note, [None] * len(values) if blank_values else values)
    return Block(block.label, block.headers, rows, block.with_header_row)


# --- workbook kinds: each returns the blocks of one unit-side workbook --------
def standard(m: Maker) -> list[Block]:
    return [
        m.block("Pad 1", PAD_HEADERS, PAD_BASE),
        m.block("Pad 2", PAD_HEADERS, PAD_BASE),
        m.block("SR Pad 1", PAD_HEADERS[:4], SR_PAD_BASE),
        m.block("Trace 1", TRACE_HEADERS, TRACE_BASE),
        m.block("Trace 2", TRACE_HEADERS, TRACE_BASE),
        m.block("via 1", VIA_HEADERS, VIA_BASE),
        m.block("via 2", VIA_HEADERS, VIA_BASE),
    ]


def annular_pads(m: Maker) -> list[Block]:
    return [
        m.block("Pad 1", ANNULAR_HEADERS, ANNULAR_BASE),
        m.block("Pad 2", ANNULAR_HEADERS, ANNULAR_BASE),
        m.block("Trace 1", TRACE_HEADERS, TRACE_BASE),
    ]


def line_instead_of_width(m: Maker) -> list[Block]:
    headers = (*TRACE_HEADERS[:3], "Line", "Space")
    return [m.block("Trace 1", headers, TRACE_BASE), m.block("Pad 1", PAD_HEADERS, PAD_BASE)]


def position_labels(m: Maker) -> list[Block]:
    return [
        m.block("Pad Pos 1", PAD_HEADERS, PAD_BASE),
        m.block("Pad Pos 2", PAD_HEADERS, PAD_BASE),
        m.block("SR Pad Pos 1", PAD_HEADERS[:4], SR_PAD_BASE),
        m.block("Trace Pos 1", TRACE_HEADERS, TRACE_BASE),
        m.block("Via Pos 1", VIA_HEADERS, VIA_BASE),
        m.block("Landing Pad 1", PAD_HEADERS[:4], PAD_BASE[:4]),
    ]


def future_features(m: Maker) -> list[Block]:
    return [
        m.block(
            "Fiducial 1", ("Distance 1", "Distance 2", "Angle", "Area"), (120.0, 85.0, 90.0, 510.0)
        ),
        m.block("Micro Bump 3", ("Height", "Diameter"), (8.5, 24.0)),
        m.block("Pad 1", PAD_HEADERS, PAD_BASE),
    ]


def messy_values(m: Maker) -> list[Block]:
    pad = with_cells(
        m.block("Pad 1", PAD_HEADERS, PAD_BASE),
        {
            (0, 3): None,  # blank Radius
            (1, 4): 0,  # zero Dimple
            (2, 0): "n/a",  # text
            (3, 0): "12,5",  # number typed as text with a comma
            (4, 5): "#DIV/0!",  # Excel error text
            (5, 2): " 16.48 ",  # number typed as text
        },
    )
    via = m.block("via 1", VIA_HEADERS, VIA_BASE)
    zeros: dict[tuple[int, int], Cell] = {(row, 0): 0 for row in range(len(via.rows))}
    via = with_cells(via, zeros)  # every Dimple is 0
    return [pad, via]


def implausible_values(m: Maker) -> list[Block]:
    """Values the sanity checks should catch: swapped Min/Max, a decimal slip, a negative."""
    pad = m.block("Pad 1", PAD_HEADERS, PAD_BASE)
    first, second = pad.rows[0][2], pad.rows[1][2]
    pad = with_cells(
        pad,
        {
            (0, 0): first[1],  # Max and Min swapped on the first unit
            (0, 1): first[0],
            (1, 3): round(float(str(second[3])) * 100, 5),  # Radius typed 100 times too large
            (2, 5): -1.8,  # negative Bump
        },
    )
    return [pad, m.block("via 1", VIA_HEADERS, VIA_BASE)]


def operator_notes(m: Maker) -> list[Block]:
    pad = with_note(m.block("Pad 1", PAD_HEADERS, PAD_BASE), 4, "scratched - not measurable", True)
    trace = with_note(m.block("Trace 1", TRACE_HEADERS, TRACE_BASE), 2, "re-measured", False)
    return [pad, trace]


def missing_header_row(m: Maker) -> list[Block]:
    return [
        m.block("Pad 1", PAD_HEADERS, PAD_BASE),
        m.block("Pad 2", PAD_HEADERS, PAD_BASE, with_header_row=False),  # operator forgot it
        m.block("via 1", VIA_HEADERS, VIA_BASE),
    ]


def many_units(m: Maker) -> list[Block]:
    return [
        m.block("Pad 1", PAD_HEADERS, PAD_BASE, UNITS_36),
        m.block("Trace 1", TRACE_HEADERS, TRACE_BASE, UNITS_36),
    ]


def duplicate_block(m: Maker) -> list[Block]:
    return [
        m.block("Pad 1", PAD_HEADERS, PAD_BASE),
        m.block("Pad 1", PAD_HEADERS, PAD_BASE),  # measured twice under the same label
        m.block("via 1", VIA_HEADERS, VIA_BASE),
    ]


def values_without_header(m: Maker) -> list[Block]:
    return [m.block("Pad 1", PAD_HEADERS[:4], PAD_BASE), m.block("via 1", VIA_HEADERS, VIA_BASE)]


def empty_block(m: Maker) -> list[Block]:
    trace = m.block("Trace 1", TRACE_HEADERS, TRACE_BASE)
    blank: dict[tuple[int, int], Cell] = {
        (row, column): None for row in range(len(trace.rows)) for column in range(5)
    }
    return [m.block("Pad 1", PAD_HEADERS, PAD_BASE), with_cells(trace, blank)]


def unlabelled_block(m: Maker) -> list[Block]:
    return [m.block(None, PAD_HEADERS, PAD_BASE), m.block("Pad 1", PAD_HEADERS, PAD_BASE)]


def title_rows(m: Maker) -> list[Block]:
    title = Block(None, (), [("Measured by operator 7 on tool HRM-2", None, [])], False)
    return [title, m.block("Pad 1", PAD_HEADERS, PAD_BASE), m.block("via 1", VIA_HEADERS, VIA_BASE)]


def duplicate_columns(m: Maker) -> list[Block]:
    headers = (*TRACE_HEADERS[:3], "Width", "Line", "Space")  # Width twice once 'Line' is mapped
    return [m.block("Trace 1", headers, (*TRACE_BASE[:4], 21.6, 33.8))]


KINDS: tuple[tuple[str, Callable[[Maker], list[Block]]], ...] = (
    ("standard", standard),
    ("annular pads", annular_pads),
    ("Line instead of Width", line_instead_of_width),
    ("standard", standard),
    ("Pad Pos / Via Pos labels", position_labels),
    ("unknown features and metrics", future_features),
    ("blank, zero and text values", messy_values),
    ("standard", standard),
    ("operator notes in column B", operator_notes),
    ("missing header row", missing_header_row),
    ("36 units", many_units),
    ("same block twice", duplicate_block),
    ("values without a header", values_without_header),
    ("empty block", empty_block),
    ("block without a label", unlabelled_block),
    ("title row above the blocks", title_rows),
    ("same column twice", duplicate_columns),
    ("implausible values", implausible_values),
)


def canonical(buildup_folder: str) -> str:
    """'bu-04' / 'BU 03' -> 'BU04' / 'BU03', as HRM writes it in sheet and file names."""
    return "BU" + "".join(c for c in buildup_folder if c.isdigit()).zfill(2)


def file_name(buildup: str, tag: str, stamp: str = "2031-03-01_08-00-00") -> str:
    return f"{stamp}_ENG_{PROJECT}_{buildup}_{tag}_Summary.xlsx"


def sheet_name(part: str, buildup: str, tag: str) -> str:
    return f"ENG_{part}_{buildup}_{tag}"[:31]


def coupon_blocks(m: Maker, number: int) -> list[Block]:
    blocks = [
        m.block("Pad 1", PAD_HEADERS, PAD_BASE, COUPONS),
        m.block("Trace 1", TRACE_HEADERS, TRACE_BASE, COUPONS),
    ]
    if number % 3 == 0:
        blocks.append(m.block("via 1", VIA_HEADERS, VIA_BASE, COUPONS))
    return blocks


# --- problem cases: one per panel folder of BU08 ------------------------------
def _good(m: Maker, folder: Path, part: str, tag: str = "Front", **names: str) -> Path:
    buildup = names.get("buildup", PROBLEM_BUILDUP)
    return write_workbook(
        folder / names.get("file", file_name(buildup, tag)),
        names.get("sheet", sheet_name(names.get("sheet_part", part), buildup, tag)),
        [m.block("Pad 1", PAD_HEADERS, PAD_BASE), m.block("via 1", VIA_HEADERS, VIA_BASE)],
    )


def problem_cases(root: Path, part: str, m: Maker) -> list[str]:
    """Write BU08 and return a description of every case, for the printout."""
    hrm = root / PROBLEM_BUILDUP / "HRM"
    process = hrm / "post QA_HRM-2031-0999"
    described: list[str] = []

    def case(panel: int, text: str) -> Path:
        described.append(f"Panel {panel:02d}: {text}")
        return process / f"Panel {panel:02d}"

    folder = case(1, "three workbooks in one side folder (none is chosen)")
    for hour in ("08", "09", "10"):
        _good(
            m,
            folder / "front",
            part,
            file=file_name(PROBLEM_BUILDUP, "Front", f"2031-03-01_{hour}-00-00"),
        )

    folder = case(2, "only an Excel lock file and a text file (no workbook)")
    (folder / "front").mkdir(parents=True)
    (folder / "front" / ("~$" + file_name(PROBLEM_BUILDUP, "Front"))).write_bytes(b"lock")
    (folder / "front" / "operator notes.txt").write_text("made-up note", encoding="utf-8")

    folder = case(3, "a good workbook next to one with the wrong file name")
    _good(m, folder / "front", part)
    _good(m, folder / "front", part, file="Panel 03 report.xlsx")

    folder = case(4, "only a workbook with the wrong file name")
    _good(m, folder / "front", part, file="export.xlsx")

    folder = case(5, "corrupt workbook (front) and zero-byte workbook (back)")
    (folder / "front").mkdir(parents=True)
    (folder / "front" / file_name(PROBLEM_BUILDUP, "Front")).write_bytes(b"not a real xlsx file")
    (folder / "back").mkdir(parents=True)
    (folder / "back" / file_name(PROBLEM_BUILDUP, "Back")).write_bytes(b"")

    folder = case(6, "valid workbook without any measurement block")
    empty = openpyxl.Workbook()
    assert empty.active is not None
    empty.active.title = sheet_name(part, PROBLEM_BUILDUP, "Front")
    empty.active.append(["Summary pending"])
    (folder / "front").mkdir(parents=True)
    empty.save(folder / "front" / file_name(PROBLEM_BUILDUP, "Front"))

    folder = case(7, "workbook named BU09 / Back stored under BU08 / front (conflict)")
    _good(m, folder / "front", part, tag="Back", buildup="BU09")

    folder = case(8, "sheet name states another Part Number (conflict)")
    _good(m, folder / "front", part, sheet_part="PN-OTHER-99")

    folder = case(9, "side folders that are not front/back ('left', 'top view')")
    _good(m, folder / "left", part)
    _good(m, folder / "top view", part)
    _good(m, folder / "back", part, tag="Back")

    folder = case(10, "extra sheets, and an old copy in a sub-folder (ignored)")
    write_workbook(
        folder / "front" / file_name(PROBLEM_BUILDUP, "Front"),
        sheet_name(part, PROBLEM_BUILDUP, "Front"),
        [m.block("Pad 1", PAD_HEADERS, PAD_BASE)],
        extra_sheets=["Raw data", "Notes"],
    )
    _good(m, folder / "front" / "old", part)

    folder = case(12, "workbook left in the panel folder (fix plan: move into 'back')")
    _good(m, folder, part, tag="Back")
    folder = case(13, "side folder named 'Front (remeasure)' (fix plan: rename to 'front')")
    _good(m, folder / "Front (remeasure)", part)
    described.append("'Pnl 14': misspelled panel folder (fix plan: rename to 'Panel 14')")
    _good(m, process / "Pnl 14" / "front", part)

    described.append("Panel 11: empty panel folder")
    (process / "Panel 11").mkdir(parents=True)
    described.append("'Pnl A': folder that is not a panel folder")
    _good(m, process / "Pnl A" / "front", part)
    described.append("'post EMPTY_HRM-2031-1000': empty process folder")
    (hrm / "post EMPTY_HRM-2031-1000").mkdir(parents=True)
    described.append("'Rework run 2': process name that cannot be parsed (folder name is used)")
    _good(m, hrm / "Rework run 2" / "Panel 01" / "front", part)
    return described


def write_reference(path: Path) -> Path:
    """Limits for the stress project, including a few deliberately bad rows."""
    alpha, beta = "PN-ALPHA-01", "PN-BETA-02"
    rows: list[dict[str, object]] = [
        {"Part_Number": alpha, "Feature_Type": "Pad", "Metric": "Mean_Stepheight",
         "LSL": 15.5, "Target": 16.5, "USL": 17.5, "Comment": "all Buildups and sides"},
        {"Part_Number": alpha, "Feature_Type": "Pad", "Metric": "Radius",
         "LSL": 41.0, "Target": 42.0, "USL": 43.0},
        {"Part_Number": alpha, "Buildup": "BU03", "Side": "Back", "Feature_Type": "Pad",
         "Metric": "Radius", "LSL": 41.6, "Target": 42.0, "USL": 42.4,
         "Comment": "tighter on BU-03 back; 'BU03' is understood as BU-03"},
        {"Part_Number": alpha, "Buildup": "BU-03", "Side": "Back", "Feature_Type": "Pad",
         "Feature_Number": 2, "Metric": "Radius", "LSL": 41.8, "Target": 42.0, "USL": 42.2,
         "Comment": "Pad 2 only"},
        {"Part_Number": alpha, "Feature_Type": "Trace", "Metric": "Width",
         "LSL": 20.5, "Target": 21.5, "USL": 22.5},
        {"Part_Number": alpha, "Feature_Type": "Trace", "Metric": "Space",
         "LSL": 32.5, "USL": 35.0},
        {"Part_Number": alpha, "Feature_Type": "SR Pad", "Metric": "Radius",
         "LSL": 245.0, "Target": 251.4, "USL": 258.0},
        {"Feature_Type": "Via", "Metric": "Dimple", "USL": 0.62, "Comment": "both parts, USL only"},
        {"Feature_Type": "Roughness", "Metric": "Ra_Mean", "Target": 108.0, "USL": 112.0,
         "Comment": "roughness limits are in nm"},
        {"Part_Number": beta, "Feature_Type": "Pad", "Metric": "Radius",
         "LSL": 41.5, "Target": 42.5, "USL": 43.5, "Comment": "other part, other limits"},
        {"Feature_Type": "Fiducial", "Metric": "Angle", "LSL": 89.0, "Target": 90.0, "USL": 91.0,
         "Comment": "a feature the config does not know"},
        # --- deliberately bad rows, to show how they are reported ---
        {"Part_Number": alpha, "Feature_Type": "Padd", "Metric": "Radius", "USL": 43.0,
         "Comment": "BAD: typo in Feature_Type, matches nothing"},
        {"Part_Number": alpha, "Feature_Type": "Trace", "Metric": "Max_Stepheight",
         "LSL": 18.0, "USL": 15.0, "Comment": "BAD: LSL greater than USL"},
        {"Part_Number": alpha, "Feature_Type": "Via", "Metric": "Bump",
         "Comment": "BAD: no limits"},
        {"Buildup": "BU-02", "Feature_Type": "Trace", "Metric": "Mean_Stepheight", "USL": 17.0,
         "Comment": "BAD: clashes with the next row on BU-02 front"},
        {"Side": "Front", "Feature_Type": "Trace", "Metric": "Mean_Stepheight", "USL": 16.8,
         "Comment": "BAD: clashes with the previous row on BU-02 front"},
    ]  # fmt: skip
    columns = ["Part_Number", "Buildup", "Side", "Feature_Type", "Feature_Number", "Metric",
               "LSL", "Target", "USL", "Comment"]  # fmt: skip
    path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=columns, dtype=object).to_excel(
        path, sheet_name="Limits", index=False
    )
    return path


@dataclass
class StressInfo:
    project: Path
    reference: Path
    workbooks: int
    problem_cases: list[str]


def create_stress_project(root: Path, size: str = "full") -> StressInfo:
    """Create the stress project below ``root`` (``size``: 'full' or 'small')."""
    project = root / PROJECT
    if project.exists():
        raise FileExistsError(f"Stress project already exists: {project}")
    layout = FULL_LAYOUT if size == "full" else SMALL_LAYOUT
    rng = random.Random(SEED)
    number = 0  # workbooks written so far: rotates the workbook kinds
    process_number = 0  # process folders written so far: rotates the panel names

    for part, lots in layout.items():
        for lot, buildups in lots.items():
            lot_dir = project / part / lot
            for buildup_position, folder_name in enumerate(buildups):
                buildup = canonical(folder_name)
                buildup_dir = lot_dir / folder_name
                maker = Maker(rng, level=1 + 0.006 * int(buildup[2:]))
                (buildup_dir / "AOI").mkdir(parents=True)
                write_workbook(  # another machine's file: must never be read
                    buildup_dir / "XRF" / "Panel 02" / "front" / "xrf_Summary.xlsx",
                    "XRF",
                    [maker.block("Pad 1", PAD_HEADERS, PAD_BASE, COUPONS)],
                )
                process_count = 1 if size == "small" else 2 + buildup_position % 2
                for process_position in range(process_count):
                    process = PROCESSES[(buildup_position + process_position) % len(PROCESSES)]
                    process_dir = buildup_dir / "HRM" / process.format(n=100 + number)
                    process_number += 1
                    panel_count = 1 if size == "small" else 2 + (process_number % 2)
                    for panel_position in range(panel_count):
                        panel = PANELS[(process_number + panel_position) % len(PANELS)]
                        sides = SIDE_SETS[(buildup_position + panel_position) % len(SIDE_SETS)]
                        for folder, tag, coupon in sides:
                            number += 1
                            if coupon:
                                blocks = coupon_blocks(maker, number)
                            else:
                                blocks = KINDS[number % len(KINDS)][1](maker)
                                if tag == "Front":
                                    blocks.append(maker.roughness(correct_header=number % 4 == 0))
                            write_workbook(
                                process_dir / panel / folder / file_name(buildup, tag),
                                sheet_name(part, buildup, tag),
                                blocks,
                            )

    first_part = next(iter(layout))
    first_lot = project / first_part / next(iter(layout[first_part]))
    cases = problem_cases(first_lot, first_part, Maker(rng))
    (first_lot / "BU06" / "XRF").mkdir(parents=True)  # a Buildup without an HRM folder
    cases.append("BU06: Buildup folder without an HRM folder")
    (first_lot / "Reports").mkdir()
    (first_lot / "Reports" / "weekly summary.txt").write_text("made-up report", encoding="utf-8")
    cases.append("Reports: a folder in the lot that is not a Buildup (ignored)")

    reference = write_reference(root / REFERENCE_NAME)
    workbooks = sum(1 for path in project.rglob("*.xlsx") if "HRM" in path.parts)
    return StressInfo(project, reference, workbooks, cases)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Create a large, messy HRM demo project.")
    parser.add_argument("--output", type=Path, default=Path("test_data"), help="Target folder.")
    parser.add_argument("--size", choices=("full", "small"), default="full")
    args = parser.parse_args(argv)
    try:
        info = create_stress_project(args.output, args.size)
    except FileExistsError as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        return 1
    print(f"Stress project created: {info.project.resolve()}")
    print(f"  {info.workbooks} Excel files under HRM folders")
    print(f"Limits workbook       : {info.reference.resolve()}")
    print(f"Problem cases (first lot, {PROBLEM_BUILDUP} unless stated):")
    for text in info.problem_cases:
        print(f"  - {text}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
