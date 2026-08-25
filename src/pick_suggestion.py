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
     drafted picks instead of an opponent's.
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


def my_position_need(draft_state: DraftState, config: dict) -> dict[str, float]:
    """Unfilled-starter-slot demand for MY OWN roster, spread across each
    open slot's eligible positions -- the same heuristic
    src/roster_needs.py uses to infer opponents' needs, just pointed at
    my_team's own drafted picks instead."""
    starters = config["roster"]["starters"]
    counts = team_position_counts(draft_state.my_roster())
    unfilled = unfilled_starter_slots(counts, starters)
    return dict(positions_that_would_fill(unfilled, starters))


def _normalize(raw: dict[str, float]) -> dict[str, float]:
    peak = max(raw.values()) if raw else 0.0
    if peak <= 0:
        return {k: 0.0 for k in raw}
    return {k: v / peak for k, v in raw.items()}


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

    for position, s in scores.items():
        s.composite = (
            VALUE_WEIGHT * value_norm[position]
            + NEED_WEIGHT * need_norm[position]
            + SCARCITY_WEIGHT * scarcity_norm[position]
        )

    ranked = sorted(scores.values(), key=lambda s: s.composite, reverse=True)
    top = ranked[0]
    reasoning = _describe(top, horizon)

    return PickSuggestion(
        recommended_position=top.position,
        all_scores=ranked,
        reasoning=reasoning,
        picks_before_my_next_turn=horizon,
    )


def _describe(top: PositionScore, horizon: int) -> str:
    reasons = []
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
