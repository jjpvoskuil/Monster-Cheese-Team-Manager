"""
Parse raw-captured CBS "Free Agent Recommendations" pages (the
/stats/stats-main report with PLAYER STATUS = FREE AGENTS) into a
canonical waiver-wire candidate table -- one row per free-agent player,
covering all three CBS position groupings (ALL OFFENSE, K, DST) and both
TIMEFRAMEs the recommendation engine (src/waiver_recommendations.py)
needs: WEEK N (PROJ) for "who fills a bye-week hole THIS week" and REST
OF SEASON (PROJ) for "who's a better long-term add than someone already
on my roster."

WHY THIS SOURCE (2026-09-09, league-manager request -- see the two
AskUserQuestion answers this was built from, "Capture CBS's own live
Available Players page" and "Capture CBS's full-league weekly stats page
too"): CBS's own free-agent list is the actual pool of pickup-able
players (this app has no other way to know who's unrostered across all
10 teams), and this same page ALSO carries CBS's own SportsLine-powered
FPTS projections for each candidate -- no separate "who are the free
agents" + "what does CBS project for them" capture needed, one page
covers both.

CAPTURE METHOD: same login-gated live-browser pattern as every other
CBS-sourced file in this app (cbs.py, weekly_matchup.py, transactions.py)
-- https://<league>.football.cbssports.com/stats/stats-main, POSITIONS
filter set to ALL OFFENSE / K / DST in turn, PLAYER STATUS = FREE AGENTS,
TIMEFRAME cycled between "Week N (Proj)" and "Rest of Season (Proj)".
Each (position group, timeframe) combination is its own raw capture file:
    data/waiver_wire/raw/{year}_week{N}_{group}.txt
    data/waiver_wire/raw/{year}_restofseason_{group}.txt
    where group is "offense", "k", or "dst".
See scripts/fetch_waiver_wire.py's docstring for the full re-capture
procedure (filter click order matters -- CBS's SPA silently drops the
PLAYER STATUS or print_rows state on some filter changes; that script's
docstring documents the sequence that reliably worked).

ROW FORMAT (all three CBS tables, once blank lines are stripped, share
this shape -- confirmed against real captures of all 6 files this parser
was built from): each data row is one line, tab-separated, always
starting with the AVAIL column ("W (9/10)" -- waiver-available since
M/D), and always ending with FPTS as its LAST field:
    AVAIL \t PLAYER \t OPP \t OVP \t BYE \t ROST \t START \t <stat
    columns... count and meaning vary by position group, not parsed
    individually, see below> \t FPTS
The PLAYER field itself packs name + position + NFL team into one
string, e.g. "Elic Ayomanor WR • TEN", "Titans DST • TEN " (a DST's
"name" is just its city+mascot -- CBS's own drafted-DST naming
convention, matching src.projections.NFL_CITY_TO_MASCOT's target form),
or "Taysom Hill QB,TE • NO" (CBS's dual-eligibility notation,
comma-separated) -- _PLAYER_RE below handles all three shapes.

DELIBERATELY NOT parsed: the per-position stat columns between START and
FPTS (passing/rushing/receiving/fumbles for offense; FG-by-distance
-bracket for K; sack/turnover/points-against/yards-against for DST) --
different shape per position group, and nothing downstream needs them:
the recommendation engine only ever compares FPTS. If a future request
needs the raw stat detail, capture it as extra columns rather than
throwing away this simpler "first 7 fields fixed, last field is always
FPTS" positional parsing, which has held across all 3 tables x 2
timeframes captured so far without a single unmatched row.

BYE here is the NUMERIC NFL bye-week for that player's real team (CBS's
own BYE column) -- unlike src/data_sources/weekly_matchup.py's
_bye_names(), which can only detect a bye via a text match against a
specific captured week's matchup_desc, this is a direct, reliable value
for FREE AGENTS. It says nothing about a player already on someone's
roster -- src.waiver_recommendations still relies on the weekly-matchup
-based bye detection for THOSE players, since this page only lists
unrostered ones. Not cross-checked against a team currently ON its bye
this capture (Week 1, 2026 -- no NFL team has a Week 1 bye), so a
mid-season recapture should double check a bye-week free agent shows OPP
as literal "BYE" text (this parser doesn't special-case that -- it
stores whatever OPP says, as-is).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_POS = r"(?:QB|RB|WR|TE|K|DST)"
_PLAYER_RE = re.compile(
    rf"^(?P<name>.+?)\s+(?P<pos>{_POS}(?:,{_POS})*)\s*•\s*(?P<team>[A-Z]{{2,4}})\s*$"
)


@dataclass
class WaiverCandidate:
    name: str
    position: str   # dash-joined for a dual-eligible row ("QB-TE"), matching
                     # src.lineup_value._is_eligible's split-on-"-" convention
                     # -- CBS itself uses a comma here, normalized on parse
    nfl_team: str
    opp: str
    bye_week: int | None
    rost_pct: float | None
    fpts: float


def _to_float(s: str) -> float | None:
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _to_int(s: str) -> int | None:
    v = _to_float(s)
    return int(v) if v is not None else None


def parse_free_agent_table(text: str) -> list[WaiverCandidate]:
    """Parse one raw-captured CBS free-agent table (any position group,
    any timeframe) into a list of WaiverCandidate.

    Raises ValueError if literally no data rows are found (an empty or
    fundamentally broken capture -- nothing to salvage). An individual
    row that doesn't match the expected shape (a bad hand-transcription,
    or CBS someday changing the PLAYER field's format) is just skipped
    rather than failing the whole file -- same defensive philosophy as
    src.data_sources.transactions' "other" fallback and
    src.roster_state's per-transaction warnings, though this function
    has no `warnings` list to report skips through (in practice: 0
    skipped rows across all 6,003 rows this parser was built and tested
    against)."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    rows = [ln for ln in lines if ln.startswith("W (") and "\t" in ln]
    if not rows:
        raise ValueError("No free-agent data rows found (looked for lines starting with 'W (')")

    candidates = []
    for row in rows:
        fields = row.split("\t")
        if len(fields) < 8:  # AVAIL, PLAYER, OPP, OVP, BYE, ROST, START, ..., FPTS
            continue
        m = _PLAYER_RE.match(fields[1])
        if not m:
            continue
        candidates.append(WaiverCandidate(
            name=m.group("name").strip(),
            position=m.group("pos").replace(",", "-"),
            nfl_team=m.group("team"),
            opp=fields[2],
            bye_week=_to_int(fields[4]),
            rost_pct=_to_float(fields[5]),
            fpts=_to_float(fields[-1]) or 0.0,
        ))
    return candidates


def load_raw_file(path: str) -> list[WaiverCandidate]:
    with open(path, encoding="utf-8") as f:
        text = f.read()
    # Strip this module's own leading "# ..." documentation comment block,
    # same convention as src.data_sources.weekly_matchup.load_raw_file --
    # see data/waiver_wire/raw/*.txt's header.
    marker = "===== RAW TEXT BELOW ====="
    if marker in text:
        text = text.split(marker, 1)[1]
    return parse_free_agent_table(text)


def candidates_to_rows(candidates: list[WaiverCandidate], year: int, timeframe: str) -> list[dict]:
    """Flatten to plain dicts for pd.DataFrame() -- the canonical shape
    saved to data/waiver_wire/{year}_{timeframe}.csv. `timeframe` is
    "week<N>" or "restofseason", matching the raw filename convention."""
    return [
        {
            "year": year, "timeframe": timeframe,
            "name": c.name, "position": c.position, "nfl_team": c.nfl_team,
            "opp": c.opp, "bye_week": c.bye_week, "rost_pct": c.rost_pct,
            "fpts": c.fpts,
        }
        for c in candidates
    ]
