"""
Cross-reference each opponent's currently-drafted roster against this
league's starter-slot requirements (config/league_settings.yaml
roster.starters) to flag which positions they still need to fill.

Used together with src/draft_tendencies.py's historical position-run
predictions: "the teams picking before my next turn haven't filled their
RB slots yet AND RB is historically a hot position in this pick range" is
a much stronger signal than either fact alone.
"""

from __future__ import annotations

from collections import Counter

from src.draft_state import DraftState


def team_position_counts(picks: list) -> dict[str, int]:
    """picks: a list of src.draft_state.Pick for one team."""
    counts: Counter[str] = Counter()
    for p in picks:
        if p.position:
            counts[p.position] += 1
    return dict(counts)


def unfilled_starter_slots(position_counts: dict[str, int], starters: list[dict]) -> dict[str, int]:
    """Greedily assign a team's drafted players to starter slots (most
    position-restrictive slots first, e.g. the dedicated QB/RB/TE/K/DST
    slots, before the broader WR_TE_FLEX/SUPERFLEX/FLEX slots) and return
    {slot_name: still_needed} for any slot that can't be fully filled
    from what's been drafted so far.

    This is a heuristic, not a claim about the team's actual intended
    lineup -- it answers "if this team stopped drafting right now, which
    starter slots would be empty," which is exactly the signal useful for
    guessing what they'll draft next.
    """
    available = dict(position_counts)
    unfilled: dict[str, int] = {}
    slots_sorted = sorted(starters, key=lambda s: len(s["eligible"]))
    for slot in slots_sorted:
        need = slot["count"]
        for pos in slot["eligible"]:
            if need == 0:
                break
            take = min(need, available.get(pos, 0))
            available[pos] = available.get(pos, 0) - take
            need -= take
        if need > 0:
            unfilled[slot["slot"]] = need
    return unfilled


def positions_that_would_fill(unfilled_slots: dict[str, int], starters: list[dict]) -> Counter:
    """Turn {slot_name: needed_count} back into a per-POSITION demand
    weight, by spreading each unfilled slot's need evenly across its
    eligible positions (e.g. a still-empty WR_TE_FLEX spot contributes
    0.5 demand to WR and 0.5 to TE). Positions eligible for more unfilled
    slots accumulate more weight."""
    by_slot_name = {s["slot"]: s for s in starters}
    demand: Counter[str] = Counter()
    for slot_name, need in unfilled_slots.items():
        slot = by_slot_name[slot_name]
        eligible = slot["eligible"]
        if not eligible:
            continue
        share = need / len(eligible)
        for pos in eligible:
            demand[pos] += share
    return demand


def opponent_needs_before_next_pick(draft_state: DraftState, config: dict) -> dict[str, Counter]:
    """For every team that will pick before draft_state's my_team picks
    next, return {team_name: Counter(position -> unfilled-slot demand)}.
    Empty dict if it's already my_team's turn or the draft is complete."""
    picks_until_me = draft_state.picks_until_my_turn()
    if not picks_until_me:
        return {}

    starters = config["roster"]["starters"]
    rosters = draft_state.roster_by_team()

    upcoming_teams = []
    for offset in range(picks_until_me):
        overall = draft_state.next_overall_pick + offset
        upcoming_teams.append(draft_state.team_for_pick(overall))

    result: dict[str, Counter] = {}
    for team in upcoming_teams:
        counts = team_position_counts(rosters.get(team, []))
        unfilled = unfilled_starter_slots(counts, starters)
        result[team] = positions_that_would_fill(unfilled, starters)
    return result


def aggregate_opponent_demand(opponent_needs: dict[str, Counter]) -> Counter:
    """Sum position demand across all upcoming opponents into one ranked
    Counter, for a simple "these are the positions the teams ahead of you
    are most likely to need" view."""
    total: Counter[str] = Counter()
    for demand in opponent_needs.values():
        total.update(demand)
    return total
