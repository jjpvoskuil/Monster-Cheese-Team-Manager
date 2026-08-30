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
from src.roster_needs import (
    aggregate_opponent_demand,
    opponent_needs_before_next_pick,
    positions_at_cap,
    positions_blocked_for_all,
    team_position_counts,
)
from src.scoring import load_config
from src.ui_text import team_text_column

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



# ---------------------------------------------------------------------
# Sidebar filter widgets (years / lookahead) run here, in the OUTER
# (non-fragment) script -- NOT inside render_tendencies().
#
# Streamlit 1.50 raises StreamlitFragmentWidgetsNotAllowedOutsideError
# ("Fragments cannot write widgets to outside containers") for ANY
# widget written into a container created outside the fragment's own
# delta path -- confirmed with a minimal repro against a pinned 1.50.0
# install (st.button() reproduces it just as well as st.multiselect()
# did here). See pages/1_Draft_Board.py's matching comment for the full
# story -- this page is where the bug was first caught.
#
# Since selecting either of these widgets always triggers a full rerun
# anyway (neither lives inside a fragment), moving them to plain
# top-level code is both correct and simpler than threading their values
# through a reserved container. render_tendencies() below reads
# selected_years/rounds_ahead as ordinary module globals -- correct even
# on a fragment-only (run_every) rerun, since a fragment-only rerun never
# touches this module-level code, so it always sees whatever value the
# most recent FULL rerun (i.e. the last time one of these widgets
# actually changed) left behind.
# ---------------------------------------------------------------------
_history_for_sidebar = load_history()

with st.sidebar:
    st.header("Years to include")
    if _history_for_sidebar.empty:
        st.caption("No draft history loaded yet.")
        selected_years: list[int] = []
        rounds_ahead = 2
    else:
        _years_for_sidebar = available_years(_history_for_sidebar)
        selected_years = st.multiselect(
            "Average across", options=_years_for_sidebar, default=_years_for_sidebar,
            help="Pick one year alone, or several to average together — mirrors "
                 "how the old TARGETS spreadsheet's 'Alt Targets' tab compared "
                 "recent years side by side.",
        )
        st.divider()
        rounds_ahead = st.slider(
            "Look ahead (rounds)", min_value=1, max_value=3, value=2,
            help="How many rounds ahead to predict positional runs for.",
        )


