"""HRM converter - Streamlit app.

A thin screen over the same engine the command line uses: pick a folder,
convert, look at the long and wide tables, download the workbooks.

Run:  streamlit run app.py
"""

from __future__ import annotations

import dataclasses
import io
import subprocess
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

from hrm_converter.config import Config, load_config
from hrm_converter.logging_setup import close_logging, setup_logging
from hrm_converter.models import HrmConverterError, RunResult
from hrm_converter.output_writer import issues_frame, long_frame, summary_frame
from hrm_converter.pipeline import run_conversion
from hrm_converter.reference import load_reference, reference_template
from hrm_converter.validation import IssueCollector
from hrm_converter.wide import OUT_OF_SPEC, WideResult, build_wide, write_wide

APP_DIR = Path(__file__).resolve().parent
STYLESHEET = APP_DIR / "assets" / "styles.css"
OUT_OF_SPEC_STYLE = "background-color: rgba(243, 139, 168, 0.35); font-weight: bold"
MAX_STYLED_ROWS = 5000
VIEWS = ["Summary", "Long", "Wide", "Issues", "Reference"]
_PICK_FOLDER = (
    "import tkinter as tk; from tkinter import filedialog; r = tk.Tk(); r.withdraw(); "
    "r.attributes('-topmost', True); "
    "print(filedialog.askdirectory(title='Select a Project, Part Number, Lot or Buildup folder'))"
)


@dataclasses.dataclass
class Run:
    """Everything one conversion produced, kept in the session between reruns."""

    result: RunResult
    long: pd.DataFrame
    wide: WideResult
    wide_path: Path
    reference_name: str | None


def base_config() -> Config:
    """config.yaml next to the app; output and logs are kept next to the app too."""
    path = APP_DIR / "config.yaml"
    config = load_config(path if path.is_file() else None)
    return dataclasses.replace(
        config,
        output=dataclasses.replace(config.output, directory=APP_DIR / config.output.directory),
        logging=dataclasses.replace(config.logging, directory=APP_DIR / config.logging.directory),
    )


def browse_folder() -> None:
    """Native folder dialog in a helper process (Streamlit itself cannot open one)."""
    try:
        done = subprocess.run(
            [sys.executable, "-c", _PICK_FOLDER], capture_output=True, text=True, timeout=600
        )
    except (OSError, subprocess.SubprocessError):
        st.session_state["browse_failed"] = True
        return
    if done.stdout.strip():
        st.session_state["folder"] = done.stdout.strip()
    elif done.returncode != 0:
        st.session_state["browse_failed"] = True


def convert(
    folder: str, lot_name: str, strict: bool, reference_file: object, reference_path: str = ""
) -> Run:
    """Run the conversion. Limits come from the upload, else the typed path, else the config."""
    config = base_config()
    config = dataclasses.replace(
        config,
        metadata=dataclasses.replace(
            config.metadata, default_lot_name=lot_name or config.metadata.default_lot_name
        ),
        processing=dataclasses.replace(config.processing, strict_metadata_conflicts=strict),
    )
    log_path = setup_logging(config.logging.directory, config.logging.level)
    try:
        result = run_conversion(Path(folder), config)
    finally:
        close_logging()
    result.log_path = log_path

    long = long_frame(result.records)
    issues = IssueCollector()
    reference, reference_name = None, None
    on_disk = Path(reference_path) if reference_path else config.wide.reference_path
    if reference_file is not None:
        reference_name = str(getattr(reference_file, "name", "reference.xlsx"))
        data = io.BytesIO(reference_file.getvalue())  # type: ignore[attr-defined]
        reference = load_reference(data, config, issues, name=reference_name)
    elif on_disk is not None:
        reference_name = on_disk.name
        reference = load_reference(on_disk, config, issues)
    wide = build_wide(long, reference, config, issues)
    assert result.output_path is not None
    wide_path = write_wide(wide, result.output_path.with_name(config.wide.filename))
    return Run(result, long, wide, wide_path, reference_name)


def showable(frame: pd.DataFrame) -> pd.DataFrame:
    """Copy for st.dataframe: columns mixing numbers and text (Unit: 7 / 'C7') become text."""
    shown: pd.DataFrame = frame.copy()
    for column in shown.columns:
        kinds = {type(v) for v in shown[column] if v is not None and not pd.isna(v)}
        if len(kinds) > 1 and str in kinds:
            shown[column] = shown[column].map(lambda v: "" if v is None or pd.isna(v) else str(v))
        else:
            shown[column] = shown[column].infer_objects()
    return shown


