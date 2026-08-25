"""
Projections — view each stat-projection source individually, pick per-source
weights, and see the resulting blended stat line. This is where the Draft
Board's rankings actually come from (src/projections.py's blend_projections
+ build_draft_board); this page exposes that pipeline directly instead of
only showing the final ranked output.

Sources currently wired in (data/projections/*.csv):
  - cbs           — all rostered players, no live refresh (CBS requires a
                    logged-in session; re-pull manually via a browser
                    capture + scripts/fetch_draft_order.py's pattern).
  - fftoday       — ~50 players/skill-position, all 32 DSTs. Live refresh
                    supported below (server-rendered page, plain HTTP works).
  - fantasypros   — top 10 players per position only (free-tier cap — see
                    src/data_sources/fantasypros.py's module docstring).
                    Live refresh attempted below but UNVERIFIED outside a
                    real deployment (this repo's dev sandbox has no general
                    internet egress to test against fantasypros.com).

Sites keep updating their season projections up until the first regular-
season game, so each live source has its own "Refresh from web" button
that re-fetches right now rather than relying only on the CSV snapshots
committed to the repo.
"""

from __future__ import annotations

import os
import traceback

import pandas as pd
import streamlit as st

from src.data_sources.fantasypros import fetch_all as fetch_fantasypros_all
from src.data_sources.fftoday import fetch_all as fetch_fftoday_all
from src.data_sources.manual_import import load_many
from src.projections import blend_projections, score_and_rank
from src.scoring import load_config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config", "league_settings.yaml")
DATA_DIR = os.path.join(ROOT, "data", "projections")
DATA_EXTENSIONS = (".csv", ".tsv", ".xlsx", ".xlsm", ".xltx", ".xls")

# Sources with a working live-refresh path. CBS is deliberately absent —
# it requires a logged-in browser session the deployed app doesn't have.
LIVE_REFRESH = {
    "fftoday": {"fetch": fetch_fftoday_all, "csv": os.path.join(DATA_DIR, "fftoday_2026.csv")},
    "fantasypros": {"fetch": fetch_fantasypros_all, "csv": os.path.join(DATA_DIR, "fantasypros_2026.csv")},
}

st.set_page_config(page_title="Projections — Monster Cheese", page_icon="📊", layout="wide")


def _data_files() -> list[str]:
    if not os.path.isdir(DATA_DIR):
        return []
    return sorted(
        os.path.join(DATA_DIR, name)
        for name in os.listdir(DATA_DIR)
        if os.path.splitext(name)[1].lower() in DATA_EXTENSIONS
    )


@st.cache_resource
def get_config():
    return load_config(CONFIG_PATH)


@st.cache_data
def load_raw(_mtimes: tuple) -> pd.DataFrame:
    """All per-source rows, unblended, tagged by source (filename minus
    extension). _mtimes busts the cache whenever a source CSV changes on
    disk — including right after a live refresh overwrites one."""
    paths = _data_files()
    if not paths:
        return pd.DataFrame()
    sources = [(p, os.path.splitext(os.path.basename(p))[0]) for p in paths]
    return load_many(sources)


@st.cache_data
def blend_and_score(_mtimes: tuple, weight_items: tuple, _raw_df: pd.DataFrame) -> pd.DataFrame:
    weights = dict(weight_items)
    blended = blend_projections(_raw_df, weights)
    return score_and_rank(blended, get_config())


def _refresh_source(source: str) -> None:
    spec = LIVE_REFRESH[source]
    with st.spinner(f"Fetching latest {source} projections…"):
        try:
            df = spec["fetch"]()
        except Exception as exc:  # noqa: BLE001 — surface any failure to the user, don't guess
            st.session_state["_refresh_error"] = (source, str(exc), traceback.format_exc())
            return
    df.to_csv(spec["csv"], index=False)
    st.session_state["_refresh_ok"] = (source, len(df))
    load_raw.clear()
    blend_and_score.clear()


st.title("📊 Projections")

paths = _data_files()
if not paths:
    st.error("No projection files found in `data/projections/`.")
    st.stop()

mtimes = tuple(os.path.getmtime(p) for p in paths)
raw_df = load_raw(mtimes)
available_sources = sorted(raw_df["source"].unique().tolist()) if not raw_df.empty else []

# ---------------------------------------------------------------------
# Refresh-from-web controls
# ---------------------------------------------------------------------

st.subheader("Refresh source data")
st.caption(
    "Sites keep updating projections up until the first regular-season game — "
    "pull the latest numbers right now instead of relying only on the snapshots below."
)

