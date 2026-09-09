"""
Waiver-wire pickup recommendations -- ranks free-agent candidates
(src.data_sources.waiver_wire) against Monster Cheese's current roster
and picks the top adds, per the league manager's own priority order
(2026-09-09 request):

  1. An empty/uncovered starting-lineup slot THIS WEEK (a bye no bench
     player can legally back-fill) is the #1 priority.
  2. A free agent now projected better than a player already on the
     roster is a good pickup even without an empty slot.
  3. An open bench slot (roster under the 27-player cap) at a
     thin/shallow position is a good add even with no drop needed.
  4. A full 27/27 roster can still upgrade by dropping its weakest
     player for a better free agent -- always names BOTH players.

Every recommendation is tagged with the SOURCE that drove it (CBS or
FantasyPoints -- the league manager's explicit requirement: "Please
indicate if it is a recommendation based on CBS projections or Fantasy
Points projections"), since the two sources can and do disagree.

DESIGN NOTE on what "the same source" means here: this module doesn't
know or care how the caller derived each RosterPlayer's/FreeAgent's
week_points/season_points -- it just compares numbers already labeled
with a common source. pages/9_Waiver_Wire.py is what decides, per
source, how a rostered player's value is computed to be comparable to
that source's free-agent numbers:
  - CBS: free agents come directly from CBS's own live free-agent-page
    FPTS (src.data_sources.waiver_wire); a rostered player's equivalent
    is this app's own ScoringEngine applied to their row in
    data/projections/cbs_2026.csv (CBS's season stat projections,
    captured pre-draft, scored under this league's real rules). These
    are NOT the exact same underlying number (one is CBS's own live
    in-league engine on a fresher rest-of-season projection; the other
    is this app's engine on an older season-total projection) -- a
    documented approximation in the same spirit as this codebase's
    other estimation_assumptions, not a claim of source-level parity.
  - FantasyPoints: BOTH sides (rostered players and free-agent
    candidates) are scored by this app's own ScoringEngine over
    data/projections/fantasypoints_2026.csv's raw stat rows -- a free
    agent is simply any row in that file whose name doesn't match a
    current roster spot on any of the league's 10 teams. This side IS
    fully apples-to-apples (same source file, same engine, same rules)
    since there's no separate live FantasyPoints free-agent capture.
  - Week-specific numbers (bye-gap fill, tier 1) use
    data/weekly_matchups/{year}_week{N}.csv (CBS, already captured for
    the Weekly Matchup page) and data/weekly_projections/
    fantasypoints_{year}_week{N}.csv (FantasyPoints) the same way.

Reuses src.lineup_value.optimal_lineup_assignment for tier 1 -- exactly
the same optimal-assignment solver the Weekly Matchup page's start/bench
highlighting already uses -- rather than a new ad hoc heuristic for
"what's the best possible lineup right now."
"""

from __future__ import annotations

from dataclasses import dataclass

from src.lineup_value import LineupPlayer, optimal_lineup_assignment

# Lower number = shown first / preferred when a player would otherwise
# get recommended for more than one reason (see build_recommendations'
# dedup step).
_CATEGORY_PRIORITY = {
    "bye_gap": 0,
    "season_upgrade": 1,
    "bench_depth": 2,
    "full_roster_swap": 3,
}

CATEGORY_LABELS = {
    "bye_gap": "Fills an empty starting slot this week",
    "season_upgrade": "Better than a rostered player, season-long",
    "bench_depth": "Adds bench depth at a thin position",
    "full_roster_swap": "Worth dropping someone for (roster full)",
}


@dataclass
class FreeAgent:
    name: str
    position: str                  # e.g. "RB", or dash-joined "QB-TE" for dual eligibility
    nfl_team: str
    week_points: float | None = None
    season_points: float | None = None


@dataclass
class RosterPlayer:
    name: str
    position: str
    week_points: float | None = None
    season_points: float | None = None
    is_starter: bool = False
    is_bye: bool = False


@dataclass
class Recommendation:
    category: str          # one of _CATEGORY_PRIORITY's keys
    source: str             # "CBS" or "FantasyPoints"
    add_name: str
    add_position: str
    add_team: str
    add_value: float
    reason: str
    drop_name: str | None = None
    compare_value: float | None = None
    slot: str | None = None  # the empty starter slot this fills, for bye_gap only


def _eligible_positions(position: str) -> set[str]:
    return set(position.split("-"))


