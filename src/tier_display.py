"""
Turn a tiered, display-ready DataFrame (see src.projections.compute_tiers)
into one with visible divider rows between tiers, for st.dataframe.

Streamlit's st.dataframe doesn't support inserting a styled separator
between arbitrary rows of a plain DataFrame, so this takes the low-tech but
reliable approach: insert an actual row, labeled "— Tier N —" in the first
column and blank everywhere else, right before each new tier's first
player. It reads cleanly at a glance and works in any Streamlit version
without depending on pandas.Styler support.
"""

from __future__ import annotations

import pandas as pd


def add_tier_divider_rows(display_df: pd.DataFrame, tier_col: str = "Tier", label_col: str = "Player") -> pd.DataFrame:
    """display_df must already be sorted in the order you want tiers to
    read top-to-bottom (best tier first) and must contain tier_col. Only
    meaningful for a single-position view -- tier numbers are relative to
    whatever position(s) are present, so mixing positions here will insert
    a confusing number of dividers as tiers reset per position.

    The divider's label text goes into label_col specifically (must already
    be a text/name column, e.g. "Player") rather than whichever column
    happens to be first -- putting a string into a numeric rank column
    (e.g. "VOR Rk") degrades that column to mixed object dtype and breaks
    Arrow serialization in st.dataframe. Every other column gets None
    (not "") so pandas upcasts a numeric column to float+NaN, which Arrow
    handles cleanly, instead of object dtype mixing numbers and strings."""
    if display_df.empty or tier_col not in display_df.columns:
        return display_df
    if label_col not in display_df.columns:
        raise ValueError(f"label_col {label_col!r} not in display_df columns: {list(display_df.columns)}")

    rows = []
    prev_tier = None
    for _, row in display_df.iterrows():
        cur_tier = row[tier_col]
        if cur_tier != prev_tier:
            divider = {c: None for c in display_df.columns}
            divider[label_col] = f"— Tier {int(cur_tier)} —"
            rows.append(divider)
            prev_tier = cur_tier
        rows.append(row.to_dict())
    return pd.DataFrame(rows, columns=display_df.columns)
