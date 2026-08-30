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


def normalize_weights(years: list[int], weights: dict[int, float] | None) -> dict[int, float]:
    """Turn a raw {year: weight} mapping (e.g. straight off UI sliders,
    which have no reason to add up to anything in particular) into
    weights that sum to EXACTLY 1.0 across `years` -- punch-list item #8's
    "a slider so I can adjust the weight of each year with the total
    going to 100%". Not a strict UI validation step: any positive numbers
    work and get rescaled proportionally, so a person doesn't have to
    fuss with getting sliders to add to exactly 100 themselves.

    Falls back to equal weighting across `years` (reproducing the
    original unweighted .mean() behavior exactly) when `weights` is
    None/empty, covers none of the given years, or every relevant weight
    is zero/negative -- so every existing call site that doesn't pass
    `weights` keeps working unchanged."""
    if not years:
        return {}
    if not weights:
        share = 1.0 / len(years)
        return {y: share for y in years}
    relevant = {y: max(0.0, float(weights.get(y, 0.0))) for y in years}
    total = sum(relevant.values())
    if total <= 0:
        share = 1.0 / len(years)
        return {y: share for y in years}
    return {y: w / total for y, w in relevant.items()}


def round_preserve_sum(values: pd.Series, target: int) -> pd.Series:
    """Round every value to the nearest integer using the largest
    -remainder method (a.k.a. Hamilton apportionment), so the rounded
    values sum to EXACTLY `target` -- unlike rounding each value
    independently (`round(4.75)=5, round(4.75)=5, round(0.5)=0` sums to
    10 by luck, but plenty of other splits don't, e.g.
    `round(3.4)+round(3.4)+round(3.2)=3+3+3=9`, one short of 10).

    Method: take each value's floor, then hand out the few remaining
    "whole picks" (target - sum of floors) one at a time to whichever
    values have the largest fractional remainder -- the values closest
    to rounding up "deserve" the extra pick first.
    """
    if len(values) == 0:
        return values.astype(int)

    floors = values.apply(lambda v: int(v // 1) if v == v else 0)  # v==v guards NaN
    remainder = target - int(floors.sum())

    if remainder > 0:
        fracs = (values - floors).sort_values(ascending=False)
        bump_idx = fracs.index[:remainder]
        result = floors.copy()
        result.loc[bump_idx] += 1
    elif remainder < 0:
        # target is smaller than the sum of floors (only possible if
        # `target` was passed smaller than the values' own sum) -- take
        # picks back from the smallest fractional remainders first.
        fracs = (values - floors).sort_values(ascending=True)
        take_idx = fracs.index[: -remainder]
        result = floors.copy()
        result.loc[take_idx] -= 1
    else:
        result = floors.copy()

    return result.astype(int)


def round_table_preserve_row_sums(table: pd.DataFrame, target: int) -> pd.DataFrame:
    """Apply `round_preserve_sum` to every row of a position-count table
    (e.g. counts_by_round's output), so each row still adds up to
    `target` (a draft round always has exactly `target` = teams_per_round
    picks, even though the historical average can land on fractions like
    4.75 QB / 4.75 RB / 0.5 WR)."""
    if table.empty:
        return table
    return table.apply(lambda row: round_preserve_sum(row, target), axis=1)


def counts_by_round(
    df: pd.DataFrame,
    years: list[int] | None = None,
    weights: dict[int, float] | None = None,
) -> pd.DataFrame:
    """Average number of each position drafted per round, across the
    selected years. Index = round (1..max), columns = KNOWN_POSITIONS
    (plus any other position values encountered), values = weighted mean
    count.

    This is the headline "league tendency" table: e.g. a value of 3.5 for
    (round=1, position=RB) means an average of 3.5 RBs get taken in round
    1 across the selected seasons.

    `weights` is an optional {year: weight} mapping (see
    normalize_weights()) letting some years count more than others --
    e.g. weighting last season heaviest. Omitting it (the default)
    reproduces the original equal-weighted mean exactly.
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
    # didn't get drafted that round, or the later weighted sum would
    # silently skip fewer years than actually happened for that position.
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
    year_weights = normalize_weights(all_years, weights)
    # Weights sum to exactly 1.0 across all_years, so a weighted SUM here
    # is equivalent to (and replaces) the original weighted MEAN.
    filled["weighted_n"] = filled["n"] * filled["year"].map(year_weights)
    avg = filled.groupby(["round", "position"])["weighted_n"].sum().unstack("position").fillna(0.0)
    return avg.sort_index()


def cumulative_counts_by_pick(
    df: pd.DataFrame,
    years: list[int] | None = None,
    weights: dict[int, float] | None = None,
) -> pd.DataFrame:
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

    `weights` is an optional {year: weight} mapping (see
    normalize_weights()) letting some years count more than others.
    Omitting it (the default) reproduces the original equal-weighted
    average exactly.
    """
    picks = _valid_picks(df, years)
    if picks.empty:
        return pd.DataFrame()

    all_positions = sorted(picks["position"].unique())
    max_pick = int(picks["overall_pick"].max())
    pick_index = pd.RangeIndex(1, max_pick + 1, name="overall_pick")
    all_years = sorted(picks["year"].unique())
    year_weights = normalize_weights(all_years, weights)

    # Weighted sum of each year's curve, rather than concat + groupby
    # .mean() -- since year_weights sums to exactly 1.0 across all_years,
    # a weighted sum here IS a weighted average, and collapses to the
    # original equal-weighted mean when weights is None.
    weighted_total = pd.DataFrame(0.0, index=pick_index, columns=all_positions)
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
        weighted_total = weighted_total + year_curve * year_weights.get(year, 0.0)

    return weighted_total


def predict_position_counts(
    df: pd.DataFrame,
    years: list[int] | None,
    current_overall_pick: int,
    picks_ahead: int,
    weights: dict[int, float] | None = None,
) -> pd.Series:
    """Expected number of each position to be drafted in the NEXT
    `picks_ahead` picks (i.e. picks current_overall_pick+1 through
    current_overall_pick+picks_ahead), averaged across the selected
    years' historical cumulative curves.

    `current_overall_pick` is the overall pick about to happen (1-indexed
    -- e.g. if 14 picks have already happened, pass 15). Clipped to the
    available historical pick range. `weights` is passed straight through
    to cumulative_counts_by_pick() -- see its docstring.
    """
    cum = cumulative_counts_by_pick(df, years, weights=weights)
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
    weights: dict[int, float] | None = None,
) -> list[str]:
    """Ranked shortlist of positions most likely to see a "run" in the
    next `picks_ahead` picks, e.g. ["RB", "WR"] -- mirrors the manually
    -typed "Next Run" hints in the Alt Targets spreadsheet. Positions
    with a historically negligible expected count (< min_expected) are
    dropped even if top_n isn't filled, so a quiet position doesn't get
    flagged just to pad the list. `weights` is passed straight through to
    predict_position_counts() -- see cumulative_counts_by_pick()'s
    docstring."""
    predicted = predict_position_counts(df, years, current_overall_pick, picks_ahead, weights=weights)
    predicted = predicted[predicted >= min_expected]
    return predicted.head(top_n).index.tolist()


def actual_cumulative_at_pick(
    picks: list, through_overall_pick: int, positions: tuple[str, ...] = KNOWN_POSITIONS
) -> dict[str, int]:
    """Real cumulative count of each position drafted by ANYONE, from the
    live/in-progress draft's own actual pick log (a list of
    src.draft_state.Pick), through and including `through_overall_pick`.

    This is the live, exact counterpart to cumulative_counts_by_pick()'s
    historical AVERAGE -- the league manager used to hand-tally this same
    number on the old "Alt Targets" worksheet round by round as the real
    draft happened; this computes it directly from the already-tracked
    live draft state instead, so it needs no manual entry and is never
    off. Picks with no recognized position (blank, e.g. a name-only
    manual log) are ignored, same spirit as _valid_picks() above for
    historical data."""
    counts = {p: 0 for p in positions}
    for pick in picks:
        if pick.overall_pick > through_overall_pick:
            continue
        if pick.position in counts:
            counts[pick.position] += 1
    return counts


def historical_cumulative_at_pick(cumulative_df: pd.DataFrame, overall_pick: int) -> pd.Series:
    """Look up cumulative_counts_by_pick()'s output at a single overall
    pick number, clipped to the historical data's own pick range (the
    same clipping predict_position_counts() applies) -- a pick number
    beyond what history covers returns the last available row instead of
    raising a KeyError. Returns an empty Series if `cumulative_df` is
    empty (e.g. no draft history loaded)."""
    if cumulative_df.empty:
        return pd.Series(dtype=float)
    max_pick = cumulative_df.index.max()
    clipped = min(max(overall_pick, 1), max_pick)
    return cumulative_df.loc[clipped]
