"""
Weekly Matchup — this week's Monster Cheese vs. opponent scoring preview,
laid out the same way CBS's own "Scoring Preview" page shows it (by
starting-lineup slot, then bench), with a toggle to view either CBS's
own weekly point projections or FantasyPoints.com's.

**Lineups come from CBS, not this app's own heuristic** (league-manager
request, 2026-09-09): unlike My Roster / League Rosters (which recompute
"who'd be starting" via src.roster_needs.assign_roster_slots), this page
shows exactly who CBS has slotted as starters vs. bench for BOTH teams
this week -- real in-season lineup decisions (byes, injuries, a manager
benching someone) that a heuristic replayed from draft day can't see.
That data comes from a raw-captured CBS "Scoring Preview" page, parsed
by src.data_sources.weekly_matchup -- see that module's docstring for
the full capture procedure and page-layout notes.

**Why a page, not a live pull**: CBS and FantasyPoints are both login
-gated sites (see src/data_sources/cbs.py, fantasypoints.py) -- there's
no plain-HTTP path a deployed Streamlit app can hit on its own. Getting
a new week's data in is always: ask Claude ("update this week's
matchup", "refresh fantasypoints weekly projections", or similar) to
capture it via a live logged-in browser session and commit the result --
same two-stage raw-capture-then-parse pattern as draft_history/
transactions/projections. The "Log in & refresh" buttons below just open
each site so you (the league manager) can sign in; the actual capture
still needs to be a live Claude session, per the league's git/credential
workflow (SESSION_NOTES.md) which never wants a password pasted into
chat. New data pulls aren't limited to these two sources or this one
shape -- ask for whatever's useful and a new raw-capture format gets
added here.

Week selector reads whichever data/weekly_matchups/{year}_week{N}.csv
files exist (scripts/fetch_weekly_matchup.py writes one per captured
week) -- add a new week by capturing + running that script, no code
change needed here.

**Start/bench highlighting (Monster Cheese only, league-manager request
2026-09-09)**: runs src.lineup_value.optimal_lineup_assignment() over
Monster Cheese's full roster (starters + bench) using whichever
projection `source` is currently toggled, and highlights green any
benched player who belongs in the optimal 12 and red any current
starter who doesn't -- same optimal-assignment solver
scripts/simulate_draft.py already uses, not a new heuristic. Recomputed
live on every source/week change, not cached, since it's cheap (12
slots, <30 players). Not shown for the opponent -- there's no "should
start" advice to give about someone else's roster.

**Bye-week highlighting (both teams)**: a player whose matchup_desc
reads as a bye is flagged amber wherever they appear (bench, or --
worse -- still sitting in a starting slot) and excluded entirely from
the start/bench solver above, since starting them isn't legal no matter
how good their projection looks. See _bye_names()'s docstring: no real
captured week has actually contained a bye yet (Week 1 has none), so
the "bye" text match hasn't been cross-validated against a live CBS
capture -- revisit if a captured week ever shows different wording.
"""

from __future__ import annotations

import os
import re

import pandas as pd
import streamlit as st

from src.data_sources.weekly_projections import build_lookup, match_key
from src.lineup_value import LineupPlayer, optimal_lineup_assignment
from src.scoring import load_config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config", "league_settings.yaml")
MATCHUP_DIR = os.path.join(ROOT, "data", "weekly_matchups")
PROJECTIONS_DIR = os.path.join(ROOT, "data", "weekly_projections")

MATCHUP_FILE_RE = re.compile(r"^(\d{4})_week(\d+)\.csv$")

LOGIN_LINKS = {
    "CBS Scoring Preview": "https://maniacfl.football.cbssports.com/scores",
    "FantasyPoints Weekly Projections": "https://www.fantasypoints.com/nfl/projections",
}


@st.cache_resource
def get_config():
    return load_config(CONFIG_PATH)


def _available_weeks() -> list[tuple[int, int]]:
    if not os.path.isdir(MATCHUP_DIR):
        return []
    weeks = []
    for name in os.listdir(MATCHUP_DIR):
        m = MATCHUP_FILE_RE.match(name)
        if m:
            weeks.append((int(m.group(1)), int(m.group(2))))
    return sorted(weeks)


