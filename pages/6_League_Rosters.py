"""
League Rosters — every team's drafted roster in one place, filling in
live as picks are logged. Punch-list item #2: "Create a page that shows
the entire roster of each team in the league that fills as we are
drafting. This will allow us to look at each team to help id their needs
and adjust ours. Also add a column to each roster to who the project
points for all the players and the total for each team. Have a breakdown
of total points for the roster and a second for the projected starting
line up for each team."

Reads the same data/draft_state.json every other page does (a pick
logged anywhere shows up here on the next rerun), and the same blended
projections board the Draft Board itself uses (src.projections
.build_draft_board), so the point totals here always match what's shown
there.

Two point totals per team, deliberately different methodologies:
  - "Roster pts" = sum of every drafted player's projected points,
    regardless of position or slot. A simple "how much value have they
    accumulated" number.
  - "Starting lineup pts" = src.lineup_value.optimal_lineup_points() --
    the best-possible total from a LEGAL starting lineup assembled from
    that team's drafted players (a proper assignment-problem
    optimization, not the draft-order heuristic src.roster_needs uses on
    the My Roster page). This is what actually decides weekly scoring,
    so it's the more useful number for sizing up an opponent's team
    strength -- a team that's hoarded 4 late-round QBs will have a much
    lower starting-lineup total than its raw roster total suggests.
"""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from src.data_sources.manual_import import load_many
from src.draft_state import DraftState
from src.lineup_value import LineupPlayer, optimal_lineup_points
from src.projections import build_draft_board
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
    Board (pages/1_Draft_Board.py) -- keeps every page's point totals
    consistent with each other."""
    real_paths = _data_files(REAL_DATA_DIR)
    if real_paths:
        mtimes = tuple(os.path.getmtime(p) for p in real_paths)
        return get_ranked_players(REAL_DATA_DIR, mtimes), False
    sample_paths = _data_files(SAMPLE_DATA_DIR)
    if sample_paths:
        mtimes = tuple(os.path.getmtime(p) for p in sample_paths)
        return get_ranked_players(SAMPLE_DATA_DIR, mtimes), True
    return pd.DataFrame(), False


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
starters = config["roster"]["starters"]
my_team = config["league"]["team_name"]

st.title("🏆 League Rosters")
st.caption(
    "Every team's drafted roster, updating live as picks are logged. Use "
    "this to spot other teams' needs (and gaps you might be able to "
    "exploit) and to see how your own roster stacks up on projected points."
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

if not using_real_team_order:
    st.warning(
        "⚠️ No real draft order found — using placeholder team names "
        "(Team 1, Team 2, ...). See the Draft Board page to set the real order.",
        icon="⚠️",
    )

points_by_name = players_df.set_index("name")["score_total"]
rosters = draft_state.roster_by_team()

# ---------------------------------------------------------------------
# Per-team totals -- "Roster pts" (sum of everything drafted) and
# "Starting lineup pts" (optimal_lineup_points -- best legal lineup from
# what's been drafted so far, not a draft-order heuristic).
# ---------------------------------------------------------------------

team_summaries = []
per_team_rows: dict[str, list[dict]] = {}
missing_projection_players: dict[str, list[str]] = {}

for team in teams:
    picks = sorted(rosters.get(team, []), key=lambda p: p.overall_pick)
    lineup_players = []
    rows = []
    missing = []
    roster_pts = 0.0
    for pick in picks:
        pts = points_by_name.get(pick.player_name)
        if pts is None or pd.isna(pts):
            pts = 0.0
            missing.append(pick.player_name)
        else:
            pts = float(pts)
        roster_pts += pts
        lineup_players.append(LineupPlayer(name=pick.player_name, position=pick.position, points=pts))
        rows.append({
            "Player": pick.player_name,
            "Pos": pick.position,
            "NFL Team": pick.nfl_team,
            "Rd": pick.round,
            "Pick": pick.overall_pick,
            "Proj Pts": round(pts, 1),
        })
    lineup_pts = optimal_lineup_points(lineup_players, starters)
    per_team_rows[team] = rows
    missing_projection_players[team] = missing
    team_summaries.append({
        "Team": f"🎯 {team}" if team == my_team else team,
        "_team_raw": team,
        "Picks": len(picks),
        "Roster Pts": round(roster_pts, 1),
        "Starting Lineup Pts": round(lineup_pts, 1),
    })

st.divider()
st.subheader("League summary")
st.caption(
    "**Roster Pts** = sum of every drafted player's projected points. "
    "**Starting Lineup Pts** = best-possible total from a *legal* starting "
    "lineup assembled from that team's drafted players (roster.starters "
    "slots) — the number that actually predicts weekly scoring strength."
)
summary_df = pd.DataFrame(team_summaries).sort_values("Starting Lineup Pts", ascending=False)
st.dataframe(
    summary_df.drop(columns=["_team_raw"]),
    hide_index=True,
    use_container_width=True,
)

st.divider()
st.subheader("Team-by-team rosters")

# My own team's expander opens by default; others start collapsed so the
# page doesn't overwhelm on load with 10 teams x 22 rounds.
for team in teams:
    rows = per_team_rows[team]
    label = f"🎯 {team}" if team == my_team else team
    summary_row = next(s for s in team_summaries if s["_team_raw"] == team)
    with st.expander(
        f"{label} — {summary_row['Picks']} picks · {summary_row['Roster Pts']} roster pts · "
        f"{summary_row['Starting Lineup Pts']} starting-lineup pts",
        expanded=(team == my_team),
    ):
        if not rows:
            st.caption("No picks logged yet.")
        else:
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        missing = missing_projection_players[team]
        if missing:
            st.caption(
                "⚠️ No projection found for: " + ", ".join(missing) +
                " — scored as 0 pts above (name mismatch between the draft "
                "log and projections data, or an undrafted-in-projections "
                "player)."
            )

st.divider()
st.page_link("pages/1_Draft_Board.py", label="← Back to Draft Board", icon="🏈")