def load_css() -> None:
    """Button, heading and metric styling shared with the QVM dashboard."""
    if STYLESHEET.is_file():
        st.markdown(
            f"<style>{STYLESHEET.read_text(encoding='utf-8')}</style>", unsafe_allow_html=True
        )


def highlighted(frame: pd.DataFrame, flagged: list[tuple[int, str]]) -> object:
    """The frame for st.dataframe, with out-of-spec cells tinted red.

    ``flagged`` holds (row label, column) pairs. Large tables are shown plain,
    because cell styling gets slow; the ``Out_of_Spec`` column still marks them.
    """
    shown = showable(frame)
    cells = [(row, column) for row, column in flagged if row in shown.index]
    if not cells or len(shown) > MAX_STYLED_ROWS:
        return shown

    def paint(data: pd.DataFrame) -> pd.DataFrame:
        styles: pd.DataFrame = pd.DataFrame("", index=data.index, columns=data.columns)
        for row, column in cells:
            styles.loc[row, column] = OUT_OF_SPEC_STYLE
        return styles

    return shown.style.apply(paint, axis=None).format(precision=4, na_rep="")


def template_bytes(long: pd.DataFrame, sheet: str) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        reference_template(long).to_excel(writer, sheet_name=sheet, index=False)
    return buffer.getvalue()


def render_nav(options: list[str], state_key: str) -> str:
    if st.session_state.get(state_key) not in options:
        st.session_state[state_key] = options[0]
    for column, label in zip(st.columns(len(options)), options, strict=True):
        column.button(
            label,
            key=f"{state_key}_{label}",
            type="primary" if st.session_state[state_key] == label else "secondary",
            width="stretch",
            on_click=lambda chosen=label: st.session_state.update({state_key: chosen}),
        )
    return str(st.session_state[state_key])


def render_sidebar() -> None:
    config = base_config()
    with st.sidebar:
        st.header("Source folder")
        st.text_input(
            "Project, Part Number, Lot or Buildup folder",
            key="folder",
            placeholder=r"L:\...\Chiplet4Future\FHR0020\19198",
        )
        st.button("Browse…", on_click=browse_folder, key="browse")
        if st.session_state.pop("browse_failed", False):
            st.warning("The folder dialog could not be opened. Paste the folder path instead.")

        with st.expander("Job information", expanded=False):
            st.text_input("Lot name", key="lot_name", value=config.metadata.default_lot_name)

        st.header("Limits")
        st.file_uploader(
            "Reference workbook (optional)",
            type=["xlsx"],
            key="reference",
            help="Excel sheet with LSL / Target / USL per Part Number, Buildup, Side, "
            "feature and metric. See the Reference page for a template.",
        )
        st.text_input(
            "…or path of the reference workbook",
            key="reference_path",
            value=str(config.wide.reference_path or ""),
            help="Use this when the reference file stays in one place; no upload needed.",
        )

        st.header("Options")
        st.checkbox(
            "Skip files whose name contradicts their folder",
            key="strict",
            value=config.processing.strict_metadata_conflicts,
            help="On: a workbook named BU03 / Back that sits in a BU01 / front folder is skipped. "
            "Off: the folder is trusted and the disagreement is only reported.",
        )
        st.button("Convert", type="primary", key="convert", width="stretch")


def render_summary(run: Run) -> None:
    result = run.result
    st.caption(f"{result.scope.role.value} folder: `{result.scope.start_path}`")
    values = [
        ("HRM folders", result.hrm_folder_count),
        ("Processed", result.processed_count),
        ("Skipped", result.skipped_count),
        ("Long rows", len(result.records)),
        ("Warnings", result.warning_count),
        ("Errors", result.error_count),
    ]
    for column, (label, value) in zip(st.columns(len(values)), values, strict=True):
        column.metric(label, f"{value:,}")
    st.subheader("Workbooks")
    st.dataframe(showable(summary_frame(result.file_results)), width="stretch", hide_index=True)
    st.caption(f"Saved: `{result.output_path}`  ·  `{run.wide_path}`  ·  log `{result.log_path}`")