refresh_cols = st.columns(len(LIVE_REFRESH) + 1)
for i, source in enumerate(LIVE_REFRESH):
    with refresh_cols[i]:
        csv_path = LIVE_REFRESH[source]["csv"]
        if os.path.exists(csv_path):
            st.caption(f"**{source}** — last updated {pd.Timestamp(os.path.getmtime(csv_path), unit='s').strftime('%Y-%m-%d %H:%M')}")
        else:
            st.caption(f"**{source}** — no data yet")
        if st.button(f"🔄 Refresh {source}", key=f"refresh_{source}", use_container_width=True):
            _refresh_source(source)
            st.rerun()
with refresh_cols[-1]:
    st.caption("**cbs** — no live refresh (requires a logged-in CBS session)")
    st.caption("Re-pull manually via a browser capture; see `SESSION_NOTES.md`.")

if "_refresh_ok" in st.session_state:
    source, n = st.session_state.pop("_refresh_ok")
    st.success(f"Refreshed **{source}**: {n} rows fetched and saved.")
if "_refresh_error" in st.session_state:
    source, msg, tb = st.session_state.pop("_refresh_error")
    st.error(f"Refreshing **{source}** failed: {msg}")
    with st.expander("Full error"):
        st.code(tb)

st.divider()

if raw_df.empty:
    st.warning("No projection data loaded — add files to `data/projections/` and reload.")
    st.stop()

# ---------------------------------------------------------------------
# Per-source weighting
# ---------------------------------------------------------------------

st.subheader("Source weights")
st.caption(
    "Set any source's weight to 0 to exclude it entirely, or use a single non-zero "
    "weight to view one source alone. Weights are relative — 2 vs 1 counts double, not "
    "an absolute percentage."
)

weight_cols = st.columns(len(available_sources))
weights: dict[str, float] = {}
for col, source in zip(weight_cols, available_sources):
    with col:
        weights[source] = st.slider(source, min_value=0.0, max_value=3.0, value=1.0, step=0.1, key=f"weight_{source}")

weight_items = tuple(sorted(weights.items()))
board = blend_and_score(mtimes, weight_items, raw_df)

st.divider()

# ---------------------------------------------------------------------
# Player lookup: per-source raw lines + blended result
# ---------------------------------------------------------------------

st.subheader("Player comparison")

all_names = sorted(raw_df["name"].unique().tolist())
player = st.selectbox("Player", options=[""] + all_names, index=0)

display_stat_cols = [
    "pass_yards", "pass_td", "pass_int", "rush_yards", "rush_td",
    "receptions", "rec_yards", "rec_td", "fumbles_lost", "fg_made", "xp_made",
    "def_sacks", "def_int", "def_fumble_rec", "def_td", "def_safeties",
    "points_allowed_per_game", "yards_allowed_per_game",
]

if player:
    per_source = raw_df[raw_df["name"] == player].copy()
    shown_cols = ["source", "position", "nfl_team", "games"] + [
        c for c in display_stat_cols if per_source[c].notna().any()
    ]
    st.markdown(f"**Per-source raw projections — {player}**")
    st.dataframe(per_source[shown_cols], hide_index=True, use_container_width=True)

    blended_row = board[board["name"] == player]
    if not blended_row.empty:
        st.markdown("**Blended result (with current weights)**")
        b_shown = ["sources", "num_sources", "games"] + [
            c for c in display_stat_cols if blended_row[c].notna().any()
        ] + ["score_total", "vor", "overall_rank", "position_rank", "vor_rank"]
        st.dataframe(
            blended_row[b_shown].rename(columns={"score_total": "Proj Pts", "vor": "VOR"}),
            hide_index=True,
            use_container_width=True,
        )
    else:
        st.caption("No blended row for this player — every source weight may be 0.")

st.divider()

# ---------------------------------------------------------------------
# Full blended board
# ---------------------------------------------------------------------

st.subheader("Full blended board")

bcol1, bcol2 = st.columns([2, 1])
with bcol1:
    search = st.text_input("Search player", "", key="board_search")
with bcol2:
    positions = sorted(board["position"].unique().tolist())
    pos_filter = st.multiselect("Position", positions, default=[], key="board_pos_filter")

view = board
if search:
    view = view[view["name"].str.contains(search, case=False, na=False)]
if pos_filter:
    view = view[view["position"].isin(pos_filter)]
view = view.sort_values("vor_rank")

st.dataframe(
    view[["vor_rank", "name", "position", "nfl_team", "sources", "num_sources", "score_total", "vor"]].rename(
        columns={
            "vor_rank": "VOR Rk", "name": "Player", "position": "Pos", "nfl_team": "Team",
            "sources": "Sources", "num_sources": "# Sources", "score_total": "Proj Pts", "vor": "VOR",
        }
    ),
    hide_index=True,
    use_container_width=True,
    height=500,
)
