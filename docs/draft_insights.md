# Draft insights — real 2026 CBS projections

Generated 2026-08-24 by running `src/projections.build_draft_board` against
real CBS 2026 season projections (`data/projections/cbs_2026.csv`, 415
players across QB/RB/WR/TE/K/DST) scored with our real league rules
(`config/league_settings.yaml`).

## The QB-dominance hypothesis: confirmed for raw score, REVERSED for draft value

A prior pass using placeholder 2025 sample data suggested QBs might
dominate the top of overall rankings, "plausibly because of the superflex
slot and generous passing bonuses." With real 2026 data, that's half
right — and the half that's wrong matters for how you should actually
draft.

**By raw projected score, QBs do dominate**: 14 of the top 15 highest
scoring players leaguewide are QBs (Josh Allen leads at 810 pts, and the
QB pool stays rich well past the top names — Jaxson Dart, Baker Mayfield,
and Daniel Jones all project inside the top 15 overall by raw score).
This confirms this league's passing-yardage bonus tiers (up to 38 pts for
600+ pass yards in a game) and 6pt/TD-plus-bonus scoring make QB the
highest-scoring position by a wide margin.

**But by value-over-replacement (VOR) — what should actually drive draft
order — RBs dominate instead.** 18 of the top 24 VOR-ranked players are
RBs; only 1 QB (Josh Allen) makes that cut. The reason: this league needs
roughly **15.5 startable QBs** leaguewide (10 dedicated QB slots + an
estimated 5.5 from superflex demand) but the QB talent pool is *deep* —
the 15th-best projected QB (Daniel Jones, 744 pts) is barely behind the
QB1 (Allen, 810 pts), a ~66-point gap. RB demand is far higher (**~36
startable RBs** leaguewide: 30 dedicated RB-slot starters + flex/superflex
spillover) and the RB talent pool falls off a cliff — RB1 (Jahmyr Gibbs,
771 pts) to RB36-ish replacement level is a much steeper drop, which is
exactly what VOR is built to detect.

**Practical takeaway for draft day**: don't let the raw "Proj Pts" column
alone drive early picks — sort the Draft Board by VOR (the default sort).
Early QBs still have real value (Allen shows up at VOR rank #24, still a
first-two-rounds-worthy value), but the board says prioritize the top RBs
first, not punt them for a run on QBs just because QBs post the biggest
raw numbers.

## Caveats

- VOR depends on the `estimation_assumptions.flex_position_splits` in
  `config/league_settings.yaml` — how superflex/flex demand is assumed to
  split across positions. Those are documented, tunable assumptions, not
  known facts (nobody knows how the other 9 managers will actually use
  their flex slots). Reasonable alternative splits could narrow the
  RB/QB VOR gap somewhat, though the RB scarcity effect is large enough
  that it's unlikely to flip the overall conclusion.
- This is CBS's own projections only (see main handoff — FantasyPros/ESPN
  blending is a nice-to-have not yet done). A blended multi-source view
  could shift individual player rankings, though the position-level
  scarcity dynamic above is a function of the whole position's depth, not
  any one player's projection, so it should be fairly robust to blending.
- Kicker FG-distance bonus and defensive PA/yards-allowed scoring still
  rely on the documented estimates in `config/league_settings.yaml` (see
  its `metadata.notes` and `estimation_assumptions` sections) — treat K/DST
  rankings as directionally useful, not precise.
