"""
Live "what should I draft next" recommendation for the Draft Board.

Combines three independent signals into one recommended POSITION (not a
single player -- the league manager's request was specifically "suggest
the next position to pick and the top 3 players available at the pick",
so the position call and the player shortlist are two separate steps):

  1. VALUE  -- the best available player's VOR at that position (VOR is
     already cross-position comparable by design -- see
     src/projections.py's module docstring -- so "best available VOR at
     each position" is a fair apples-to-apples comparison without any
     extra normalization needed at the raw-signal level).
  2. NEED   -- how much MY roster still needs that position to fill its
     starting lineup, reusing src/roster_needs.py's slot-filling logic
     (originally built for opponent-need inference) against my own
     drafted picks instead of an opponent's. A flex slot's need is
     weighted by config's estimation_assumptions.flex_position_splits
     (e.g. an unfilled SUPERFLEX counts ~90% toward QB, not an even 25%
     across QB/RB/WR/TE) -- fixed 2026-08-26 after an even split made a
     real 2nd-QB need invisible to this signal; see
     positions_that_would_fill()'s docstring.
  3. SCARCITY -- run risk: how many players of that position are
     historically expected to be drafted (by ANYONE) before my next turn,
     relative to how many top-tier players of that position are still on
     the board right now. A position with plenty of tier-1 players left
     and a low predicted pick count is safe to wait on; a position nearly
     out of top-tier talent with several picks predicted before I'm back
     on the clock is a run risk worth jumping on now.

Each signal is normalized to 0..1 (divided by its own max across the
positions being compared) before combining, since VOR points, a demand
weight, and a predicted-pick-count-per-remaining-tier-1-player ratio are
on three unrelated scales and would otherwise dominate the composite
arbitrarily based on which happens to have the largest raw numbers.

REDUNDANCY & EARLY-ROUND ADJUSTMENTS (added 2026-08-26, after a Monte
Carlo simulation across many full mock drafts -- see SESSION_NOTES --
showed the raw 3-signal composite above pathologically over-recommending
shallow-pool positions like K/DST/TE once starter-slot NEED hits zero:
their "best available VOR" stays mildly positive far longer than a skill
position's does, because a shallow pool never craters the way RB/WR/QB's
does once past replacement level. A first attempt that only squashed the
composite by a flat REDUNDANCY_PENALTY still lost that comparison most of
the time (0.05 x a small positive number can easily beat a skill
position whose composite has gone negative) -- rerunning the simulation
against that first attempt is what caught it. Four adjustments now
apply, checked in this order (most drastic first):

  - MANDATORY-DEADLINE FILL (checked first, overrides everything):
    positions with a dedicated single-eligible-position slot (QB/RB/TE/
    K/DST) that I haven't filled yet, where I'm down to my LAST chance(s)
    to ever fill it before the draft ends. Discovered when fixing
    REDUNDANCY below actually made this worse: with K/DST/TE properly
    excluded once capped, some simulated drafts went all the way to round
    22 having NEVER drafted a single QB, because a deep QB replacement
    pool means QB's raw VOR rarely craters enough to win the
    value/need/scarcity composite against RB/WR -- see the VOR analysis
    in docs/draft_insights.md and 2026-08-24's SESSION_NOTES entry. An
    empty mandatory dedicated slot scores zero for that slot every week
    of the season, so this overrides value/need/scarcity entirely, no
    exceptions -- see _mandatory_deadline_positions()'s docstring.
  - ROUND-BASED QUOTA DEADLINE (checked alongside MANDATORY-DEADLINE,
    same override tier): a generalization of the above for configured
    "must have N (of one or more eligible positions) by round R"
    categories (config's estimation_assumptions.round_based_fill_targets
    -- a list of {slot, eligible, count, by_round} entries, the same
    shape as roster.starters), for requirements that don't map to a
    dedicated roster.starters slot. Originally added for a self-imposed
    "2 QBs in the first ~7 rounds" target; extended 2026-08-27 once the
    league manager uploaded the real "Maniac Football League Draft Sheet"
    requirements document, which adds 7 more real by-round-20 categories
    (2 K, 2 DEF, 5 RB, 5 WR/TE, 1 RB-or-WR-or-TE, 1 mandatory TE, 2 any-
    position). Categories sharing a deadline are checked as a GROUP, not
    independently, so a combined shortfall across several categories is
    still caught even when no single category looks urgent alone -- see
    _round_based_quota_positions()'s docstring for why and how. The same
    unfilled categories also feed my_position_need() as soft demand all
    draft long, not just at the hard deadline -- see that function's
    docstring.
  - REDUNDANCY (checked next): once my own drafted count at a position
    meets or exceeds config's roster.position_active_limits max (QB/RB/
    TE/K/DST -- see _position_cap()), that position's NEED is zeroed (a
    still-open flex slot that's technically eligible for it, e.g.
    WR_TE_FLEX for TE or FLEX for K, stops feeding it a "need" it's no
    longer legal/useful to fill), its composite is squashed by
    REDUNDANCY_PENALTY for display, AND it is excluded from
    RECOMMENDATION as long as any not-at-cap position is still in the
    running -- a hard preference, not just a squash, because a squash
    alone can't guarantee it loses to an alternative whose own value has
    gone negative. Only falls back to an at-cap position when every
    position is at cap, so a fully maxed-out board can still recommend
    something. This exclusion applies within the MANDATORY/QUOTA tier too
    (added 2026-08-27, see suggest_position()'s must_fill handling) -- a
    multi-eligible quota category being urgent doesn't mean an already
    -capped member of it (e.g. TE within "WR or TE") should win against an
    uncapped one (WR) just because the override tier's raw composite
    comparison doesn't otherwise know to skip it.
  - EARLY-ROUND DISCOUNT (checked alongside REDUNDANCY, same exclusion
    tier): K and DST specifically get a squash before a configured round
    (config's estimation_assumptions.position_early_round_discount), per
    league-manager feedback (2026-08-26) that these are "pretty much a
    dime a dozen, rarely worth taking before round 17." Originally a
    softer, squash-only adjustment that did NOT exclude from
    recommendation -- upgraded to a hard exclusion (like REDUNDANCY
    above) after a second Monte Carlo run caught the identical failure
    mode: K/DST still got recommended in rounds 11-15 once every other
    position's need was satisfied and its value had gone negative, for
    the same reason a flat squash wasn't enough for REDUNDANCY. You can
    still draft one manually any time, and the MANDATORY-DEADLINE-FILL
    check above guarantees the dedicated slot still gets force-filled
    before it's too late even with this exclusion in place. Expected to
    need reconciling once the league's real "2 kickers and 2 defenses
    must be picked prior to round 21" rule is confirmed and added to
    round_based_fill_targets; see _early_round_discount()'s docstring.

This module deliberately does NOT pick a player -- src/pick_suggestion.py
recommends a position and hands back that position's top-N available
players by VOR (top_available_players below); the Draft Board page lets
the league manager draft straight from that shortlist, browse the full
grid instead, or override the recommended position to see a different
one's shortlist -- all three explicitly requested.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

from src.draft_state import DraftState
from src.draft_tendencies import predict_position_counts
from src.roster_needs import (
    positions_that_would_fill,
    team_position_counts,
    unfilled_starter_slots,
)

# Composite weights -- documented, tunable constants in the same spirit as
# this app's other heuristic knobs (e.g. projections.py's flex_position_splits,
# tiering.py's max_spread_fraction). Value is weighted highest because
# points ultimately win leagues; need keeps roster construction from being
# ignored in favor of pure best-player-available; scarcity is the smallest
# weight because it's a tie-breaking urgency signal, not a primary driver
# -- a position with mediocre value and no roster need shouldn't jump the
# queue just because a run is predicted.
VALUE_WEIGHT = 0.45
NEED_WEIGHT = 0.30
SCARCITY_WEIGHT = 0.25


# Squash factor applied to a position's composite once MY drafted count
# there has already reached config's roster.position_active_limits max
# (see _redundancy_penalty()'s docstring). Not zero: an utterly bare
# board (every position capped) should still be able to recommend
# SOMETHING rather than every position tying at exactly 0.
REDUNDANCY_PENALTY = 0.05

# Positions whose config roster.position_active_limits entry maps to a
# single, unambiguous skill position. WR is deliberately excluded: CBS's
# rules-page table (and this config) only reports a combined "WR_TE" max,
# and splitting that back into a per-position WR cap would mean guessing
# at an interpretation nobody has confirmed -- same spirit as the
# TE-legality ambiguity documented in league_settings.yaml's
# roster.validation section. Flag to revisit if WR redundancy ever looks
# like a real problem in simulation.
_CAPPABLE_POSITIONS = {"QB", "RB", "TE", "K", "DST"}


@dataclass
class PositionScore:
    position: str
    composite: float
    value_raw: float           # best available player's VOR at this position
    need_raw: float            # unfilled-starter-slot demand weight, from MY roster
    predicted_picks: float     # expected # of this position drafted (by anyone) before my next turn
    remaining_top_tier: int    # players still available in tier 1 at this position
    remaining_players: int     # total players still available at this position
    scarcity_ratio: float      # predicted_picks / max(1, remaining_top_tier)
    top_vor_rank: Optional[int] = None
    at_position_cap: bool = False  # my drafted count already meets/exceeds the configured active-roster max
    early_round_discounted: bool = False  # K/DST early-round discount applied (squashed + excluded unless nothing else is available)
    mandatory_fill: bool = False  # I'm about to run out of picks to ever fill this dedicated slot
    quota_deadline: bool = False  # I'm about to run out of picks to hit a configured round_based_fill_target


@dataclass
class PickSuggestion:
    recommended_position: Optional[str]
    all_scores: list[PositionScore] = field(default_factory=list)
    reasoning: str = ""
    picks_before_my_next_turn: int = 0


def picks_before_my_next_turn(draft_state: DraftState) -> int:
    """How many picks (by any team) happen strictly between right now and
    the next time my_team is on the clock. If it's my_team's pick right
    now, this looks PAST the current pick to the following turn -- what
    matters for "should I grab this position now, or will it still be
    here" is whether it survives until I pick AGAIN, not whether it
    survives until right now (trivially true; I'm picking right now)."""
    if draft_state.is_draft_complete:
        return 0
    start = draft_state.next_overall_pick
    if draft_state.team_for_pick(start) == draft_state.my_team:
        start += 1
    count = 0
    for p in range(start, draft_state.total_picks + 1):
        if draft_state.team_for_pick(p) == draft_state.my_team:
            return count
        count += 1
    return count  # draft ends before I'm on the clock again (I had the last pick)


def _remaining_my_picks(draft_state: DraftState) -> int:
    """How many more times my_team will be on the clock, counting right
    now if it's currently my pick, through the end of the draft. Used to
    detect "I'm about to run out of chances to ever fill this slot" --
    see _mandatory_deadline_positions()."""
    if draft_state.is_draft_complete:
        return 0
    count = 0
    for p in range(draft_state.next_overall_pick, draft_state.total_picks + 1):
        if draft_state.team_for_pick(p) == draft_state.my_team:
            count += 1
    return count


def _mandatory_deadline_positions(draft_state: DraftState, config: dict) -> set[str]:
    """Positions with a dedicated, single-eligible-position starter slot
    (this league's QB/RB/TE/K/DST slots) that I still haven't fully
    filled, where I'm down to my last chance(s) to ever fill it before the
    draft ends.

    Added 2026-08-26 after a Monte Carlo simulation (see SESSION_NOTES)
    showed the value/need/scarcity composite alone -- even with the
    redundancy and early-round adjustments above -- can let a mandatory
    slot like the single dedicated QB slot go completely unfilled for an
    entire 22-round simulated draft, because a deep QB pool means QB's
    raw VOR never drops enough to win the composite against RB/WR. That
    scores zero for that slot every week for the whole season -- no
    amount of "better value elsewhere" earlier in the draft makes up for
    literally never drafting one. This is intentionally blunt: any
    position in the returned set is force-ranked above everything else
    in suggest_position(), regardless of value/need/scarcity, because by
    definition there's no more room to be clever about it.
    """
    starters = config["roster"]["starters"]
    my_counts = team_position_counts(draft_state.my_roster())
    remaining = _remaining_my_picks(draft_state)
    urgent: set[str] = set()
    for slot in starters:
        if len(slot["eligible"]) != 1:
            continue  # only unambiguous, single-position dedicated slots
        position = slot["eligible"][0]
        unfilled = max(0, slot["count"] - my_counts.get(position, 0))
        if unfilled > 0 and unfilled >= remaining:
            urgent.add(position)
    return urgent


def _remaining_my_picks_before_round(draft_state: DraftState, round_limit: int) -> int:
    """How many more times my_team will be on the clock at or before the
    end of `round_limit` (inclusive), counting right now if it's currently
    my pick. Like _remaining_my_picks() but bounded to a deadline round
    instead of the whole draft -- see _round_based_quota_positions()."""
    if draft_state.is_draft_complete:
        return 0
    count = 0
    for p in range(draft_state.next_overall_pick, draft_state.total_picks + 1):
        rnd, _ = draft_state.round_and_slot_for_pick(p)
        if rnd > round_limit:
            break  # picks are in increasing round order -- nothing further qualifies
        if draft_state.team_for_pick(p) == draft_state.my_team:
            count += 1
    return count


def _round_based_quota_positions(draft_state: DraftState, config: dict) -> set[str]:
    """Positions belonging to a configured "must have N by round R"
    requirement category (config's estimation_assumptions.
    round_based_fill_targets) where I'm down to my last chance(s) to hit
    it -- or to hit the GROUP of categories sharing that same deadline.

    Added 2026-08-26 per league-manager feedback: _mandatory_deadline_
    positions() above only forces a fill once I'm on my literal LAST pick
    of the entire draft -- correct for "never miss a legally required
    slot," but too permissive for a strategic target like "get 2 QBs in
    the first ~7 rounds or it's a disaster." Extended 2026-08-27 once the
    league manager uploaded the real "Maniac Football League Draft Sheet"
    requirements document: round_based_fill_targets is now a LIST of
    {slot, eligible, count, by_round} categories (the same shape as
    roster.starters, reused deliberately -- see below), because several
    real requirement categories share ONE eligible position across
    multiple entries (RB appears in both a dedicated 5-RB category and a
    1-slot "RB, WR, or TE" category) or share ONE deadline across many
    categories (7 of the 8 configured entries are all due by round 20).

    Two things a naive per-entry check would get wrong, both fixed here:

      1. DOUBLE-COUNTING a drafted player across overlapping categories.
         Fixed by reusing src.roster_needs.unfilled_starter_slots() --
         exactly the same greedy, most-restrictive-slot-first allocator
         used for roster.starters above, just pointed at this
         requirements list instead. A drafted TE is claimed by the
         single-eligible "TE (Mandatory)" category before the broader
         "WR/TE" category gets a chance at it, so still-needed counts
         reflect one real pool of drafted players, not eight independent
         re-countings of the same picks.

      2. UNDERSTATING urgency when several categories share one deadline.
         Checking each round-20 category's remaining need against my
         TOTAL remaining picks before round 20 independently can miss a
         combined shortfall -- e.g. needing K:2 + DEF:2 + RB:1 with
         exactly 5 picks left before round 20 looks fine for each
         category alone (each has slack against the full 5), even though
         the COMBINED need (5) already exhausts the combined remaining
         picks (5) and there's zero real slack left. Fixed by GROUPING
         unfilled categories by their shared `by_round` deadline and
         checking the group's TOTAL still-needed count against remaining
         picks before that shared deadline -- once a group is out of
         slack, every eligible position across the whole group is forced,
         not just whichever single category happens to look worst alone.

    A category's `count`/`eligible` need not match roster.starters' own
    dedicated slot for that position (e.g. QB's dedicated starter slot is
    1, but this list's QB category targets 2, for SUPERFLEX too) -- this
    deliberately does NOT reuse _mandatory_deadline_positions()'s
    starters-derived logic, and draws from a separate, independently
    configured list."""
    targets = config.get("estimation_assumptions", {}).get("round_based_fill_targets", [])
    if not targets:
        return set()
    my_counts = team_position_counts(draft_state.my_roster())
    current_round, _ = draft_state.round_and_slot_for_pick(draft_state.next_overall_pick)
    unfilled = unfilled_starter_slots(my_counts, targets)  # {slot_name: still_needed}
    if not unfilled:
        return set()
    by_slot_name = {t["slot"]: t for t in targets}

    # Group still-unfilled categories by shared, not-yet-passed deadline.
    groups: dict[int, list[str]] = {}
    for slot_name in unfilled:
        target = by_slot_name[slot_name]
        by_round = target.get("by_round")
        if by_round is None or current_round > by_round:
            continue  # deadline already passed -- nothing left to force here
        groups.setdefault(by_round, []).append(slot_name)

    urgent: set[str] = set()
    for by_round, slot_names in groups.items():
        group_still_needed = sum(unfilled[s] for s in slot_names)
        if _remaining_my_picks_before_round(draft_state, by_round) <= group_still_needed:
            for slot_name in slot_names:
                urgent.update(by_slot_name[slot_name]["eligible"])
    return urgent


def my_position_need(draft_state: DraftState, config: dict) -> dict[str, float]:
    """Unfilled-starter-slot demand for MY OWN roster, spread across each
    open slot's eligible positions -- the same heuristic
    src/roster_needs.py uses to infer opponents' needs, just pointed at
    my_team's own drafted picks instead. Flex slots (SUPERFLEX, FLEX,
    WR_TE_FLEX) are weighted by config's flex_position_splits rather than
    split evenly across eligible positions -- see
    positions_that_would_fill()'s docstring for why an even split badly
    understates a slot like SUPERFLEX's real QB need in this league.

    Also folds in a second, SOFT demand source (added 2026-08-27): unfilled
    categories from config's estimation_assumptions.round_based_fill_targets
    (this league's real by-round-20 draft requirements -- see
    _round_based_quota_positions()'s docstring for the full shape/rationale).
    That function only forces a pick once a deadline GROUP is truly out of
    slack; this lets an unfilled requirement category (say, still needing a
    2nd DEF) nudge the ongoing value/need/scarcity composite well before
    that hard deadline, the same way an unfilled roster.starters slot
    already does. Uses the same unfilled_starter_slots() allocator as
    roster.starters above so a drafted player isn't double-counted across
    overlapping categories (e.g. a drafted TE satisfies "TE (Mandatory)"
    before "WR/TE" gets a claim on it). Unlike roster.starters, no
    flex_splits weighting applies here -- these categories don't have a
    directly analogous "which position actually gets started" ambiguity
    the way SUPERFLEX does, so an even split across each category's
    eligible positions is used instead."""
    starters = config["roster"]["starters"]
    flex_splits = config.get("estimation_assumptions", {}).get("flex_position_splits", {})
    counts = team_position_counts(draft_state.my_roster())
    unfilled = unfilled_starter_slots(counts, starters)
    demand = positions_that_would_fill(unfilled, starters, flex_splits)

    targets = config.get("estimation_assumptions", {}).get("round_based_fill_targets", [])
    if targets:
        targets_unfilled = unfilled_starter_slots(counts, targets)
        demand.update(positions_that_would_fill(targets_unfilled, targets))
    return dict(demand)


def _normalize(raw: dict[str, float]) -> dict[str, float]:
    peak = max(raw.values()) if raw else 0.0
    if peak <= 0:
        return {k: 0.0 for k in raw}
    return {k: v / peak for k, v in raw.items()}


def _position_cap(position: str, config: dict) -> Optional[int]:
    """My active-roster max for `position`, from config's
    roster.position_active_limits, or None if this position isn't one of
    the ones we can safely cap (see _CAPPABLE_POSITIONS)."""
    if position not in _CAPPABLE_POSITIONS:
        return None
    limits = config.get("roster", {}).get("position_active_limits", {})
    entry = limits.get(position) or {}
    return entry.get("max")


def _redundancy_penalty(position: str, my_counts: dict[str, int], config: dict) -> tuple[float, bool]:
    """Squash multiplier for `position`'s composite, and whether it's
    currently at (or over) its configured active-roster cap.

    Once my own drafted count at a position already meets config's
    roster.position_active_limits max, its raw "value" signal can still
    look attractive for a shallow-pool position (K/DST/TE) whose best
    remaining VOR never craters the way a skill position's does past
    replacement level -- see this module's docstring and the 2026-08-26
    SESSION_NOTES Monte Carlo findings. REDUNDANCY_PENALTY squashes (never
    zeroes) the composite once at cap, so a board where every position is
    already capped can still recommend SOMETHING rather than a 6-way tie
    at exactly 0."""
    cap = _position_cap(position, config)
    if cap is None:
        return 1.0, False
    at_cap = my_counts.get(position, 0) >= cap
    return (REDUNDANCY_PENALTY, True) if at_cap else (1.0, False)


def _early_round_discount(position: str, current_round: int, config: dict) -> tuple[float, bool]:
    """Squash multiplier on K/DST's composite before a configured round,
    and whether it was applied.

    Per league-manager feedback (2026-08-26): "kickers and defenses are
    pretty much a dime a dozen, rarely worth taking before round 17."
    Config-driven (estimation_assumptions.position_early_round_discount in
    league_settings.yaml) rather than hardcoded. This function only
    returns the squash value + whether it applies; suggest_position()
    additionally treats "applied" as a hard exclusion from recommendation
    (same tier as REDUNDANCY -- see this module's docstring) as long as
    any not-discounted, not-capped position is still available, since a
    squash alone wasn't enough to reliably lose to a legitimately-worse
    (negative-value) alternative. Still just a recommendation nudge, not
    a block on manually drafting K/DST early by hand, and the league also
    has a real round-based fill requirement ("2 kickers and 2 defenses
    must be picked prior to round 21") that isn't confirmed/wired in yet
    (league manager still tracking down the exact source) -- once added
    to round_based_fill_targets, a looming deadline there will correctly
    override this exclusion via the MANDATORY-DEADLINE-FILL/QUOTA tier."""
    rule = config.get("estimation_assumptions", {}).get("position_early_round_discount", {}).get(position)
    if not rule:
        return 1.0, False
    before_round = rule.get("before_round")
    if before_round is not None and current_round < before_round:
        return float(rule.get("multiplier", 1.0)), True
    return 1.0, False


def suggest_position(
    available: pd.DataFrame,
    draft_state: DraftState,
    config: dict,
    history: Optional[pd.DataFrame] = None,
    years: Optional[list[int]] = None,
    value_weight: Optional[float] = None,
    need_weight: Optional[float] = None,
    scarcity_weight: Optional[float] = None,
) -> PickSuggestion:
    """Recommend the position to draft next, plus a full breakdown of
    every other position considered (so the Draft Board can show "why").

    `available` must already be scored/ranked/tiered (the output of
    build_draft_board() + compute_tiers() with whatever tier-gap setting
    the page is currently using -- this module reads "tier" and "vor"
    straight off it rather than recomputing anything, so the suggestion
    always matches what's on screen). `history` is draft_history.csv's
    loaded DataFrame (src.data_sources.draft_history.load_draft_history);
    pass None or an empty frame to skip the scarcity signal entirely
    (falls back to value+need only -- still a fine recommendation, just
    without run-risk awareness).

    `value_weight`/`need_weight`/`scarcity_weight` override this module's
    VALUE_WEIGHT/NEED_WEIGHT/SCARCITY_WEIGHT constants for this call only,
    when given (all three, or none -- partial overrides aren't validated
    against summing to 1). Added 2026-08-26 so the Monte Carlo simulation
    harness (see SESSION_NOTES) can A/B different weightings against the
    same draft/opponent conditions without needing a code change per
    variant tried; the Draft Board itself always calls this with the
    defaults.
    """
    if draft_state.is_draft_complete:
        return PickSuggestion(recommended_position=None, reasoning="Draft complete.")
    if available.empty:
        return PickSuggestion(recommended_position=None, reasoning="No players available.")

    horizon = picks_before_my_next_turn(draft_state)
    need = my_position_need(draft_state, config)

    # Zero out need for a position I've already drafted up to its
    # configured active-roster cap -- otherwise a flex slot that's still
    # technically eligible for that position (e.g. WR_TE_FLEX for TE, FLEX
    # for K) keeps feeding it a real, nonzero "need" weight forever, even
    # though drafting another would be illegal/pointless. See
    # _redundancy_penalty()'s docstring for the fuller story; this handles
    # the NEED side, the redundancy penalty below handles the VALUE side.
    my_counts = team_position_counts(draft_state.my_roster())
    for position in list(need.keys()):
        cap = _position_cap(position, config)
        if cap is not None and my_counts.get(position, 0) >= cap:
            need[position] = 0.0

    predicted: pd.Series = pd.Series(dtype=float)
    if history is not None and not history.empty:
        window_start = draft_state.next_overall_pick
        if draft_state.team_for_pick(window_start) == draft_state.my_team:
            window_start += 1
        predicted = predict_position_counts(history, years, window_start, horizon)

    value_raw: dict[str, float] = {}
    scores: dict[str, PositionScore] = {}
    for position, group in available.groupby("position"):
        if group.empty:
            continue
        best = group.sort_values("vor", ascending=False).iloc[0]
        remaining_top_tier = int((group["tier"] == 1).sum())
        pred = float(predicted.get(position, 0.0))
        scarcity_ratio = pred / max(1, remaining_top_tier)
        value_raw[position] = float(best["vor"])
        scores[position] = PositionScore(
            position=position,
            composite=0.0,  # filled in below, once normalized
            value_raw=float(best["vor"]),
            need_raw=need.get(position, 0.0),
            predicted_picks=pred,
            remaining_top_tier=remaining_top_tier,
            remaining_players=len(group),
            scarcity_ratio=scarcity_ratio,
            top_vor_rank=int(best["vor_rank"]) if "vor_rank" in best else None,
        )

    if not scores:
        return PickSuggestion(recommended_position=None, reasoning="No players available.")

    value_norm = _normalize({p: s.value_raw for p, s in scores.items()})
    need_norm = _normalize({p: s.need_raw for p, s in scores.items()})
    scarcity_norm = _normalize({p: s.scarcity_ratio for p, s in scores.items()})

    current_round, _ = draft_state.round_and_slot_for_pick(draft_state.next_overall_pick)
    w_value = VALUE_WEIGHT if value_weight is None else value_weight
    w_need = NEED_WEIGHT if need_weight is None else need_weight
    w_scarcity = SCARCITY_WEIGHT if scarcity_weight is None else scarcity_weight

    for position, s in scores.items():
        s.composite = (
            w_value * value_norm[position]
            + w_need * need_norm[position]
            + w_scarcity * scarcity_norm[position]
        )
        redundancy_mult, at_cap = _redundancy_penalty(position, my_counts, config)
        discount_mult, discounted = _early_round_discount(position, current_round, config)
        s.at_position_cap = at_cap
        s.early_round_discounted = discounted
        s.composite *= redundancy_mult * discount_mult

    mandatory = _mandatory_deadline_positions(draft_state, config)
    quota_deadline = _round_based_quota_positions(draft_state, config)
    for position, s in scores.items():
        s.mandatory_fill = position in mandatory
        s.quota_deadline = position in quota_deadline

    ranked = sorted(scores.values(), key=lambda s: s.composite, reverse=True)
    # A mandatory-deadline or quota-deadline position (see
    # _mandatory_deadline_positions()/_round_based_quota_positions())
    # overrides everything else, including the redundancy cap below --
    # I'm out of chances to ever satisfy it otherwise. Checked first.
    must_fill = [s for s in ranked if s.mandatory_fill or s.quota_deadline]
    if must_fill:
        # Still prefer a not-at-cap option WITHIN the must-fill set when
        # one exists (added 2026-08-27 after a Monte Carlo run caught
        # Monster Cheese drafting up to 6 TEs in a single simulated draft,
        # well past the configured position_active_limits max of 2). Most
        # of this league's real by-round-20 requirement categories share
        # ONE deadline (round 20), so an unfilled WR_TE_REQUIREMENT
        # (eligible WR or TE) gets grouped with several others into one
        # big urgent bucket, and this branch used to just take the single
        # highest-composite position across that WHOLE bucket with no cap
        # check at all -- unlike the ordinary (non-must-fill) path below,
        # which already excludes at-cap positions first. Once TE hit its
        # cap, its composite gets squashed by REDUNDANCY_PENALTY (0.05x)
        # same as always, but a shallow position's VOR can still stay
        # mildly positive long after WR's has cratered well past
        # replacement level in the late rounds this quota tends to fire
        # in -- so 0.05 x (small positive TE composite) kept beating a
        # deeply negative WR composite even though WR was the intended way
        # to satisfy that same requirement category. Falls back to the
        # full must_fill list (capped position and all) only if EVERY
        # urgent position is at cap -- e.g. a single-eligible mandatory
        # slot (TE_MANDATORY) that's somehow still unfilled despite TE
        # being at cap, which the requirement itself doesn't allow us to
        # skip.
        #
        # Deliberately does NOT also exclude early_round_discounted here,
        # unlike the ordinary path below -- tried that first, and a
        # same-seed Monte Carlo A/B (see SESSION_NOTES) showed it makes
        # things worse (avg league rank 1.28 -> 2.12 of 10, worst-case
        # rank 4 -> 7): K/DST's early-round discount is a pure TIMING
        # preference ("not ideal yet, but still full value"), unlike the
        # redundancy cap's "this many more contribute ~nothing" -- once a
        # shared round-20 deadline group is genuinely out of slack, it's
        # correct to grab a merely-early K/DST now rather than force a
        # worse-value alternative from elsewhere in the same group just to
        # respect a soft timing preference that was never a hard "don't."
        clean_must_fill = [s for s in must_fill if not s.at_position_cap]
        top = clean_must_fill[0] if clean_must_fill else must_fill[0]
    else:
        # Neither an at-cap position NOR an early-round-discounted one
        # outranks a "clean" alternative, no matter how the squashed
        # composite compares numerically -- a squash alone doesn't
        # reliably win that comparison, since a shallow-pool position's
        # VOR can stay positive long after a skill position's has gone
        # deeply negative past replacement level (this is what the
        # 2026-08-26 Monte Carlo run caught for the redundancy case, and a
        # second run caught the identical failure mode for the early
        # -round discount: K/DST kept getting recommended in rounds
        # 11-15, well before the configured round-17 cutoff, once every
        # other position's need was satisfied and its value had gone
        # negative -- the discount narrowed the gap but a positive
        # (if discounted) K/DST composite still beat a negative one).
        # Real fantasy strategy backs this up too: an early "dead zone"
        # pick is generally better spent on bench/handcuff depth than on
        # a K/DST you'll need anyway later. Only fall back to a
        # capped/discounted position when literally nothing else is
        # available -- see REDUNDANCY_PENALTY's and
        # _early_round_discount()'s docstrings for why that fallback
        # still returns something nonzero.
        clean = [s for s in ranked if not s.at_position_cap and not s.early_round_discounted]
        top = clean[0] if clean else ranked[0]
    reasoning = _describe(top, horizon)

    return PickSuggestion(
        recommended_position=top.position,
        all_scores=ranked,
        reasoning=reasoning,
        picks_before_my_next_turn=horizon,
    )


def _describe(top: PositionScore, horizon: int) -> str:
    reasons = []
    if top.mandatory_fill:
        reasons.append(
            "you're out of picks left to ever fill this starter slot otherwise — "
            "this overrides value/need/scarcity entirely"
        )
    if top.quota_deadline:
        reasons.append(
            "you're about to run out of chances to hit your configured round-based "
            "target for this position — this overrides value/need/scarcity entirely"
        )
    if top.at_position_cap:
        reasons.append(
            "already at your configured active-roster max for this position — "
            "still recommended because nothing else scored higher right now"
        )
    if top.early_round_discounted:
        reasons.append(
            "usually not worth taking this early, but nothing else scored higher right now"
        )
    if top.need_raw > 0:
        reasons.append(f"fills an open starter slot (need weight {top.need_raw:.1f})")
    if top.value_raw > 0:
        rank_part = f" (VOR rank #{top.top_vor_rank})" if top.top_vor_rank else ""
        reasons.append(f"has the best remaining value here{rank_part}")
    if top.predicted_picks >= 0.5 and top.remaining_top_tier > 0:
        reasons.append(
            f"history predicts ~{top.predicted_picks:.1f} {top.position}(s) drafted "
            f"in the next {horizon} pick(s) before your turn, against only "
            f"{top.remaining_top_tier} tier-1 {top.position}(s) left"
        )
    if not reasons:
        reasons.append("it's the best composite of value, need, and scarcity right now")
    return f"Recommended: {top.position} — " + "; ".join(reasons) + "."


def top_available_players(available: pd.DataFrame, position: str, n: int = 3) -> pd.DataFrame:
    """Top-N available players at `position`, best value (lowest/best
    vor_rank) first. Returns an empty frame (not an error) if the
    position has no players left or isn't present at all."""
    if available.empty or "position" not in available.columns:
        return available.iloc[0:0]
    pool = available[available["position"] == position]
    if pool.empty:
        return pool
    return pool.sort_values("vor", ascending=False).head(n)
