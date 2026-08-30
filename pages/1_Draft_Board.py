"""
Draft Board — ranked available players, live draft status, and the
sidebar's round-by-round pick history + upcoming-picks lookahead. This is
the tool actually used live on draft day. The main player grid IS the
manual pick-logging mechanism: clicking any available player's row logs
that pick for whichever team is currently on the clock (see the grid's
on_select handling below) -- no separate "log a pick" form. Picks can
ALSO arrive here automatically via a live CBS sync (see src/live_sync.py)
run by an active Claude session during the draft — both write to the
same data/draft_state.json, so this page doesn't need to know or care
which one produced a given pick. My own roster (by starting-lineup slot)
lives on its own page -- see pages/4_My_Roster.py.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone

import pandas as pd
import streamlit as st

from src.data_sources.draft_history import load_draft_history
from src.data_sources.manual_import import load_many
from src.data_sources.simulation_results import format_adp_as_round_pick, load_adp, load_team_points
from src.draft_state import DraftState
from src.live_sync import read_sync_status
from src.pick_suggestion import suggest_position, top_available_players
from src.projections import build_draft_board, compute_tiers
from src.scoring import load_config
from src.tier_display import add_tier_divider_rows
from src.ui_text import team_text_column

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config", "league_settings.yaml")
# Only match actual data files here — a bare "*.*" glob also picks up
# data/projections/README.md and hands it to pd.read_csv(), which throws
# a ParserError (README.md isn't a CSV). Restrict to the extensions
# load_table() actually knows how to read.
DATA_EXTENSIONS = (".csv", ".tsv", ".xlsx", ".xlsm", ".xltx", ".xls")
REAL_DATA_DIR = os.path.join(ROOT, "data", "projections")
SAMPLE_DATA_DIR = os.path.join(ROOT, "data", "sample")
DRAFT_STATE_FILE = os.path.join(ROOT, "data", "draft_state.json")
LIVE_SYNC_STATUS_FILE = os.path.join(ROOT, "data", "live_sync_status.json")
DRAFT_HISTORY_CSV = os.path.join(ROOT, "data", "draft_history", "draft_history.csv")
SIMULATED_ADP_CSV = os.path.join(ROOT, "data", "simulations", "adp_2026.csv")
SIMULATED_TEAM_POINTS_CSV = os.path.join(ROOT, "data", "simulations", "team_points_2026.csv")


def _set_position_override(key: str, position: str) -> None:
    """Callback for the "Back to <recommended>" button below -- must run
    as an on_click callback rather than inline after the button check, or
    Streamlit raises (you can't assign to a widget's session_state key
    after that widget has already been instantiated in the same script
    pass; on_click callbacks run before the next rerun's widgets exist)."""
    st.session_state[key] = position


def _data_files(data_dir: str) -> list[str]:
    if not os.path.isdir(data_dir):
        return []
    return sorted(
        os.path.join(data_dir, name)
        for name in os.listdir(data_dir)
        if os.path.splitext(name)[1].lower() in DATA_EXTENSIONS
    )


@st.cache_resource
def get_config():
    return load_config(CONFIG_PATH)


@st.cache_data
def get_ranked_players(data_dir: str, _mtimes: tuple) -> tuple[pd.DataFrame, bool]:
    """Returns (ranked_df, is_sample_data). _mtimes busts the cache when
    source files change on disk."""
    paths = _data_files(data_dir)
    if not paths:
        return pd.DataFrame(), False
    sources = [(p, os.path.splitext(os.path.basename(p))[0]) for p in paths]
    raw = load_many(sources)
    ranked = build_draft_board(raw, get_config())
    return ranked, False


def load_players() -> tuple[pd.DataFrame, bool]:
    real_paths = _data_files(REAL_DATA_DIR)
    if real_paths:
        mtimes = tuple(os.path.getmtime(p) for p in real_paths)
        df, _ = get_ranked_players(REAL_DATA_DIR, mtimes)
        return df, False
    sample_paths = _data_files(SAMPLE_DATA_DIR)
    if sample_paths:
        mtimes = tuple(os.path.getmtime(p) for p in sample_paths)
        df, _ = get_ranked_players(SAMPLE_DATA_DIR, mtimes)
        return df, True
    return pd.DataFrame(), False


@st.cache_data
def get_history(_mtime: float) -> pd.DataFrame:
    return load_draft_history(DRAFT_HISTORY_CSV)


def load_draft_history_df() -> pd.DataFrame:
    """Historical draft-history CSV, for the suggested-pick page's
    scarcity/run-risk signal. Not an error if it's missing — the
    suggestion just falls back to value+need only (see
    src/pick_suggestion.py's suggest_position() docstring)."""
    if not os.path.exists(DRAFT_HISTORY_CSV):
        return pd.DataFrame()
    return get_history(os.path.getmtime(DRAFT_HISTORY_CSV))


@st.cache_data
def get_simulated_adp(_mtime: float) -> pd.DataFrame:
    return load_adp(SIMULATED_ADP_CSV)


def load_simulated_adp_df() -> pd.DataFrame:
    """Per-player ADP from scripts/simulate_draft.py's --adp-csv output
    (punch-list item #1). Not an error if it's missing -- the "ADP"
    column just doesn't show up on the board until someone runs the
    simulation (see that script's module docstring for the command)."""
    if not os.path.exists(SIMULATED_ADP_CSV):
        return pd.DataFrame()
    return get_simulated_adp(os.path.getmtime(SIMULATED_ADP_CSV))


@st.cache_data
def get_simulated_team_points(_mtime: float) -> pd.DataFrame:
    return load_team_points(SIMULATED_TEAM_POINTS_CSV)


def load_simulated_team_points_df() -> pd.DataFrame:
    """Per-team average simulated optimal-lineup points + rank from
    scripts/simulate_draft.py's --team-points-csv output (punch-list
    item #1). Not an error if it's missing, same as load_simulated_adp_df()."""
    if not os.path.exists(SIMULATED_TEAM_POINTS_CSV):
        return pd.DataFrame()
    return get_simulated_team_points(os.path.getmtime(SIMULATED_TEAM_POINTS_CSV))


config = get_config()
real_team_order = config.get("draft", {}).get("team_order") or []
using_real_team_order = bool(real_team_order) and config["league"]["team_name"] in real_team_order
if using_real_team_order:
    teams = real_team_order
else:
    # No real draft order captured yet for this season — run
    # scripts/fetch_draft_order.py (see its docstring) once CBS has
    # published the order. Placeholder opponent names can be renamed in
    # the sidebar below in the meantime.
    teams = [config["league"]["team_name"]] + [f"Team {i}" for i in range(1, config["league"]["teams"])]
if "team_names" not in st.session_state:
    st.session_state.team_names = teams

@st.fragment(run_every=3)
def render_sidebar() -> None:
    """The entire sidebar -- draft status, live-sync status, undo/reset,
    picks-by-round history, upcoming picks, and team renaming. Called
    from inside `with st.sidebar:` below, NOT via `st.sidebar.xxx()`
    calls made from a fragment whose own position is in the main body.

    That distinction matters a lot on Streamlit 1.50: a fragment whose
    home delta path is the main body, writing into the sidebar via
    `st.sidebar` (or a container object created either inside or outside
    itself), raises StreamlitFragmentWidgetsNotAllowedOutsideError for
    any WIDGET -- and, worse, for plain non-widget elements it doesn't
    raise anything but silently fails to clear the sidebar's previous
    content before redrawing, so the content piles up forever (confirmed
    live: a single st.write() in that shape duplicated on every
    run_every(3) tick, 2 copies after ~5s, 7 after ~20s, unbounded). The
    only combination that behaves correctly is calling the *entire
    fragment* from inside `with st.sidebar:`, so the fragment's own delta
    path is rooted in the sidebar -- every plain st.* call inside it,
    widget or not, is then naturally within that path and gets properly
    cleared and redrawn each run.

    DraftState is built fresh every run (same reasoning as
    render_live_board()'s docstring) so Undo/Reset act on current data
    and the status panel reflects live-synced picks without a manual
    reload. st.rerun() defaults to scope="app" in Streamlit 1.50, so
    Undo/Reset here immediately refresh the main board fragment too, not
    just this sidebar fragment.
    """
    draft_state = DraftState(
        teams=st.session_state.team_names,
        rounds=config["draft"]["rounds"],
        my_team=config["league"]["team_name"],
        state_file=DRAFT_STATE_FILE,
        reverse_last_n_rounds=config["draft"].get("reverse_last_n_rounds", 0),
    )

    st.header("Draft status")
    if draft_state.is_draft_complete:
        st.success("Draft complete!")
    else:
        on_clock = draft_state.on_the_clock
        rnd, slot = draft_state.round_and_slot_for_pick(draft_state.next_overall_pick)
        st.metric("On the clock", on_clock)
        st.caption(f"Pick {draft_state.next_overall_pick} overall (Round {rnd}, Slot {slot})")
        if draft_state.is_my_pick:
            st.success("🎯 It's your pick!")
        else:
            until = draft_state.picks_until_my_turn()
            st.caption(f"{until} picks until your turn")

    sync_status = read_sync_status(LIVE_SYNC_STATUS_FILE)
    if sync_status:
        st.divider()
        st.subheader("🔴 Live sync from CBS")
        synced_at = datetime.fromisoformat(sync_status["last_sync_at"])
        age_seconds = (datetime.now(timezone.utc) - synced_at).total_seconds()
        st.caption(f"Last synced pick: #{sync_status['last_synced_overall_pick']}")
        if age_seconds < 150:
            st.caption(f"✅ Updated {int(age_seconds)}s ago")
        elif age_seconds < 600:
            st.caption(f"⚠️ Updated {int(age_seconds // 60)} min ago — may be behind")
        else:
            st.caption(
                f"🛑 Last update was {int(age_seconds // 60)} min ago — live sync "
                f"looks stopped. Log picks manually below until it resumes."
            )
        if sync_status["mismatches"]:
            st.error(
                "Live sync found a mismatch with what's already logged — "
                "check with whoever is running the sync before trusting "
                "the board:\n" + "\n".join(f"- {m}" for m in sync_status["mismatches"])
            )
        if sync_status["pending_ahead"]:
            st.caption(
                f"{len(sync_status['pending_ahead'])} live pick(s) seen out of "
                f"order, waiting on a gap to close"
            )

    if st.button("↩️ Undo last pick", use_container_width=True, disabled=not draft_state.picks):
        undone = draft_state.undo_last_pick()
        if undone:
            st.toast(f"Undid: {undone.team} — {undone.player_name}")
        st.rerun()

    with st.expander("Reset draft (danger zone)"):
        st.warning("This clears the entire pick log — cannot be undone.")
        confirm_reset = st.checkbox("Yes, clear every logged pick", key="confirm_reset_draft")
        if st.button(
            "Reset draft", type="primary", disabled=not confirm_reset, key="reset_draft_button"
        ):
            draft_state.reset()
            # Force a brand-new, unselected grid widget post-reset too --
            # not just cosmetic: without this, the grid keeps whatever key
            # (and therefore whatever session_state) it had before the
            # reset, and there's no reason to trust stale selection state
            # against a completely different (now fully available) player
            # pool. See the grid_pick_nonce comment further down this file.
            st.session_state.grid_pick_nonce = 0
            st.toast("✅ Draft reset — all picks cleared.")
            st.rerun()

    st.divider()
    st.subheader("Picks by round")
    if not draft_state.picks:
        st.caption("No picks logged yet.")
    else:
        # Most recent pick first -- this is a live ticker, not a
        # scorecard, so what just happened belongs at the top.
        by_round_df = pd.DataFrame(
            [
                {"Rd": p.round, "Pick": p.overall_pick, "Team": p.team, "Player": p.player_name, "Pos": p.position}
                for p in sorted(draft_state.picks, key=lambda p: p.overall_pick, reverse=True)
            ]
        )
        st.dataframe(
            by_round_df, hide_index=True, use_container_width=True, height=260,
            column_config={"Team": team_text_column("Team", st.session_state.team_names)},
        )

    st.subheader("Next 10 picks")
    upcoming = draft_state.upcoming_picks(10)
    if not upcoming:
        st.caption("Draft complete." if draft_state.is_draft_complete else "No upcoming picks.")
    else:
        upcoming_df = pd.DataFrame(
            [
                {
                    "Pick": u["overall_pick"],
                    "Rd": u["round"],
                    "Team": f"🎯 {u['team']}" if u["team"] == draft_state.my_team else u["team"],
                }
                for u in upcoming
            ]
        )
        st.dataframe(
            upcoming_df, hide_index=True, use_container_width=True, height=260,
            column_config={"Team": team_text_column("Team", st.session_state.team_names)},
        )
    st.page_link("pages/4_My_Roster.py", label="Full roster by position →", icon="📋")

    with st.expander("Rename opponent teams"):
        for i, name in enumerate(st.session_state.team_names):
            if name == config["league"]["team_name"]:
                continue
            new_name = st.text_input(f"Team {i+1}", value=name, key=f"team_name_{i}")
            st.session_state.team_names[i] = new_name


with st.sidebar:
    render_sidebar()


@st.fragment(run_every=3)
def render_live_board() -> None:
    """The main body: the suggested-pick panel and the ranked player grid.
    (The sidebar -- draft status, pick history, Undo/Reset/Rename -- is
    its own separate fragment, render_sidebar() above.) Wrapped in a
    fragment (not the old whole-page-reload src.live_refresh hack) so a
    live sync landing a pick updates this in place every few seconds
    without ever navigating the browser -- no flash, no scroll jump,
    because nothing reloads. A widget interaction in here (clicking a
    grid row, a filter) also only reruns this fragment, not the whole
    page.

    IMPORTANT: DraftState is constructed FRESH inside this function, on
    every fragment run -- not once at module level. A fragment rerun
    (whether from this run_every timer or from clicking something inside
    it) re-executes ONLY this function's body, reusing whatever objects
    were closed over from the last FULL script run for anything defined
    outside it (that's the whole performance point of a fragment). If
    draft_state were built at module level instead, this fragment would
    keep showing the same in-memory pick list forever after the first
    load and never notice picks an external live-sync process (or the
    other CBS-hook receiver) writes straight into the JSON file -- which
    defeats the entire purpose of auto-refreshing. Re-reading the file
    every 3 seconds is cheap (a small JSON parse), so there's no real
    cost to paying it every tick.
    """
    draft_state = DraftState(
        teams=st.session_state.team_names,
        rounds=config["draft"]["rounds"],
        my_team=config["league"]["team_name"],
        state_file=DRAFT_STATE_FILE,
        reverse_last_n_rounds=config["draft"].get("reverse_last_n_rounds", 0),
    )
    players_df, is_sample = load_players()

    simulated_adp = load_simulated_adp_df()
    if not players_df.empty:
        if not simulated_adp.empty:
            players_df = players_df.merge(simulated_adp[["name", "adp"]], on="name", how="left")
            players_df = players_df.rename(columns={"adp": "sim_adp"})
        else:
            players_df["sim_adp"] = pd.NA

    # The entire sidebar (status, live-sync info, undo/reset, picks
    # history, rename) now lives in its own separate fragment,
    # render_sidebar() above, called from inside `with st.sidebar:` --
    # see that function's docstring for why it has to be structured that
    # way rather than writing into the sidebar from THIS fragment.

    # ---------------------------------------------------------------------
    # Main: ranked available players -- clicking a row logs that pick
    # ---------------------------------------------------------------------

    st.title("🏈 Draft Board")

    if players_df.empty:
        st.error(
            "No projection data found. Drop CSV/Excel projection files into "
            "`data/projections/` (real 2026 data) or `data/sample/` (fallback) "
            "and reload."
        )
        st.stop()

    if is_sample:
        st.warning(
            "⚠️ Using **data/sample/** — this is last season's (2025) placeholder "
            "data, not real 2026 projections. Add real files to `data/projections/` "
            "before relying on these rankings for draft-day decisions.",
            icon="⚠️",
        )

    if not using_real_team_order:
        st.warning(
            "⚠️ No real draft order found in `config/league_settings.yaml` — using "
            "placeholder team names (Team 1, Team 2, ...). Run "
            "`scripts/fetch_draft_order.py` against a saved copy of the CBS "
            "draft-results page once this season's order is published (see that "
            "script's docstring), or rename opponents manually in the sidebar.",
            icon="⚠️",
        )

    simulated_team_points = load_simulated_team_points_df()
    if not simulated_team_points.empty:
        with st.expander(f"📊 Simulated league strength ({int(simulated_team_points['trials'].iloc[0])} mock drafts)"):
            st.caption(
                "Each team's average projected points from its OPTIMAL starting "
                "lineup, across many full simulated drafts (scripts/simulate_draft.py, "
                "punch-list item #1) — Monster Cheese always drafts using this app's "
                "real pick-suggestion logic; opponents draft from real historical "
                "per-round positional tendencies. Ranked #1 = highest average points."
            )
            points_display = simulated_team_points[
                ["rank", "team", "avg_points", "avg_finish_rank", "best_rank", "worst_rank"]
            ].rename(columns={
                "rank": "Rank", "team": "Team", "avg_points": "Avg Pts",
                "avg_finish_rank": "Avg Finish", "best_rank": "Best Finish", "worst_rank": "Worst Finish",
            })
            st.dataframe(
                points_display, hide_index=True, use_container_width=True,
                column_config={"Team": team_text_column("Team", st.session_state.team_names)},
            )

    drafted = draft_state.drafted_player_names()
    available = players_df[~players_df["name"].isin(drafted)].copy()

    tier_col1, tier_col2 = st.columns([1, 3])
    with tier_col1:
        tier_gap_input = st.number_input(
            "Tier gap override (pts)", min_value=0.0, value=0.0, step=1.0,
            help="0 = auto-detect tier breaks (a statistically significant point "
                 "drop-off per position). Set a number to force a new tier whenever "
                 "the gap to the next player exceeds it, e.g. 10 = every player "
                 "within 10 pts of each other is the same tier.",
        )
    with tier_col2:
        st.caption(
            "Tier breaks are shown as divider rows when filtered to a single "
            "position below, and drive the suggested-pick scarcity signal above."
        )

    gap_threshold = tier_gap_input if tier_gap_input > 0 else None
    available_tiered = compute_tiers(available, gap_threshold=gap_threshold)

    # ---------------------------------------------------------------------
    # Suggested pick — recommends a position from need + available value +
    # historical run risk, and lets you draft straight from its shortlist or
    # browse any other position's best-available players instead.
    # ---------------------------------------------------------------------

    st.divider()
    st.subheader("🎯 Suggested pick")

    if draft_state.is_draft_complete:
        st.success("Draft complete!")
    elif available_tiered.empty:
        st.info("No players available to suggest from.")
    else:
        history = load_draft_history_df()
        suggestion = suggest_position(available_tiered, draft_state, config, history=history)

        if suggestion.recommended_position is None:
            st.info(suggestion.reasoning or "No suggestion available.")
        else:
            if draft_state.is_my_pick:
                st.success(suggestion.reasoning)
            else:
                st.info(
                    f"Preview for your next turn ({draft_state.picks_until_my_turn()} "
                    f"pick(s) away): {suggestion.reasoning}"
                )

            with st.expander("Why? Compare every position"):
                breakdown_df = pd.DataFrame([
                    {
                        "Position": s.position,
                        "Composite": round(s.composite, 3),
                        "Best available VOR": round(s.value_raw, 1),
                        "Roster need": round(s.need_raw, 2),
                        "Predicted picks before your turn": round(s.predicted_picks, 1),
                        "Tier-1 remaining": s.remaining_top_tier,
                        "Total remaining": s.remaining_players,
                    }
                    for s in suggestion.all_scores
                ])
                st.dataframe(breakdown_df, hide_index=True, use_container_width=True)
                st.caption(
                    "Composite = 45% best-available VOR + 30% your unfilled-starter"
                    "-slot need + 25% run-risk scarcity (predicted picks at this "
                    "position before your turn, vs. tier-1 players left), each "
                    "normalized 0-1 across positions before weighting."
                )

            position_options = [s.position for s in suggestion.all_scores]
            default_idx = position_options.index(suggestion.recommended_position)
            override_key = "suggestion_position_override"
            # A position can drop out of the list entirely (e.g. K/DST fully
            # drafted) between reruns -- if whatever was previously selected
            # (including a value the reset button below just set) is no
            # longer a valid option, drop it so the selectbox falls back to
            # its default `index` instead of raising.
            if st.session_state.get(override_key) not in position_options:
                st.session_state.pop(override_key, None)

            pos_select_col, pos_reset_col = st.columns([3, 1])
            with pos_select_col:
                chosen_position = st.selectbox(
                    "Top players for position",
                    options=position_options,
                    index=default_idx,
                    help="Defaults to the recommended position — change this to see "
                         "the best available players/value at any other position.",
                    key=override_key,
                )
            if chosen_position != suggestion.recommended_position:
                with pos_reset_col:
                    st.write("")
                    st.write("")
                    # Setting st.session_state[override_key] has to happen in
                    # an on_click callback, not inline after the button check
                    # -- the selectbox above already instantiated that key
                    # THIS run, and Streamlit raises if you assign to a
                    # widget's session_state key after its widget has run in
                    # the same script pass. on_click callbacks run before the
                    # next rerun's widgets are (re)created, so it's safe there.
                    st.button(
                        f"↩️ Back to {suggestion.recommended_position}",
                        use_container_width=True,
                        help="Jump back to the app's recommended position.",
                        on_click=_set_position_override,
                        args=(override_key, suggestion.recommended_position),
                    )
                st.caption(
                    f"Showing **{chosen_position}** (overriding the recommended "
                    f"**{suggestion.recommended_position}**)."
                )

            top_players = top_available_players(available_tiered, chosen_position, n=3)
            if top_players.empty:
                st.caption(f"No {chosen_position} left on the board.")
            else:
                cols = st.columns(len(top_players))
                for col, (_, row) in zip(cols, top_players.iterrows()):
                    with col:
                        st.markdown(f"**{row['name']}**")
                        st.caption(
                            f"{row['position']} · {row['nfl_team']} · Tier {int(row['tier'])}"
                        )
                        st.caption(
                            f"VOR {row['vor']:.1f} (rank #{int(row['vor_rank'])}) · "
                            f"{row['score_total']:.1f} proj pts"
                        )
                        if st.button(
                            "Draft this player",
                            key=f"suggest_draft_{row['name']}",
                            use_container_width=True,
                            disabled=not draft_state.is_my_pick,
                        ):
                            pick = draft_state.log_pick_on_the_clock(
                                row["name"], position=row["position"], nfl_team=row["nfl_team"]
                            )
                            st.toast(
                                f"Logged: {pick.team} took {pick.player_name} "
                                f"(Rd {pick.round}, Pick {pick.overall_pick})"
                            )
                            st.rerun()
            if not draft_state.is_my_pick:
                st.caption("Draft buttons enable when it's your turn.")

    st.divider()
    filt_col1, filt_col2, filt_col3 = st.columns([2, 2, 1])
    with filt_col1:
        search = st.text_input("Search player", "")
    with filt_col2:
        positions = sorted(available["position"].unique().tolist())
        pos_filter = st.multiselect("Position", positions, default=[])
    with filt_col3:
        sort_by = st.selectbox("Sort by", ["vor_rank", "overall_rank", "position_rank"], index=0)

    view = available_tiered
    if search:
        view = view[view["name"].str.contains(search, case=False, na=False)]
    if pos_filter:
        view = view[view["position"].isin(pos_filter)]
    view = view.sort_values(sort_by)

    display_cols = [
        "vor_rank", "overall_rank", "position_rank", "name", "position", "nfl_team",
        "score_total", "vor", "tier", "num_sources", "sim_adp",
    ]
    display_view = view[display_cols].rename(columns={
        "vor_rank": "VOR Rk", "overall_rank": "Ovr Rk", "position_rank": "Pos Rk",
        "name": "Player", "position": "Pos", "nfl_team": "Team",
        "score_total": "Proj Pts", "vor": "VOR", "tier": "Tier", "num_sources": "# Sources",
        "sim_adp": "ADP",
    })
    # Punch-list item #9: show ADP as "round.pick" (e.g. "5.3" for round 5,
    # 3rd pick in that round) instead of a raw overall-pick number like
    # 43.2 -- applied here, after sorting/filtering, so sort_by above still
    # sorts by the underlying rank columns (unaffected -- ADP was never a
    # sort option) and this only ever touches the display copy.
    display_view["ADP"] = display_view["ADP"].apply(
        lambda v: format_adp_as_round_pick(v, len(teams))
    )
    has_tier_dividers = len(pos_filter) == 1
    if has_tier_dividers:
        display_view = add_tier_divider_rows(display_view, tier_col="Tier", label_col="Player")

    # A brand-new dataframe display each rerun (via display_view's row indices
    # possibly changing as picks are logged) needs a fresh selection widget
    # key each time we act on a click -- otherwise Streamlit's selection state
    # for the OLD key would appear to still be "row 3 selected" against a grid
    # whose row 3 is now a different player, re-triggering the pick every
    # subsequent rerun. Bumping this nonce after each processed click forces a
    # brand-new, unselected widget instance. See src/draft_state.py's
    # log_pick_on_the_clock and the analogous session_state-assignment gotcha
    # already documented on the suggestion-override button above.
    if "grid_pick_nonce" not in st.session_state:
        st.session_state.grid_pick_nonce = 0

    if draft_state.is_draft_complete:
        st.dataframe(display_view, hide_index=True, use_container_width=True, height=500)
    else:
        st.caption(
            f"👆 Click any player's row to log that pick for **{draft_state.on_the_clock}** "
            f"(whoever's on the clock — not just your own picks)."
        )
        grid_event = st.dataframe(
            display_view,
            hide_index=True,
            use_container_width=True,
            height=500,
            on_select="rerun",
            selection_mode="single-row",
            key=f"player_grid_{st.session_state.grid_pick_nonce}",
        )
        selected_rows = list(grid_event.selection["rows"]) if grid_event and grid_event.selection else []
        if selected_rows:
            picked_row = display_view.iloc[selected_rows[0]]
            picked_name = picked_row.get("Player")
            # Tier-divider rows (only inserted when has_tier_dividers) have
            # None in every column except a "— Tier N —" label in Player --
            # clicking one shouldn't log a phantom pick.
            if picked_name and not str(picked_name).startswith("— Tier"):
                match = players_df[players_df["name"] == picked_name]
                position = match["position"].iat[0] if not match.empty else ""
                nfl_team = match["nfl_team"].iat[0] if not match.empty else ""
                pick = draft_state.log_pick_on_the_clock(picked_name, position=position, nfl_team=nfl_team)
                st.session_state.grid_pick_nonce += 1
                st.toast(f"Logged: {pick.team} took {pick.player_name} (Rd {pick.round}, Pick {pick.overall_pick})")
                st.rerun()

    st.divider()
    with st.expander("Full pick log"):
        if draft_state.picks:
            log_df = pd.DataFrame(
                [
                    {"Pick": p.overall_pick, "Rd": p.round, "Team": p.team, "Player": p.player_name, "Pos": p.position}
                    for p in draft_state.picks
                ]
            )
            st.dataframe(
                log_df, hide_index=True, use_container_width=True,
                column_config={"Team": team_text_column("Team", st.session_state.team_names)},
            )
        else:
            st.caption("No picks logged yet.")


render_live_board()
