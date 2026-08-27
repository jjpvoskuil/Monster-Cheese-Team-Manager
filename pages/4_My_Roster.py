"""
My Roster — Monster Cheese's drafted players, organized by starting
-lineup slot (config/league_settings.yaml -> roster.starters), filling in
live as picks are logged. Reads the same data/draft_state.json every
other page does, so a pick logged from the Draft Board's clickable grid,
its Suggested Pick shortlist, or an active CBS live sync all show up here
immediately on the next rerun/refresh -- no separate wiring needed.

Slot assignment (src.roster_needs.assign_roster_slots) is a heuristic,
same spirit as the opponent-needs inference it's built from: dedicated
slots (QB/RB/TE/K/DST) are filled first, then the broader flex slots
(WR_TE_FLEX/SUPERFLEX/FLEX), earliest-drafted player first among each
slot's eligible positions. It's "if the draft stopped right now, this is
how the lineup would fill in" -- not a claim about your actual intended
starters, which is exactly the same caveat src/roster_needs.py documents
for reading opponents.
"""

from __future__ import annotations

import os

import pandas as pd
import streamlit as st

from src.draft_state import DraftState
from src.roster_needs import assign_roster_slots
from src.scoring import load_config

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(ROOT, "config", "league_settings.yaml")
DRAFT_STATE_FILE = os.path.join(ROOT, "data", "draft_state.json")

st.set_page_config(page_title="My Roster — Monster Cheese", page_icon="📋", layout="wide")


@st.cache_resource
def get_config():
    return load_config(CONFIG_PATH)


config = get_config()

# Same live-team-order resolution as the Draft Board / Draft Tendencies
# pages, so DraftState's team list (and therefore my_team's snake slot)
# always matches what's actually being used elsewhere in the app.
real_team_order = config.get("draft", {}).get("team_order") or []
using_real_team_order = bool(real_team_order) and config["league"]["team_name"] in real_team_order
if using_real_team_order:
    teams = real_team_order
else:
    teams = [config["league"]["team_name"]] + [f"Team {i}" for i in range(1, config["league"]["teams"])]

draft_state = DraftState(
    teams=teams,
    rounds=config["draft"]["rounds"],
    my_team=config["league"]["team_name"],
    state_file=DRAFT_STATE_FILE,
    reverse_last_n_rounds=config["draft"].get("reverse_last_n_rounds", 0),
)

st.title(f"📋 My Roster — {config['league']['team_name']}")

my_picks = draft_state.my_roster()
starters = config["roster"]["starters"]
slots, bench = assign_roster_slots(my_picks, starters)

roster_cfg = config["roster"]
st.caption(
    f"{len(my_picks)} player(s) drafted · {roster_cfg['total_starters']} starting slots · "
    f"roster limit {roster_cfg['roster_total_min']}-{roster_cfg['roster_total_max']}"
)
if not my_picks:
    st.info("No picks yet — this page fills in as you draft.")

st.divider()
st.subheader("Starting lineup")

# Display-only relabeling -- doesn't touch eligibility/assignment logic
# (src.roster_needs still sees "SUPERFLEX" and its real QB/RB/WR/TE
# eligible list). Per league-manager feedback: this league's scoring
# makes SUPERFLEX an automatic QB start every week (see
# config/league_settings.yaml's flex_position_splits.SUPERFLEX comment,
# 100% QB), so labeling the slot "QB (Flex)" here reads more honestly than
# the generic "SUPERFLEX" name while still being clearly a flex slot.
SLOT_DISPLAY_NAMES = {"SUPERFLEX": "QB (Flex)"}

rows = []
for slot in starters:
    filled = slots.get(slot["slot"], [None] * slot["count"])
    label_base = SLOT_DISPLAY_NAMES.get(slot["slot"], slot["slot"].replace("_", " "))
    for i, pick in enumerate(filled, start=1):
        label = label_base if slot["count"] == 1 else f"{label_base} {i}"
        if pick is not None:
            rows.append({
                "Slot": label,
                "Player": pick.player_name,
                "Pos": pick.position,
                "NFL Team": pick.nfl_team,
                "Rd": pick.round,
                "Pick": pick.overall_pick,
            })
        else:
            rows.append({
                "Slot": label,
                "Player": "— empty —",
                "Pos": "/".join(slot["eligible"]),
                "NFL Team": "",
                "Rd": None,
                "Pick": None,
            })