@st.fragment(run_every=3)
def render_tendencies() -> None:
    """Everything on this page that reads live draft_state -- the sidebar
    year/lookahead controls, the live tracker, and the opponent-needs
    detail. DraftState is constructed fresh at the top of this function
    on every fragment run (not once at module level) -- see
    pages/1_Draft_Board.py's render_live_board() docstring for exactly
    why that matters: a fragment rerun only re-executes this function's
    body, so a DraftState built outside it would never notice new picks
    an external live-sync process writes into the JSON file.
    """
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

    # Years / lookahead widgets live in plain top-level sidebar code above
    # (see the module-level comment there) -- selected_years and
    # rounds_ahead are read as module globals set by that code.
    if not selected_years:
        st.warning("Select at least one year.")
        st.stop()

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
    # and at the top so it's immediately visible during the draft. One
    # compact column per position, one row per round of YOUR draft slot:
    # "proj" = historical cumulative average at that pick, "(Δ)" = the
    # ACTUAL draft vs. that projection once a round is reached, and a
    # same-row read on which positions are worth grabbing before your next
    # pick vs. which can wait -- downgraded to "can wait" whenever every
    # opponent in that window is already roster-capped on a position, since
    # a real cap makes them structurally unable to draft more of it no
    # matter what history says usually happens.
    # ---------------------------------------------------------------------
    st.subheader("🎯 Live Draft Tracker")
    st.caption(
        "One row per ROUND (Pick # / Your pick show YOUR slot in that round "
        "for reference). Each position has TWO narrow columns, both totaled "
        "across the WHOLE round (all "
        f"{teams_n if teams_n else config['league']['teams']} picks in it): "
        "the position code alone (e.g. **QB**) = historical average "
        "cumulative count drafted league-wide through the LAST pick of that "
        "round (years selected in the sidebar) -- round 1 totals to the "
        "round's full team count, round 2 to double that, and so on; "
        "**Δ** + the code (e.g. **ΔQB**) = the ACTUAL draft vs. that "
        "projection once the WHOLE round is complete (🔴 running hotter than "
        "history = scarcer than usual, 🟢 running cooler = safer than usual; "
        "blank until the round finishes). **Consider now** / **Can wait** "
        "are different on purpose -- they stay scoped to YOUR draft position, "
        "looking at the projected run of picks between this round's pick and "
        "your NEXT pick, not the whole round -- 🔒 marks a position moved to "
        "\"can wait\" because every opponent picking in that window has "
        "already hit this league's real roster cap for it (can't legally "
        "draft more), overriding what history alone would suggest."
    )

    cum_hist = cumulative_counts_by_pick(history, years=selected_years)
    my_team_name = config["league"]["team_name"]
    picks_made = len(draft_state.picks)
    picks_by_overall = {p.overall_pick: p for p in draft_state.picks}
    total_rounds = config["draft"]["rounds"]

    # Current position counts per team, as of RIGHT NOW -- used only for the
    # "already capped" check below. That check is valid forever once true (a
    # real roster max can only be reached, never un-reached), so it's a safe
    # floor to apply even to rounds well ahead of where the draft currently
    # stands -- though a team not yet capped today could still become capped
    # by a future round, which this can't foresee; it only ever gets MORE
    # accurate as the real draft catches up to each row.
    capped_positions_now = {
        team: positions_at_cap(team_position_counts(picks), config)
        for team, picks in draft_state.roster_by_team().items()
    }

    # The position-count columns (proj + Δ) are scoped to the WHOLE round --
    # round_size teams' worth of picks, ending at round_end -- not just to
    # YOUR pick within it, per the league manager's request: round 1's
    # projected totals across positions should sum to a full round of picks
    # (e.g. 10 in a 10-team league), round 2's to two rounds, etc. teams_n
    # comes from the historical draft data (see caption above) and is
    # expected to match the real league's team count -- both are 10 here.
    round_size = teams_n if teams_n else config["league"]["teams"]

    tracker_rows = []
    for rnd in range(1, total_rounds + 1):
        my_anchor = draft_state.team_pick_in_round(my_team_name, rnd)
        if my_anchor is None:
            continue
        next_my_anchor = (
            draft_state.team_pick_in_round(my_team_name, rnd + 1) if rnd < total_rounds else None
        )

        round_end = rnd * round_size
        round_complete = round_end <= picks_made

        proj_row = (
            historical_cumulative_at_pick(cum_hist, round_end) if not cum_hist.empty
            else pd.Series(0.0, index=list(KNOWN_POSITIONS))
        )
        actual_counts = actual_cumulative_at_pick(draft_state.picks, round_end) if round_complete else None

        my_pick = picks_by_overall.get(my_anchor)
        my_pick_label = f"{my_pick.position or '—'} · {my_pick.player_name}" if my_pick else "—"

        # Consider now / Can wait stay scoped to YOUR draft position (not the
        # whole-round scope above) -- windowed on THIS round's actual gap to
        # your next pick (not the sidebar's fixed look-ahead), same
        # prediction engine as "What's likely to happen next" below, just
        # scoped per-row. window_teams is who's picking in that gap --
        # fully determined by the snake order, regardless of what they've
        # actually drafted.
        if next_my_anchor is not None and next_my_anchor > my_anchor and not cum_hist.empty:
            window = next_my_anchor - my_anchor
            consider = next_run_positions(history, selected_years, my_anchor, window, top_n=3, min_expected=0.5)
            window_teams = [draft_state.team_for_pick(o) for o in range(my_anchor + 1, next_my_anchor)]
        else:
            consider = []
            window_teams = []

        blocked = positions_blocked_for_all(window_teams, capped_positions_now)
        demoted = {pos for pos in consider if pos in blocked}
        consider_final = [p for p in consider if p not in demoted]
        can_wait_final = [p for p in KNOWN_POSITIONS if p not in consider_final]

        row = {"Round": rnd, "Pick #": my_anchor, "Your pick": my_pick_label}
        for pos in KNOWN_POSITIONS:
            proj_val = float(proj_row.get(pos, 0.0))
            row[pos] = round(proj_val, 1)
            row[f"Δ{pos}"] = (
                round(actual_counts.get(pos, 0) - proj_val, 1) if round_complete else float("nan")
            )
        row["Consider now"] = ", ".join(consider_final) if consider_final else "—"
        row["Can wait"] = (
            ", ".join(f"{p}🔒" if p in demoted else p for p in can_wait_final) if can_wait_final else "—"
        )
        tracker_rows.append(row)

    if not tracker_rows:
        st.info("No rounds to show yet.")
    else:
        tracker_df = pd.DataFrame(tracker_rows).set_index("Round")
        proj_cols = list(KNOWN_POSITIONS)
        delta_cols = [f"Δ{pos}" for pos in KNOWN_POSITIONS]

        def _delta_color(val: float) -> str:
            if pd.isna(val):
                return ""
            if val > 0:
                return "background-color: rgba(220, 38, 38, 0.20);"
            if val < 0:
                return "background-color: rgba(34, 197, 94, 0.20);"
            return ""

        # A single merged .format() call, not two chained ones -- pandas'
        # Styler.format() resets any earlier call's per-column formatters for
        # columns it doesn't explicitly re-list, so calling it twice (once for
        # proj_cols, once for delta_cols) silently dropped the FIRST call's
        # "{:.1f}" and left proj columns rendering with pandas' raw default
        # float precision (6 decimals, e.g. "2.200000") instead of "2.2".
        number_format = {c: "{:.1f}" for c in proj_cols}
        number_format.update({c: "{:+.1f}" for c in delta_cols})
        styled_tracker = (
            tracker_df.style
            .map(_delta_color, subset=delta_cols)
            .format(number_format, na_rep="–")
        )

        def _display_width(s: str) -> int:
            """Rough rendered-width estimate in "character units" -- wide glyphs
            (emoji like the 🔒 lock, the Δ prefix, or the · separator) count for
            more than a plain ASCII letter, since len() alone undercounts how
            wide they actually render."""
            return sum(2 if ord(ch) > 0x2000 else 1 for ch in s)

        def _col_px(header: str, values, per_char: int = 6, pad: int = 10, min_px: int = 32) -> int:
            """Pixel width just wide enough for this column's own longest
            actual DISPLAYED value (or its header, if that's longer) -- so
            every column sizes to what it actually shows instead of a fixed
            preset. `values` should already be the same strings the Styler
            will render (e.g. "18.0", "+1.0", "–"), not raw numbers, so a
            narrow numeric column (like a position code's Δ) comes out just
            as tight as the position abbreviation itself. Recomputed every
            rerun, so it tracks the real draft as picks get logged."""
            widest = max([_display_width(header)] + [_display_width(str(v)) for v in values])
            return max(min_px, pad + per_char * widest)

        tracker_column_config = {
            "_index": st.column_config.NumberColumn(
                "Rnd", width=_col_px("Rnd", tracker_df.index.astype(str).tolist())
            ),
            "Pick #": st.column_config.NumberColumn(
                "Pick #", width=_col_px("Pick #", tracker_df["Pick #"].astype(str).tolist())
            ),
            "Your pick": st.column_config.TextColumn(
                "Your pick", width=_col_px("Your pick", tracker_df["Your pick"].tolist())
            ),
            "Consider now": st.column_config.TextColumn(
                "Consider now", width=_col_px("Consider now", tracker_df["Consider now"].tolist())
            ),
            "Can wait": st.column_config.TextColumn(
                "Can wait", width=_col_px("Can wait", tracker_df["Can wait"].tolist())
            ),
        }
        for pos in proj_cols:
            proj_display = [f"{v:.1f}" for v in tracker_df[pos]]
            tracker_column_config[pos] = st.column_config.NumberColumn(
                pos, width=_col_px(pos, proj_display)
            )
        for dcol in delta_cols:
            delta_display = ["–" if pd.isna(v) else f"{v:+.1f}" for v in tracker_df[dcol]]
            tracker_column_config[dcol] = st.column_config.NumberColumn(
                dcol, width=_col_px(dcol, delta_display)
            )

        st.dataframe(styled_tracker, use_container_width=True, column_config=tracker_column_config)
        st.caption(
            "🔴 running hotter than history · 🟢 running cooler than history · "
            "🔒 downgraded to \"can wait\" because every opponent in that "
            "window is already capped out · rows update live as picks are "
            "logged on the Draft Board."
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
                st.dataframe(
                    pd.DataFrame(rows), hide_index=True, use_container_width=True,
                    column_config={"Team": team_text_column("Team", live_teams)},
                )

                total_demand = aggregate_opponent_demand(needs)
                if total_demand:
                    st.markdown("**Combined demand from teams picking ahead of you:**")
                    demand_df = pd.Series(dict(total_demand)).sort_values(ascending=False).rename(
                        "Unfilled-slot demand"
                    ).round(1).to_frame()
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


render_tendencies()
