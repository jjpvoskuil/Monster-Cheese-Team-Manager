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
against that first attempt is what caught it. Three adjustments now
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
  - REDUNDANCY (checked second): once my own drafted count at a position
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
    something.
  - EARLY-ROUND DISCOUNT (a softer, independent squash): K and DST
    specifically get a multiplier-only squash before a configured round
    (config's estimation_assumptions.position_early_round_discount), per
    league-manager feedback (2026-08-26) that these are "pretty much a
    dime a dozen, rarely worth taking before round 17." Deliberately NOT
    a hard exclusion like the redundancy cap above -- you can still draft
    one manually any time, and it's expected to need reconciling once the
    league's round-based fill requirement ("2 kickers and 2 defenses must
    be picked prior to round 21") is confirmed and wired in; see
    _early_round_discount()'s docstring.

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
    early_round_discounted: bool = False  # K/DST early-round soft discount was applied
    mandatory_fill: bool = False  # I'm about to run out of picks to ever fill this dedicated slot


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


def my_position_need(draft_state: DraftState, config: dict) -> dict[str, float]:
    """Unfilled-starter-slot demand for MY OWN roster, spread across each
    open slot's eligible positions -- the same heuristic
    src/roster_needs.py uses to infer opponents' needs, just pointed at
    my_team's own drafted picks instead. Flex slots (SUPERFLEX, FLEX,
    WR_TE_FLEX) are weighted by config's flex_position_splits rather than
    split evenly across eligible positions -- see
    positions_that_would_fill()'s docstring for why an even split badly
    understates a slot like SUPERFLEX's real QB need in this league."""
    starters = config["roster"]["starters"]
    flex_splits = config.get("estimation_assumptions", {}).get("flex_position_splits", {})
    counts = team_position_counts(draft_state.my_roster())
    unfilled = unfilled_starter_slots(counts, starters)
    return dict(positions_that_would_fill(unfilled, starters, flex_splits))


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
    """Soft squash multiplier on K/DST's composite before a configured
    round, and whether it was applied.

    Per league-manager feedback (2026-08-26): "kickers and defenses are
    pretty much a dime a dozen, rarely worth taking before round 17."
    Config-driven (estimation_assumptions.position_early_round_discount in
    league_settings.yaml) rather than hardcoded, and deliberately a SOFT
    multiplier rather than a hard block -- the league also has a
    round-based fill requirement ("2 kickers and 2 defenses must be
    picked prior to round 21") that isn't confirmed/wired in yet (league
    manager is still tracking down the exact source). Once that lands, a
    looming deadline should be able to override this discount; until
    then, this only softens the recommendation, it doesn't forbid
    drafting K/DST early by hand."""
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

    for position, s in scores.items():
        s.composite = (
            VALUE_WEIGHT * value_norm[position]
            + NEED_WEIGHT * need_norm[position]
            + SCARCITY_WEIGHT * scarcity_norm[position]
        )
        redundancy_mult, at_cap = _redundancy_penalty(position, my_counts, config)
        discount_mult, discounted = _early_round_discount(position, current_round, config)
        s.at_position_cap = at_cap
        s.early_round_discounted = discounted
        s.composite *= redundancy_mult * discount_mult

    mandatory = _mandatory_deadline_positions(draft_state, config)
    for position, s in scores.items():
        s.mandatory_fill = position in mandatory

    ranked = sorted(scores.values(), key=lambda s: s.composite, reverse=True)
    # A mandatory-deadline position (see _mandatory_deadline_positions)
    # overrides everything else, including the redundancy cap below --
    # I'm out of chances to ever fill it otherwise. Checked first.
    must_fill = [s for s in ranked if s.mandatory_fill]
    if must_fill:
        top = must_fill[0]
    else:
        # A capped position never outranks a legal (not-at-cap) one, no
        # matter how its squashed composite compares numerically --
        # multiplying by REDUNDANCY_PENALTY narrows the gap but a
        # shallow-pool position's VOR can stay positive long after a
        # skill position's has gone deeply negative past replacement
        # level, so a squash alone doesn't reliably win the comparison
        # (this is what the 2026-08-26 Monte Carlo run caught: K/DST/TE
        # still got recommended most of the time even with the squash in
        # place). Only fall back to an at-cap position when literally
        # nothing else is available -- see REDUNDANCY_PENALTY's docstring
        # for why that fallback still returns something nonzero.
        not_at_cap = [s for s in ranked if not s.at_position_cap]
        top = not_at_cap[0] if not_at_cap else ranked[0]
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
