"""
Score every player in a SINGLE named season-projection source
(data/projections/{source}_2026.csv) under this league's real scoring
rules -- shared by pages/9_Waiver_Wire.py and pages/10_Trade_Finder.py,
both of which need to compare what CBS specifically projects against
what FantasyPoints specifically projects, not this app's own blended
multi-source view (src.projections.build_draft_board blends several
sources together, which is exactly what these two pages must NOT do --
the whole point is showing where the two named sources disagree).

Reuses src.projections.score_and_rank (the same scoring + VOR/
position_rank pipeline build_draft_board calls after blending) rather
than hand-rolling a second scoring path -- passing it a single-source
df instead of a blended one works unchanged, since score_and_rank only
ever looks at "games", "position", and the canonical stat columns.

NaN-SAFETY (bug found 2026-09-09 building the Waiver Wire page):
src.data_sources.manual_import.load_table() only fills a canonical stat
column that's entirely ABSENT from the source file with 0 -- an
individual blank CELL within a present column (e.g. a TE's pass_yards
cell) stays NaN. src.projections.blend_projections() has its own
explicit NaN-safe weighted-average logic for the multi-source path (see
its long 2026-09-02 comment), but a single-source path never gets that
guard -- confirmed live: scoring a player with even one blank stat cell
directly produced a "nan" point total. Fixed here with an explicit
fillna(0) on stat columns (and a games_per_season fallback for a blank
games cell) before scoring, once, so every caller of this module gets
it for free instead of re-discovering the same bug.
"""

from __future__ import annotations

import pandas as pd

from src.data_sources.manual_import import CANONICAL_COLUMNS, load_table
from src.projections import _normalize_dst_names, score_and_rank

_STAT_COLUMNS = [c for c in CANONICAL_COLUMNS if c not in ("name", "position", "nfl_team", "games")]


def load_scored_season_source(path: str, source: str, config: dict) -> pd.DataFrame:
    """Every player in `path` (a single projection source's season CSV),
    scored and ranked under this league's rules. Returns score_and_rank's
    full output -- name, position, nfl_team, games, every raw stat
    column, score_total, score_<component>..., overall_rank,
    position_rank, replacement_score, vor, position_demand, vor_rank.
    `vor` (value over this league's real per-position replacement level,
    already accounting for flex-slot demand splits -- see
    src.projections.compute_position_demand) is the metric both the
    Waiver Wire and Trade Finder pages actually rank players by, not raw
    score_total -- same "true value" framework this app already uses
    for the Draft Board and Suggested Pick, rather than a second,
    inconsistent notion of value invented just for these pages."""
    df = load_table(path, source)
    df = _normalize_dst_names(df)
    df = df.copy()
    df[_STAT_COLUMNS] = df[_STAT_COLUMNS].fillna(0)
    df["games"] = df["games"].fillna(config.get("estimation_assumptions", {}).get("games_per_season", 17))
    return score_and_rank(df, config)
