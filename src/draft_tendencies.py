"""
Historical positional draft tendencies, computed from
data/draft_history/draft_history.csv (built by scripts/fetch_draft_history.py
from src/data_sources/draft_history.py).

The core question this module answers, per the league manager's request:
"the number of players per position per draft round is somewhat
consistent... I'd like to predict what will happen in the next round or
two by position, to know if I need to draft a position now or can likely
wait a round or two." It mirrors (and automates) the manual "Alt Targets"
sheet in TARGETS 2025.xlsx, which tracked cumulative position counts by
overall pick number for a few recent years side by side.

All functions take a `years` argument (an iterable of season years to
include) so the UI can offer "average all 4 years" (years=None, meaning
every year present in the data) or "just 2024 and 2025" etc.

Skipped picks (src/data_sources/draft_history.py's is_skipped) and picks
with an unrecognized position are excluded from every count here -- they
carry no positional information.
"""

from __future__ import annotations

import pandas as pd

KNOWN_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DST")


def _valid_picks(df: pd.DataFrame, years: list[int] | None = None) -> pd.DataFrame:
    out = df[~df["is_skipped"].astype(bool) & df["position"].notna()].copy()
    if years is not None:
        out = out[out["year"].isin(years)]
    return out


def available_years(df: pd.DataFrame) -> list[int]:
    return sorted(df["year"].dropna().unique().tolist())


def teams_per_round(df: pd.DataFrame) -> int:
    """Derived from the data (max pick_in_round seen) rather than assumed,
    so this keeps working if league size ever changes across seasons."""
    if df.empty:
        return 0
    return int(df["pick_in_round"].max())


def counts_by_round(df: pd.DataFrame, years: list[int] | None = None) -> pd.DataFrame:
    """Average number of each position drafted per round, across the
    selected years. Index = round (1..max), columns = KNOWN_POSITIONS
    (plus any other position values encountered), values = mean count.

    This is the headline "league tendency" table: e.g. a value of 3.5 for
    (round=1, position=RB) means an average of 3.5 RBs get taken in round
    1 across the selected seasons.
    """
    picks = _valid_picks(df, years)
    if picks.empty:
        return pd.DataFrame()

    per_year_round = (
        picks.groupby(["year", "round", "position"])
        .size()
        .rename("n")
        .reset_index()
    )
    # Every (year, round) combo needs an explicit 0 for positions that
    # didn't get drafted that round, or the later mean() would silently
    # average over fewer years than actually happened for that position.
    all_years = sorted(picks["year"].unique())
    all_rounds = sorted(picks["round"].unique())
    all_positions = sorted(picks["position"].unique())
    full_index = pd.MultiIndex.from_product(
        [all_years, all_rounds, all_positions], names=["year", "round", "position"]
    )
    filled = (
        per_year_round.set_index(["year", "round", "position"])["n"]
        .reindex(full_index, fill_value=0)
        .reset_index()
    )
    avg = filled.groupby(["round", "position"])["n"].mean().unstack("position").fillna(0.0)
    return avg.sort_index()


def cumulative_counts_by_pick(df: pd.DataFrame, years: list[int] | None = None) -> pd.DataFrame:
    """Average CUMULATIVE count of each position drafted through (and
    including) each overall pick number, across the selected years.
    Index = overall_pick (1..max shared pick count), columns = positions.

    This is what "Alt Targets" tracked by hand: at any given overall pick
    number, how many QBs/RBs/WRs/etc. have historically been off the
    board by that point. Different years must share the same max overall
    pick count (true for the 4 captured seasons -- 22 rounds x 10 teams =
    220 every year); years with a different total are still included but
    their cumulative curve is forward-filled flat past their own last
    pick, which is a reasonable "nothing more happened" assumption for a
    league that hasn't changed size mid-history.
    """
    picks = _valid_picks(df, years)
    if picks.empty:
        return pd.DataFrame()

    all_positions = sorted(picks["position"].unique())
    max_pick = int(picks["overall_pick"].max())
    pick_index = pd.RangeIndex(1, max_pick + 1, name="overall_pick")

    per_year_curves = []
    for year, year_df in picks.groupby("year"):
        year_curve = pd.DataFrame(0, index=pick_index, columns=all_positions, dtype=float)
        for pos in all_positions:
            pos_picks = year_df[year_df["position"] == pos]["overall_pick"].sort_values()
            counts = pd.Series(0, index=pick_index, dtype=float)
            for p in pos_picks:
                counts.loc[p:] += 1
            year_curve[pos] = counts
        # forward-fill flat past this year's own last observed pick (only
        # matters if a year's total pick count differs from max_pick)
        year_curve = year_curve.reindex(pick_index).ffill().fillna(0.0)
        per_year_curves.append(year_curve)

    stacked = pd.concat(per_year_curves, keys=range(len(per_year_curves)))
    return stacked.groupby(level=1).mean()


def predict_position_counts(
    df: pd.DataFrame,
    years: list[int] | None,
    current_overall_pick: int,
    picks_ahead: int,
) -> pd.Series:
    """Expected number of each position to be drafted in the NEXT
    `picks_ahead` picks (i.e. picks current_overall_pick+1 through
    current_overall_pick+picks_ahead), averaged across the selected
    years' historical cumulative curves.

    `current_overall_pick` is the overall pick about to happen (1-indexed
    -- e.g. if 14 picks have already happened, pass 15). Clipped to the
    available historical pick range.
    """
    cum = cumulative_counts_by_pick(df, years)
    if cum.empty:
        return pd.Series(dtype=float)

    max_pick = cum.index.max()
    start = max(0, current_overall_pick - 1)
    end = min(max_pick, start + picks_ahead)
    start = min(start, max_pick)

    start_counts = cum.loc[start] if start >= 1 else pd.Series(0.0, index=cum.columns)
    end_counts = cum.loc[end] if end >= 1 else pd.Series(0.0, index=cum.columns)
    return (end_counts - start_counts).clip(lower=0.0).sort_values(ascending=False)


def next_run_positions(
    df: pd.DataFrame,
    years: list[int] | None,
    current_overall_pick: int,
    picks_ahead: int,
    top_n: int = 2,
    min_expected: float = 0.5,
) -> list[str]:
    """Ranked shortlist of positions most likely to see a "run" in the
    next `picks_ahead` picks, e.g. ["RB", "WR"] -- mirrors the manually
    -typed "Next Run" hints in the Alt Targets spreadsheet. Positions
    with a historically negligible expected count (< min_expected) are
    dropped even if top_n isn't filled, so a quiet position doesn't get
    flagged just to pad the list."""
    predicted = predict_position_counts(df, years, current_overall_pick, picks_ahead)
    predicted = predicted[predicted >= min_expected]
    return predicted.head(top_n).index.tolist()
