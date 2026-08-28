"""
Draft Tendencies — a live, on-the-clock draft tracker (projected
cumulative counts from 2022-2025 CBS draft history, the actual draft's
live counts as a delta off that projection, and a same-row consider
-now/can-wait read) up top, with the supporting historical/predictive
detail collapsed below it.

Answers the questions the league manager asked for:
  1. "We track actual counts as we go through the draft, cumulative
     pick by pick, filling in as the actual draft proceeds" -- the old
     hand-tallied 'Alt Targets' worksheet, automated.
  2. "The number of players per position per round is pretty consistent
     -- if I'm seeing a run on a position, is it predictable?"
  3. "Will the teams picking before my next turn likely take a position
     I want, based on what's still open on their rosters?"
"""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from src.data_sources.draft_history import load_draft_history
from src.draft_state import DraftState
from src.draft_tendencies import (
    KNOWN_POSITIONS,
    actual_cumulative_at_pick,
    available_years,
    counts_by_round,
    cumulative_counts_by_pick,
    historical_cumulative_at_pick,
    next_run_positions,
    predict_position_counts,
    round_preserve_sum,
    round_table_preserve_row_sums,
    teams_per_round,
)
from src.roster_needs import aggregate_opponent_demand, opponent_needs_before_next_pick
from src.scoring import load_config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config", "league_settings.yaml")
DRAFT_STATE_FILE = os.path.join(ROOT, "data", "draft_state.json")
DRAFT_HISTORY_CSV = os.path.join(ROOT, "data", "draft_history", "draft_history.csv")


@st.cache_resource
def get_config():
    return load_config(CONFIG_PATH)


@st.cache_data
def get_history(_mtime: float) -> pd.DataFrame:
    return load_draft_history(DRAFT_HISTORY_CSV)


def load_history() -> pd.DataFrame:
    if not os.path.exists(DRAFT_HISTORY_CSV):
        return pd.DataFrame()
    return get_history(os.path.getmtime(DRAFT_HISTORY_CSV))


config = get_config()
history = load_history()

st.title("📈 Draft Tendencies")

if history.empty:
    st.error(
        "No draft history found. Run `python scripts/fetch_draft_history.py` "
        "after saving raw draft-results captures to "
        "`data/draft_history/raw/<year>_raw.txt` (see "
        "`src/data_sources/draft_history.py` for the capture workflow)."
    )
    st.stop()

years = available_years(history)
teams_n = teams_per_round(history)

st.caption(
    f"Loaded {len(history)} historical picks across {len(years)} seasons "
    f"({', '.join(str(y) for y in years)}), {teams_n} teams/round."
)

with st.sidebar:
    st.header("Years to include")
    selected_years = st.multiselect(
        "Average across", options=years, default=years,
        help="Pick one year alone, or several to average together — mirrors "
             "how the old TARGETS spreadsheet's 'Alt Targets' tab compared "
             "recent years side by side.",
    )
    if not selected_years:
        st.warning("Select at least one year.")
        st.stop()

    st.divider()
    rounds_ahead = st.slider(
        "Look ahead (rounds)", min_value=1, max_value=3, value=2,
        help="How many rounds ahead to predict positional runs for.",
    )

# ---------------------------------------------------------------------
# Live draft state (shared with the Draft Board page)
# ---------------------------------------------------------------------
real_team_order = config.get("draft", {}).get("team_order") or []
using_real_team_order = bool(real_team_order) and config["league"]["team_name"] in real_team_order
if using_real_team_order:
    live_teams = real_team_order
else:
    live_teams = [config["league"]["team_name"]] + [f"Team {i}" for i in range(1, config["league"]["teams"])]

draft_state = DraftState(
    teams=live_teams,
    rounds=config["draft"]["rounds"],
    my_team=config["league"]["team_name"],
    state_file=DRAFT_STATE_FILE,
    reverse_last_n_rounds=config["draft"].get("reverse_last_n_rounds", 0),
)

if draft_state.is_draft_complete:
    st.success("Live draft is complete — showing historical tendencies only.")
    current_pick = None
else:
    current_pick = draft_state.next_overall_pick
    rnd, slot = draft_state.round_and_slot_for_pick(current_pick)
    c1, c2, c3 = st.columns(3)
    c1.metric("Next overall pick", current_pick, help=f"Round {rnd}, slot {slot}")
    c2.metric("On the clock", draft_state.on_the_clock)
    until = draft_state.picks_until_my_turn()
    c3.metric("Picks until your turn", until if until is not None else "—")

