"""
Optimal starting-lineup point value for a drafted roster -- used by the
Monte Carlo simulation harness (scripts/simulate_draft.py) to compare
teams on what actually decides fantasy standings (weekly points), not
just "did they fill their slots legally."

This is deliberately NOT the same as src/roster_needs.assign_roster_slots(),
which fills slots in DRAFT ORDER (a "if the draft stopped right now, here's
how it would look" heuristic used by the live Draft Board / My Roster
page). Maximizing projected points needs the actual best eligible player
in each slot, regardless of when it was drafted -- a proper assignment
problem, solved here via scipy's linear_sum_assignment (weighted
bipartite matching): rows = individual starter-slot instances (e.g. "RB"
count=3 becomes 3 separate rows), columns = drafted players, cost = -
projected points for an eligible (slot, player) pair, a large penalty for
an ineligible pair. A slot instance that can't be filled by any remaining
eligible player (e.g. a team that never drafted a kicker) counts as 0
points -- an empty slot -- rather than being forced into an illegal
placement.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import linear_sum_assignment

# Large enough to always lose to any real (even deeply negative-VOR-but-
# still-scored) player/slot pairing, small enough to never overflow when
# summed across a full 12-slot lineup.
INELIGIBLE_PENALTY = 1e6


@dataclass
class LineupPlayer:
    name: str
    position: str
    points: float


def expand_slots(starters: list[dict]) -> list[dict]:
    """A {slot, count, eligible} list (roster.starters, or any list of the
    same shape) -> one entry per individual slot INSTANCE, e.g. an RB slot
    with count=3 becomes 3 separate {slot, eligible} rows. Needed because
    the assignment problem below is one row per physical roster spot, not
    one row per named slot category."""
    expanded = []
    for slot in starters:
        for _ in range(slot["count"]):
            expanded.append({"slot": slot["slot"], "eligible": slot["eligible"]})
    return expanded


def optimal_lineup_points(players: list[LineupPlayer], starters: list[dict]) -> float:
    """Best-possible total projected points for a legal starting lineup
    assembled from `players`, given `starters` slot definitions. Returns
    0.0 if there are no slots or no players."""
    slots = expand_slots(starters)
    if not slots or not players:
        return 0.0

    n_slots = len(slots)
    players = list(players)
    # linear_sum_assignment needs at least as many columns as rows to
    # assign every row -- pad with dummy (0-point, ineligible-for-
    # everything) players if a roster somehow has fewer drafted players
    # than starter slots. Shouldn't happen on a real 22-round draft, but
    # keeps this safe for partial/test rosters.
    if len(players) < n_slots:
        pad = n_slots - len(players)
        players = players + [
            LineupPlayer(name=f"__empty_{i}", position="", points=0.0) for i in range(pad)
        ]

    n_players = len(players)
    cost = np.full((n_slots, n_players), INELIGIBLE_PENALTY, dtype=float)
    for i, slot in enumerate(slots):
        eligible = set(slot["eligible"])
        for j, p in enumerate(players):
            if p.position in eligible:
                cost[i, j] = -p.points

    row_ind, col_ind = linear_sum_assignment(cost)
    total = 0.0
    for r, c in zip(row_ind, col_ind):
        if cost[r, c] < INELIGIBLE_PENALTY:
            total += -cost[r, c]
        # else: no eligible player left for this slot instance -- an empty
        # slot contributes 0, rather than being forced into an illegal fill.
    return total