def render_long(run: Run) -> None:
    long = run.long
    left, right = st.columns(2)
    features = left.multiselect(
        "Feature", sorted(long["Feature_Type"].unique()), key="long_feature"
    )
    buildups = right.multiselect(
        "Buildup", list(dict.fromkeys(long["Buildup"])), key="long_buildup"
    )
    shown = long
    if features:
        shown = shown[shown["Feature_Type"].isin(features)]
    if buildups:
        shown = shown[shown["Buildup"].isin(buildups)]
    st.caption(f"{len(shown):,} of {len(long):,} rows")
    st.dataframe(showable(shown), width="stretch", hide_index=True)
    assert run.result.output_path is not None
    st.download_button(
        "Download long workbook",
        run.result.output_path.read_bytes(),
        file_name=run.result.output_path.name,
        key="download_long",
    )


def render_wide(run: Run) -> None:
    wide = run.wide
    if not wide.sheets:
        st.info("No measurements to show.")
        return
    limited = int(wide.summary["With_Limits"].sum())
    total = int(wide.summary["Values"].sum())
    first, second, third = st.columns(3)
    first.metric("Wide rows", f"{wide.row_count:,}")
    second.metric(f"With limits (of {total:,})", f"{limited:,}")
    third.metric("Out of spec", f"{wide.out_of_spec_count:,}")
    if run.reference_name is None:
        st.info("No reference workbook loaded, so no limits are shown. Add one in the sidebar.")
    elif wide.out_of_spec_count:
        st.caption("Out-of-spec values are tinted red here and in the downloaded workbook.")

    sheet = st.selectbox("Feature", list(wide.sheets), key="wide_feature")
    frame = wide.sheets[sheet]
    if OUT_OF_SPEC in frame.columns and st.checkbox("Only rows out of spec", key="wide_only_out"):
        frame = frame[frame[OUT_OF_SPEC] != ""]
    st.caption(f"{len(frame):,} rows")
    st.dataframe(highlighted(frame, wide.flagged.get(sheet, [])), width="stretch", hide_index=True)
    st.download_button(
        "Download wide workbook",
        run.wide_path.read_bytes(),
        file_name=run.wide_path.name,
        key="download_wide",
    )
    with st.expander("Limit coverage per feature and metric"):
        st.dataframe(showable(wide.summary), width="stretch", hide_index=True)


def render_issues(run: Run) -> None:
    conversion = issues_frame(run.result.issues)
    st.subheader(f"Conversion ({len(conversion)})")
    if conversion.empty:
        st.success("No warnings or errors.")
    else:
        st.dataframe(showable(conversion), width="stretch", hide_index=True)
    limits = issues_frame(run.wide.issues)
    st.subheader(f"Limits ({len(limits)})")
    if limits.empty:
        st.success("No warnings or errors.")
    else:
        st.dataframe(showable(limits), width="stretch", hide_index=True)


def render_reference(run: Run) -> None:
    st.markdown(
        "One row per limit. **Feature_Type** and **Metric** are required. Leave **Part_Number**, "
        "**Buildup**, **Side** or **Feature_Number** blank to apply the row to all of them; when "
        "several rows fit, the one with the most cells filled in wins. Limits use the unit of the "
        "long table (roughness in nm)."
    )
    st.download_button(
        "Download a template for this data",
        template_bytes(run.long, base_config().wide.reference_sheet),
        file_name="HRM_Reference.xlsx",
        key="download_template",
    )
    if run.wide.reference is None:
        st.info("No reference workbook loaded.")
        return
    st.subheader(run.reference_name or "Reference")
    st.caption("Matched_Groups = how many measurement groups each row was applied to.")
    st.dataframe(showable(run.wide.reference), width="stretch", hide_index=True)


def main() -> None:
    st.set_page_config(page_title="HRM Converter", layout="wide")
    load_css()
    st.title("HRM Converter")
    render_sidebar()

    if st.session_state.get("convert"):
        folder = str(st.session_state.get("folder") or "").strip().strip('"')
        if not folder:
            st.error("Enter or browse to a folder first.")
        else:
            try:
                with st.spinner("Converting…"):
                    st.session_state["run"] = convert(
                        folder,
                        str(st.session_state.get("lot_name") or "").strip(),
                        bool(st.session_state.get("strict", True)),
                        st.session_state.get("reference"),
                        str(st.session_state.get("reference_path") or "").strip().strip('"'),
                    )
            except HrmConverterError as exc:
                st.session_state.pop("run", None)
                st.error(str(exc))

    run: Run | None = st.session_state.get("run")
    if run is None:
        st.info("Choose a folder in the sidebar and press **Convert**.")
        return

    view = render_nav(VIEWS, "view")
    st.divider()
    {
        "Summary": render_summary,
        "Long": render_long,
        "Wide": render_wide,
        "Issues": render_issues,
        "Reference": render_reference,
    }[view](run)


if __name__ == "__main__":
    main()
