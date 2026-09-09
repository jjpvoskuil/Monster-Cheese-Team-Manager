"""
Trade Finder -- proposes multi-player trades with other teams in the
league, ranked by src/trade_recommendations.py. League-manager request,
2026-09-09 (see that module's docstring for the full request text and
the reasoning behind every design choice below -- this page is
deliberately thin: load real data, hand it to the pure trade-matching
engine, render what comes back).

TWO LENSES, ON PURPOSE: my own needs/surplus and how much I gain are
judged by FantasyPoints projections (the source trusted for this
analysis, per the league-manager's explicit request); the OTHER team's
needs/surplus and how much THEY gain are judged by CBS projections
(since "most other teams will use CBS"). A trade only gets proposed
when BOTH sides clear a positive-gain bar under their OWN trusted
source -- see src/trade_recommendations.find_trades. Every proposal
also shows what CBS would say I gained, specifically to surface the
risk the league manager flagged: "situations where Fantasypoints values
a player higher than CBS might make the trade seem better than it
actual is."

VALUE METRIC: VOR (this league's real per-position replacement level --
same src.projections framework as the Draft Board), not raw points --
see src.season_scoring's docstring for why.

DATA: every current roster (src.roster_state.current_roster_by_team,
all 10 teams) joined by exact name match against src.season_scoring's
CBS- and FantasyPoints-scored season projections (data/projections/
cbs_2026.csv, fantasypoints_2026.csv -- the same season files the
Waiver Wire and Draft Board pages already use). A rostered player
missing from one or both projection sources (name mismatch, or a source
never projected them) gets a VOR of 0 for that source rather than being
dropped -- shown separately below as a data-quality note, same
transparency spirit as pages/6_League_Rosters.py's "no projection found
for" warning, since silently treating an unprojected player as
worthless would bias needs/surplus around them.

Bye weeks (for the informational "bonus: also helps bye-week risk"
note) come from data/waiver_wire's own captured BYE column -- an NFL
team's bye week is a fixed schedule fact independent of fantasy roster
status, so this reuses that data rather than needing a new capture; not
every NFL team necessarily appears if no waiver-wire data has been
captured yet, in which case bye notes just don't show up.
"""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from src.data_sources.transactions import load_transactions
from src.draft_state import DraftState
from src.roster_state import current_roster_by_team
from src.scoring import load_config
from src.season_scoring import load_scored_season_source
from src.trade_recommendations import TeamPlayer, find_trades
from src.ui_text import team_text_column

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config", "league_settings.yaml")
DRAFT_STATE_FILE = os.path.join(ROOT, "data", "draft_state.json")
TRANSACTIONS_CSV = os.path.join(ROOT, "data", "transactions", "transactions.csv")
PROJECTIONS_DIR = os.path.join(ROOT, "data", "projections")
WAIVER_DIR = os.path.join(ROOT, "data", "waiver_wire")

MAX_PLAYERS_PER_SIDE = 3


@st.cache_resource
def get_config():
    return load_config(CONFIG_PATH)


@st.cache_data
def _scored_season(path: str, source: str, _mtime: float) -> pd.DataFrame:
    return load_scored_season_source(path, source, get_config())


@st.cache_data
def _nfl_bye_weeks(_mtime: float) -> dict:
    """nfl_team -> bye week, built from whichever data/waiver_wire/
    *_restofseason.csv (preferred -- covers every position group) or
    *_week*.csv (fallback) files exist. Empty dict if none captured yet
    -- bye notes just won't appear anywhere, not an error."""
    if not os.path.isdir(WAIVER_DIR):
        return {}
    candidates = sorted(
        (f for f in os.listdir(WAIVER_DIR) if f.endswith("_restofseason.csv")), reverse=True
    ) or sorted((f for f in os.listdir(WAIVER_DIR) if f.endswith(".csv")), reverse=True)
    if not candidates:
        return {}
    df = pd.read_csv(os.path.join(WAIVER_DIR, candidates[0]))
    df = df[df["nfl_team"] != "FA"]
    return df.groupby("nfl_team")["bye_week"].agg(lambda s: s.mode().iat[0] if not s.mode().empty else None).to_dict()


def _build_team_players(
    picks: list, cbs_scores: dict, fp_scores: dict, bye_weeks: dict,
) -> tuple[list[TeamPlayer], list[str]]:
    players = []
    unmatched = []
    for p in picks:
        fp_vor = fp_scores.get(p.player_name)
        cbs_vor = cbs_scores.get(p.player_name)
        if fp_vor is None and cbs_vor is None:
            unmatched.append(p.player_name)
        players.append(TeamPlayer(
            name=p.player_name, position=p.position, nfl_team=p.nfl_team,
            fp_vor=fp_vor or 0.0, cbs_vor=cbs_vor or 0.0,
            bye_week=bye_weeks.get(p.nfl_team),
        ))
    return players, unmatched


st.title("🔄 Trade Finder")

st.caption(
    "Every recommendation below is judged two ways: your gain by FantasyPoints projections "
    "(the source trusted for this analysis), and the other team's gain by CBS projections "
    "(what most other teams are assumed to use) — a trade only shows up here when BOTH sides "
    "come out ahead under their own trusted source. Value is VOR (value over this league's "
    "real replacement level at that position), same framework as the Draft Board."
)

config = get_config()
my_team = config["league"]["team_name"]

cbs_path = os.path.join(PROJECTIONS_DIR, "cbs_2026.csv")
fp_path = os.path.join(PROJECTIONS_DIR, "fantasypoints_2026.csv")
if not os.path.exists(cbs_path) or not os.path.exists(fp_path):
    st.warning("Missing `data/projections/cbs_2026.csv` and/or `fantasypoints_2026.csv` — nothing to compare yet.")
    st.stop()