# ---------------------------------------------------------------------
# LIVE DRAFT TRACKER -- the primary view of this page, kept uncollapsed
# and at the top so it's immediately visible during the draft. One row
# per round of YOUR draft slot: the historical PROJECTED cumulative
# count per position, how the ACTUAL draft is running vs. that
# projection (as a delta, once a round is reached), and a same-row read
# on which positions are worth grabbing before your next pick vs. which
# can wait. Replaces the earlier (2026-08-27) "Live cumulative picks by
# round" section -- that one showed actual OR projected per round; this
# shows projected always, with actual expressed as the delta, which is
# the more useful "am I ahead of or behind the historical pace" read.
# ---------------------------------------------------------------------
st.subheader("🎯 Live Draft Tracker")
st.caption(
    "One row per round of YOUR draft slot. **Proj** = historical average "
    "cumulative count of that position drafted league-wide by this pick "
    "(years selected in the sidebar). **Δ** = the ACTUAL draft vs. that "
    "projection, once a round is reached (actual − projected: 🔴 positive "
    "= running hotter than history, that position is disappearing faster "
    "than usual; 🟢 negative = running cooler, safer than usual); shows "
    "– for rounds not reached yet. **Consider now** / **Can wait** "
    "look at the projected run of picks between this round and your NEXT "
    "pick to flag what's worth grabbing now vs. what should still be "
    "there next round."
)

cum_hist = cumulative_counts_by_pick(history, years=selected_years)
my_team_name = config["league"]["team_name"]
picks_made = len(draft_state.picks)
picks_by_overall = {p.overall_pick: p for p in draft_state.picks}
total_rounds = config["draft"]["rounds"]

tracker_rows = []
for rnd in range(1, total_rounds + 1):
    anchor = draft_state.team_pick_in_round(my_team_name, rnd)
    if anchor is None:
        continue
    next_anchor = (
        draft_state.team_pick_in_round(my_team_name, rnd + 1) if rnd < total_rounds else None
    )
    reached = anchor <= picks_made

    proj_row = (
        historical_cumulative_at_pick(cum_hist, anchor) if not cum_hist.empty
        else pd.Series(0.0, index=list(KNOWN_POSITIONS))
    )
    actual_counts = actual_cumulative_at_pick(draft_state.picks, anchor) if reached else None

    my_pick = picks_by_overall.get(anchor)
    my_pick_label = f"{my_pick.position or '—'} · {my_pick.player_name}" if my_pick else "—"

    # Windowed on THIS round's actual gap to your next pick (not the
    # sidebar's fixed look-ahead) -- same prediction engine as "What's
    # likely to happen next" below, just scoped per-row.
    if next_anchor is not None and next_anchor > anchor and not cum_hist.empty:
        window = next_anchor - anchor
        consider = next_run_positions(history, selected_years, anchor, window, top_n=3, min_expected=0.5)
    else:
        consider = []
    can_wait = [p for p in KNOWN_POSITIONS if p not in consider]

    row = {"Round": rnd, "Pick #": anchor, "Your pick": my_pick_label}
    for pos in KNOWN_POSITIONS:
        proj_val = float(proj_row.get(pos, 0.0))
        row[f"{pos} Proj"] = round(proj_val, 1)
        if reached:
            row[f"{pos} Δ"] = round(actual_counts.get(pos, 0) - proj_val, 1)
        else:
            row[f"{pos} Δ"] = float("nan")
    row["Consider now"] = ", ".join(consider) if consider else "—"
    row["Can wait"] = ", ".join(can_wait) if can_wait else "—"
    tracker_rows.append(row)

if not tracker_rows:
    st.info("No rounds to show yet.")
else:
    tracker_df = pd.DataFrame(tracker_rows).set_index("Round")
    delta_cols = [f"{pos} Δ" for pos in KNOWN_POSITIONS]
    proj_cols = [f"{pos} Proj" for pos in KNOWN_POSITIONS]

    def _delta_color(val) -> str:
        if pd.isna(val):
            return ""
        if val > 0:
            return "background-color: rgba(220, 38, 38, 0.20);"
        if val < 0:
            return "background-color: rgba(34, 197, 94, 0.20);"
        return ""

    styled_tracker = (
        tracker_df.style
        .map(_delta_color, subset=delta_cols)
        .format({c: "{:.1f}" for c in proj_cols})
        .format({c: "{:+.1f}" for c in delta_cols}, na_rep="–")
    )
    st.dataframe(styled_tracker, use_container_width=True)
    st.caption(
        "🔴 running hotter than history (scarcer than usual right now) · "
        "🟢 running cooler than history (safer than usual right now) · "
        "rows update live as picks are logged on the Draft Board."
    )

