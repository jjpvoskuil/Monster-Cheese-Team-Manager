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

**Layout (league-manager request, 2026-09-09, superseding an earlier
full-width-stacked layout from the same day)**: both teams' grids side
by side again, but abbreviated to still avoid horizontal scrolling at
half the page width each -- Pos + NFL Team folded into one "Pos/Tm"
column, "Matchup" reduced from the full "TEAM vs. TEAM | kickoff time"
to just "vs OPP"/"@ OPP" (_abbreviate_matchup), player names shortened
to "F. Last" (_abbreviate_player_name), and slot headings shortened to
their standard short codes (_SLOT_ABBREVIATIONS). Each team's section is
ONLY a header immediately followed by its grid -- no caption in between
-- so the two side-by-side grids' rows line up; the highlight legend and
the "N starters missing a projection" note both moved out of that gap
(the legend to a single shared caption above both columns, "missing"
to below each team's own grid) after league-manager feedback that a
caption present in only one column was pushing that grid down relative
to the other's.

**Bench padding**: the bench grid pads with blank "(empty)" rows up to
roster.bench_max (config/league_settings.yaml -- 15, i.e. the league's
27-player roster cap minus the 12 active starters) when a team hasn't
used its whole roster, rather than just showing a shorter table for
whichever team has fewer bench players -- also a nice side effect for
keeping the two side-by-side bench grids the same height. See
_pad_bench_rows().
"""

from __future__ import annotations

import os
import re

import pandas as pd
import streamlit as st

from src.data_sources.weekly_projections import build_lookup, match_key
from src.injury_status import build_injury_lookup, capture_summary, injury_icon, load_injury_table, render_injury_notes_expander
from src.lineup_value import LineupPlayer, optimal_lineup_assignment
from src.scoring import load_config

# CBS's own slot-heading vocabulary (see src/data_sources/weekly_matchup.py's
# SLOT_HEADINGS / current_slot construction) -> a short label that fits a
# narrow side-by-side column. Anything not in this map (shouldn't happen,
# but a renamed CBS heading shouldn't crash the page) is shown as-is.
_SLOT_ABBREVIATIONS = {
    "Quarterbacks": "QB",
    "Running Backs": "RB",
    "Tight Ends": "TE",
    "Flex WR/TEs": "FLEX",
    "Kickers": "K",
    "Defense/STs": "DST",
    "Flex": "FLEX",
    "Bench": "Bench",
}

# Matches the "TEAM vs. TEAM" / "TEAM vs TEAM" / "TEAM @ TEAM" prefix of a
# matchup_desc (both the bench form and the starter form, which appends
# " | <time>" -- ignored here). See _abbreviate_matchup().
_MATCHUP_TEAMS_RE = re.compile(r"^([A-Za-z.]+)\s*(vs\.?|@)\s*([A-Za-z.]+)")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config", "league_settings.yaml")
MATCHUP_DIR = os.path.join(ROOT, "data", "weekly_matchups")
PROJECTIONS_DIR = os.path.join(ROOT, "data", "weekly_projections")
INJURY_CSV = os.path.join(ROOT, "data", "injury_report", "current.csv")

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
def _injury_lookup(mtime: float) -> tuple[dict, str | None]:
    # NOTE: must NOT have a leading underscore -- Streamlit's cache_data
    # silently excludes underscore-prefixed params from the cache key
    # (see pages/10_Trade_Finder.py's _injury_lookup() for the full
    # story of how this was found).
    df = load_injury_table(INJURY_CSV)
    return build_injury_lookup(df), capture_summary(df)


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


# League-manager feedback, 2026-09-09: wants both teams' grids SIDE BY SIDE
# (reverting the earlier full-width-stacked layout) but still no horizontal
# scrolling -- since side-by-side halves the available width per table,
# that now requires abbreviating content, not just narrowing columns: Pos
# and NFL Team are folded into one "Pos/Tm" column, Matchup drops the
# kickoff time and is reduced to just "vs OPP"/"@ OPP" (_abbreviate_matchup),
# player names shorten to "F. Last" (_abbreviate_player_name), and slot
# headings shorten to their standard short codes (_SLOT_ABBREVIATIONS). All
# columns stay "small" so 5 (starters) or 4 (bench) of them comfortably fit
# half a laptop-width browser window.
_STARTER_COLUMN_CONFIG = {
    "Slot": st.column_config.TextColumn(width="small"),
    "Player": st.column_config.TextColumn(width="small"),
    "Pos/Tm": st.column_config.TextColumn(width="small"),
    "Opp": st.column_config.TextColumn(width="small"),
    "Points": st.column_config.NumberColumn(width="small", format="%.1f"),
}
_BENCH_COLUMN_CONFIG = {k: v for k, v in _STARTER_COLUMN_CONFIG.items() if k != "Slot"}


def _abbreviate_slot(slot: str) -> str:
    return _SLOT_ABBREVIATIONS.get(slot, slot)


def _abbreviate_player_name(name: str) -> str:
    """"Patrick Mahomes" -> "P. Mahomes". Leaves single-word names (DST
    rows use just the team nickname, e.g. "Eagles") unchanged."""
    parts = str(name).split()
    if len(parts) < 2:
        return name
    return f"{parts[0][0]}. {' '.join(parts[1:])}"


def _abbreviate_matchup(desc, nfl_team: str) -> str:
    """"PHI vs. WAS | Sun 3:25PM CT" (starters) or "PHI vs. WAS" (bench) ->
    just "vs WAS" (or "@ CAR" for an away game) -- drops the kickoff time
    entirely and keeps only the OPPONENT half of the matchup (the player's
    own team, already shown in Pos/Tm, would be redundant here). Falls
    back to the raw text if it doesn't match the expected "TEAM vs/@ TEAM"
    shape (e.g. a bye week -- see _bye_names(), which already flags those
    separately via row highlighting)."""
    if not isinstance(desc, str) or not desc:
        return desc
    m = _MATCHUP_TEAMS_RE.match(desc.strip())
    if not m:
        return desc
    team_a, symbol, team_b = m.group(1), m.group(2), m.group(3)
    symbol = "@" if symbol.startswith("@") else "vs"
    opp = team_b if team_a.upper() == str(nfl_team).upper() else team_a
    return f"{symbol} {opp}"


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


def _row_style(row: pd.Series, index_to_name: pd.Series, should_start: set, should_bench: set, bye_names: set) -> list:
    # Matched by the ORIGINAL (full) player name via the row's index, not
    # row["Player"] -- that column now holds the abbreviated display name
    # ("P. Mahomes"), which wouldn't match should_start/should_bench/
    # bye_names (all built from full names). index_to_name is the same
    # index the display frame was built from (never reset), so this
    # lookup is stable across the rename/abbreviate step.
    name = index_to_name.get(row.name)
    if name in bye_names:
        color = "background-color: rgba(250, 204, 21, 0.35)"  # amber -- can't start (bye)
    elif name in should_start:
        color = "background-color: rgba(34, 197, 94, 0.28)"  # green -- should be starting
    elif name in should_bench:
        color = "background-color: rgba(239, 68, 68, 0.25)"  # red -- should bench instead
    else:
        return [""] * len(row)
    return [color] * len(row)


def _pad_bench_rows(
    bench_display: pd.DataFrame, full_names: pd.Series, bench_max: int | None,
) -> tuple[pd.DataFrame, pd.Series]:
    """Appends blank rows up to `bench_max` total (league-manager request,
    2026-09-09: roster.bench_max is 15 -- config/league_settings.yaml's
    roster.roster_total_max (27) minus roster.total_starters (12) -- show
    those as empty slots when a team hasn't filled its bench all the way,
    rather than just a shorter table). No-op (beyond the index reset
    below) if bench_max isn't given or the team's already at/over it
    (can't happen under the real roster cap, but a synthetic/test roster
    could exceed it, so this isn't enforced as an error here).

    Always renumbers the returned frame to a plain 0..N-1 RangeIndex
    (`ignore_index=True`) rather than keeping the real bench rows' CBS
    -derived index alongside string labels for the padded ones -- a
    mixed int/str index made Streamlit's Arrow serialization blow up
    (`pyarrow.lib.ArrowInvalid: Could not convert '__empty_0' ... to
    int64`), caught by this function's own test. Returns the padded
    frame together with a `full_names` Series reindexed to match (real
    names for real rows, None for padded ones) so callers can still
    style rows by the ORIGINAL full player name via that new positional
    index -- see _row_style, which looks up `index_to_name.get(row.name)`
    against whatever's returned here."""
    names = list(full_names)
    if bench_max and len(bench_display) < bench_max:
        pad_n = bench_max - len(bench_display)
        # Keyed by column NAME, not dtype -- pandas 3's default
        # infer_string setting makes text columns a "str" extension
        # dtype rather than plain numpy `object`, so a `dtype == object`
        # check silently misses them and fills text columns with NaN
        # instead of the intended blank text. Points is the only numeric
        # column in this frame; everything else here is text.
        blank_values = {"Player": "(empty)", "Pos/Tm": "", "Opp": "", "Points": float("nan")}
        empty_rows = pd.DataFrame({
            col: [blank_values.get(col, "")] * pad_n
            for col in bench_display.columns
        })
        bench_display = pd.concat([bench_display, empty_rows], ignore_index=True)
        names = names + [None] * pad_n
    else:
        bench_display = bench_display.reset_index(drop=True)
    return bench_display, pd.Series(names)


def _display_name(name: str, injury_lookup: dict) -> str:
    """Abbreviated display name with a trailing injury-status icon
    (src.injury_status.injury_icon) when flagged -- no room for a
    separate "Inj" column in this page's deliberately narrow
    side-by-side layout (see module docstring), so the icon rides
    along in the Player cell itself, same compact-space pattern as
    League Rosters' dense grid."""
    icon = injury_icon(name, injury_lookup)
    base = _abbreviate_player_name(name)
    return f"{base} {icon}" if icon else base


def _render_team_tables(
    df: pd.DataFrame, team: str, source: str, fp_lookup: dict,
    recommend: bool = False, starters_config: list[dict] | None = None,
    bench_max: int | None = None, injury_lookup: dict | None = None,
) -> float:
    injury_lookup = injury_lookup or {}
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

    # Just the header, immediately followed by the starters grid below --
    # league-manager feedback, 2026-09-09: any caption in between (the
    # "missing projection" note, the highlight legend) pushed that team's
    # grid down relative to the other team's when the two are side by
    # side, since only one side would have that line. The legend now lives
    # once, above both columns (see the page body below); "missing" moves
    # to AFTER the grid so it can't offset the grid's own top-alignment.
    st.markdown(f"#### {team} — {starter_total:.1f} pts ({source})")

    starters_display = pd.DataFrame({
        "Slot": starters["slot"].map(_abbreviate_slot),
        "Player": starters["player_name"].map(lambda n: _display_name(n, injury_lookup)),
        "Pos/Tm": starters["position"] + "·" + starters["nfl_team"],
        "Opp": [
            _abbreviate_matchup(desc, team)
            for desc, team in zip(starters["matchup_desc"], starters["nfl_team"])
        ],
        "Points": starters["Points"],
    }, index=starters.index)
    if should_start or should_bench or bye_names:
        starters_display = starters_display.style.apply(
            _row_style, axis=1, index_to_name=starters["player_name"],
            should_start=should_start, should_bench=should_bench, bye_names=bye_names,
        )
    st.dataframe(
        starters_display,
        hide_index=True, use_container_width=True, column_config=_STARTER_COLUMN_CONFIG,
    )
    if missing:
        st.caption(f"{missing} starter(s) have no {source} projection, not counted above")

    bench_names = set(bench["player_name"])
    bench_flagged = bool((should_start & bench_names) or (bye_names & bench_names))
    bench_label = f"Bench ({len(bench)} of {bench_max})" if bench_max else f"Bench ({len(bench)})"
    with st.expander(bench_label, expanded=bench_flagged):
        bench_display = pd.DataFrame({
            "Player": bench["player_name"].map(lambda n: _display_name(n, injury_lookup)),
            "Pos/Tm": bench["position"] + "·" + bench["nfl_team"],
            "Opp": [
                _abbreviate_matchup(desc, team)
                for desc, team in zip(bench["matchup_desc"], bench["nfl_team"])
            ],
            "Points": bench["Points"],
        }, index=bench.index)
        bench_display, bench_index_to_name = _pad_bench_rows(bench_display, bench["player_name"], bench_max)
        if should_start or should_bench or bye_names:
            bench_display = bench_display.style.apply(
                _row_style, axis=1, index_to_name=bench_index_to_name,
                should_start=should_start, should_bench=should_bench, bye_names=bye_names,
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

# One shared legend line above both columns, not a per-team caption --
# league-manager feedback, 2026-09-09: a caption only my team's column had
# (the recommend legend) pushed that grid down relative to the opponent's,
# breaking the side-by-side row alignment. Shown once here so each
# team's section below starts with nothing but its header, then its grid.
st.caption(
    "🟩 should be in your starting lineup this week · 🟥 bench this player instead "
    "· 🟨 on a bye — can't legally start (either team's grid, whichever applies) · "
    "🚑❌❓⚠️ injury/practice-report flag (see notes below)"
)

injury_lookup, injury_as_of = _injury_lookup(
    os.path.getmtime(INJURY_CSV) if os.path.exists(INJURY_CSV) else 0.0
)

# Side by side (league-manager request, 2026-09-09, reverting the earlier
# full-width-stacked layout) -- the abbreviated columns above (Pos/Tm, Opp,
# shortened names/slots) are what keep each half-width table from forcing
# horizontal scroll now that they're back to sharing the page.
my_col, opp_col = st.columns(2)
with my_col:
    my_total = _render_team_tables(
        df, my_team_display, source, fp_lookup,
        recommend=True, starters_config=config["roster"]["starters"],
        bench_max=config["roster"]["bench_max"], injury_lookup=injury_lookup,
    )
with opp_col:
    opp_total = _render_team_tables(
        df, opp_display, source, fp_lookup,
        bench_max=config["roster"]["bench_max"], injury_lookup=injury_lookup,
    )

render_injury_notes_expander(df["player_name"].dropna().unique().tolist(), injury_lookup)
if injury_as_of:
    st.caption(injury_as_of)

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
