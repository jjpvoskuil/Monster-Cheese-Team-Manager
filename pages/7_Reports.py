"""
Reports — punch-list item #7: "Lets create a selectable download button
and option. We should be able to select multiple grids and reports from
various pages and be able to extract each selected grid/report as a
Excel file."

Pick any combination of reports below and download them all as ONE
Excel workbook (one sheet per report; League Rosters expands into one
sheet per team, same as a real draft-day roster binder). The actual
row-building for each report lives in src.report_catalog (unit-tested
there) -- this page only wires up the picker + the download button.

Reads the same data/draft_state.json and blended projections board
every other page does, so numbers here always match what's shown there.
"""

from __future__ import annotations

import io
import os
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from src.data_sources.manual_import import load_many
from src.draft_state import DraftState
from src.projections import build_draft_board
from src.report_catalog import REPORTS, ReportContext, build_workbook_sheets
from src.scoring import load_config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config", "league_settings.yaml")
DRAFT_STATE_FILE = os.path.join(ROOT, "data", "draft_state.json")
# Same extension allowlist as the Draft Board -- keeps out
# data/projections/README.md, which isn't a data file.
DATA_EXTENSIONS = (".csv", ".tsv", ".xlsx", ".xlsm", ".xltx", ".xls")
REAL_DATA_DIR = os.path.join(ROOT, "data", "projections")
SAMPLE_DATA_DIR = os.path.join(ROOT, "data", "sample")


@st.cache_resource
def get_config():
    return load_config(CONFIG_PATH)


def _data_files(data_dir: str) -> list[str]:
    if not os.path.isdir(data_dir):
        return []
    return sorted(
        os.path.join(data_dir, name)
        for name in os.listdir(data_dir)
        if os.path.splitext(name)[1].lower() in DATA_EXTENSIONS
    )


@st.cache_data
def get_ranked_players(data_dir: str, _mtimes: tuple) -> pd.DataFrame:
    paths = _data_files(data_dir)
    if not paths:
        return pd.DataFrame()
    sources = [(p, os.path.splitext(os.path.basename(p))[0]) for p in paths]
    raw = load_many(sources)
    return build_draft_board(raw, get_config())


def load_players() -> tuple[pd.DataFrame, bool]:
    """Same real-data-preferred, sample-data-fallback pattern as the Draft
    Board (pages/1_Draft_Board.py) -- keeps every page's numbers, this
    report page included, consistent with each other."""
    real_paths = _data_files(REAL_DATA_DIR)
    if real_paths:
        mtimes = tuple(os.path.getmtime(p) for p in real_paths)
        return get_ranked_players(REAL_DATA_DIR, mtimes), False
    sample_paths = _data_files(SAMPLE_DATA_DIR)
    if sample_paths:
        mtimes = tuple(os.path.getmtime(p) for p in sample_paths)
        return get_ranked_players(SAMPLE_DATA_DIR, mtimes), True
    return pd.DataFrame(), False


def build_workbook_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for sheet_name, df in sheets.items():
            df.to_excel(writer, sheet_name=sheet_name, index=False)
    return buffer.getvalue()



@st.fragment(run_every=3)
def render_reports() -> None:
    """Everything on this page that reads live draft_state. DraftState is
    constructed fresh at the top of this function on every fragment run
    (not once at module level) -- see pages/1_Draft_Board.py's
    render_live_board() docstring for why: a fragment rerun only
    re-executes this function's body, so a DraftState built outside it
    would never notice new picks an external live-sync process writes
    into the JSON file. (This page's download button works fine inside
    a fragment -- it's still a normal Streamlit widget.)
    """
    config = get_config()
    real_team_order = config.get("draft", {}).get("team_order") or []
    using_real_team_order = bool(real_team_order) and config["league"]["team_name"] in real_team_order
    if using_real_team_order:
        teams = real_team_order
    else:
        teams = [config["league"]["team_name"]] + [f"Team {i}" for i in range(1, config["league"]["teams"])]

    draft_state = DraftState(
        teams=teams,
        rounds=config["draft"]["rounds"],
        my_team=config["league"]["team_name"],
        state_file=DRAFT_STATE_FILE,
        reverse_last_n_rounds=config["draft"].get("reverse_last_n_rounds", 0),
    )

    players_df, is_sample = load_players()
    my_team = config["league"]["team_name"]

    st.title("📥 Reports")
    st.caption(
        "Pick any grids/reports below and download them all in one Excel "
        "workbook — one sheet per report (League Rosters expands into one "
        "sheet per team)."
    )

    if players_df.empty:
        st.error(
            "No projection data found. Drop CSV/Excel projection files into "
            "`data/projections/` (real 2026 data) or `data/sample/` (fallback) "
            "and reload."
        )
        st.stop()

    if is_sample:
        st.warning(
            "⚠️ Using **data/sample/** — this is last season's (2025) placeholder "
            "data, not real 2026 projections.",
            icon="⚠️",
        )

    points_by_name = players_df.set_index("name")["score_total"]
    ctx = ReportContext(
        config=config, draft_state=draft_state, teams=teams, my_team=my_team,
        players_df=players_df, points_by_name=points_by_name,
    )

    label_to_report = {r.label: r for r in REPORTS}
    selected_labels = st.multiselect(
        "Reports to include",
        options=list(label_to_report.keys()),
        default=list(label_to_report.keys()),
        help="Everything's selected by default -- deselect anything you don't want in the download.",
    )

    if not selected_labels:
        st.info("Select at least one report above to build a download.")
        st.stop()

    selected_reports = [label_to_report[label] for label in selected_labels]
    sheets = build_workbook_sheets(selected_reports, ctx)

    st.caption(f"Will produce {len(sheets)} sheet(s): " + ", ".join(sheets.keys()))

    workbook_bytes = build_workbook_bytes(sheets)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M")
    st.download_button(
        "⬇️ Download selected reports as Excel",
        data=workbook_bytes,
        file_name=f"monster_cheese_reports_{timestamp}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        use_container_width=True,
    )

    st.divider()
    st.subheader("Preview")
    preview_labels = list(sheets.keys())
    preview_choice = st.selectbox("Sheet", preview_labels)
    st.dataframe(sheets[preview_choice], hide_index=True, use_container_width=True)

    st.divider()
    st.page_link("pages/1_Draft_Board.py", label="← Back to Draft Board", icon="🏈")


render_reports()