@st.cache_data
def _load_matchup(year: int, week: int, _mtime: float) -> pd.DataFrame:
    return pd.read_csv(os.path.join(MATCHUP_DIR, f"{year}_week{week}.csv"))


@st.cache_data
def _load_fantasypoints_lookup(year: int, week: int, _mtime: float) -> dict:
    path = os.path.join(PROJECTIONS_DIR, f"fantasypoints_{year}_week{week}.csv")
    if not os.path.exists(path):
        return {}
    rows = pd.read_csv(path).to_dict(orient="records")
    return build_lookup(rows)


def _points_column(df: pd.DataFrame, source: str, fp_lookup: dict) -> pd.Series:
    if source == "CBS":
        return df["cbs_points"]
    if df.empty:
        # df.apply(..., axis=1) on an empty DataFrame returns an empty
        # DataFrame, not a Series (a pandas quirk) -- short-circuit rather
        # than let that blow up the assignment below.
        return pd.Series([], dtype="float64", index=df.index)
    keys = df.apply(lambda r: match_key(r["player_name"], r["position"], r["nfl_team"]), axis=1)
    return keys.map(fp_lookup)  # NaN where FantasyPoints has no row for this player


# Explicit narrow widths for the short columns so "Points" (the one column
# a scroll would most annoyingly hide) always stays on-screen without
# horizontal scrolling, even on a laptop-width browser window -- paired
# with rendering each team's table full-width (one team, then the next,
# not side-by-side st.columns) rather than squeezing two tables into half
# the page each. See league-manager feedback, 2026-09-09.
_STARTER_COLUMN_CONFIG = {
    "Slot": st.column_config.TextColumn(width="medium"),
    "Player": st.column_config.TextColumn(width="medium"),
    "Pos": st.column_config.TextColumn(width="small"),
    "NFL Team": st.column_config.TextColumn(width="small"),
    "Matchup": st.column_config.TextColumn(width="medium"),
    "Points": st.column_config.NumberColumn(width="small", format="%.1f"),
}
_BENCH_COLUMN_CONFIG = {k: v for k, v in _STARTER_COLUMN_CONFIG.items() if k != "Slot"}


def _team_total(df: pd.DataFrame, team: str, source: str, fp_lookup: dict) -> tuple[float, int]:
    """Starting-lineup point total (+ count of starters missing a
    projection from `source`) -- split out from rendering so the total can
    be shown next to the team name before the table itself is drawn."""
    team_df = df[df["team"] == team]
    starters = team_df[team_df["roster_group"] == "starter"]
    points = _points_column(starters, source, fp_lookup)
    return points.sum(skipna=True), int(points.isna().sum())


def _bye_names(team_df: pd.DataFrame) -> set:
    """Player names on this team whose matchup_desc reads as a bye week
    (league-manager request, 2026-09-09: "highlight in a different color
    so I know I cannot start that person"). CBS's Scoring Preview page
    hasn't actually shown us a real bye-week row yet (none fall in Week 1,
    the only week captured so far -- see src/data_sources/weekly_matchup.py)
    so this is a best-effort text match ("bye" appearing anywhere in the
    matchup description) rather than something cross-validated against a
    real capture. Revisit this if a captured week ever shows CBS using
    different wording for a bye."""
    desc = team_df["matchup_desc"].fillna("")
    return set(team_df.loc[desc.str.contains("bye", case=False), "player_name"])


def _compute_recommendations(team_df: pd.DataFrame, bye_names: set, starters_config: list[dict]) -> tuple[set, set]:
    """Which currently-benched players should be starting instead, and
    which currently-started players should be benched, based on
    src.lineup_value's optimal-assignment solver run over this team's full
    roster (starters ∪ bench) using whichever projection source's Points
    column is already on team_df. Bye-week players are excluded from the
    solver's player pool entirely (they can't legally start no matter how
    good their projection would otherwise be) -- a currently-started bye
    player therefore always comes back as "should bench" too, since they
    can never appear in the optimal set."""
    current_starters = set(team_df.loc[team_df["roster_group"] == "starter", "player_name"])
    pool = team_df[~team_df["player_name"].isin(bye_names)]
    players = [
        LineupPlayer(
            name=row.player_name,
            position=row.position,
            points=0.0 if pd.isna(row.Points) else float(row.Points),
        )
        for row in pool.itertuples()
    ]
    assignment = optimal_lineup_assignment(players, starters_config)
    optimal_names = {a.player.name for a in assignment if a.player is not None}
    should_start = optimal_names - current_starters
    should_bench = (current_starters - optimal_names) | (current_starters & bye_names)
    return should_start, should_bench


