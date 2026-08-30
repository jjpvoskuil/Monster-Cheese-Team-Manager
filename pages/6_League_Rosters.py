"""
League Rosters — one single wide grid with every team side by side,
organized by starting-lineup slot exactly like My Roster's own layout
(pages/4_My_Roster.py's src.roster_needs.assign_roster_slots() draft
-order heuristic: dedicated slots filled first, then flex slots,
earliest-drafted player first among each slot's eligible positions).
Layout matches the league manager's own spreadsheet mockup (2026-08-28,
second revision): ONE table for the whole league, not a table per team
-- each team gets its own Player/Proj Pts column pair, all sharing the
same Roster Position row labels down the left edge, ending in Starting
Lineup Pts / Bench Points / Total Team Points rows that literally sum
the columns above them. (The first revision built a separate
league-wide summary table plus a per-team expander each; the league
manager asked for one unified grid instead, so that summary table is
gone -- the totals now live as rows at the bottom of the single grid.)

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
there. All the row/point-building logic lives in src.league_grid (unit
-tested there) -- this file only turns that into an HTML table, since
Streamlit's native st.dataframe can't merge a "Team Name" header across
each team's Player+Proj Pts column pair the way the mockup wants.
"""

from __future__ import annotations

import html
import os

import pandas as pd
import streamlit as st

from src.data_sources.manual_import import load_many
from src.draft_state import DraftState
from src.league_grid import LeagueGrid, build_league_grid
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

GRID_CSS = """
<style>
.league-grid-wrap { overflow-x: auto; margin-bottom: 1rem; border: 1px solid #d0d0d0; }
.league-grid { border-collapse: collapse; font-size: 0.82rem; white-space: nowrap; width: 100%; }
.league-grid th, .league-grid td { border: 1px solid #d8d8d8; padding: 3px 8px; text-align: left; }
.league-grid th.team-header { background: #e3e3e3; text-align: center; font-size: 0.9rem; }
.league-grid th.team-header.mine { background: #ffe08a; }
.league-grid th.sub, .league-grid th.corner { background: #f0f0f0; font-weight: 600; }
.league-grid td.rowlabel { font-weight: 600; background: #fafafa; position: sticky; left: 0; z-index: 1; }
.league-grid th.corner { position: sticky; left: 0; z-index: 2; }
.league-grid tr.section td { background: #d9d9d9; font-weight: 700; }
.league-grid tr.spacer td { border: none; height: 6px; background: transparent; }
.league-grid tr.summary td.rowlabel { background: #dbe7ff; }
.league-grid tr.summary td { background: #eef3ff; font-weight: 700; }
.league-grid td.num { text-align: right; font-variant-numeric: tabular-nums; }
.league-grid td.empty { color: #999; }
</style>
"""


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


def _fmt(pts) -> str:
    return f"{pts:.1f}" if pts is not None else ""


def _esc(text) -> str:
    return html.escape(str(text))


def render_grid_html(grid: LeagueGrid, my_team: str) -> str:
    n_teams = len(grid.columns)
    parts: list[str] = ['<div class="league-grid-wrap"><table class="league-grid">']

    # Row 1: team-name headers, each spanning that team's Player + Proj Pts columns.
    parts.append('<tr><th class="corner"></th>')
    for col in grid.columns:
        cls = "team-header mine" if col.team == my_team else "team-header"
        display = f"🎯 {_esc(col.team)}" if col.team == my_team else _esc(col.team)
        parts.append(f'<th class="{cls}" colspan="2">{display}</th>')
    parts.append("</tr>")

    # Row 2: sub-headers.
    parts.append('<tr><th class="corner">Roster Position</th>')
    for _ in grid.columns:
        parts.append('<th class="sub">Player</th><th class="sub">Proj Pts</th>')
    parts.append("</tr>")

    def section_row(label: str) -> str:
        return f'<tr class="section"><td class="rowlabel">{_esc(label)}</td><td colspan="{n_teams * 2}"></td></tr>'

    def spacer_row() -> str:
        return f'<tr class="spacer"><td colspan="{1 + n_teams * 2}"></td></tr>'

    parts.append(section_row("Starters"))
    for i, label in enumerate(grid.starter_labels):
        row = [f'<td class="rowlabel">{_esc(label)}</td>']
        for col in grid.columns:
            player = col.starter_players[i]
            pts = col.starter_pts[i]
            if player:
                row.append(f"<td>{_esc(player)}</td>")
            else:
                row.append('<td class="empty">—</td>')
            row.append(f'<td class="num">{_fmt(pts)}</td>')
        parts.append("<tr>" + "".join(row) + "</tr>")

    if grid.max_bench:
        parts.append(spacer_row())
        parts.append(section_row("Bench"))
        for i in range(grid.max_bench):
            row = [f'<td class="rowlabel">Bench {i + 1}</td>']
            for col in grid.columns:
                if i < len(col.bench_players):
                    row.append(f"<td>{_esc(col.bench_players[i])}</td>")
                    row.append(f'<td class="num">{_fmt(col.bench_pts[i])}</td>')
                else:
                    row.append('<td class="empty">—</td><td></td>')
            parts.append("<tr>" + "".join(row) + "</tr>")

    parts.append(spacer_row())

    def summary_row(label: str, value) -> str:
        row = [f'<tr class="summary"><td class="rowlabel">{_esc(label)}</td>']
        for col in grid.columns:
            row.append(f'<td></td><td class="num">{_fmt(value(col))}</td>')
        row.append("</tr>")
        return "".join(row)

    parts.append(summary_row("Starting Lineup Pts", lambda c: c.starting_pts))
    parts.append(summary_row("Bench Points", lambda c: c.bench_pts_total))
    parts.append(summary_row("Total Team Points", lambda c: c.total_pts))

    parts.append("</table></div>")
    return "".join(parts)



@st.fragment(run_every=3)
def render_league_rosters() -> None:
    """Everything on this page that reads live draft_state. DraftState is
    constructed fresh at the top of this function on every fragment run
    (not once at module level) -- see pages/1_Draft_Board.py's
    render_live_board() docstring for why: a fragment rerun only
    re-executes this function's body, so a DraftState built outside it
    would never notice new picks an external live-sync process writes
    into the JSON file.
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
    starters = config["roster"]["starters"]
    my_team = config["league"]["team_name"]

    st.title("🏆 League Rosters")
    st.caption(
        "Every team's drafted roster, side by side, updating live as picks are "
        "logged. Use this to spot other teams' needs (and gaps you might be able "
        "to exploit) and to see how your own roster stacks up on projected "
        "points. Scroll right for the rest of the league — Roster Position stays "
        "pinned on the left."
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

    grid = build_league_grid(rosters, teams, starters, points_by_name)

    st.markdown(GRID_CSS, unsafe_allow_html=True)
    st.markdown(render_grid_html(grid, my_team), unsafe_allow_html=True)

    all_missing = sorted({
        f"{name} ({col.team})"
        for col in grid.columns
        for name in col.missing_projection
    })
    if all_missing:
        st.caption(
            "⚠️ No projection found for: " + ", ".join(all_missing) +
            " — scored as 0 pts above (name mismatch between the draft log and "
            "projections data, or an undrafted-in-projections player)."
        )

    st.divider()
    st.page_link("pages/1_Draft_Board.py", label="← Back to Draft Board", icon="🏈")


render_league_rosters()
