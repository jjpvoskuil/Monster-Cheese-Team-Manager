"""
Current roster state -- the draft-day snapshot (src.draft_state
.DraftState.roster_by_team(), frozen the moment the real draft ended)
replayed forward through every waiver add / drop / trade captured by
src.data_sources.transactions, so pages/4_My_Roster.py and
pages/6_League_Rosters.py can show what's ACTUALLY on each roster right
now instead of only what was drafted.

Deliberately reuses src.draft_state.Pick as the output type for
transaction-added players (rather than inventing a parallel data
shape) so every existing consumer of a team's roster --
src.roster_needs.assign_roster_slots(), src.league_grid
.build_league_grid(), etc. -- works unchanged against either the
as-drafted or the current view; see pages/4_My_Roster.py's toggle for
how the two views are selected. Fabricated Picks for post-draft
additions use `round=0` (never a real draft round) as the signal that a
player got here by transaction, not by being drafted -- pages that
display `Rd` should treat 0 as "added after the draft."

This module does NOT persist anything of its own -- current roster
state is computed fresh every call from draft_state (already loaded)
plus the transactions CSV (loaded fresh each time, so a re-run of
scripts/fetch_transactions.py is picked up on the next page rerun with
no separate cache-invalidation logic needed), the same "derive, don't
duplicate stored state" spirit as src.roster_needs.assign_roster_slots.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from src.draft_state import DraftState, Pick


@dataclass
class RosterStateResult:
    rosters: dict[str, list[Pick]]
    # Player names a transaction referenced that couldn't be matched
    # against that team's current roster (e.g. a drop/trade-away for a
    # player the draft log never attributed to them -- a real data
    # inconsistency, not something to silently ignore). Each entry is a
    # human-readable note, not raised as an exception, so one bad
    # transaction doesn't blank the whole page -- same defensive
    # philosophy as src.data_sources.transactions' "other" fallback.
    warnings: list[str]


def _remove_player(roster: list[Pick], player_name: str) -> bool:
    """Remove the first Pick matching player_name (case-insensitive) from
    roster, in place. Returns True if a match was found and removed."""
    target = player_name.strip().lower()
    for i, pick in enumerate(roster):
        if pick.player_name.strip().lower() == target:
            del roster[i]
            return True
    return False


def current_roster_by_team(
    draft_state: DraftState, transactions: pd.DataFrame
) -> RosterStateResult:
    """Replay `transactions` (as returned by
    src.data_sources.transactions.load_transactions -- must already be
    in chronological order, which that loader guarantees) on top of
    `draft_state`'s frozen draft-day roster to compute each team's
    CURRENT roster.

    Transaction handling:
      - "drop": remove the named player from `team`'s roster.
      - "waiver_add": add a new Pick to `team`'s roster.
      - "trade_in": remove the named player from `from_team`'s roster
        (if set) and add a new Pick to `team`'s roster -- CBS's report
        only shows the RECEIVING side of each trade leg (see
        src.data_sources.transactions' module docstring), so the giving
        side is inferred entirely from `from_team`.
      - "other" (unrecognized action text): skipped, with a warning --
        not enough information to safely mutate a roster from an
        unrecognized transaction type.

    A drop/trade-away naming a player not found on the expected team's
    current roster (name mismatch, or a transaction predating this
    project's capture) is skipped with a warning rather than raising,
    same reasoning as the unrecognized-type case above.
    """
    rosters: dict[str, list[Pick]] = {
        team: list(picks) for team, picks in draft_state.roster_by_team().items()
    }
    warnings: list[str] = []

    if transactions is None or transactions.empty:
        return RosterStateResult(rosters=rosters, warnings=warnings)

    existing_overalls = [p.overall_pick for picks in rosters.values() for p in picks]
    next_overall = (max(existing_overalls) if existing_overalls else 0) + 1

    for _, row in transactions.iterrows():
        txn_type = row["txn_type"]
        team = row["team"]
        player_name = row["player_name"]
        timestamp = row["date"]

        if team not in rosters:
            warnings.append(
                f"{timestamp}: transaction for unknown team {team!r} (not in this "
                f"league's configured team_order) -- skipped."
            )
            continue

        if txn_type == "drop":
            if not _remove_player(rosters[team], player_name):
                warnings.append(
                    f"{timestamp}: {team} dropped {player_name!r}, but they weren't "
                    f"found on {team}'s current roster -- skipped."
                )
            continue

        if txn_type == "trade_in":
            from_team = row.get("from_team")
            if from_team and from_team in rosters:
                if not _remove_player(rosters[from_team], player_name):
                    warnings.append(
                        f"{timestamp}: {player_name!r} traded from {from_team} to {team}, "
                        f"but wasn't found on {from_team}'s current roster -- added to "
                        f"{team} anyway, but rosters may now be out of sync."
                    )
            elif from_team:
                warnings.append(
                    f"{timestamp}: {player_name!r} traded from {from_team!r} (not a "
                    f"known team) to {team} -- added to {team}, source roster unchanged."
                )
            rosters[team].append(Pick(
                overall_pick=next_overall, round=0, pick_in_round=0, team=team,
                player_name=player_name, position=row.get("position") or "",
                nfl_team=row.get("nfl_team") or "", timestamp=str(timestamp),
            ))
            next_overall += 1
            continue

        if txn_type == "waiver_add":
            rosters[team].append(Pick(
                overall_pick=next_overall, round=0, pick_in_round=0, team=team,
                player_name=player_name, position=row.get("position") or "",
                nfl_team=row.get("nfl_team") or "", timestamp=str(timestamp),
            ))
            next_overall += 1
            continue

        # txn_type == "other" (or anything future/unrecognized)
        warnings.append(
            f"{timestamp}: {team} -- unrecognized transaction type {txn_type!r} for "
            f"{player_name!r} ({row.get('action_text', '')!r}) -- skipped."
        )

    return RosterStateResult(rosters=rosters, warnings=warnings)


def current_roster_for_team(
    draft_state: DraftState, transactions: pd.DataFrame, team: str
) -> RosterStateResult:
    """Convenience wrapper for a single team (e.g. My Roster's own team)
    -- still computes every team's roster internally (trades need both
    sides), just narrows the returned dict to `team`."""
    result = current_roster_by_team(draft_state, transactions)
    return RosterStateResult(
        rosters={team: result.rosters.get(team, [])}, warnings=result.warnings
    )