def _row_style(row: pd.Series, should_start: set, should_bench: set, bye_names: set) -> list:
    name = row["Player"]
    if name in bye_names:
        color = "background-color: rgba(250, 204, 21, 0.35)"  # amber -- can't start (bye)
    elif name in should_start:
        color = "background-color: rgba(34, 197, 94, 0.28)"  # green -- should be starting
    elif name in should_bench:
        color = "background-color: rgba(239, 68, 68, 0.25)"  # red -- should bench instead
    else:
        return [""] * len(row)
    return [color] * len(row)


def _render_team_tables(
    df: pd.DataFrame, team: str, source: str, fp_lookup: dict,
    recommend: bool = False, starters_config: list[dict] | None = None,
) -> float:
    team_df = df[df["team"] == team].copy()
    team_df["Points"] = _points_column(team_df, source, fp_lookup)
    bye_names = _bye_names(team_df)

    starters = team_df[team_df["roster_group"] == "starter"].sort_values("order")
    bench = team_df[team_df["roster_group"] == "bench"].sort_values("order")

    starter_total = starters["Points"].sum(skipna=True)
    missing = int(starters["Points"].isna().sum())

    should_start: set = set()
    should_bench: set = set()
    if recommend and starters_config is not None:
        should_start, should_bench = _compute_recommendations(team_df, bye_names, starters_config)

    st.markdown(f"#### {team} — {starter_total:.1f} pts ({source})")
    if missing:
        st.caption(f"{missing} starter(s) have no {source} projection, not counted above")
    if recommend:
        st.caption(
            "🟩 should be in your starting lineup this week · 🟥 bench this player instead"
            + (" · 🟨 on a bye — cannot start" if bye_names else "")
        )
    elif bye_names:
        st.caption("🟨 on a bye this week")

    starters_display = starters[["slot", "player_name", "position", "nfl_team", "matchup_desc", "Points"]].rename(
        columns={"slot": "Slot", "player_name": "Player", "position": "Pos",
                 "nfl_team": "NFL Team", "matchup_desc": "Matchup"}
    )
    if should_start or should_bench or bye_names:
        starters_display = starters_display.style.apply(
            _row_style, axis=1, should_start=should_start, should_bench=should_bench, bye_names=bye_names
        )
    st.dataframe(
        starters_display,
        hide_index=True, use_container_width=True, column_config=_STARTER_COLUMN_CONFIG,
    )

    bench_names = set(bench["player_name"])
    bench_flagged = bool((should_start & bench_names) or (bye_names & bench_names))
    with st.expander(f"Bench ({len(bench)})", expanded=bench_flagged):
        bench_display = bench[["player_name", "position", "nfl_team", "matchup_desc", "Points"]].rename(
            columns={"player_name": "Player", "position": "Pos",
                     "nfl_team": "NFL Team", "matchup_desc": "Matchup"}
        )
        if should_start or should_bench or bye_names:
            bench_display = bench_display.style.apply(
                _row_style, axis=1, should_start=should_start, should_bench=should_bench, bye_names=bye_names
            )
        st.dataframe(
            bench_display,
            hide_index=True, use_container_width=True, column_config=_BENCH_COLUMN_CONFIG,
        )

    return starter_total


st.title("🆚 Weekly Matchup")

st.subheader("Data sources")
st.caption(
    "CBS and FantasyPoints are both login-gated — there's no button here that fetches "
    "live data on its own. Sign in via the links below, then ask Claude to capture and "
    "refresh whatever's needed (this week's matchup, updated projections, a different "
    "source entirely — the capture format is flexible, not locked to these two)."
)
link_cols = st.columns(len(LOGIN_LINKS))
for col, (label, url) in zip(link_cols, LOGIN_LINKS.items()):
    with col:
        st.link_button(f"🔗 Log in & open {label}", url, use_container_width=True)