def _bye_gap_recommendations(
    roster: list[RosterPlayer], free_agents: list[FreeAgent],
    starters_config: list[dict], source: str, roster_names: set[str],
) -> list[Recommendation]:
    """Tier 1: run the same optimal-lineup solver the Weekly Matchup page
    uses (excluding bye players and anyone with no week_points for this
    source) over the current roster; any starter-slot instance that
    comes back with no player at all is a real, unfillable gap -- CBS's
    "the #1 priority" case. Recommends the single best-projected free
    agent eligible for that slot. Silently produces nothing if no
    roster player has a week_points value for this source (no weekly
    matchup/weekly projections data captured for the selected week
    yet) -- pages/9_Waiver_Wire.py surfaces that as a page-level notice,
    not a per-recommendation warning."""
    pool = [p for p in roster if not p.is_bye and p.week_points is not None]
    if not pool:
        return []

    lineup_players = [LineupPlayer(p.name, p.position, p.week_points) for p in pool]
    assignment = optimal_lineup_assignment(lineup_players, starters_config)

    slot_eligible = {s["slot"]: set(s["eligible"]) for s in starters_config}
    recs = []
    for a in assignment:
        if a.player is not None:
            continue
        eligible = slot_eligible.get(a.slot, set())
        candidates = [
            fa for fa in free_agents
            if fa.week_points is not None and fa.name not in roster_names
            and _eligible_positions(fa.position) & eligible
        ]
        if not candidates:
            continue
        best = max(candidates, key=lambda fa: fa.week_points)
        recs.append(Recommendation(
            category="bye_gap", source=source, add_name=best.name,
            add_position=best.position, add_team=best.nfl_team,
            add_value=best.week_points,
            reason=(
                f"No eligible player for your {a.slot} slot this week (bye/no bench "
                f"coverage) -- {best.name} ({best.position}) projects {best.week_points:.1f} "
                f"pts by {source}."
            ),
            slot=a.slot,
        ))
    return recs


def _season_upgrade_recommendations(
    roster: list[RosterPlayer], free_agents: list[FreeAgent], source: str, roster_names: set[str],
) -> list[Recommendation]:
    """Tier 2: for each free agent with a season_points value, compare
    against the WEAKEST current roster player eligible for the same
    position(s) (not just an exact position match -- a free agent
    labeled "WR-TE" competes against the weakest of your WRs and TEs
    together, same spirit as a flex slot). Recommends the free agent
    whenever they beat that weakest comparable player -- this is
    deliberately permissive (every such free agent becomes a candidate
    recommendation here, not just the very best one) since
    build_recommendations' final ranking/dedup step is what narrows this
    down to the top handful shown to the league manager."""
    recs = []
    for fa in free_agents:
        if fa.season_points is None or fa.name in roster_names:
            continue
        eligible = _eligible_positions(fa.position)
        comparable = [
            p for p in roster
            if p.season_points is not None and _eligible_positions(p.position) & eligible
        ]
        if not comparable:
            continue
        weakest = min(comparable, key=lambda p: p.season_points)
        if fa.season_points > weakest.season_points:
            recs.append(Recommendation(
                category="season_upgrade", source=source, add_name=fa.name,
                add_position=fa.position, add_team=fa.nfl_team, add_value=fa.season_points,
                drop_name=weakest.name, compare_value=weakest.season_points,
                reason=(
                    f"{fa.name} ({fa.position}) projects {fa.season_points:.1f} season pts by "
                    f"{source}, ahead of your {weakest.name}'s {weakest.season_points:.1f}."
                ),
            ))
    return recs


def _position_depth(roster: list[RosterPlayer], position: str) -> int:
    return sum(1 for p in roster if position in _eligible_positions(p.position))


def _bench_depth_recommendations(
    roster: list[RosterPlayer], free_agents: list[FreeAgent], starters_config: list[dict],
    source: str, roster_names: set[str], open_bench_slots: int,
) -> list[Recommendation]:
    """Tier 3: only fires when there's real bench room (roster below the
    27-player cap). "Thin" is deliberately simple: a position counts as
    thin if the roster doesn't have at least one more player at that
    position than the COMBINED starter count of every slot this position
    is eligible for (e.g. TE is eligible for both the dedicated TE slot
    AND the WR_TE_FLEX slot in this league -- both counts are summed, not
    just whichever slot happens to be checked first, since a single
    -slot threshold understated real demand for a position shared across
    multiple slots). Recommends the single best season_points free agent
    at each thin position, added outright (no drop)."""
    if open_bench_slots <= 0:
        return []
    recs = []
    combined_slot_count: dict[str, int] = {}
    for slot in starters_config:
        for pos in slot["eligible"]:
            combined_slot_count[pos] = combined_slot_count.get(pos, 0) + slot["count"]

    for pos, required in combined_slot_count.items():
        depth = _position_depth(roster, pos)
        if depth > required:
            continue  # already has bench cover at this position
        candidates = [
            fa for fa in free_agents
            if fa.season_points is not None and fa.name not in roster_names
            and pos in _eligible_positions(fa.position)
        ]
        if not candidates:
            continue
        best = max(candidates, key=lambda fa: fa.season_points)
        recs.append(Recommendation(
            category="bench_depth", source=source, add_name=best.name,
            add_position=best.position, add_team=best.nfl_team,
            add_value=best.season_points,
            reason=(
                f"Only {depth} {pos}(s) rostered against {required} combined starting slot(s) "
                f"eligible for {pos} -- {best.name} adds depth "
                f"({best.season_points:.1f} season pts by {source}), open bench slot available."
            ),
        ))
    return recs