cbs_df = _scored_season(cbs_path, "cbs", os.path.getmtime(cbs_path))
fp_df = _scored_season(fp_path, "fantasypoints", os.path.getmtime(fp_path))
cbs_scores = dict(zip(cbs_df["name"], cbs_df["vor"]))
fp_scores = dict(zip(fp_df["name"], fp_df["vor"]))

waiver_mtime = max(
    (os.path.getmtime(os.path.join(WAIVER_DIR, f)) for f in os.listdir(WAIVER_DIR)) if os.path.isdir(WAIVER_DIR) else [0.0],
    default=0.0,
)
bye_weeks = _nfl_bye_weeks(waiver_mtime)

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

if not all_rosters.get(my_team):
    st.info("No picks on your roster yet — this page fills in once you've drafted/added players.")
    st.stop()

rosters: dict[str, list[TeamPlayer]] = {}
all_unmatched: dict[str, list[str]] = {}
for team, picks in all_rosters.items():
    players, unmatched = _build_team_players(picks, cbs_scores, fp_scores, bye_weeks)
    rosters[team] = players
    if unmatched:
        all_unmatched[team] = unmatched

if all_unmatched:
    total_unmatched = sum(len(v) for v in all_unmatched.values())
    with st.expander(f"⚠️ {total_unmatched} rostered player(s) missing from both projection sources"):
        st.caption(
            "Treated as 0 VOR below (name mismatch between the draft log and the projection file, "
            "or a source that never projected this player) rather than dropped — this can understate "
            "a team's real need/surplus at that player's position."
        )
        for team, names in all_unmatched.items():
            st.caption(f"**{team}**: {', '.join(names)}")

trades = find_trades(my_team, rosters, config["roster"]["starters"], max_players_per_side=MAX_PLAYERS_PER_SIDE)

st.divider()
st.subheader("🤝 Proposed trades")

teams_with_rosters = [t for t in all_rosters if t != my_team and all_rosters.get(t)]
teams_without_trade = sorted(set(teams_with_rosters) - {t.other_team for t in trades})

if not trades:
    st.info(
        "No trades clear both bars right now — either no team has a complementary need/surplus "
        "match with you, or the numbers don't work out in both teams' favor under their own "
        "trusted projection source."
    )
else:
    for trade in trades:
        with st.container(border=True):
            st.markdown(f"### ↔️ {my_team} ⇄ {trade.other_team}")
            col1, col2 = st.columns(2)
            with col1:
                st.markdown(f"**You give** ({', '.join(sorted(trade.give_positions))})")
                st.dataframe(
                    pd.DataFrame([
                        {"Player": p.name, "Pos": p.position, "Team": p.nfl_team,
                         "FantasyPoints VOR": round(p.fp_vor, 1), "CBS VOR": round(p.cbs_vor, 1)}
                        for p in trade.give
                    ]),
                    hide_index=True, use_container_width=True,
                )
            with col2:
                st.markdown(f"**You get** ({', '.join(sorted(trade.get_positions))})")
                st.dataframe(
                    pd.DataFrame([
                        {"Player": p.name, "Pos": p.position, "Team": p.nfl_team,
                         "FantasyPoints VOR": round(p.fp_vor, 1), "CBS VOR": round(p.cbs_vor, 1)}
                        for p in trade.get
                    ]),
                    hide_index=True, use_container_width=True,
                )

            m1, m2, m3 = st.columns(3)
            m1.metric("Your gain (FantasyPoints)", f"{trade.fp_gain_mine:+.1f}")
            m2.metric("Your gain (CBS)", f"{trade.cbs_gain_mine:+.1f}")
            m3.metric(f"{trade.other_team}'s gain (CBS)", f"{trade.cbs_gain_theirs:+.1f}")

            if trade.cbs_gain_mine <= 0:
                st.warning(
                    f"⚠️ This trade only looks good under FantasyPoints — CBS would say you "
                    f"{'break even' if trade.cbs_gain_mine == 0 else 'actually lose value'} "
                    f"({trade.cbs_gain_mine:+.1f}). Since most other teams use CBS, "
                    f"{trade.other_team} may value this differently than the numbers above suggest, "
                    "or push back on the specific players involved."
                )
            elif trade.cbs_gain_mine < trade.fp_gain_mine * 0.5:
                st.caption(
                    f"ℹ️ FantasyPoints likes this trade for you more than CBS does "
                    f"({trade.fp_gain_mine:+.1f} vs {trade.cbs_gain_mine:+.1f}) — still a gain either way, "
                    "just a smaller one if CBS's numbers turn out closer to reality."
                )

            if trade.bye_note:
                st.caption(trade.bye_note)

if teams_without_trade:
    st.caption(
        "No trade basis found with: " + ", ".join(teams_without_trade) +
        " (no complementary need/surplus match, or the numbers didn't clear both sides' bars)."
    )

st.divider()
with st.expander("All rosters (VOR used above)"):
    rows = []
    for team, players in rosters.items():
        for p in players:
            rows.append({
                "Team": team, "Player": p.name, "Pos": p.position, "NFL Team": p.nfl_team,
                "Bye": p.bye_week, "FantasyPoints VOR": round(p.fp_vor, 1), "CBS VOR": round(p.cbs_vor, 1),
            })
    st.dataframe(
        pd.DataFrame(rows), hide_index=True, use_container_width=True,
        column_config={"Team": team_text_column("Team", list(rosters.keys()))},
    )

st.divider()
st.page_link("pages/4_My_Roster.py", label="← Back to My Roster", icon="📋")
