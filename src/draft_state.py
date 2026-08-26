"""
Live draft state for a snake draft: pick order, pick log, roster-by-team,
persisted to a local JSON file so the Draft Board survives app restarts
(Streamlit reruns constantly, and draft day is not the time to lose state).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Pick:
    overall_pick: int
    round: int
    pick_in_round: int
    team: str
    player_name: str
    position: str = ""
    nfl_team: str = ""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class DraftState:
    def __init__(self, teams: list[str], rounds: int, my_team: str,
                 state_file: str = "data/draft_state.json"):
        if my_team not in teams:
            raise ValueError(f"my_team {my_team!r} must be one of {teams!r}")
        self.teams = list(teams)
        self.rounds = rounds
        self.my_team = my_team
        self.state_file = state_file
        self.picks: list[Pick] = []
        self._load_if_exists()

    # ------------------------------------------------------------------
    # Snake order
    # ------------------------------------------------------------------

    def team_for_pick(self, overall_pick: int) -> str:
        """1-indexed overall pick number -> team on the clock."""
        n = len(self.teams)
        rnd0 = (overall_pick - 1) // n  # 0-indexed round
        pos_in_round = (overall_pick - 1) % n
        if rnd0 % 2 == 0:
            idx = pos_in_round
        else:
            idx = n - 1 - pos_in_round
        return self.teams[idx]

    def round_and_slot_for_pick(self, overall_pick: int) -> tuple[int, int]:
        n = len(self.teams)
        rnd = (overall_pick - 1) // n + 1
        pick_in_round = (overall_pick - 1) % n + 1
        return rnd, pick_in_round

    @property
    def total_picks(self) -> int:
        return len(self.teams) * self.rounds

    @property
    def next_overall_pick(self) -> int:
        return len(self.picks) + 1

    @property
    def is_draft_complete(self) -> bool:
        return self.next_overall_pick > self.total_picks

    @property
    def on_the_clock(self) -> Optional[str]:
        if self.is_draft_complete:
            return None
        return self.team_for_pick(self.next_overall_pick)

    @property
    def is_my_pick(self) -> bool:
        return self.on_the_clock == self.my_team

    def picks_until_my_turn(self) -> Optional[int]:
        """How many picks (including the current one) until it's my_team's turn.
        0 means it's my pick right now. None if draft is complete."""
        if self.is_draft_complete:
            return None
        n = self.total_picks
        for p in range(self.next_overall_pick, n + 1):
            if self.team_for_pick(p) == self.my_team:
                return p - self.next_overall_pick
        return None

    # ------------------------------------------------------------------
    # Logging picks
    # ------------------------------------------------------------------

    def log_pick(self, team: str, player_name: str, position: str = "", nfl_team: str = "") -> Pick:
        if self.is_draft_complete:
            raise RuntimeError("Draft is already complete.")
        if team not in self.teams:
            raise ValueError(f"Unknown team {team!r}")
        overall = self.next_overall_pick
        rnd, slot = self.round_and_slot_for_pick(overall)
        pick = Pick(
            overall_pick=overall,
            round=rnd,
            pick_in_round=slot,
            team=team,
            player_name=player_name,
            position=position,
            nfl_team=nfl_team,
        )
        self.picks.append(pick)
        self.save()
        return pick

    def log_pick_on_the_clock(self, player_name: str, position: str = "", nfl_team: str = "") -> Pick:
        """Convenience: log a pick for whichever team is currently on the clock."""
        team = self.on_the_clock
        if team is None:
            raise RuntimeError("Draft is already complete.")
        return self.log_pick(team, player_name, position, nfl_team)

    def undo_last_pick(self) -> Optional[Pick]:
        if not self.picks:
            return None
        p = self.picks.pop()
        self.save()
        return p

    def upcoming_picks(self, n: int) -> list[dict]:
        """The next up to n picks starting from next_overall_pick, each as
        {overall_pick, round, pick_in_round, team}. Capped at total_picks
        (returns fewer than n near the end of the draft); empty list once
        the draft is complete. Used by the Draft Board sidebar's "next N
        picks" lookahead panel."""
        if self.is_draft_complete:
            return []
        start = self.next_overall_pick
        end = min(start + n - 1, self.total_picks)
        result = []
        for overall in range(start, end + 1):
            rnd, slot = self.round_and_slot_for_pick(overall)
            result.append({
                "overall_pick": overall,
                "round": rnd,
                "pick_in_round": slot,
                "team": self.team_for_pick(overall),
            })
        return result

    def drafted_player_names(self) -> set[str]:
        return {p.player_name for p in self.picks}

    def roster_by_team(self) -> dict[str, list[Pick]]:
        rosters: dict[str, list[Pick]] = {t: [] for t in self.teams}
        for p in self.picks:
            rosters[p.team].append(p)
        return rosters

    def my_roster(self) -> list[Pick]:
        return self.roster_by_team()[self.my_team]

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.state_file) or ".", exist_ok=True)
        payload = {
            "teams": self.teams,
            "rounds": self.rounds,
            "my_team": self.my_team,
            "picks": [asdict(p) for p in self.picks],
        }
        tmp = self.state_file + ".tmp"
        with open(tmp, "w") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, self.state_file)

    def _load_if_exists(self) -> None:
        if not os.path.exists(self.state_file) or os.path.getsize(self.state_file) == 0:
            return
        with open(self.state_file, "r") as f:
            try:
                payload = json.load(f)
            except json.JSONDecodeError:
                # Corrupt/partial state file (e.g. an interrupted write) —
                # don't crash draft day, just start from an empty pick log.
                return
        # Trust the on-disk pick log; teams/rounds/my_team come from config
        # at construction time (so a league-settings change is picked up),
        # but we sanity check they still match before loading picks.
        if payload.get("teams") == self.teams and payload.get("my_team") == self.my_team:
            self.picks = [Pick(**p) for p in payload.get("picks", [])]

    def reset(self) -> None:
        self.picks = []
        self.save()
