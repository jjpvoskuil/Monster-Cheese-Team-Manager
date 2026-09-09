"""
Trade recommendations -- proposes multi-player trades with other teams
in the league, per league-manager request (2026-09-09):

  "I'd like to get recommendations of potential trades with other
  teams. The trade should obviously upgrade our team and may also be
  used to cover for bye week risks on the roster (knowing that that is
  a trade only good for one week in and of itself). In order for trades
  to generally work, it has to be in the best perceived interest of
  both teams. An example is trading to get a better RB in exchange for
  a QB because one team has a gap at RB and the other team has a gap at
  QB and typically has the depth to give up a player at a position for
  a position without depth. For the sake of this analysis, we want to
  see value only based on Fantasypoints projections, however, most
  other teams will use CBS, so situations where Fantasypoints values a
  player higher than CBS might make the trade seem better than it
  actual is for the team using CBS projections. No team will trade away
  more than 3 players."

DESIGN -- two different lenses, on purpose:
  - MY needs/surplus, and how much I gain, are judged by FantasyPoints
    (the source the league manager trusts).
  - THEIR needs/surplus, and how much THEY gain, are judged by CBS
    (what "most other teams" are assumed to be looking at) -- this is
    exactly the guard against the risk called out above: a trade that
    only looks good because FantasyPoints rates a player higher than
    CBS does would show up as a false positive under a same-source
    evaluation. Requiring the OTHER team's gain to be positive under
    CBS specifically (not FantasyPoints) is what filters those out.

VALUE METRIC: VOR (value over this league's real per-position
replacement level -- src.projections.compute_position_demand/
score_and_rank), not raw season points. Same "true value" framework
this app already uses for the Draft Board and Suggested Pick, so a
thin-position player's VOR premium (and a deep-position player's VOR
discount) is already baked in -- exactly the mechanism behind the
worked example above ("a team ... typically has the depth to give up a
player at a position without depth" only makes sense in VOR terms: a
surplus QB is a QB whose OWN team has other QBs with comparable value,
i.e. low marginal VOR to give up, not literally the raw-points-weakest
player at the position).

NEED / SURPLUS, per team per position: every league team runs this
league's SAME starters config, so "how many starters at position P
across the whole league" (src.trade_recommendations._combined_slot_count,
same combined-across-slots logic as
src.waiver_recommendations._bench_depth_recommendations) is a fixed
number. A team's rostered players eligible for P, ranked by VOR
descending: the top `required` of them are that team's "starters" at P;
anyone beyond that is spare/tradeable SURPLUS. NEED at P is flagged
when the team is numerically short of `required` players at P, OR when
its actual starters at P include one below replacement level (VOR < 0)
-- a numerically-full-but-weak position is still a real need, just
without the missing-body signal alone catching it.

MATCHING: for my team vs. each other team, look for a position I have
SURPLUS at that they NEED (my give side) and a position they have
SURPLUS at that I NEED (my get side). No such complementary pair means
no trade basis with that team -- skipped outright, not forced. Within
that, try every (give_count, get_count) pair up to the 3-per-side cap
(taking the give side's most-CBS-attractive surplus players and the
get side's most-FantasyPoints-valuable surplus players first, since
those are what each side would actually want to include), and keep the
best-scoring combination where BOTH my FantasyPoints-based gain AND
their CBS-based gain are positive.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import combinations


def combined_slot_count(starters_config: list[dict]) -> dict[str, int]:
    """Total starter-slot count across the whole config for every
    position, summed over every slot that position is eligible for
    (e.g. TE counts toward both a dedicated TE slot and WR_TE_FLEX in
    this league) -- same logic as
    src.waiver_recommendations._bench_depth_recommendations, pulled out
    here since both trade and waiver-wire depth checks need it."""
    counts: dict[str, int] = {}
    for slot in starters_config:
        for pos in slot["eligible"]:
            counts[pos] = counts.get(pos, 0) + slot["count"]
    return counts


def _eligible_positions(position: str) -> set[str]:
    return set(position.split("-"))


def _dedup_by_identity(players: list) -> list:
    seen: set[int] = set()
    out = []
    for p in players:
        if id(p) in seen:
            continue
        seen.add(id(p))
        out.append(p)
    return out


@dataclass
class TeamPlayer:
    name: str
    position: str          # may be dash-joined for dual eligibility ("QB-TE")
    nfl_team: str
    fp_vor: float = 0.0     # FantasyPoints-projection VOR (my evaluation lens)
    cbs_vor: float = 0.0    # CBS-projection VOR ("most other teams" lens)
    bye_week: int | None = None


@dataclass
class PositionProfile:
    starters: list[TeamPlayer]
    surplus: list[TeamPlayer]   # sorted, most valuable first (by the value_key used to build it)
    is_need: bool


def _position_groups(
    roster: list[TeamPlayer], required_by_position: dict[str, int], value_key: str,
) -> dict[str, PositionProfile]:
    by_pos: dict[str, list[TeamPlayer]] = {}
    for p in roster:
        for pos in _eligible_positions(p.position):
            by_pos.setdefault(pos, []).append(p)

    profiles: dict[str, PositionProfile] = {}
    for pos, players in by_pos.items():
        ranked = sorted(players, key=lambda pl: getattr(pl, value_key), reverse=True)
        required = required_by_position.get(pos, 0)
        starters, surplus = ranked[:required], ranked[required:]
        missing = required - len(starters)
        weak_starter = any(getattr(p, value_key) < 0 for p in starters)
        profiles[pos] = PositionProfile(starters=starters, surplus=surplus, is_need=(missing > 0 or weak_starter))
    return profiles


@dataclass
class TradeProposal:
    other_team: str
    give: list[TeamPlayer]      # my players going out
    get: list[TeamPlayer]       # their players coming in
    fp_gain_mine: float          # my perceived VOR gain, FantasyPoints-valued
    cbs_gain_mine: float         # what CBS would say I gained (for comparison/flagging)
    cbs_gain_theirs: float       # what CBS would say THEY gained (their likely incentive to accept)
    give_positions: set[str]
    get_positions: set[str]
    bye_note: str | None = None


def _best_combo(
    give_pool: list[TeamPlayer], get_pool: list[TeamPlayer], max_per_side: int,
) -> tuple[list[TeamPlayer], list[TeamPlayer], float, float, float] | None:
    """Try every (give_count, get_count) size up to max_per_side, taking
    the top `count` players already ranked into each pool (see callers
    -- give_pool is ranked by CBS attractiveness to the other side,
    get_pool by FantasyPoints value to me), and keep the valid
    combination (positive gain for both sides, under each side's own
    trusted source) that maximizes MY FantasyPoints VOR gain. Returns
    None if no combination clears both bars."""
    best = None
    best_fp_gain = float("-inf")
    for give_count in range(1, min(max_per_side, len(give_pool)) + 1):
        give = give_pool[:give_count]
        for get_count in range(1, min(max_per_side, len(get_pool)) + 1):
            get = get_pool[:get_count]
            fp_gain_mine = sum(p.fp_vor for p in get) - sum(p.fp_vor for p in give)
            cbs_gain_mine = sum(p.cbs_vor for p in get) - sum(p.cbs_vor for p in give)
            cbs_gain_theirs = sum(p.cbs_vor for p in give) - sum(p.cbs_vor for p in get)
            if fp_gain_mine > 0 and cbs_gain_theirs > 0 and fp_gain_mine > best_fp_gain:
                best_fp_gain = fp_gain_mine
                best = (give, get, fp_gain_mine, cbs_gain_mine, cbs_gain_theirs)
    return best


def _bye_week_note(my_roster: list[TeamPlayer], get: list[TeamPlayer], get_positions: set[str]) -> str | None:
    """Informational only (league-manager request: trades "may also be
    used to cover for bye week risks ... knowing that that is a trade
    only good for one week in and of itself") -- flags when an incoming
    player's bye week differs from a bye week shared by 2+ of my
    existing players at the same position, without treating bye-week
    coverage as a ranking factor. Not run for positions with no shared
    -bye risk at all -- most won't have one."""
    for pos in get_positions:
        same_pos = [p for p in my_roster if pos in _eligible_positions(p.position) and p.bye_week]
        bye_counts: dict[int, int] = {}
        for p in same_pos:
            bye_counts[p.bye_week] = bye_counts.get(p.bye_week, 0) + 1
        clustered = {wk for wk, n in bye_counts.items() if n >= 2}
        if not clustered:
            continue
        incoming = [p for p in get if pos in _eligible_positions(p.position)]
        for p in incoming:
            if p.bye_week and p.bye_week not in clustered:
                weeks = ", ".join(str(w) for w in sorted(clustered))
                return (
                    f"Bonus: {p.name}'s bye (week {p.bye_week}) also spreads out your {pos} bye-week "
                    f"risk -- {len(same_pos)} of your {pos}s currently share week(s) {weeks} (good for "
                    f"only that one week, but worth knowing)."
                )
    return None


def find_trades(
    my_team: str,
    rosters: dict[str, list[TeamPlayer]],
    starters_config: list[dict],
    max_players_per_side: int = 3,
) -> list[TradeProposal]:
    """One candidate trade per other team (at most), ranked by my
    FantasyPoints VOR gain descending. A team with no complementary
    need/surplus match, or where no player-count combination clears
    both sides' gain bars, contributes nothing -- this deliberately
    does not force a trade to exist with every team."""
    required = combined_slot_count(starters_config)
    my_roster = rosters.get(my_team, [])
    my_profiles = _position_groups(my_roster, required, "fp_vor")
    my_needs = {pos for pos, prof in my_profiles.items() if prof.is_need}
    my_surplus = {pos: prof.surplus for pos, prof in my_profiles.items() if prof.surplus}

    proposals: list[TradeProposal] = []
    for other_team, other_roster in rosters.items():
        if other_team == my_team or not other_roster:
            continue
        their_profiles = _position_groups(other_roster, required, "cbs_vor")
        their_needs = {pos for pos, prof in their_profiles.items() if prof.is_need}
        their_surplus = {pos: prof.surplus for pos, prof in their_profiles.items() if prof.surplus}

        give_positions = set(my_surplus) & their_needs      # I can spare it, they need it
        get_positions = set(their_surplus) & my_needs        # they can spare it, I need it
        if not give_positions or not get_positions:
            continue

        give_pool = sorted(
            (p for pos in give_positions for p in my_surplus[pos]),
            key=lambda p: p.cbs_vor, reverse=True,
        )
        get_pool = sorted(
            (p for pos in get_positions for p in their_surplus[pos]),
            key=lambda p: p.fp_vor, reverse=True,
        )
        # A player could appear under more than one qualifying position
        # (dual eligibility) -- de-dup by identity while preserving the
        # sort (TeamPlayer isn't hashable, so dict.fromkeys won't work).
        give_pool = _dedup_by_identity(give_pool)
        get_pool = _dedup_by_identity(get_pool)

        combo = _best_combo(give_pool, get_pool, max_players_per_side)
        if combo is None:
            continue
        give, get, fp_gain_mine, cbs_gain_mine, cbs_gain_theirs = combo
        proposals.append(TradeProposal(
            other_team=other_team, give=give, get=get,
            fp_gain_mine=fp_gain_mine, cbs_gain_mine=cbs_gain_mine, cbs_gain_theirs=cbs_gain_theirs,
            give_positions=give_positions, get_positions=get_positions,
            bye_note=_bye_week_note(my_roster, get, get_positions),
        ))

    proposals.sort(key=lambda t: t.fp_gain_mine, reverse=True)
    return proposals
