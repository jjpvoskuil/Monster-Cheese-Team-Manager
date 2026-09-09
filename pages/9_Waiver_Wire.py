"""
Waiver Wire -- top pickup recommendations from CBS's live free-agent pool
(src/data_sources/waiver_wire.py), ranked by src/waiver_recommendations.py
against Monster Cheese's current roster.

League-manager request, 2026-09-09 (see that request's full text in
src/waiver_recommendations.py's module docstring for the priority order
this implements: an empty starting slot from a bye is priority #1, then a
season-long upgrade over a rostered player, then bench-depth adds with
open roster room, then drop-for-upgrade once the roster is full at 27).
Every recommendation says whether it's CBS- or FantasyPoints-based, per
that request's explicit requirement.

TWO PROJECTION SOURCES, VALUED DIFFERENTLY:
  - CBS: free agents come straight from CBS's own live free-agent-page
    FPTS (data/waiver_wire/{year}_week{N}.csv for this week's value,
    data/waiver_wire/{year}_restofseason.csv for season-long value --
    see src/data_sources/waiver_wire.py for the capture procedure). A
    rostered player's comparable CBS value is this app's own
    ScoringEngine applied to their row in data/projections/cbs_2026.csv
    (CBS's pre-draft season stat projections, scored under this
    league's real rules) -- see src/waiver_recommendations.py's module
    docstring for why this isn't a perfectly apples-to-apples number
    against the live free-agent FPTS, and why that's still the best
    available comparison.
  - FantasyPoints: no live free-agent capture exists for this source
    (would need per-player search or scraping FantasyPoints' own
    unrostered-player view, neither built) -- no separate FantasyPoints
    -sourced free-agent POOL is built either. Instead (league-manager
    request, 2026-09-09: "pull in FantasyPoints projections against
    CBS's available players"), CBS's own live free-agent list is treated
    as the authoritative "who's actually available" answer, and each of
    those SAME candidates is re-scored under FantasyPoints' season
    projections (data/projections/fantasypoints_2026.csv, scored by this
    app's own ScoringEngine, same as the roster side) by exact name
    match -- see _fantasypoints_free_agents(). A CBS free agent
    FantasyPoints never bothered projecting (deep bench/practice squad,
    usually) just doesn't get a FantasyPoints-sourced recommendation --
    no number to rank them by, not a guess. This keeps both sources
    working off the identical player pool, so the page's CBS/
    FantasyPoints toggle (below) shows how the SAME real candidates rank
    differently by source, not two different candidate lists.
    Season-long only -- no per-week FantasyPoints free-agent numbers,
    since FantasyPoints' weekly capture abbreviates player names
    ("J. Allen") in a way not worth cross-matching for a page whose #1
    priority is exactly "which slot is empty this week."

WEEK-SPECIFIC DATA (bye-gap fill, tier 1) is CBS-only for the same
reason: it needs data/weekly_matchups/{year}_week{N}.csv (already
captured for the Weekly Matchup page) to know which of MY roster's
players have a bye THIS specific week -- FantasyPoints has no equivalent
per-week capture in this app. If that file hasn't been captured for the
selected week, tier 1 silently produces no recommendations (see
src.waiver_recommendations._bye_gap_recommendations) and this page says
so plainly rather than guessing.
"""

from __future__ import annotations

import os
import re

import pandas as pd
import streamlit as st

