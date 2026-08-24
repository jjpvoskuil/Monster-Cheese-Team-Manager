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
