"""
Projections — view each stat-projection source individually, pick per-source
weights, and see the resulting blended stat line. This is where the Draft
Board's rankings actually come from (src/projections.py's blend_projections
+ build_draft_board); this page exposes that pipeline directly instead of
only showing the final ranked output.

Sources currently wired in (data/projections/*.csv):
  - cbs           — all rostered players. LOGIN-GATED (see below) —
                    requires a logged-in CBS session, so there's no plain
                    "Refresh" button; there's a "Log in & refresh" one
                    instead (see LOGIN_GATED below).
  - fftoday       — ~50 players/skill-position, all 32 DSTs. Live refresh
                    supported below (server-rendered page, plain HTTP works).
  - fantasypros   — top 10 players per position only (free-tier cap — see
                    src/data_sources/fantasypros.py's module docstring).
                    Live refresh attempted below but UNVERIFIED outside a
                    real deployment (this repo's dev sandbox has no general
                    internet egress to test against fantasypros.com).
  - fantasypoints — league manager's paid subscription (added 2026-08-28).
                    All 6 positions, ~630 players. LOGIN-GATED like CBS —
                    see src/data_sources/fantasypoints.py's module
                    docstring for the capture procedure and this source's
                    known gaps (no fumbles-lost; no DST points/yards
                    -allowed).

Sites keep updating their season projections up until the first regular-
season game, so each live source has its own refresh control below.
fftoday/fantasypros are plain HTTP and get a "Refresh" button that
re-fetches right now, server-side. cbs/fantasypoints are LOGIN-GATED —
Streamlit Cloud has no browser session to authenticate with, so their
button ("Log in & refresh") just opens the site in a new tab for you to
sign in; getting the actual updated data into this app still needs a
live Claude session to capture it (ask Claude "refresh cbs" or "refresh
fantasypoints" once you're logged in — see each source's module
docstring for exactly what that capture does).
"""

from __future__ import annotations

import os
import traceback

import pandas as pd
import streamlit as st

from src.data_sources.fantasypros import fetch_all as fetch_fantasypros_all
from src.data_sources.fftoday import fetch_all as fetch_fftoday_all
from src.data_sources.manual_import import load_many
from src.projections import blend_projections, compute_tiers, score_and_rank
from src.scoring import load_config
from src.tier_display import add_tier_divider_rows

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config", "league_settings.yaml")
DATA_DIR = os.path.join(ROOT, "data", "projections")
DATA_EXTENSIONS = (".csv", ".tsv", ".xlsx", ".xlsm", ".xltx", ".xls")

# Sources with a working live-refresh path: plain HTTP, so a click here
# re-fetches synchronously, server-side, right now.
LIVE_REFRESH = {
    "fftoday": {"fetch": fetch_fftoday_all, "csv": os.path.join(DATA_DIR, "fftoday_2026.csv")},
    "fantasypros": {"fetch": fetch_fantasypros_all, "csv": os.path.join(DATA_DIR, "fantasypros_2026.csv")},
}

# Sources that require a logged-in session (the league manager's own paid
# subscription, for fantasypoints) -- Streamlit Cloud has no browser to
# authenticate with, so there's no plain-HTTP "Refresh" path (see cbs.py's
# and fantasypoints.py's module docstrings). The button below just opens
# the site so the league manager can log in; getting fresh data into this
# app from there is a live-Claude-session capture, not something this
# deployed app can trigger on its own.
LOGIN_GATED = {
    "cbs": {
        "url": "https://www.cbssports.com/fantasy/football/stats/QB/2026/season/projections/nonppr/",
        "csv": os.path.join(DATA_DIR, "cbs_2026.csv"),
    },
    "fantasypoints": {
        "url": "https://www.fantasypoints.com/nfl/projections/season",
        "csv": os.path.join(DATA_DIR, "fantasypoints_2026.csv"),
    },
}


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

refresh_cols = st.columns(len(LIVE_REFRESH) + len(LOGIN_GATED))
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
for j, source in enumerate(LOGIN_GATED):
    with refresh_cols[len(LIVE_REFRESH) + j]:
        csv_path = LOGIN_GATED[source]["csv"]
        if os.path.exists(csv_path):
            st.caption(f"**{source}** — last updated {pd.Timestamp(os.path.getmtime(csv_path), unit='s').strftime('%Y-%m-%d %H:%M')}")
        else:
            st.caption(f"**{source}** — no data yet")
        st.link_button(f"🔗 Log in & refresh {source}", LOGIN_GATED[source]["url"], use_container_width=True)
        st.caption(
            "Opens the site to sign in — once you're logged in, ask Claude "
            f'"refresh {source}" and a live session will capture the latest '
            "data and update this file for you."
        )

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
# Tiering — group same-position players into tiers by point drop-off
# ---------------------------------------------------------------------

st.subheader("Tiers")
tier_col1, tier_col2 = st.columns([1, 3])
with tier_col1:
    tier_gap_input = st.number_input(
        "Tier gap override (pts)", min_value=0.0, value=0.0, step=1.0, key="tier_gap_override",
        help="0 = auto-detect tier breaks (a statistically significant point "
             "drop-off per position, relative to that position's own scale). "
             "Set a number to force a new tier whenever the gap to the next "
             "player exceeds it, e.g. 10 = every player within 10 pts of each "
             "other counts as the same tier.",
    )
with tier_col2:
    st.caption(
        "Tiers are computed per position on projected points (equivalent to VOR "
        "within a position, since VOR is just points minus a constant). Divider "
        "rows below only appear when the board is filtered to one position."
    )
tier_gap_threshold = tier_gap_input if tier_gap_input > 0 else None
board = compute_tiers(board, gap_threshold=tier_gap_threshold)

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
        ] + ["score_total", "vor", "tier", "overall_rank", "position_rank", "vor_rank"]
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

board_display = view[
    ["vor_rank", "name", "position", "nfl_team", "sources", "num_sources", "score_total", "vor", "tier"]
].rename(
    columns={
        "vor_rank": "VOR Rk", "name": "Player", "position": "Pos", "nfl_team": "Team",
        "sources": "Sources", "num_sources": "# Sources", "score_total": "Proj Pts", "vor": "VOR", "tier": "Tier",
    }
)
if len(pos_filter) == 1:
    board_display = add_tier_divider_rows(board_display, tier_col="Tier", label_col="Player")

st.dataframe(
    board_display,
    hide_index=True,
    use_container_width=True,
    height=500,
)