st.divider()

weeks = _available_weeks()
if not weeks:
    st.warning(
        "No weekly matchup data yet — ask Claude to capture this week's CBS Scoring "
        "Preview page (see `src/data_sources/weekly_matchup.py`'s docstring) to get started."
    )
    st.stop()

config = get_config()
my_team = config["league"]["team_name"]

wcol1, wcol2 = st.columns([1, 2])
with wcol1:
    year, week = st.selectbox(
        "Week", options=list(reversed(weeks)),
        format_func=lambda yw: f"{yw[0]} — Week {yw[1]}",
    )
with wcol2:
    source = st.radio("Projection source", ["CBS", "FantasyPoints"], horizontal=True)

matchup_path = os.path.join(MATCHUP_DIR, f"{year}_week{week}.csv")
matchup_mtime = os.path.getmtime(matchup_path)
df = _load_matchup(year, week, matchup_mtime)

fp_path = os.path.join(PROJECTIONS_DIR, f"fantasypoints_{year}_week{week}.csv")
fp_mtime = os.path.getmtime(fp_path) if os.path.exists(fp_path) else 0.0
fp_lookup = _load_fantasypoints_lookup(year, week, fp_mtime)
if source == "FantasyPoints" and not fp_lookup:
    st.warning(
        f"No FantasyPoints weekly projections captured for {year} Week {week} yet — "
        "showing blank point values below. Ask Claude to capture "
        "`data/weekly_projections/raw/fantasypoints/{}_week{}_all.txt`.".format(year, week)
    )

teams_this_week = df[["away_team", "home_team"]].iloc[0]
away_team, home_team = teams_this_week["away_team"], teams_this_week["home_team"]
opponent = home_team if my_team == away_team else away_team
if my_team not in (away_team, home_team):
    st.info(
        f"Monster Cheese ({my_team}) isn't one of the two teams captured for this matchup "
        f"({away_team} @ {home_team}) — showing both teams as captured."
    )
    my_team_display, opp_display = away_team, home_team
else:
    my_team_display, opp_display = my_team, opponent

# Totals next to each team name (league-manager request, 2026-09-09) --
# computed once here so the top summary line, each team's own section
# header, and the final scoreline below all agree on the same numbers.
away_total, _ = _team_total(df, away_team, source, fp_lookup)
home_total, _ = _team_total(df, home_team, source, fp_lookup)

st.caption(
    f"**{away_team} ({away_total:.1f}) @ {home_team} ({home_total:.1f})** — Week {week}, "
    f"{year} · last captured {pd.Timestamp(matchup_mtime, unit='s').strftime('%Y-%m-%d %H:%M')}"
)

st.divider()

# Each team's table gets the FULL page width, one after the other, rather
# than two tables squeezed side by side into half the width each -- that
# side-by-side layout was what forced horizontal scrolling to see the
# Points column (league-manager feedback, 2026-09-09).
my_total = _render_team_tables(
    df, my_team_display, source, fp_lookup,
    recommend=True, starters_config=config["roster"]["starters"],
)
st.divider()
opp_total = _render_team_tables(df, opp_display, source, fp_lookup)

st.divider()
diff = my_total - opp_total
verdict = "🟢 favored" if diff > 0 else ("🔴 underdog" if diff < 0 else "⚪ dead even")
st.subheader(
    f"{my_team_display} {my_total:.1f} — {opp_total:.1f} {opp_display}  ({verdict}, "
    f"{'+' if diff >= 0 else ''}{diff:.1f} by {source})"
)

st.divider()
download_df = df.copy()
download_df["points_cbs"] = df["cbs_points"]
download_df["points_fantasypoints"] = _points_column(df, "FantasyPoints", fp_lookup)
st.download_button(
    "⬇️ Download this matchup as CSV",
    data=download_df.to_csv(index=False),
    file_name=f"weekly_matchup_{year}_week{week}.csv",
    mime="text/csv",
    use_container_width=True,
)