st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

st.divider()
st.subheader("Draft Requirements")
st.caption(
    'Per the "Maniac Football League Draft Sheet" (loaded 2026-08-27): '
    "these categories must be filled by round 20 -- rounds 21-22 can be any position."
)

targets = config.get("estimation_assumptions", {}).get("round_based_fill_targets", [])
if not targets:
    st.caption("No draft requirements configured.")
else:
    # Reuses the same generic slot-filling heuristic as the Starting
    # Lineup table above (src.roster_needs.assign_roster_slots), just
    # pointed at the requirements list instead of roster.starters -- same
    # "if the draft stopped right now" caveat applies, and a drafted
    # player is claimed by the most position-restrictive unmet category
    # first (e.g. "TE (Mandatory)" before the broader "WR/TE" bucket), so
    # nobody is double-counted across overlapping categories.
    REQUIREMENT_DISPLAY_NAMES = {
        "QB": "QB",
        "K": "K",
        "DEF": "DEF",
        "RB_REQUIREMENT": "RB",
        "WR_TE_REQUIREMENT": "WR/TE",
        "RB_WR_TE_REQUIREMENT": "RB, WR, or TE",
        "TE_MANDATORY": "TE (Mandatory)",
        "ANY_POSITION_REQUIREMENT": "Any Position",
    }
    by_slot_name = {t["slot"]: t for t in targets}
    req_slots, _req_bench = assign_roster_slots(my_picks, targets)

    req_rows = []
    unmet_by_round: dict[int, int] = {}
    for slot_name, filled in req_slots.items():
        target = by_slot_name[slot_name]
        label_base = REQUIREMENT_DISPLAY_NAMES.get(slot_name, slot_name.replace("_", " ").title())
        still_needed = sum(1 for p in filled if p is None)
        if still_needed:
            by_round = target.get("by_round")
            unmet_by_round[by_round] = unmet_by_round.get(by_round, 0) + still_needed
        for i, pick in enumerate(filled, start=1):
            label = label_base if target["count"] == 1 else f"{label_base} {i}"
            if pick is not None:
                req_rows.append({
                    "Requirement": label, "Player": pick.player_name, "Pos": pick.position,
                    "Rd": pick.round, "Pick": pick.overall_pick,
                })
            else:
                req_rows.append({
                    "Requirement": label, "Player": "— empty —", "Pos": "/".join(target["eligible"]),
                    "Rd": None, "Pick": None,
                })
    st.dataframe(pd.DataFrame(req_rows), hide_index=True, use_container_width=True)

    # Warn as round 20 approaches with any by-round-20 requirement category
    # still unmet -- per league-manager request (2026-08-27): "The app
    # should give me a warning if I am near round 20 and haven't met the
    # requirements yet." Only categories with a round-20 deadline trigger
    # this banner -- the QB category's own, much tighter round-6 deadline
    # is a separate strategic nudge the Suggested Pick panel already
    # surfaces (src.pick_suggestion's mandatory/quota-deadline overrides).
    round_20_unmet = unmet_by_round.get(20, 0)
    if round_20_unmet:
        if draft_state.is_draft_complete:
            current_round = config["draft"]["rounds"]
        else:
            current_round, _ = draft_state.round_and_slot_for_pick(draft_state.next_overall_pick)
        if current_round > 20:
            st.error(
                f"🚫 Round 20's deadline has passed and {round_20_unmet} league draft "
                f"requirement(s) are still unmet."
            )
        elif current_round >= 18:
            st.warning(
                f"⚠️ Round {current_round} of {config['draft']['rounds']} — {round_20_unmet} "
                f"league draft requirement(s) still need to be filled before round 20 ends."
            )

st.divider()
st.subheader(f"Bench ({len(bench)})")
if not bench:
    st.caption("No bench players yet.")
else:
    bench_df = pd.DataFrame(
        [
            {
                "Player": p.player_name, "Pos": p.position, "NFL Team": p.nfl_team,
                "Rd": p.round, "Pick": p.overall_pick,
            }
            for p in sorted(bench, key=lambda p: p.overall_pick)
        ]
    )
    st.dataframe(bench_df, hide_index=True, use_container_width=True)

st.divider()
st.page_link("pages/1_Draft_Board.py", label="← Back to Draft Board", icon="🏈")
