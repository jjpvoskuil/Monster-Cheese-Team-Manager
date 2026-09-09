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
"""

from __future__ import annotations

import os
import re

import pandas as pd
import streamlit as st

from src.data_sources.weekly_projections import build_lookup, match_key
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


def _render_team_tables(df: pd.DataFrame, team: str, source: str, fp_lookup: dict) -> float:
    team_df = df[df["team"] == team].copy()
    team_df["Points"] = _points_column(team_df, source, fp_lookup)

    starters = team_df[team_df["roster_group"] == "starter"].sort_values("order")
    bench = team_df[team_df["roster_group"] == "bench"].sort_values("order")

    starter_total = starters["Points"].sum(skipna=True)
    missing = int(starters["Points"].isna().sum())

    st.markdown(f"#### {team}")
    st.dataframe(
        starters[["slot", "player_name", "position", "nfl_team", "matchup_desc", "Points"]].rename(
            columns={"slot": "Slot", "player_name": "Player", "position": "Pos",
                     "nfl_team": "NFL Team", "matchup_desc": "Matchup"}
        ),
        hide_index=True, use_container_width=True,
    )
    st.caption(f"**Starting lineup total ({source}): {starter_total:.1f} pts**" + (
        f" — {missing} starter(s) have no {source} projection, not counted above" if missing else ""
    ))

    with st.expander(f"Bench ({len(bench)})"):
        st.dataframe(
            bench[["player_name", "position", "nfl_team", "matchup_desc", "Points"]].rename(
                columns={"player_name": "Player", "position": "Pos",
                         "nfl_team": "NFL Team", "matchup_desc": "Matchup"}
            ),
            hide_index=True, use_container_width=True,
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

st.caption(f"**{away_team} @ {home_team}** — Week {week}, {year} · last captured "
           f"{pd.Timestamp(matchup_mtime, unit='s').strftime('%Y-%m-%d %H:%M')}")

st.divider()

col1, col2 = st.columns(2)
with col1:
    my_total = _render_team_tables(df, my_team_display, source, fp_lookup)
with col2:
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
