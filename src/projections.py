"""
Blend multiple projection sources into per-player season projections, score
them with src/scoring.py against our real league rules, and rank overall
and by position — including a value-over-replacement (VOR) ranking that
accounts for this league's superflex and RB/WR/TE/K flex slots.

VOR NOTE: "replacement level" for a position depends on how many players at
that position the league will actually need to start, which depends on how
managers split multi-eligible slots (superflex, flex) across positions.
There's no way to know that in advance, so this uses a documented, tunable
assumption (config estimation_assumptions.flex_position_splits) rather than
assuming e.g. "1 QB per team" and ignoring superflex demand — that would
badly overstate late-round QB value in exactly the way a naive ranking
tool gets wrong for superflex leagues.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from .data_sources.manual_import import CANONICAL_COLUMNS
from .scoring import ScoringEngine
from .tiering import jenks_auto_labels

_STAT_COLUMNS = [c for c in CANONICAL_COLUMNS if c not in ("name", "position", "nfl_team", "games")]


def blend_projections(df: pd.DataFrame, source_weights: Optional[dict[str, float]] = None) -> pd.DataFrame:
    """Collapse multiple source rows per player (joined on name_key +
    position) into one blended row via weighted average. Players who only
    appear in one source are kept as-is (weight of 1 for whatever source
    they have)."""
    if df.empty:
        return df

    weights = source_weights or {}
    df = df.copy()
    df["_weight"] = df["source"].map(lambda s: weights.get(s, 1.0))

    def _agg(group: pd.DataFrame) -> pd.Series:
        w = group["_weight"]
        total_w = w.sum() or 1.0
        out = {}
        for col in _STAT_COLUMNS + ["games"]:
            out[col] = (group[col] * w).sum() / total_w
        # keep the most common display name / nfl_team across sources
        out["name"] = group["name"].mode().iat[0] if not group["name"].mode().empty else group["name"].iat[0]
        out["nfl_team"] = (
            group["nfl_team"].mode().iat[0] if not group["nfl_team"].mode().empty else group["nfl_team"].iat[0]
        )
        out["sources"] = ",".join(sorted(group["source"].unique()))
        out["num_sources"] = group["source"].nunique()
        return pd.Series(out)

    blended = df.groupby(["name_key", "position"], as_index=False).apply(_agg, include_groups=False)
    blended = blended.reset_index(drop=True)
    return blended


def compute_position_demand(config: dict) -> dict[str, float]:
    """League-wide count of starters expected to be needed per position,
    splitting multi-eligible slots per config.estimation_assumptions.flex_position_splits."""
    teams = config["league"]["teams"]
    starters = config["roster"]["starters"]
    splits = config.get("estimation_assumptions", {}).get("flex_position_splits", {})

    demand: dict[str, float] = {}
    for slot in starters:
        name, count, eligible = slot["slot"], slot["count"], slot["eligible"]
        if len(eligible) == 1:
            pos = eligible[0]
            demand[pos] = demand.get(pos, 0) + teams * count
        else:
            split = splits.get(name) or {p: 1 / len(eligible) for p in eligible}
            for pos, frac in split.items():
                demand[pos] = demand.get(pos, 0) + teams * count * frac
    return demand


def score_and_rank(blended: pd.DataFrame, config: dict) -> pd.DataFrame:
    """Score every player, rank overall and by position, and compute VOR."""
    if blended.empty:
        return blended

    engine = ScoringEngine(config)
    scores = blended.apply(lambda row: engine.score_player_season(row.to_dict(), games=row["games"]), axis=1)
    out = blended.copy()
    out["score_total"] = scores.map(lambda bd: bd.total)
    for component in ("passing", "rushing", "receiving", "kicking", "fumbles",
                       "individual_special_teams", "defense"):
        out[f"score_{component}"] = scores.map(lambda bd, c=component: getattr(bd, c))

    out = out.sort_values("score_total", ascending=False).reset_index(drop=True)
    out["overall_rank"] = out.index + 1
    out["position_rank"] = out.groupby("position")["score_total"].rank(ascending=False, method="first").astype(int)

    demand = compute_position_demand(config)
    replacement_score: dict[str, float] = {}
    for pos, dem in demand.items():
        pos_players = out[out["position"] == pos].sort_values("score_total", ascending=False)
        rep_rank = max(1, round(dem))
        if len(pos_players) >= rep_rank:
            replacement_score[pos] = pos_players.iloc[rep_rank - 1]["score_total"]
        elif len(pos_players) > 0:
            replacement_score[pos] = pos_players.iloc[-1]["score_total"]
        else:
            replacement_score[pos] = 0.0

    out["replacement_score"] = out["position"].map(lambda p: replacement_score.get(p, 0.0))
    out["vor"] = out["score_total"] - out["replacement_score"]
    out["position_demand"] = out["position"].map(lambda p: round(demand.get(p, 0), 1))

    out = out.sort_values("vor", ascending=False).reset_index(drop=True)
    out["vor_rank"] = out.index + 1

    return out


def build_draft_board(df: pd.DataFrame, config: dict, source_weights: Optional[dict[str, float]] = None) -> pd.DataFrame:
    """End-to-end: raw multi-source projections -> blended -> scored -> ranked."""
    blended = blend_projections(df, source_weights)
    return score_and_rank(blended, config)


def compute_tiers(
    board: pd.DataFrame,
    metric: str = "score_total",
    gap_threshold: Optional[float] = None,
    max_tiers: int = 15,
    max_spread_fraction: float = 0.08,
) -> pd.DataFrame:
    """Group players within each position into tiers -- clusters of
    roughly-equivalent value separated by a meaningful point drop-off, the
    way draft analysts talk about "tier 1 RBs" vs "tier 2 RBs."

    Adds three columns:
      - tier: 1-indexed rank of the tier within that position (1 = best).
      - tier_gap: the point drop from the immediately preceding player at
        the same position (0.0 for a player who isn't a tier boundary,
        including every position's #1 player) -- shown for context; in
        manual mode this can be smaller than gap_threshold itself, see
        below.
      - tier_max_spread: the point range (top player's score minus bottom
        player's score) within that player's own tier. Manual mode
        guarantees this never exceeds gap_threshold; automatic mode has no
        such guarantee (it's optimizing overall variance, not a single
        tier's width) but it's included so you can see it either way.

    Two ways to pick where a tier boundary falls:
      - gap_threshold (points, e.g. 10.0): manual override. A tier holds
        every player within `gap_threshold` points of THAT TIER'S TOP
        SCORER -- not just within gap_threshold of the previous player.
        (An earlier version only checked the previous player, which let a
        chain of small sub-threshold gaps drift a tier arbitrarily wide --
        e.g. ten consecutive 3-point gaps summing to 30 points, none of
        which individually exceeded a 10-point threshold. Comparing every
        candidate against the tier's leading player instead of its
        immediate neighbor is what actually enforces "every player in a
        tier is within N points of each other.") A new tier starts the
        moment a player would fall more than gap_threshold points below
        their tier's leader.
      - gap_threshold=None (default): automatic "natural break" detection
        via Jenks natural breaks (see src/tiering.py) -- finds the
        partition into k classes that minimizes within-class variance,
        growing k only as far as needed so that no single tier spans more
        than max_spread_fraction of that position's own top-to-bottom
        point range (default 8%), capped at max_tiers classes. This
        adapts to each position's own scoring scale automatically (kickers
        cluster far tighter than QBs) and directly bounds tier width
        instead of inferring it indirectly from gap statistics -- see
        src/tiering.py's module docstring for why two earlier gap-based
        designs (a global mean+stdev threshold, then a local
        recursive-outlier variant) each looked reasonable but still
        produced too-wide tiers for a large, gradually-declining position
        pool like QB.

    metric defaults to "score_total" (raw projected points) rather than
    "vor". Within a single position these produce identical tier
    boundaries -- vor is just score_total minus that position's constant
    replacement_score -- but score_total is the more intuitive "points"
    number to reason about tier gaps in.

    Positions with 0-1 players are left as a single tier (nothing to
    compare). Requires board to already have a "position" column and the
    chosen metric column, e.g. the output of build_draft_board()/
    score_and_rank().
    """
    out = board.copy()
    out["tier"] = 1
    out["tier_gap"] = 0.0
    out["tier_max_spread"] = 0.0
    if out.empty:
        return out

    for _pos, group in out.groupby("position"):
        idx = group.sort_values(metric, ascending=False).index
        scores = out.loc[idx, metric].to_numpy(dtype=float)
        n = len(scores)
        if n <= 1:
            continue

        if gap_threshold is not None:
            tiers = np.ones(n, dtype=int)
            gaps = np.zeros(n, dtype=float)
            tier_num = 1
            anchor = scores[0]  # top scorer of the current tier
            for i in range(1, n):
                if anchor - scores[i] > gap_threshold:
                    tier_num += 1
                    anchor = scores[i]
                    gaps[i] = scores[i - 1] - scores[i]
                tiers[i] = tier_num
        else:
            # Jenks operates ascending; scores here are sorted descending
            # (best first), so reverse for the fit and invert the labels
            # back so tier 1 = highest scores.
            labels_desc, _k, _widest = jenks_auto_labels(
                scores[::-1], max_classes=max_tiers, max_spread_fraction=max_spread_fraction,
            )
            labels = labels_desc[::-1]
            chosen_max = labels.max()
            tiers = (chosen_max - labels + 1).astype(int)
            gaps = np.zeros(n, dtype=float)
            for i in range(1, n):
                if tiers[i] != tiers[i - 1]:
                    gaps[i] = scores[i - 1] - scores[i]

        spreads = np.zeros(n, dtype=float)
        for tier_val in np.unique(tiers):
            mask = tiers == tier_val
            tier_scores = scores[mask]
            spreads[mask] = tier_scores.max() - tier_scores.min()

        out.loc[idx, "tier"] = tiers
        out.loc[idx, "tier_gap"] = gaps
        out.loc[idx, "tier_max_spread"] = spreads

    return out