# ---------------------------------------------------------------------
# Everything below is supporting detail for the tracker above --
# collapsed by default so the tracker is what's immediately visible.
# ---------------------------------------------------------------------
st.divider()

with st.expander("Historical positions drafted per round"):
    st.caption(
        "Average number of each position taken in each round, across the "
        "selected years. This is the base pattern the tracker above and "
        "the predictions below are built from."
    )
    by_round = counts_by_round(history, years=selected_years)
    if by_round.empty:
        st.info("No data for the selected years.")
    else:
        by_round_int = round_table_preserve_row_sums(by_round, teams_n)
        st.dataframe(by_round_int, use_container_width=True)
        st.caption(f"Each round's row sums to exactly {teams_n} (rounded from the raw historical average).")
        st.bar_chart(by_round_int)

with st.expander("What's likely to happen next"):
    picks_ahead = rounds_ahead * teams_n if teams_n else rounds_ahead * config["league"]["teams"]
    predict_from = current_pick if current_pick is not None else 1

    predicted = predict_position_counts(history, selected_years, predict_from, picks_ahead)
    if predicted.empty:
        st.info("No prediction available (no historical data for the selected years).")
    else:
        predicted_int = round_preserve_sum(predicted, picks_ahead)
        hot = next_run_positions(history, selected_years, predict_from, picks_ahead, top_n=2)
        if hot:
            st.info(
                f"**Likely run in the next {rounds_ahead} round(s):** "
                f"{' / '.join(hot)} — historically {predicted_int[hot].to_dict()} "
                f"players taken in this pick window. Positions NOT in this list have "
                f"historically been safe to wait on for a round or two."
            )
        pred_df = predicted_int.rename("Expected # drafted").to_frame()
        st.dataframe(pred_df, use_container_width=True)
        st.caption(f"Sums to exactly {picks_ahead} — the number of picks in the next {rounds_ahead} round(s).")
        st.bar_chart(predicted_int)

with st.expander("Opponent roster needs before your next pick"):
    if draft_state.is_draft_complete:
        st.caption("Draft complete — no upcoming opponents.")
    elif draft_state.is_my_pick:
        st.success("🎯 It's your pick right now — no opponents ahead of you.")
    else:
        needs = opponent_needs_before_next_pick(draft_state, config)
        if not needs:
            st.caption("No opponents picking before your next turn.")
        else:
            rows = []
            for team, demand in needs.items():
                if demand:
                    top_positions = ", ".join(
                        f"{pos} ({wt:.1f})" for pos, wt in demand.most_common(3)
                    )
                else:
                    top_positions = "— (starters look filled)"
                rows.append({"Team": team, "Likely needs": top_positions})
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

            total_demand = aggregate_opponent_demand(needs)
            if total_demand:
                st.markdown("**Combined demand from teams picking ahead of you:**")
                demand_df = pd.Series(dict(total_demand)).sort_values(ascending=False).rename(
                    "Unfilled-slot demand"
                ).round(2).to_frame()
                st.dataframe(demand_df, use_container_width=True)

                if not predicted.empty:
                    overlap = [
                        p for p in demand_df.index
                        if p in predicted.index and predicted[p] >= 0.5 and p in demand_df.index[:3]
                    ]
                    if overlap:
                        st.warning(
                            f"⚠️ **{' / '.join(overlap)}** shows up both in opponents' "
                            f"unfilled roster needs AND the historical next-run "
                            f"prediction above — the strongest signal that this "
                            f"position may not last until your pick."
                        )

        st.caption(
            "\"Likely needs\" = starter slots this team can't yet fill from "
            "players it has already drafted (dedicated slots like QB/RB/TE/K/DST "
            "are filled first, then the flex slots), spread across each slot's "
            "eligible positions. This is a heuristic about what's still OPEN on "
            "their roster, not a guess at their draft strategy."
        )
