"""
Draft Board — ranked available players, manual pick logging, live draft
status and roster tracking. This is the tool actually used live on draft
day; manual pick entry is the reliable path regardless of whether CBS
live-sync (src/data_sources/cbs.py) ever gets built.
"""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from src.data_sources.manual_import import load_many
from src.draft_state import DraftState
from src.projections import build_draft_board
from src.scoring import load_config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config", "league_settings.yaml")
# Only match actual data files here — a bare "*.*" glob also picks up
# data/projections/README.md and hands it to pd.read_csv(), which throws
# a ParserError (README.md isn't a CSV). Restrict to the extensions
# load_table() actually knows how to read.
DATA_EXTENSIONS = (".csv", ".tsv", ".xlsx", ".xlsm", ".xltx", ".xls")
REAL_DATA_DIR = os.path.join(ROOT, "data", "projections")
SAMPLE_DATA_DIR = os.path.join(ROOT, "data", "sample")
DRAFT_STATE_FILE = os.path.join(ROOT, "data", "draft_state.json")


def _data_files(data_dir: str) -> list[str]:
    if not os.path.isdir(data_dir):
        return []
    return sorted(
        os.path.join(data_dir, name)
        for name in os.listdir(data_dir)
        if os.path.splitext(name)[1].lower() in DATA_EXTENSIONS
    )

st.set_page_config(page_title="Draft Board — Monster Cheese", page_icon="🏈", layout="wide")


@st.cache_resource
def get_config():
    return load_config(CONFIG_PATH)


@st.cache_data
def get_ranked_players(data_dir: str, _mtimes: tuple) -> tuple[pd.DataFrame, bool]:
    """Returns (ranked_df, is_sample_data). _mtimes busts the cache when
    source files change on disk."""
    paths = _data_files(data_dir)
    if not paths:
        return pd.DataFrame(), False
    sources = [(p, os.path.splitext(os.path.basename(p))[0]) for p in paths]
    raw = load_many(sources)
    ranked = build_draft_board(raw, get_config())
    return ranked, False


def load_players() -> tuple[pd.DataFrame, bool]:
    real_paths = _data_files(REAL_DATA_DIR)
    if real_paths:
        mtimes = tuple(os.path.getmtime(p) for p in real_paths)
        df, _ = get_ranked_players(REAL_DATA_DIR, mtimes)
        return df, False
    sample_paths = _data_files(SAMPLE_DATA_DIR)
    if sample_paths:
        mtimes = tuple(os.path.getmtime(p) for p in sample_paths)
        df, _ = get_ranked_players(SAMPLE_DATA_DIR, mtimes)
        return df, True
    return pd.DataFrame(), False


config = get_config()
teams = [config["league"]["team_name"]] + [f"Team {i}" for i in range(1, config["league"]["teams"])]
# Real team names aren't known until draft day rosters are set on CBS;
# placeholder opponent names can be renamed in the sidebar below.
if "team_names" not in st.session_state:
    st.session_state.team_names = teams

draft_state = DraftState(
    teams=st.session_state.team_names,
    rounds=config["draft"]["rounds"],
    my_team=config["league"]["team_name"],
    state_file=DRAFT_STATE_FILE,
)

players_df, is_sample = load_players()

# ---------------------------------------------------------------------
# Sidebar: draft status, team names, my roster, undo/reset
# ---------------------------------------------------------------------

with st.sidebar:
    st.header("Draft status")
    if draft_state.is_draft_complete:
        st.success("Draft complete!")
    else:
        on_clock = draft_state.on_the_clock
        rnd, slot = draft_state.round_and_slot_for_pick(draft_state.next_overall_pick)
        st.metric("On the clock", on_clock)
        st.caption(f"Pick {draft_state.next_overall_pick} overall (Round {rnd}, Slot {slot})")
        if draft_state.is_my_pick:
            st.success("🎯 It's your pick!")
        else:
            until = draft_state.picks_until_my_turn()
            st.caption(f"{until} picks until your turn")

    if st.button("↩️ Undo last pick", use_container_width=True, disabled=not draft_state.picks):
        undone = draft_state.undo_last_pick()
        if undone:
            st.toast(f"Undid: {undone.team} — {undone.player_name}")
        st.rerun()

    with st.expander("Reset draft (danger zone)"):
        st.warning("This clears the entire pick log.")
        if st.button("Reset draft", type="primary"):
            draft_state.reset()
            st.rerun()

    st.divider()
    st.subheader(f"My roster — {config['league']['team_name']}")
    my_picks = draft_state.my_roster()
    if not my_picks:
        st.caption("No picks yet.")
    else:
        roster_df = pd.DataFrame(
            [{"Rd": p.round, "Player": p.player_name, "Pos": p.position} for p in my_picks]
        )
        st.dataframe(roster_df, hide_index=True, use_container_width=True)

    with st.expander("Rename opponent teams"):
        for i, name in enumerate(st.session_state.team_names):
            if name == config["league"]["team_name"]:
                continue
            new_name = st.text_input(f"Team {i+1}", value=name, key=f"team_name_{i}")
            st.session_state.team_names[i] = new_name

