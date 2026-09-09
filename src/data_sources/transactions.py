"""
Parse CBS's "Transaction Reports" page (waiver adds, drops, and trades --
NOT the frozen draft-day log, which src/draft_state.py and
src/data_sources/draft_history.py already cover separately) into a
canonical per-transaction schema, so src/roster_state.py can replay them
on top of the draft-day snapshot to compute each team's CURRENT roster.

Why CBS instead of in-app manual entry: CBS is where the actual moves
happen (waiver processing, trade approval) -- the league's real system of
record -- so the app stays a read/display layer that syncs FROM CBS
rather than trying to execute real transactions on a live site (see the
2026-09-09 SESSION_NOTES entry for the reasoning). This mirrors
draft_history.py's two-stage pattern exactly: a periodic manual/Claude
-assisted capture produces a raw text file, a separate parse step turns
it into canonical structured data.

Raw input format
-----------------
A simple tab-delimited "raw" text file, one line per transaction row, in
the form:

    <date_time>\t<team>\t<players cell>\t<effective>\t<cost>

This is literally CBS's own Transaction Report table columns (Date, Team,
Players, Effective, Cost), captured as plain text -- NOT a project
-invented intermediate format like draft_history.py's pipe-delimited one,
because this page's rows are simple enough to capture directly.

Workflow to capture the current season's transactions:
  1. Log in to CBS (or use an already-logged-in browser session, e.g.
     Claude in Chrome or the built-in browser pane) and visit
     https://<league>.football.cbssports.com/transactions -- the page's
     actual URL pattern is `/transactions/<team_id|all>/<type>/<year>`,
     e.g. `/transactions/all/all_but_lineup/2026` for the whole league,
     `/transactions/4/all_but_lineup/2026` for one team's own history
     (team IDs are CBS-internal, not this project's team names -- read
     them off the page's Team filter `<select>` if you need them).
     "All but Lineup" is the right TYPE filter -- it excludes weekly
     starting-lineup changes (not roster moves) but includes adds,
     drops, and trades.
  2. Extract each data row's Date/Team/Players/Effective/Cost columns
     into the tab-delimited format above, one line per row, and save to
     data/transactions/raw/<year>_raw.txt (append new rows across
     multiple captures through the season -- duplicate rows are
     harmless, see `parse_raw_file`'s dedup note below).
  3. Run scripts/fetch_transactions.py to parse the raw file(s) into the
     canonical CSV at data/transactions/transactions.csv.

**Not yet handled: pagination.** As of the 2026-09-09 capture the whole
season had only 10 transactions league-wide, all fitting on one page --
this hasn't been tested against a page with a "next page" control. If a
future capture looks truncated (missing known-recent moves), check the
page for pagination before trusting the raw file is complete.

Players-cell format, observed 2026-09-09 (all handled by
`_parse_player_and_action`):
  - Waiver add: "Tre Tucker WR • LV  - Added off Waivers"
  - Drop: "Adam Randall RB • BAL  - Dropped"
  - Trade (each side of a trade gets its OWN row, on the RECEIVING
    team, naming who it came from -- there is no separate "traded away"
    row for the sending team; `src/roster_state.py` removes the player
    from the sending team using this same row): "Packers DST • GB -
    Traded from THE DEMONS"
  - DST rows name the NFL team's mascot as the "player", same convention
    already handled in draft_history.py/blend_projections(): "Packers
    DST" -> player_name="Packers", position="DST".
  - Untested: free-agent adds (no waiver), commissioner moves (the page
    marks these in red text, invisible to a text capture), and IR moves
    -- this league has no separate IR roster slot (confirmed with the
    league manager 2026-09-09; a season-ending injury is just a drop),
    so no IR-specific transaction type is modeled. An unrecognized
    action phrase falls back to txn_type="other" with the raw action
    text preserved in `action_text`, rather than guessing or raising --
    same defensive philosophy as draft_history.py's unrecognized
    -position handling, so one odd row doesn't kill an entire capture.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

_KNOWN_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DST")
_POS_ALTERNATION = "|".join(_KNOWN_POSITIONS)
_NAME_POS_RE = re.compile(
    rf"^(?P<name>.+?)\s+(?P<pos>(?:{_POS_ALTERNATION})(?:,(?:{_POS_ALTERNATION}))*)$"
)

_TRADED_FROM_RE = re.compile(r"^Traded from\s+(?P<team>.+)$", re.IGNORECASE)


@dataclass
class ParsedTransaction:
    year: int
    date: datetime
    team: str
    txn_type: str  # "waiver_add" | "drop" | "trade_in" | "other"
    player_name: str | None
    position: str | None
    positions: list[str] = field(default_factory=list)
    nfl_team: str | None = None
    from_team: str | None = None  # only set for txn_type == "trade_in"
    effective_round: int | None = None
    cost: float | None = None
    action_text: str = ""  # raw action phrase, always preserved for debugging/"other" rows

    def to_dict(self) -> dict:
        return {
            "year": self.year,
            "date": self.date.isoformat(),
            "team": self.team,
            "txn_type": self.txn_type,
            "player_name": self.player_name,
            "position": self.position,
            "positions": ",".join(self.positions) if self.positions else "",
            "nfl_team": self.nfl_team,
            "from_team": self.from_team,
            "effective_round": self.effective_round,
            "cost": self.cost,
            "action_text": self.action_text,
        }


def _parse_player_and_action(cell: str) -> dict:
    """Split a Players-column cell into the player (name/position/NFL
    team, same "Name POS • TEAM" shape draft_history.py's
    `_parse_player_cell` already handles) and the action phrase after
    " - " (e.g. "Added off Waivers", "Dropped", "Traded from <team>")."""
    cell = cell.strip()
    if "•" in cell:
        left, right = cell.split("•", 1)
    else:
        left, right = cell, ""
    left = left.strip()

    # `right` is "<NFL team>  - <action>" (NFL team may be blank for a
    # free agent). Split on the FIRST " - " -- action text itself is not
    # expected to contain " - ", and no observed case does.
    if " - " in right:
        team_part, action = right.split(" - ", 1)
    else:
        team_part, action = right, ""
    nfl_team = team_part.strip() or None
    action = action.strip()

    m = _NAME_POS_RE.match(left)
    if m:
        name = m.group("name").strip()
        positions = m.group("pos").split(",")
    else:
        name = left
        positions = []

    return dict(
        player_name=name or None,
        positions=positions,
        position=positions[0] if positions else None,
        nfl_team=nfl_team,
        action_text=action,
    )


def _classify_action(action_text: str) -> tuple[str, str | None]:
    """Return (txn_type, from_team). Unrecognized phrasing falls back to
    txn_type="other" rather than guessing -- see module docstring."""
    lower = action_text.lower()
    if "traded from" in lower:
        m = _TRADED_FROM_RE.match(action_text)
        return "trade_in", (m.group("team").strip() if m else None)
    if "dropped" in lower:
        return "drop", None
    if "added" in lower:
        return "waiver_add", None
    return "other", None


def _parse_cost(cost_str: str) -> float | None:
    cost_str = cost_str.strip().replace("$", "").replace(",", "")
    if not cost_str:
        return None
    try:
        return float(cost_str)
    except ValueError:
        return None


def _parse_date(date_str: str) -> datetime | None:
    """CBS renders dates like '9/3/26 3:25 AM ET' -- strip the trailing
    timezone abbreviation (not portable across Python versions to parse
    directly) and parse the rest. Returns None (rather than raising) on
    an unrecognized format, so one bad row doesn't kill the whole
    capture -- the row is still kept, just unsorted relative to others
    (see `parse_raw_file`)."""
    cleaned = date_str.strip()
    for suffix in (" ET", " EST", " EDT"):
        if cleaned.endswith(suffix):
            cleaned = cleaned[: -len(suffix)]
            break
    try:
        return datetime.strptime(cleaned.strip(), "%m/%d/%y %I:%M %p")
    except ValueError:
        return None


def parse_raw_file(path: str, year: int) -> list[ParsedTransaction]:
    """Parse one data/transactions/raw/<year>_raw.txt file into a list of
    ParsedTransaction, one per line. Duplicate lines (e.g. from
    overlapping re-captures through the season) are silently deduped by
    (date, team, player_name, action_text) -- harmless to include the
    same row twice in a raw file, only the first copy survives here."""
    with open(path, "r") as f:
        lines = [ln.rstrip("\n") for ln in f if ln.strip()]

    seen: set[tuple] = set()
    txns: list[ParsedTransaction] = []
    for ln in lines:
        parts = ln.split("\t")
        if len(parts) != 5:
            raise ValueError(
                f"{path}: malformed line (expected 5 tab-separated fields): {ln!r}"
            )
        date_s, team, players_cell, effective_s, cost_s = parts
        team = team.strip()
        date = _parse_date(date_s)
        parsed = _parse_player_and_action(players_cell)
        txn_type, from_team = _classify_action(parsed["action_text"])
        effective_round = int(effective_s.strip()) if effective_s.strip().isdigit() else None

        dedup_key = (date_s.strip(), team, parsed["player_name"], parsed["action_text"])
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        txns.append(ParsedTransaction(
            year=year,
            date=date,
            team=team,
            txn_type=txn_type,
            player_name=parsed["player_name"],
            position=parsed["position"],
            positions=parsed["positions"],
            nfl_team=parsed["nfl_team"],
            from_team=from_team,
            effective_round=effective_round,
            cost=_parse_cost(cost_s),
            action_text=parsed["action_text"],
        ))
    return txns


def parse_raw_files(paths_by_year: dict[int, str]) -> pd.DataFrame:
    """Parse multiple years' raw files and return one combined DataFrame,
    sorted chronologically (rows with an unparseable date sort last,
    stable otherwise) -- the order src/roster_state.py needs to replay
    transactions correctly."""
    all_txns: list[ParsedTransaction] = []
    for year, path in paths_by_year.items():
        all_txns.extend(parse_raw_file(path, year))
    df = pd.DataFrame([t.to_dict() for t in all_txns])
    if df.empty:
        return df
    df["_sort_date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.sort_values(["_sort_date"], na_position="last", kind="stable").drop(columns=["_sort_date"])
    return df.reset_index(drop=True)


def load_transactions(csv_path: str) -> pd.DataFrame:
    """Load the canonical CSV written by scripts/fetch_transactions.py."""
    if not os.path.exists(csv_path):
        return pd.DataFrame()
    return pd.read_csv(csv_path)


def discover_raw_files(raw_dir: str) -> dict[int, str]:
    """Find data/transactions/raw/<year>_raw.txt files and return
    {year: path}, sorted by year -- same convention as
    draft_history.discover_raw_files()."""
    if not os.path.isdir(raw_dir):
        return {}
    found = {}
    for name in sorted(os.listdir(raw_dir)):
        m = re.match(r"^(\d{4})_raw\.txt$", name)
        if m:
            found[int(m.group(1))] = os.path.join(raw_dir, name)
    return found
