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
    k: float = 1.0,
) -> pd.DataFrame:
    """Group players within each position into tiers -- clusters of
    roughly-equivalent value separated by a meaningful point drop-off, the
    way draft analysts talk about "tier 1 RBs" vs "tier 2 RBs."

    Adds two columns:
      - tier: 1-indexed rank of the tier within that position (1 = best).
      - tier_gap: the point drop from the previous-ranked player at the
        same position that triggered a new tier (0.0 for a player who
        isn't a tier boundary, including every position's #1 player).

    Two ways to pick where a tier boundary falls:
      - gap_threshold (points, e.g. 10.0): manual override -- start a new
        tier whenever the drop to the next player exceeds this many
        points. This is the "all players in a tier are within N points"
        mode a user can dial in directly.
      - gap_threshold=None (default): automatic "natural break" detection.
        For each position, computes the point-drop between every pair of
        consecutive players (sorted by metric, descending) and flags a
        drop as a tier boundary when it's a statistical outlier relative
        to that position's other drops: drop > mean(drops) + k*std(drops).
        This adapts to each position's own scoring scale automatically
        (kickers cluster far tighter than QBs in this league) rather than
        using one fixed point value across every position.

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
    if out.empty:
        return out

    for _pos, group in out.groupby("position"):
        idx = group.sort_values(metric, ascending=False).index
        scores = out.loc[idx, metric].to_numpy(dtype=float)
        n = len(scores)
        if n <= 1:
            continue

        drops = -np.diff(scores)  # drops[i] = scores[i] - scores[i+1], i.e. the gap AFTER player i
        if gap_threshold is not None:
            threshold = gap_threshold
        else:
            mean_drop = drops.mean()
            std_drop = drops.std(ddof=0)
            # A tiny epsilon keeps a perfectly uniform ladder of drops (std=0)
            # from flagging every single gap as "significant" -- with no
            # variance at all there's no natural break to find, so treat the
            # whole position as one tier rather than n singleton tiers.
            threshold = mean_drop + k * std_drop + 1e-9

        tiers = np.ones(n, dtype=int)
        gaps = np.zeros(n, dtype=float)
        tier_num = 1
        for i in range(1, n):
            gap = scores[i - 1] - scores[i]
            if gap > threshold:
                tier_num += 1
                gaps[i] = gap
            tiers[i] = tier_num
        out.loc[idx, "tier"] = tiers
        out.loc[idx, "tier_gap"] = gaps

    return out