def _full_roster_swap_recommendations(
    roster: list[RosterPlayer], free_agents: list[FreeAgent], source: str,
    roster_names: set[str], open_bench_slots: int,
) -> list[Recommendation]:
    """Tier 4: only fires at the 27-player cap (no open_bench_slots) --
    otherwise tier 3 (add without dropping) is strictly better advice.
    Compares against the single weakest bench (non-starter) player by
    season_points; if no bench player has a season_points value, falls
    back to the weakest roster player overall so this tier still has
    something to compare against."""
    if open_bench_slots > 0:
        return []
    bench = [p for p in roster if not p.is_starter and p.season_points is not None]
    pool = bench or [p for p in roster if p.season_points is not None]
    if not pool:
        return []
    weakest = min(pool, key=lambda p: p.season_points)

    recs = []
    for fa in free_agents:
        if fa.season_points is None or fa.name in roster_names:
            continue
        if fa.season_points > weakest.season_points:
            recs.append(Recommendation(
                category="full_roster_swap", source=source, add_name=fa.name,
                add_position=fa.position, add_team=fa.nfl_team, add_value=fa.season_points,
                drop_name=weakest.name, compare_value=weakest.season_points,
                reason=(
                    f"Roster is full (27/27) -- {fa.name} ({fa.position}) projects "
                    f"{fa.season_points:.1f} season pts by {source} vs. your weakest bench "
                    f"player {weakest.name}'s {weakest.season_points:.1f}. Drop {weakest.name}, "
                    f"add {fa.name}."
                ),
            ))
    return recs


def build_recommendations(
    roster_by_source: dict[str, list[RosterPlayer]],
    free_agents_by_source: dict[str, list[FreeAgent]],
    starters_config: list[dict],
    roster_total_max: int,
) -> list[Recommendation]:
    """Full pipeline across every source in `free_agents_by_source`
    (typically {"CBS": [...], "FantasyPoints": [...]})-> one ranked,
    deduplicated Recommendation list, highest priority first (tier order,
    then by how much the add beats its comparison player -- ties broken
    by raw add_value). A player who'd qualify under more than one tier
    (e.g. both a season upgrade AND a bench-depth add) keeps only their
    highest-priority (lowest tier number) recommendation -- one line per
    player, not one per reason, so the league manager doesn't see the
    same name 3 times with different justifications. Ties across
    DIFFERENT sources recommending the SAME player are NOT deduplicated
    across sources -- seeing "CBS says X, FantasyPoints also says X" is
    itself useful signal, not noise, so both are kept (still just one
    row per (player, source) pair).

    `roster_by_source` is keyed the same way as `free_agents_by_source`
    and (usually) holds the SAME roster of players, just valued
    differently per source -- e.g. Monster Cheese's own players scored
    under CBS's projections for the "CBS" key, and the same players
    scored under FantasyPoints' projections for the "FantasyPoints" key
    (see pages/9_Waiver_Wire.py for how those two valuations are built).
    Comparing a CBS free agent's FPTS against a roster player's
    FantasyPoints-scored value (or vice versa) would be an apples-to
    -oranges mismatch this function deliberately avoids by requiring a
    same-source roster valuation for every source of free agents."""
    all_recs: list[Recommendation] = []
    for source, free_agents in free_agents_by_source.items():
        roster = roster_by_source.get(source, [])
        roster_names = {p.name for p in roster}
        open_bench_slots = max(0, roster_total_max - len(roster))

        all_recs += _bye_gap_recommendations(roster, free_agents, starters_config, source, roster_names)
        all_recs += _season_upgrade_recommendations(roster, free_agents, source, roster_names)
        all_recs += _bench_depth_recommendations(
            roster, free_agents, starters_config, source, roster_names, open_bench_slots,
        )
        all_recs += _full_roster_swap_recommendations(
            roster, free_agents, source, roster_names, open_bench_slots,
        )

    def _margin(r: Recommendation) -> float:
        return r.add_value - r.compare_value if r.compare_value is not None else r.add_value

    all_recs.sort(key=lambda r: (_CATEGORY_PRIORITY[r.category], -_margin(r)))

    deduped: list[Recommendation] = []
    seen: set[tuple[str, str]] = set()  # (add_name, source)
    for r in all_recs:
        key = (r.add_name, r.source)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped
