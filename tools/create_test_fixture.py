"""Generate a synthetic HRM folder hierarchy with synthetic Excel workbooks.

Everything written here is artificial: names start with ``SYN`` and values
follow the formula ``seed + unit / 10 + column / 100``. No production data is
reproduced.

Run:  python tools/create_test_fixture.py --output test_fixture
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import openpyxl

PROJECT = "SYN_Demo_Project"
PART_A = "SYN-PART-A"
PART_B = "SYN-PART-B"
LOT_A1 = "90001"
LOT_A2 = "90002"
LOT_B1 = "80001"

PAD_HEADERS = ("Max Stepheight", "Min Stepheight", "Mean Stepheight", "Radius", "Dimple", "Bump")
TRACE_HEADERS = ("Max Stepheight", "Min Stepheight", "Mean Stepheight", "Width", "Space")
VIA_HEADERS = ("Dimple", "Bump")
# Deliberately in the wrong order, as typed by an operator.
ROUGHNESS_HEADERS = (
    "Rz max", "Rz mean", "Rz min", "Rz max", "Ra mean", "Ra Std dev", "Ra min", "Ra max",
)  # fmt: skip
UNITS = (3, 1, 2)

Cell = int | float | str | None


@dataclass(frozen=True)
class Block:
    label: str | None
    headers: Sequence[str | None]
    rows: Sequence[tuple[str, str | None, Sequence[Cell]]]
    with_header_row: bool = True


def synthetic_value(seed: float, unit: int, column: int) -> float:
    return round(seed + unit / 10 + column / 100, 4)


def make_block(
    label: str | None,
    headers: Sequence[str | None],
    seed: float,
    units: Sequence[int] = UNITS,
    unit_prefix: str = "Unit ",
) -> Block:
    rows = [
        (
            f"{unit_prefix}{unit}",
            label if position == 0 else None,
            [synthetic_value(seed, unit, column) for column in range(len(headers))],
        )
        for position, unit in enumerate(units)
    ]
    return Block(label, headers, rows)


def write_workbook(
    path: Path, sheet_name: str, blocks: Sequence[Block], extra_sheets: Sequence[str] = ()
) -> Path:
    """Write blocks in the stacked HRM summary layout (A = unit, B = label, C.. = values)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    assert sheet is not None
    sheet.title = sheet_name
    for block in blocks:
        if block.with_header_row:
            sheet.append([None, None, *block.headers])
        for unit_label, label, values in block.rows:
            sheet.append([unit_label, label, *values])
    for name in extra_sheets:
        workbook.create_sheet(name).append(["synthetic extra sheet"])
    workbook.save(path)
    return path


def workbook_name(buildup: str, side: str, stamp: str = "2099-01-01_00-00-00") -> str:
    return f"{stamp}_SYN_{PROJECT}_{buildup}_{side}_Summary.xlsx"


def sheet_name(part: str, buildup: str, side: str) -> str:
    return f"SYN_{part}_{buildup}_{side}"[:31]


@dataclass
class FixtureInfo:
    """Paths of the generated hierarchy, used by the automated tests."""

    root: Path
    project: Path
    part_a: Path
    lot_a1: Path
    buildup_a1_bu01: Path
    files: dict[str, Path] = field(default_factory=dict)
    all_source_files: list[Path] = field(default_factory=list)


def create_fixture(root: Path) -> FixtureInfo:
    """Create the full synthetic hierarchy below ``root`` (which must not exist yet)."""
    if root.exists() and any(root.iterdir()):
        raise FileExistsError(f"Target folder is not empty: {root}")
    project = root / PROJECT
    part_a, part_b = project / PART_A, project / PART_B
    lot_a1, lot_a2, lot_b1 = part_a / LOT_A1, part_a / LOT_A2, part_b / LOT_B1
    bu01 = lot_a1 / "BU01"
    info = FixtureInfo(root, project, part_a, lot_a1, bu01)
    files = info.files

    # --- Part A / Lot 90001 / BU01: the main playground -------------------
    hrm = bu01 / "HRM"
    aaa = hrm / "post AAA_HRM-2099-0001"

    # Pad + Trace + Via + Roughness; metadata agrees with the hierarchy.
    files["full"] = write_workbook(
        aaa / "Panel 2" / "front" / workbook_name("BU01", "Front"),
        sheet_name(PART_A, "BU01", "Front"),
        [
            make_block("Pad 1", PAD_HEADERS, 100),
            make_block("Pad 2", PAD_HEADERS, 200),
            make_block("SR Pad 1", PAD_HEADERS[:4], 300),
            make_block("Trace 1", TRACE_HEADERS, 400),
            make_block("via 1", VIA_HEADERS, 500),
            make_block("roughness", ROUGHNESS_HEADERS, 0),
        ],
    )
    # Pad only, no Roughness.
    files["pad_only"] = write_workbook(
        aaa / "Panel 2" / "back" / workbook_name("BU01", "Back"),
        sheet_name(PART_A, "BU01", "Back"),
        [make_block("Pad 1", PAD_HEADERS, 110), make_block("Pad 2", PAD_HEADERS, 210)],
    )
    # Trace only, on a coupon.
    files["trace_only_coupon"] = write_workbook(
        aaa / "Panel 2" / "Coupon front" / workbook_name("BU01", "Coupon_Front"),
        sheet_name(PART_A, "BU01", "Coupon_Front"),
        [make_block("Trace 1", TRACE_HEADERS, 410)],
    )
    files["pad_trace_coupon"] = write_workbook(
        aaa / "Panel 2" / "Coupon back" / workbook_name("BU01", "Coupon_Back"),
        sheet_name(PART_A, "BU01", "Coupon_Back"),
        [make_block("Pad 1", PAD_HEADERS, 120), make_block("Trace 1", TRACE_HEADERS, 420)],
    )
    # Unknown future feature, unknown metrics, blank / zero / text values.
    files["future"] = write_workbook(
        aaa / "Panel 10" / "front" / workbook_name("BU01", "Front"),
        sheet_name(PART_A, "BU01", "Front"),
        [
            make_block("Fiducial 1", ("Distance 1", "Distance 2", "Angle", "Area"), 600),
            Block(
                "Pad 1",
                ("Max Stepheight", "Radius", "Dimple"),
                [
                    ("Unit 1", "Pad 1", [10.5, None, 0]),  # blank Radius, zero Dimple
                    ("Unit 2", None, ["n/a", 42.5, 0.25]),  # unexpected text
                    ("Unit 3", None, ["12,5", 43.5, 0.5]),  # number stored as text
                ],
            ),
        ],
    )
    # Zero workbooks: only a temporary Excel lock file and a text file.
    empty_side = aaa / "Panel 10" / "back"
    empty_side.mkdir(parents=True)
    (empty_side / ("~$" + workbook_name("BU01", "Back"))).write_bytes(b"synthetic lock file")
    (empty_side / "notes.txt").write_text("synthetic note", encoding="utf-8")

    bbb = hrm / "post BBB_HRM-2099-0002"
    # More than one workbook in a final folder.
    for stamp, seed in (("2099-01-01_00-00-00", 130), ("2099-01-02_00-00-00", 140)):
        path = write_workbook(
            bbb / "Panel 2" / "front" / workbook_name("BU01", "Front", stamp),
            sheet_name(PART_A, "BU01", "Front"),
            [make_block("Pad 1", PAD_HEADERS, seed)],
        )
        files[f"multiple_{stamp[:10]}"] = path
    # Metadata conflict: stored under BU01 / back, but named BU09 / Front.
    files["conflict"] = write_workbook(
        bbb / "Panel 2" / "back" / workbook_name("BU09", "Front"),
        sheet_name(PART_A, "BU09", "Front"),
        [make_block("Pad 1", PAD_HEADERS, 150)],
    )

    (hrm / "post CCC_HRM-2099-0003").mkdir(parents=True)  # empty process folder
    (hrm / "post DDD_HRM-2099-0004" / "Panel 3").mkdir(parents=True)  # empty panel folder

    # Process folder name that cannot be parsed -> folder name is used as Process.
    files["via_only"] = write_workbook(
        hrm / "Special Run" / "Panel 1" / "front" / workbook_name("BU01", "Front"),
        sheet_name(PART_A, "BU01", "Front"),
        [make_block("via 1", VIA_HEADERS, 510), make_block("via 2", VIA_HEADERS, 520)],
    )

    # Other machine folders next to HRM: must never be entered.
    files["other_machine"] = write_workbook(
        bu01
        / "XRF"
        / "post AAA_HRM-2099-0001"
        / "Panel 2"
        / "front"
        / workbook_name("BU01", "Front"),
        sheet_name(PART_A, "BU01", "Front"),
        [make_block("Pad 1", PAD_HEADERS, 990)],
    )
    (bu01 / "AOI").mkdir()

    # --- more Buildups in the same Lot (natural order: BU02 before BU10) --
    for buildup, number, seed in (("BU02", 5, 160), ("BU10", 6, 170)):
        files[buildup.lower()] = write_workbook(
            lot_a1 / buildup / "HRM" / f"post AAA_HRM-2099-000{number}" / "Panel 1" / "front"
            / workbook_name(buildup, "Front"),
            sheet_name(PART_A, buildup, "Front"),
            [make_block("Pad 1", PAD_HEADERS, seed)],
        )  # fmt: skip
    (lot_a1 / "BU03" / "XRF").mkdir(parents=True)  # Buildup without an HRM folder

    # --- second Lot of Part A ----------------------------------------------
    files["lot_a2"] = write_workbook(
        lot_a2 / "BU01" / "HRM" / "post AAA_HRM-2099-0007" / "Panel 1" / "back"
        / workbook_name("BU01", "Back"),
        sheet_name(PART_A, "BU01", "Back"),
        [make_block("Trace 1", TRACE_HEADERS, 430), make_block("Trace 2", TRACE_HEADERS, 440)],
    )  # fmt: skip

    # --- Part B --------------------------------------------------------------
    eee = lot_b1 / "BU01" / "HRM" / "post EEE_HRM-2099-0008" / "Panel 1"
    files["part_b"] = write_workbook(
        eee / "front" / workbook_name("BU01", "Front"),
        sheet_name(PART_B, "BU01", "Front"),
        [
            make_block("Landing Pad 1", PAD_HEADERS[:4], 700),
            make_block("SR Pad 1", PAD_HEADERS[:4], 310),
        ],
    )
    corrupt = eee / "back" / workbook_name("BU01", "Back")
    corrupt.parent.mkdir(parents=True)
    corrupt.write_bytes(b"this is not a real xlsx file - synthetic corrupt workbook")
    files["corrupt"] = corrupt

    info.all_source_files = sorted(p for p in root.rglob("*") if p.is_file())
    return info


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--output", type=Path, default=Path("test_fixture"), help="Target folder.")
    args = parser.parse_args(argv)
    try:
        info = create_fixture(args.output)
    except FileExistsError as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        return 1
    print(f"Synthetic fixture created: {info.project.resolve()}")
    print(f"  {len(info.all_source_files)} files")
    print("Starting folders to try:")
    for label, path in (
        ("Project", info.project),
        ("Part Number", info.part_a),
        ("Lot Number", info.lot_a1),
        ("Buildup", info.buildup_a1_bu01),
    ):
        print(f'  {label:<12}: python -m hrm_converter --input "{path}" --config config.yaml')
    return 0


if __name__ == "__main__":
    sys.exit(main())
