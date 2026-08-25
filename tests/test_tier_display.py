import pandas as pd
import pytest

from src.tier_display import add_tier_divider_rows


def test_divider_label_goes_in_label_col_not_first_col():
    """Regression: the divider text used to be written into whichever
    column happened to be first -- on the Draft Board that's a numeric
    rank column ("VOR Rk"), which corrupts its dtype (mixed int + string)
    and breaks Arrow serialization in st.dataframe. The label must go into
    an explicit text column instead."""
    df = pd.DataFrame({
        "VOR Rk": [1, 2, 3],
        "Player": ["Josh Allen", "Lamar Jackson", "Drake Maye"],
        "Tier": [1, 1, 2],
    })
    out = add_tier_divider_rows(df, tier_col="Tier", label_col="Player")

    # divider rows' numeric column must stay null/NaN, never the label text
    divider_rows = out[out["Player"].astype(str).str.startswith("—")]
    assert len(divider_rows) == 2  # one before tier 1, one before tier 2
    assert divider_rows["VOR Rk"].isna().all()
    assert divider_rows["Player"].tolist() == ["— Tier 1 —", "— Tier 2 —"]

    # VOR Rk column must remain numeric (float, since NaN forces the
    # upcast) -- never degrade to a generic mixed-type object column.
    assert pd.api.types.is_numeric_dtype(out["VOR Rk"])


def test_unknown_label_col_raises_clear_error():
    df = pd.DataFrame({"a": [1], "Tier": [1]})
    with pytest.raises(ValueError, match="label_col"):
        add_tier_divider_rows(df, tier_col="Tier", label_col="Player")


def test_no_tier_col_returns_unchanged():
    df = pd.DataFrame({"Player": ["A", "B"]})
    out = add_tier_divider_rows(df, tier_col="Tier", label_col="Player")
    assert out is df


def test_empty_df_returns_unchanged():
    df = pd.DataFrame(columns=["Player", "Tier"])
    out = add_tier_divider_rows(df, tier_col="Tier", label_col="Player")
    assert out.empty