from src.data_sources.manual_import import CANONICAL_COLUMNS, load_table
from src.data_sources.transactions import load_transactions
from src.draft_state import DraftState
from src.projections import _normalize_dst_names
from src.roster_needs import assign_roster_slots
from src.roster_state import current_roster_by_team, current_roster_for_team
from src.scoring import ScoringEngine, load_config
from src.waiver_recommendations import (
    CATEGORY_LABELS,
    FreeAgent,
    RosterPlayer,
    build_recommendations,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config", "league_settings.yaml")
DRAFT_STATE_FILE = os.path.join(ROOT, "data", "draft_state.json")
TRANSACTIONS_CSV = os.path.join(ROOT, "data", "transactions", "transactions.csv")
WAIVER_DIR = os.path.join(ROOT, "data", "waiver_wire")
MATCHUP_DIR = os.path.join(ROOT, "data", "weekly_matchups")
PROJECTIONS_DIR = os.path.join(ROOT, "data", "projections")

WEEK_FILE_RE = re.compile(r"^(\d{4})_week(\d+)\.csv$")

LOGIN_LINKS = {
    "CBS Free Agent Recommendations": "https://maniacfl.football.cbssports.com/stats/stats-main",
}


@st.cache_resource
def get_config():
    return load_config(CONFIG_PATH)


def _available_weeks() -> list[tuple[int, int]]:
    if not os.path.isdir(WAIVER_DIR):
        return []
    weeks = []
    for name in os.listdir(WAIVER_DIR):
        m = WEEK_FILE_RE.match(name)
        if m:
            weeks.append((int(m.group(1)), int(m.group(2))))
    return sorted(weeks)


@st.cache_data
def _load_csv(path: str, _mtime: float) -> pd.DataFrame:
    return pd.read_csv(path)


@st.cache_data
def _scored_season_projections(path: str, source: str, _mtime: float) -> pd.DataFrame:
    """Every player in a single-source season projection file
    (data/projections/{source}_2026.csv), scored under this league's
    real rules by this app's own ScoringEngine -- NOT the blended
    multi-source src.projections.build_draft_board() ranking used
    elsewhere, since a same-SOURCE comparison is what makes the
    CBS-vs-FantasyPoints labeling on this page mean anything (see this
    module's docstring)."""
    config = get_config()
    df = load_table(path, source)
    df = _normalize_dst_names(df)
    df = df.copy()
    # load_table() only fills a canonical stat column that's ENTIRELY
    # missing from the source file with 0 -- an individual blank CELL
    # within a present column (e.g. a TE's pass_yards cell) stays NaN.
    # src.projections.blend_projections() explicitly guards against this
    # (see its own long comment on a 2026-09-02 bug from exactly this),
    # but that guard only runs for the multi-source blended pipeline this
    # page deliberately bypasses (single-source, so there's nothing to
    # blend) -- fillna(0) here directly instead, or a NaN stat silently
    # NaNs out ScoreBreakdown.total for any player with even one blank
    # cell (confirmed live: Darren Waller's blank passing/rushing cells
    # produced "nan" pts before this fix).
    stat_columns = [c for c in CANONICAL_COLUMNS if c not in ("name", "position", "nfl_team", "games")]
    df[stat_columns] = df[stat_columns].fillna(0)
    df["games"] = df["games"].fillna(config.get("estimation_assumptions", {}).get("games_per_season", 17))
    engine = ScoringEngine(config)
    df["score_total"] = df.apply(
        lambda row: engine.score_player_season(row.to_dict(), games=row.get("games")).total, axis=1
    )
    return df[["name", "position", "nfl_team", "score_total"]]


def _week_matchup_signals(year: int, week: int, my_team: str) -> tuple[dict, dict, set, set]:
    """If data/weekly_matchups/{year}_week{N}.csv has been captured,
    return (week_points_by_name, is_starter_by_name, bye_names,
    all_names_seen) for MY team's rows in it. Empty dict/set for all four
    if that week hasn't been captured -- callers treat that as "no
    week-specific signal available", same graceful-degradation spirit as
    pages/8_Weekly_Matchup.py's own missing-data handling."""
    path = os.path.join(MATCHUP_DIR, f"{year}_week{week}.csv")
    if not os.path.exists(path):
        return {}, {}, set(), set()
    df = _load_csv(path, os.path.getmtime(path))
    team_df = df[df["team"] == my_team]
    if team_df.empty:
        return {}, {}, set(), set()

    week_points = dict(zip(team_df["player_name"], team_df["cbs_points"]))
    is_starter = {name: True for name in team_df.loc[team_df["roster_group"] == "starter", "player_name"]}
    # Same best-effort text match as pages/8_Weekly_Matchup.py's
    # _bye_names() -- see that function's docstring for the caveat that
    # this hasn't been cross-validated against a real captured bye week
    # yet (Week 1, the only week captured so far, has none).
    desc = team_df["matchup_desc"].fillna("")
    bye_names = set(team_df.loc[desc.str.contains("bye", case=False), "player_name"])
    return week_points, is_starter, bye_names, set(team_df["player_name"])


def _cbs_roster_players(
    my_picks: list, week_points: dict, is_starter_from_week: dict, bye_names: set,
    cbs_season_scores: dict, heuristic_starter_names: set,
) -> list[RosterPlayer]:
    return [
        RosterPlayer(
            name=p.player_name,
            position=p.position,
            week_points=week_points.get(p.player_name),
            season_points=cbs_season_scores.get(p.player_name),
            is_starter=is_starter_from_week.get(
                p.player_name, p.player_name in heuristic_starter_names
            ),
            is_bye=p.player_name in bye_names,
        )
        for p in my_picks
    ]


def _fantasypoints_roster_players(
    my_picks: list, is_starter_from_week: dict, bye_names: set,
    fp_season_scores: dict, heuristic_starter_names: set,
) -> list[RosterPlayer]:
    # No week-specific FantasyPoints signal (see module docstring) --
    # week_points always None here; starter/bye flags are lineup facts,
    # not source-specific, so reuse the same ones CBS's roster view used.
    return [
        RosterPlayer(
            name=p.player_name,
            position=p.position,
            week_points=None,
            season_points=fp_season_scores.get(p.player_name),
            is_starter=is_starter_from_week.get(
                p.player_name, p.player_name in heuristic_starter_names
            ),
            is_bye=p.player_name in bye_names,
        )
        for p in my_picks
    ]


def _cbs_free_agents(year: int, week: int) -> list[FreeAgent]:
    week_path = os.path.join(WAIVER_DIR, f"{year}_week{week}.csv")
    season_path = os.path.join(WAIVER_DIR, f"{year}_restofseason.csv")
    week_df = _load_csv(week_path, os.path.getmtime(week_path)) if os.path.exists(week_path) else pd.DataFrame()
    season_df = _load_csv(season_path, os.path.getmtime(season_path)) if os.path.exists(season_path) else pd.DataFrame()

    week_points = dict(zip(week_df["name"], week_df["fpts"])) if not week_df.empty else {}
    season_points = dict(zip(season_df["name"], season_df["fpts"])) if not season_df.empty else {}
    meta_df = season_df if not season_df.empty else week_df
    if meta_df.empty:
        return []
    meta = {row.name: (row.position, row.nfl_team) for row in meta_df.itertuples()}
    # Names appearing only in the week file (not in rest-of-season) still
    # need position/team -- fold those in too.
    if not week_df.empty:
        for row in week_df.itertuples():
            meta.setdefault(row.name, (row.position, row.nfl_team))

    return [
        FreeAgent(
            name=name, position=pos, nfl_team=team,
            week_points=week_points.get(name), season_points=season_points.get(name),
        )
        for name, (pos, team) in meta.items()
    ]


def _fantasypoints_free_agents(cbs_free_agents: list[FreeAgent], fp_season_df: pd.DataFrame) -> list[FreeAgent]:
    """Re-scores CBS's own free-agent candidates under FantasyPoints'
    season projections instead of deriving a second, independent
    free-agent pool -- see this module's docstring ("pull in
    FantasyPoints projections against CBS's available players").
    Same candidate IDENTITY as the CBS list; only the value differs."""
    if fp_season_df.empty:
        return []
    fp_scores = dict(zip(fp_season_df["name"], fp_season_df["score_total"]))
    out = []
    for fa in cbs_free_agents:
        score = fp_scores.get(fa.name)
        if score is None or pd.isna(score):
            continue  # FantasyPoints never projected this player -- no number to rank by
        out.append(FreeAgent(name=fa.name, position=fa.position, nfl_team=fa.nfl_team, season_points=score))
    return out


def _render_recommendation_row(rec) -> dict:
    return {
        "Add": f"{rec.add_name} ({rec.add_position} · {rec.add_team})",
        "Drop": rec.drop_name or "—",
        "Source": rec.source,
        "Value": round(rec.add_value, 1),
        "Why": rec.reason,
    }


st.title("🧢 Waiver Wire")

st.subheader("Data source")
st.caption(
    "CBS's Free Agent Recommendations page is login-gated — there's no button here that "
    "fetches live data on its own. Sign in via the link below, then ask Claude to capture "
    "and refresh this week's free-agent tables (see `src/data_sources/waiver_wire.py`'s "
    "docstring for the capture procedure)."
)
for label, url in LOGIN_LINKS.items():
    st.link_button(f"🔗 Log in & open {label}", url, use_container_width=True)

st.divider()

weeks = _available_weeks()
if not weeks:
    st.warning(
        "No waiver-wire data captured yet — ask Claude to capture this week's CBS free-agent "
        "tables (see `src/data_sources/waiver_wire.py`'s docstring) to get started."
    )
    st.stop()

config = get_config()
my_team = config["league"]["team_name"]

year, week = st.selectbox(
    "Week (for this-week free-agent values and bye-gap detection)",
    options=list(reversed(weeks)), format_func=lambda yw: f"{yw[0]} — Week {yw[1]}",
)

season_path = os.path.join(WAIVER_DIR, f"{year}_restofseason.csv")
if not os.path.exists(season_path):
    st.info(
        "No Rest-of-Season free-agent data captured for this year yet — season-long "
        "upgrade/bench-depth/full-roster-swap recommendations need it. Week-specific "
        "bye-gap recommendations can still work without it."
    )

# ---- Roster + transactions ----
real_team_order = config.get("draft", {}).get("team_order") or []
using_real_team_order = bool(real_team_order) and my_team in real_team_order
teams = real_team_order if using_real_team_order else (
    [my_team] + [f"Team {i}" for i in range(1, config["league"]["teams"])]
)
draft_state = DraftState(
    teams=teams, rounds=config["draft"]["rounds"], my_team=my_team,
    state_file=DRAFT_STATE_FILE, reverse_last_n_rounds=config["draft"].get("reverse_last_n_rounds", 0),
)
transactions = load_transactions(TRANSACTIONS_CSV)
all_rosters = current_roster_by_team(draft_state, transactions).rosters
my_picks = all_rosters.get(my_team, [])

if not my_picks:
    st.info("No picks on your roster yet — this page fills in once you've drafted/added players.")
    st.stop()

# ---- Week-specific signals (bye gap, tier 1) ----
week_points, is_starter_from_week, bye_names, week_names_seen = _week_matchup_signals(year, week, my_team)
if not week_points:
    st.caption(
        f"⚠️ No Weekly Matchup capture found for {year} Week {week} — the #1-priority "
        "\"empty starting slot\" check needs it and will show nothing below. Season-long "
        "recommendations are unaffected. Ask Claude to capture this week's matchup "
        "(see the Weekly Matchup page) to enable this."
    )

heuristic_slots, heuristic_bench = assign_roster_slots(my_picks, config["roster"]["starters"])
heuristic_starter_names = {p.player_name for filled in heuristic_slots.values() for p in filled if p is not None}

# ---- Season-long scoring, per source ----
cbs_season_path = os.path.join(PROJECTIONS_DIR, "cbs_2026.csv")
fp_season_path = os.path.join(PROJECTIONS_DIR, "fantasypoints_2026.csv")
cbs_season_df = (
    _scored_season_projections(cbs_season_path, "cbs", os.path.getmtime(cbs_season_path))
    if os.path.exists(cbs_season_path) else pd.DataFrame(columns=["name", "position", "nfl_team", "score_total"])
)
fp_season_df = (
    _scored_season_projections(fp_season_path, "fantasypoints", os.path.getmtime(fp_season_path))
    if os.path.exists(fp_season_path) else pd.DataFrame(columns=["name", "position", "nfl_team", "score_total"])
)
cbs_season_scores = dict(zip(cbs_season_df["name"], cbs_season_df["score_total"]))
fp_season_scores = dict(zip(fp_season_df["name"], fp_season_df["score_total"]))

# ---- Build roster + free-agent pools per source ----
roster_by_source = {
    "CBS": _cbs_roster_players(
        my_picks, week_points, is_starter_from_week, bye_names, cbs_season_scores, heuristic_starter_names,
    ),
    "FantasyPoints": _fantasypoints_roster_players(
        my_picks, is_starter_from_week, bye_names, fp_season_scores, heuristic_starter_names,
    ),
}
cbs_free_agents = _cbs_free_agents(year, week)
free_agents_by_source = {
    "CBS": cbs_free_agents,
    "FantasyPoints": _fantasypoints_free_agents(cbs_free_agents, fp_season_df),
}

recommendations = build_recommendations(
    roster_by_source, free_agents_by_source,
    config["roster"]["starters"], config["roster"]["roster_total_max"],
)

st.divider()

# Toggle (league-manager request, 2026-09-09: "be able to toggle between
# CBS and Fantasypoints projections to see if it affects recommendations")
# -- same candidate pool either way (see _fantasypoints_free_agents), just
# filters which source's recommendations drive the Top 3 / category views
# below, so switching it shows how the SAME real free agents rank
# differently depending which projection source is trusted.
source_filter = st.radio(
    "Projection source", ["Both", "CBS", "FantasyPoints"], horizontal=True,
    help="\"Both\" shows every recommendation, labeled by whichever source produced it. "
         "Switch to CBS or FantasyPoints alone to see how that one source's projections "
         "would change the picks.",
)
displayed = recommendations if source_filter == "Both" else [r for r in recommendations if r.source == source_filter]

st.subheader("🏆 Top pickup recommendations")
if not displayed:
    st.info("No recommendations right now — your roster looks solid against this week's free-agent pool.")
else:
    top3 = displayed[:3]
    cols = st.columns(len(top3))
    for col, rec in zip(cols, top3):
        with col:
            st.markdown(f"**{rec.add_name}** ({rec.add_position} · {rec.add_team})")
            st.caption(CATEGORY_LABELS[rec.category])
            st.metric(f"{rec.source} projection", f"{rec.add_value:.1f}")
            if rec.drop_name:
                st.caption(f"↔️ Drop: {rec.drop_name}")
            st.caption(rec.reason)

st.divider()
st.subheader("All recommendations by category")
if not displayed:
    st.caption("Nothing to show.")
else:
    for category, label in CATEGORY_LABELS.items():
        cat_recs = [r for r in displayed if r.category == category]
        if not cat_recs:
            continue
        with st.expander(f"{label} ({len(cat_recs)})", expanded=(category == "bye_gap")):
            st.dataframe(
                pd.DataFrame([_render_recommendation_row(r) for r in cat_recs]),
                hide_index=True, use_container_width=True,
            )

st.divider()
with st.expander("Your current roster (values used above)"):
    roster_rows = []
    for p in my_picks:
        roster_rows.append({
            "Player": p.player_name, "Pos": p.position, "NFL Team": p.nfl_team,
            "Starter this week": is_starter_from_week.get(p.player_name, p.player_name in heuristic_starter_names),
            "Bye this week": p.player_name in bye_names,
            "CBS week pts": week_points.get(p.player_name),
            "CBS season pts": cbs_season_scores.get(p.player_name),
            "FantasyPoints season pts": fp_season_scores.get(p.player_name),
        })
    st.dataframe(pd.DataFrame(roster_rows), hide_index=True, use_container_width=True)
    st.caption(
        f"{len(my_picks)} of {config['roster']['roster_total_max']} roster spots used."
    )

st.divider()
st.page_link("pages/4_My_Roster.py", label="← Back to My Roster", icon="📋")
