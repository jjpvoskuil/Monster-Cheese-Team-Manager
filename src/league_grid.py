"""
Builds the data behind the League Rosters page's single wide grid: every
team side by side in one table, one shared row per starting-lineup slot
instance (src.roster_needs.assign_roster_slots's draft-order heuristic,
the SAME logic My Roster's own "Starting lineup" section uses) plus each
team's bench, capped with Starting Lineup Pts / Bench Points / Total
Team Points summary rows -- literal sums of the rows above them.

Kept separate from pages/6_League_Rosters.py (which only turns this into
an HTML table) so the row-building/point-summing logic is directly
unit-testable without going through Streamlit's AppTest harness.

Layout matches the league manager's own spreadsheet mockup (2026-08-28,
second revision): ONE grid for the whole league -- not a separate table
per team -- with each team as a side-by-side Player/Proj Pts column
pair, sharing the same Roster Position row labels down the left edge.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from src.data_sources.manual_import import normalize_name
from src.draft_state import Pick
from src.roster_needs import assign_roster_slots

# Display-only relabeling, same as My Roster -- doesn't touch
# eligibility/assignment logic (src.roster_needs still sees "SUPERFLEX"
# and its real QB/RB/WR/TE eligible list).
SLOT_DISPLAY_NAMES = {"SUPERFLEX": "QB (Flex)"}


@dataclass
class TeamColumn:
    team: str
    # Both lists are aligned to LeagueGrid.starter_labels (same length,
    # same order) -- starter_players[i]/starter_pts[i] describe whoever
    # (if anyone) is in starter_labels[i] for this team.
    starter_players: list[str]  # "" for an unfilled slot
    starter_pts: list[Optional[float]]  # None for an unfilled slot
    bench_players: list[str]  # draft order
    bench_pts: list[float]
    starting_pts: float
    bench_pts_total: float
    total_pts: float
    missing_projection: list[str]  # drafted player names not found in points_by_name (scored 0)


@dataclass
class LeagueGrid:
    starter_labels: list[str]
    max_bench: int  # deepest bench among all teams -- how many bench rows the grid needs
    columns: list[TeamColumn] = field(default_factory=list)


def _starter_labels(starters: list[dict]) -> list[str]:
    labels = []
    for slot in starters:
        label_base = SLOT_DISPLAY_NAMES.get(slot["slot"], slot["slot"].replace("_", " "))
        for i in range(1, slot["count"] + 1):
            labels.append(label_base if slot["count"] == 1 else f"{label_base} {i}")
    return labels


def build_league_grid(
    rosters: dict[str, list[Pick]],
    teams: list[str],
    starters: list[dict],
    points_by_name: pd.Series,
) -> LeagueGrid:
    starter_labels = _starter_labels(starters)
    columns: list[TeamColumn] = []

    # Fallback lookup keyed by normalized name (lowercase, punctuation and
    # Jr./Sr./II/III/IV stripped -- src.data_sources.manual_import's same
    # normalize_name() used to join projection sources together), tried
    # only when the exact player_name from the draft log doesn't match a
    # projection row verbatim. Real gap found live 2026-09-02: CBS logs
    # "Brian Robinson Jr." but at least one projection source has him as
    # plain "Brian Robinson" -- an exact match on points_by_name's raw
    # index silently scored him 0 and flagged him "missing" even though
    # his projection genuinely exists. Built once per call, not per pick.
    normalized_lookup: dict[str, float] = {}
    for raw_name, pts in points_by_name.items():
        key = normalize_name(raw_name)
        if key and key not in normalized_lookup:
            normalized_lookup[key] = pts

    for team in teams:
        picks = rosters.get(team, [])
        slots, bench = assign_roster_slots(picks, starters)
        bench_sorted = sorted(bench, key=lambda p: p.overall_pick)
        missing: list[str] = []

        def _points_for(pick: Pick) -> float:
            # Closes over this iteration's `missing` list -- called only
            # within this same iteration (never stored/deferred), so the
            # usual late-binding closure pitfall doesn't apply here.
            pts = points_by_name.get(pick.player_name)
            if pts is None or pd.isna(pts):
                pts = normalized_lookup.get(normalize_name(pick.player_name))
            if pts is None or pd.isna(pts):
                missing.append(pick.player_name)
                return 0.0
            return float(pts)

        starter_players: list[str] = []
        starter_pts: list[Optional[float]] = []
        starting_pts = 0.0
        for slot in starters:
            filled = slots.get(slot["slot"], [None] * slot["count"])
            for pick in filled:
                if pick is not None:
                    pts = _points_for(pick)
                    starting_pts += pts
                    starter_players.append(pick.player_name)
                    starter_pts.append(pts)
                else:
                    starter_players.append("")
                    starter_pts.append(None)

        bench_players: list[str] = []
        bench_pts: list[float] = []
        bench_pts_total = 0.0
        for pick in bench_sorted:
            pts = _points_for(pick)
            bench_pts_total += pts
            bench_players.append(pick.player_name)
            bench_pts.append(pts)

        columns.append(TeamColumn(
            team=team,
            starter_players=starter_players,
            starter_pts=starter_pts,
            bench_players=bench_players,
            bench_pts=bench_pts,
            starting_pts=starting_pts,
            bench_pts_total=bench_pts_total,
            total_pts=starting_pts + bench_pts_total,
            missing_projection=missing,
        ))

    max_bench = max((len(c.bench_players) for c in columns), default=0)
    return LeagueGrid(starter_labels=starter_labels, max_bench=max_bench, columns=columns)
