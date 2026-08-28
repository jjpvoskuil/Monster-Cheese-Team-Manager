"""
Registry of downloadable "reports" for pages/7_Reports.py (punch-list
item #7: "Lets create a selectable download button and option. We
should be able to select multiple grids and reports from various pages
and be able to extract each selected grid/report as a Excel file.").

Each report builder is a plain function of a shared `ReportContext` --
no Streamlit involved -- returning either a single pd.DataFrame (written
to one sheet named after the report) or a dict[str, pd.DataFrame] (one
sheet per key; used by the League Rosters report, one sheet per team).
Kept here rather than in the page so every builder is directly
unit-testable (see tests/test_report_catalog.py) without going through
Streamlit's AppTest harness, and so it's a data source pages/7_Reports.py
just wires up rather than reimplements.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Union

import pandas as pd

from src.draft_state import DraftState
from src.league_grid import build_league_grid
from src.roster_needs import assign_roster_slots, opponent_needs_before_next_pick

ReportOutput = Union[pd.DataFrame, dict[str, pd.DataFrame]]


@dataclass
class ReportContext:
    config: dict
    draft_state: DraftState
    teams: list[str]
    my_team: str
    players_df: pd.DataFrame  # full ranked/blended board, src.projections.build_draft_board's output
    points_by_name: pd.Series  # players_df.set_index("name")["score_total"]


@dataclass
class Report:
    key: str
    label: str
    build: Callable[[ReportContext], ReportOutput]


# Excel sheet names: max 31 chars, and : \ / ? * [ ] are illegal. Team
# names are configured by the league manager (and can be renamed live in
# the Draft Board sidebar), so sanitize defensively rather than assume
# they're always Excel-safe.
_ILLEGAL_SHEET_CHARS = re.compile(r"[:\\/?*\[\]]")


def safe_sheet_name(name: str, taken: set[str]) -> str:
    cleaned = _ILLEGAL_SHEET_CHARS.sub(" ", name).strip() or "Sheet"
    cleaned = cleaned[:31]
    candidate = cleaned
    n = 2
    while candidate in taken:
        suffix = f" ({n})"
        candidate = cleaned[: 31 - len(suffix)] + suffix
        n += 1
    taken.add(candidate)
    return candidate


def _points_for(player_name: str, points_by_name: pd.Series) -> float:
    pts = points_by_name.get(player_name)
    if pts is None or pd.isna(pts):
        return 0.0
    return float(pts)


def available_players_report(ctx: ReportContext) -> pd.DataFrame:
    if ctx.players_df.empty:
        return pd.DataFrame(columns=["VOR Rk", "Ovr Rk", "Pos Rk", "Player", "Pos", "Team", "Proj Pts", "VOR", "Tier"])
    drafted = ctx.draft_state.drafted_player_names()
    available = ctx.players_df[~ctx.players_df["name"].isin(drafted)].copy()
    cols = ["vor_rank", "overall_rank", "position_rank", "name", "position", "nfl_team", "score_total", "vor", "tier"]
    cols = [c for c in cols if c in available.columns]
    out = available[cols]
    if "vor_rank" in out.columns:
        out = out.sort_values("vor_rank")
    return out.rename(columns={
        "vor_rank": "VOR Rk", "overall_rank": "Ovr Rk", "position_rank": "Pos Rk",
        "name": "Player", "position": "Pos", "nfl_team": "Team",
        "score_total": "Proj Pts", "vor": "VOR", "tier": "Tier",
    })


def pick_log_report(ctx: ReportContext) -> pd.DataFrame:
    if not ctx.draft_state.picks:
        return pd.DataFrame(columns=["Pick", "Rd", "Team", "Player", "Pos", "NFL Team"])
    return pd.DataFrame([
        {
            "Pick": p.overall_pick, "Rd": p.round, "Team": p.team,
            "Player": p.player_name, "Pos": p.position, "NFL Team": p.nfl_team,
        }
        for p in ctx.draft_state.picks
    ])


def _my_roster_rows(ctx: ReportContext):
    picks = ctx.draft_state.roster_by_team().get(ctx.my_team, [])
    starters = ctx.config["roster"]["starters"]
    return assign_roster_slots(picks, starters)


def my_roster_lineup_report(ctx: ReportContext) -> pd.DataFrame:
    from src.league_grid import SLOT_DISPLAY_NAMES  # display-only relabeling, same as My Roster/League Rosters
    slots, _bench = _my_roster_rows(ctx)
    starters = ctx.config["roster"]["starters"]
    rows = []
    for slot in starters:
        filled = slots.get(slot["slot"], [None] * slot["count"])
        label_base = SLOT_DISPLAY_NAMES.get(slot["slot"], slot["slot"].replace("_", " "))
        for i, pick in enumerate(filled, start=1):
            label = label_base if slot["count"] == 1 else f"{label_base} {i}"
            if pick is not None:
                rows.append({
                    "Roster Position": label, "Player": pick.player_name, "Pos": pick.position,
                    "NFL Team": pick.nfl_team, "Rd": pick.round, "Pick": pick.overall_pick,
                    "Proj Pts": round(_points_for(pick.player_name, ctx.points_by_name), 1),
                })
            else:
                rows.append({
                    "Roster Position": label, "Player": "— empty —", "Pos": "/".join(slot["eligible"]),
                    "NFL Team": "", "Rd": None, "Pick": None, "Proj Pts": "",
                })
    return pd.DataFrame(rows)


def my_roster_bench_report(ctx: ReportContext) -> pd.DataFrame:
    _slots, bench = _my_roster_rows(ctx)
    if not bench:
        return pd.DataFrame(columns=["Player", "Pos", "NFL Team", "Rd", "Pick", "Proj Pts"])
    rows = [
        {
            "Player": p.player_name, "Pos": p.position, "NFL Team": p.nfl_team,
            "Rd": p.round, "Pick": p.overall_pick,
            "Proj Pts": round(_points_for(p.player_name, ctx.points_by_name), 1),
        }
        for p in sorted(bench, key=lambda p: p.overall_pick)
    ]
    return pd.DataFrame(rows)


def league_rosters_report(ctx: ReportContext) -> dict[str, pd.DataFrame]:
    """One sheet per team -- the same Roster Position / Player / Proj Pts
    layout as the League Rosters page's grid, just split back out per
    team the way a real draft-day roster binder would be, since a single
    Excel sheet can't merge a "Team Name" header the way that page's HTML
    grid does. Keys are the RAW team names -- sanitizing/de-duplicating
    into Excel-safe sheet names happens once, workbook-wide, in
    build_workbook_sheets() below, not per-report."""
    rosters = ctx.draft_state.roster_by_team()
    grid = build_league_grid(rosters, ctx.teams, ctx.config["roster"]["starters"], ctx.points_by_name)

    sheets: dict[str, pd.DataFrame] = {}
    for col in grid.columns:
        rows = []
        for label, player, pts in zip(grid.starter_labels, col.starter_players, col.starter_pts):
            rows.append({
                "Roster Position": label,
                "Player": player if player else "— empty —",
                "Proj Pts": round(pts, 1) if pts is not None else "",
            })
        for i, (player, pts) in enumerate(zip(col.bench_players, col.bench_pts), start=1):
            rows.append({"Roster Position": f"Bench {i}", "Player": player, "Proj Pts": round(pts, 1)})
        rows.append({"Roster Position": "", "Player": "", "Proj Pts": ""})
        rows.append({"Roster Position": "Starting Lineup Pts", "Player": "", "Proj Pts": round(col.starting_pts, 1)})
        rows.append({"Roster Position": "Bench Points", "Player": "", "Proj Pts": round(col.bench_pts_total, 1)})
        rows.append({"Roster Position": "Total Team Points", "Player": "", "Proj Pts": round(col.total_pts, 1)})
        sheets[col.team] = pd.DataFrame(rows)
    return sheets


def opponent_needs_report(ctx: ReportContext) -> pd.DataFrame:
    needs = opponent_needs_before_next_pick(ctx.draft_state, ctx.config)
    if not needs:
        return pd.DataFrame(columns=["Team", "Likely needs"])
    rows = []
    for team, demand in needs.items():
        if demand:
            top_positions = ", ".join(f"{pos} ({wt:.1f})" for pos, wt in demand.most_common(3))
        else:
            top_positions = "— (starters look filled)"
        rows.append({"Team": team, "Likely needs": top_positions})
    return pd.DataFrame(rows)


REPORTS: list[Report] = [
    Report("available_players", "Draft Board — Available Players (ranked)", available_players_report),
    Report("pick_log", "Draft Board — Full Pick Log", pick_log_report),
    Report("my_lineup", "My Roster — Starting Lineup", my_roster_lineup_report),
    Report("my_bench", "My Roster — Bench", my_roster_bench_report),
    Report("league_rosters", "League Rosters — All Teams (one sheet per team)", league_rosters_report),
    Report("opponent_needs", "Draft Tendencies — Opponent Roster Needs", opponent_needs_report),
]


def build_workbook_sheets(selected: list[Report], ctx: ReportContext) -> dict[str, pd.DataFrame]:
    """Runs each selected report's builder and flattens the results into
    one ordered {sheet_name: DataFrame} dict ready for pandas.ExcelWriter
    -- a single-DataFrame report becomes one sheet named after its label;
    a multi-sheet report (currently only League Rosters) contributes one
    sheet per key it returns. Sheet-name sanitizing/de-duplicating
    (Excel's 31-char limit and illegal characters) happens exactly once
    here, across the WHOLE workbook, so e.g. a report label and a team
    name can never collide even though they're sanitized independently."""
    taken: set[str] = set()
    sheets: dict[str, pd.DataFrame] = {}
    for report in selected:
        output = report.build(ctx)
        if isinstance(output, dict):
            for name, df in output.items():
                sheets[safe_sheet_name(name, taken)] = df
        else:
            sheets[safe_sheet_name(report.label, taken)] = output
    return sheets