# ---------------------------------------------------------------------
# Main: ranked available players + log-a-pick
# ---------------------------------------------------------------------

st.title("🏈 Draft Board")

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
        "data, not real 2026 projections. Add real files to `data/projections/` "
        "before relying on these rankings for draft-day decisions.",
        icon="⚠️",
    )

drafted = draft_state.drafted_player_names()
available = players_df[~players_df["name"].isin(drafted)].copy()

filt_col1, filt_col2, filt_col3 = st.columns([2, 2, 1])
with filt_col1:
    search = st.text_input("Search player", "")
with filt_col2:
    positions = sorted(available["position"].unique().tolist())
    pos_filter = st.multiselect("Position", positions, default=[])
with filt_col3:
    sort_by = st.selectbox("Sort by", ["vor_rank", "overall_rank", "position_rank"], index=0)

view = available
if search:
    view = view[view["name"].str.contains(search, case=False, na=False)]
if pos_filter:
    view = view[view["position"].isin(pos_filter)]
view = view.sort_values(sort_by)

display_cols = [
    "vor_rank", "overall_rank", "position_rank", "name", "position", "nfl_team",
    "score_total", "vor", "num_sources",
]
st.dataframe(
    view[display_cols].rename(columns={
        "vor_rank": "VOR Rk", "overall_rank": "Ovr Rk", "position_rank": "Pos Rk",
        "name": "Player", "position": "Pos", "nfl_team": "Team",
        "score_total": "Proj Pts", "vor": "VOR", "num_sources": "# Sources",
    }),
    hide_index=True,
    use_container_width=True,
    height=500,
)

st.divider()
st.subheader("Log a pick")

with st.form("log_pick_form", clear_on_submit=True):
    lc1, lc2, lc3 = st.columns([2, 2, 1])
    with lc1:
        player_choice = st.selectbox(
            "Player", options=[""] + view["name"].tolist(), index=0,
            help="Pick from ranked available players, or type a name manually below "
                 "(useful for kickers/DSTs not in your projection file).",
        )
        manual_name = st.text_input("...or type a player name manually")
    with lc2:
        team_choice = st.selectbox(
            "Team", options=st.session_state.team_names,
            index=st.session_state.team_names.index(draft_state.on_the_clock)
            if not draft_state.is_draft_complete else 0,
        )
    with lc3:
        st.write("")
        st.write("")
        submitted = st.form_submit_button("Log pick", use_container_width=True, type="primary")

    if submitted:
        name = manual_name.strip() or player_choice
        if not name:
            st.error("Enter or select a player name.")
        else:
            row = players_df[players_df["name"] == name]
            position = row["position"].iat[0] if not row.empty else ""
            nfl_team = row["nfl_team"].iat[0] if not row.empty else ""
            pick = draft_state.log_pick(team_choice, name, position=position, nfl_team=nfl_team)
            st.toast(f"Logged: {pick.team} took {pick.player_name} (Rd {pick.round}, Pick {pick.overall_pick})")
            st.rerun()

st.divider()
with st.expander("Full pick log"):
    if draft_state.picks:
        log_df = pd.DataFrame(
            [
                {"Pick": p.overall_pick, "Rd": p.round, "Team": p.team, "Player": p.player_name, "Pos": p.position}
                for p in draft_state.picks
            ]
        )
        st.dataframe(log_df, hide_index=True, use_container_width=True)
    else:
        st.caption("No picks logged yet.")
