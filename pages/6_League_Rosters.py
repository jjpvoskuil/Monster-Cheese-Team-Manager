"""
League Rosters — every team's drafted roster in one place, organized by
starting-lineup slot exactly like My Roster's own layout
(pages/4_My_Roster.py's src.roster_needs.assign_roster_slots() draft
-order heuristic: dedicated slots filled first, then flex slots,
earliest-drafted player first among each slot's eligible positions) --
so "Starting Lineup Pts" below is a literal sum of the rows shown above
it, not a separate harder-to-verify figure. Layout matches the league
manager's own spreadsheet mockup (2026-08-28): one Roster Position /
Player / Proj Pts table per team, capped with Starting Lineup Pts /
Bench Points / Total Team Points rows.

Punch-list item #2: "Create a page that shows the entire roster of each
team in the league that fills as we are drafting. This will allow us to
look at each team to help id their needs and adjust ours. Also add a
column to each roster to who the project points for all the players and
the total for each team. Have a breakdown of total points for the
roster and a second for the projected starting line up for each team."

Reads the same data/draft_state.json every other page does (a pick
logged anywhere shows up here on the next rerun), and the same blended
projections board the Draft Board itself uses (src.projections
.build_draft_board), so point totals here always match what's shown
there.

NOTE: this deliberately uses the SAME draft-order heuristic as My
Roster (src.roster_needs.assign_roster_slots), not
src.lineup_value.optimal_lineup_points()'s "best mathematically
possible legal lineup" figure -- the mockup's rows need to be an actual,
literal slot assignment for the summary sums to visibly match what's
printed above them. If a "best possible" number is ever wanted again
alongside this, it'd have to be a separate column/metric, since it
doesn't correspond to any single set of slot rows.
"""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from src.data_sources.manual_import import load_many
from src.draft_state import DraftState
from src.projections import build_draft_board
from src.roster_needs import assign_roster_slots
from src.scoring import load_config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config", "league_settings.yaml")
DRAFT_STATE_FILE = os.path.join(ROOT, "data", "draft_state.json")
# Same extension allowlist as the Draft Board -- keeps out
# data/projections/README.md, which isn't a data file.
DATA_EXTENSIONS = (".csv", ".tsv", ".xlsx", ".xlsm", ".xltx", ".xls")
REAL_DATA_DIR = os.path.join(ROOT, "data", "projections")
SAMPLE_DATA_DIR = os.path.join(ROOT, "data", "sample")

# Display-only relabeling, same as My Roster -- doesn't touch
# eligibility/assignment logic (src.roster_needs still sees "SUPERFLEX"
# and its real QB/RB/WR/TE eligible list).
SLOT_DISPLAY_NAMES = {"SUPERFLEX": "QB (Flex)"}


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


def _points_for(pick, missing: list[str]) -> float:
    pts = points_by_name.get(pick.player_name)
    if pts is None or pd.isna(pts):
        missing.append(pick.player_name)
        return 0.0
    return float(pts)


# ---------------------------------------------------------------------
# Per-team table: one row per starting-lineup slot instance (draft-order
# heuristic, same as My Roster), then one row per bench player, then a
# blank spacer row, then Starting Lineup Pts / Bench Points / Total Team
# Points summary rows -- literal sums of the rows above them.
# ---------------------------------------------------------------------

team_summaries = []
per_team_tables: dict[str, pd.DataFrame] = {}
missing_projection_players: dict[str, list[str]] = {}

for team in teams:
    picks = rosters.get(team, [])
    slots, bench = assign_roster_slots(picks, starters)
    bench_sorted = sorted(bench, key=lambda p: p.overall_pick)

    rows = []
    missing: list[str] = []
    starting_pts = 0.0
    for slot in starters:
        filled = slots.get(slot["slot"], [None] * slot["count"])
        label_base = SLOT_DISPLAY_NAMES.get(slot["slot"], slot["slot"].replace("_", " "))
        for i, pick in enumerate(filled, start=1):
            label = label_base if slot["count"] == 1 else f"{label_base} {i}"
            if pick is not None:
                pts = _points_for(pick, missing)
                starting_pts += pts
                rows.append({"Roster Position": label, "Player": pick.player_name, "Proj Pts": round(pts, 1)})
            else:
                rows.append({"Roster Position": label, "Player": "— empty —", "Proj Pts": ""})

    bench_pts = 0.0
    for i, pick in enumerate(bench_sorted, start=1):
        pts = _points_for(pick, missing)
        bench_pts += pts
        label = "Bench" if len(bench_sorted) == 1 else f"Bench {i}"
        rows.append({"Roster Position": label, "Player": pick.player_name, "Proj Pts": round(pts, 1)})

    total_pts = starting_pts + bench_pts

    rows.append({"Roster Position": "", "Player": "", "Proj Pts": ""})
    rows.append({"Roster Position": "Starting Lineup Pts", "Player": "", "Proj Pts": round(starting_pts, 1)})
    rows.append({"Roster Position": "Bench Points", "Player": "", "Proj Pts": round(bench_pts, 1)})
    rows.append({"Roster Position": "Total Team Points", "Player": "", "Proj Pts": round(total_pts, 1)})

    per_team_tables[team] = pd.DataFrame(rows)
    missing_projection_players[team] = missing
    team_summaries.append({
        "Team": f"🎯 {team}" if team == my_team else team,
        "_team_raw": team,
        "Picks": len(picks),
        "Starting Lineup Pts": round(starting_pts, 1),
        "Bench Points": round(bench_pts, 1),
        "Total Team Points": round(total_pts, 1),
    })

st.divider()
st.subheader("League summary")
st.caption(
    "**Starting Lineup Pts** = sum of the Starting Lineup rows in each team's "
    "table below — same slot-filling logic as the My Roster page's own "
    "\"Starting lineup\" section (earliest-drafted player first among each "
    "slot's eligible positions). **Bench Points** = everyone else drafted. "
    "**Total Team Points** = both combined."
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
    label = f"🎯 {team}" if team == my_team else team
    summary_row = next(s for s in team_summaries if s["_team_raw"] == team)
    with st.expander(
        f"{label} — {summary_row['Picks']} picks · {summary_row['Total Team Points']} total pts",
        expanded=(team == my_team),
    ):
        st.dataframe(per_team_tables[team], hide_index=True, use_container_width=True)
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
