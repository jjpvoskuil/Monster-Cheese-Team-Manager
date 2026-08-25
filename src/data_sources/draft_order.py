"""
Parse the CBS "Draft Results" page into a structured draft order.

CBS requires a logged-in session and blocks robots.txt/plain HTTP fetches
for this page, so it can't be pulled with `requests`/`pd.read_csv`-style
code the way projections are. The realistic "auto-populate next year"
workflow is:

  1. Build the URL for the new season with `draft_results_url(year)`.
  2. Have a logged-in browser (e.g. Claude in Chrome, or the user's own
     browser) visit that URL and grab the page's plain text (e.g. via
     the browser automation "get page text" action, or just select-all /
     copy from the page).
  3. Save that raw text to a file and run `scripts/fetch_draft_order.py`
     on it (see that script's docstring), which calls
     `parse_draft_order_text()` below and writes the structured JSON.

This module only handles the pre-draft "order" case, where every pick's
PLAYER column is still empty (CBS shows "NOT STARTED" for the draft).
Once a draft has actually happened, the PLAYER column is populated with
drafted players — parsing that into pick results is a different, not-yet
-built feature (would feed src/draft_state.py directly instead of just
seeding a preseason team order).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


def draft_results_url(year: int, league_slug: str = "maniacfl",
                       sport: str = "football",
                       draft_name: str = "MFL Draft {year}",
                       phase: str = "Pre-season") -> str:
    """Build the CBS draft-results URL for a given season.

    Confirmed working pattern for this league (2026):
      https://maniacfl.football.cbssports.com/draft/results/2026:Pre-season:MFL%20Draft%202026/

    The three colon-separated segments after /draft/results/ are
    <year>:<phase>:<draft name as configured in CBS>. `draft_name` is a
    template string; "{year}" in it is substituted. If a commissioner
    ever renames the draft event in CBS (unlikely, but it happens),
    update `draft_name` here or pass an override.
    """
    name = draft_name.format(year=year)
    segment = f"{year}:{phase}:{name}"
    # CBS's own links percent-encode spaces as %20 but leave the ":"
    # separators between year/phase/draft-name literal.
    from urllib.parse import quote
    return f"https://{league_slug}.{sport}.cbssports.com/draft/results/{quote(segment, safe=':')}/"


@dataclass
class DraftOrderResult:
    year: int | None
    source_url: str | None
    captured_at: str | None
    rounds: int
    teams_per_round: int
    round_orders: list[list[str]] = field(default_factory=list)  # 1 list of team names per round
    team_order: list[str] = field(default_factory=list)  # round 1 order
    is_standard_snake: bool = False
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "year": self.year,
            "source_url": self.source_url,
            "captured_at": self.captured_at,
            "rounds": self.rounds,
            "teams_per_round": self.teams_per_round,
            "team_order": self.team_order,
            "is_standard_snake": self.is_standard_snake,
            "round_orders": self.round_orders,
            "notes": self.notes,
        }


_ROUND_HEADER_RE = re.compile(r"^ROUND\s+(\d+)\s*$", re.IGNORECASE)
_PICK_LINE_RE = re.compile(r"^(\d+)\s+(.+?)\s*$")
_NON_TEAM_LINES = {"PICK TEAM PLAYER", "TEAM", "PLAYER", "PICK"}


def parse_draft_order_text(text: str) -> DraftOrderResult:
    """Parse raw page text (as returned by a "get page text"-style browser
    extraction) from a CBS draft-results page that hasn't started yet
    (every pick's PLAYER column empty) into a structured draft order.

    Raises ValueError if no ROUND blocks are found, if rounds have
    inconsistent pick counts, or if any pick line looks like it already
    has a drafted player attached (a sign the draft has actually started
    and this parser's assumptions don't hold).
    """
    lines = [ln.strip() for ln in text.splitlines()]

    round_orders: dict[int, list[tuple[int, str]]] = {}
    current_round: int | None = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        m = _ROUND_HEADER_RE.match(line)
        if m:
            current_round = int(m.group(1))
            round_orders.setdefault(current_round, [])
            continue
        if current_round is None:
            continue
        if line.upper() in _NON_TEAM_LINES:
            continue
        # Stop consuming once we hit the footnote/legend lines that follow
        # the last round block.
        if line.startswith("*"):
            current_round = None
            continue
        pm = _PICK_LINE_RE.match(line)
        if not pm:
            continue
        pick_num = int(pm.group(1))
        team_name = pm.group(2).strip()
        round_orders[current_round].append((pick_num, team_name))

    if not round_orders:
        raise ValueError(
            "No 'ROUND N' blocks found — is this really a CBS draft-results "
            "page's text? (Expected lines like 'ROUND 1' followed by "
            "'<pick#> <team name>' lines.)"
        )

    rounds_sorted = sorted(round_orders)
    if rounds_sorted != list(range(1, len(rounds_sorted) + 1)):
        raise ValueError(f"Expected contiguous rounds starting at 1, got {rounds_sorted}")

    sizes = {r: len(picks) for r, picks in round_orders.items()}
    distinct_sizes = set(sizes.values())
    if len(distinct_sizes) != 1:
        raise ValueError(f"Rounds have inconsistent pick counts: {sizes}")
    teams_per_round = distinct_sizes.pop()

    ordered_rounds: list[list[str]] = []
    for r in rounds_sorted:
        picks = sorted(round_orders[r], key=lambda p: p[0])
        expected_picks = list(range(1, teams_per_round + 1))
        actual_picks = [p[0] for p in picks]
        if actual_picks != expected_picks:
            raise ValueError(f"Round {r}: expected picks {expected_picks}, got {actual_picks}")
        ordered_rounds.append([team for _, team in picks])

    team_order = ordered_rounds[0]
    if len(set(team_order)) != len(team_order):
        raise ValueError(f"Round 1 has duplicate team names: {team_order}")

    is_standard_snake = True
    for i, order in enumerate(ordered_rounds):
        expected = team_order if i % 2 == 0 else list(reversed(team_order))
        if order != expected:
            is_standard_snake = False
            break

    notes = []
    if not is_standard_snake:
        notes.append(
            "Round order does NOT follow a strict alternating snake pattern "
            "(round N = round 1 order, or its exact reverse, for every N). "
            "src/draft_state.py's DraftState.team_for_pick() ASSUMES a strict "
            "snake from a single team_order list — if this league's draft "
            "uses e.g. a 3rd-round reversal or a custom order, DraftState "
            "will compute the wrong team-on-the-clock for some picks. Use "
            "round_orders (the full per-round breakdown) as ground truth "
            "instead, or extend DraftState to accept an explicit order."
        )

    return DraftOrderResult(
        year=None,
        source_url=None,
        captured_at=None,
        rounds=len(ordered_rounds),
        teams_per_round=teams_per_round,
        round_orders=ordered_rounds,
        team_order=team_order,
        is_standard_snake=is_standard_snake,
        notes=notes,
    )
