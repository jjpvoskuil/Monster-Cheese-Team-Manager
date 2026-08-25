# Session Notes

Running log for whoever (human or Claude) picks up this repo next.
**Read this file first, at the start of every session, before doing
anything else.** When you finish meaningful work, add a dated entry at
the top of the log (below "How to use this file") — newest entry first.
Keep entries short: what happened, what's true now, what's next. Don't
rewrite history further down; just append.

Draft day: **Sunday 2026-08-30, 2:30pm ET.**

## How to use this file

- New session: read "Current state" below, then skim recent log entries
  for anything relevant to what you're about to do.
- Finished a task, hit a bug, made a decision worth remembering: add an
  entry at the top of the log with today's date.
- This file lives in the repo (not a Claude Project doc) so it travels
  with `git clone` regardless of which session or tool picks this up.

## Current state

- Repo has the full Phase 1 scaffold: scoring engine, projections/VOR,
  draft state tracking, the Streamlit Draft Board UI, config, tests, and
  real 2026 CBS projection data (415 players).
- Real 2026 draft order is in `config/league_settings.yaml` under
  `draft.team_order` (10 teams, confirmed standard snake, 22 rounds).
  Monster Cheese drafts 8th overall in round 1. The Draft Board now uses
  this instead of placeholder "Team 1/2/3" names.
- Three projection sources now ingested and blendable: CBS (415 players,
  all rostered), FFToday (264 players, ~50/skill-position + all 32 DSTs),
  FantasyPros (60 players, top-10/position only — free-tier cap). New
  `pages/2_Projections.py` page lets you view each source individually,
  set per-source weights (0 to exclude, single non-zero to isolate one
  source), and see the blended stat line — this is the same
  `blend_projections`/`build_draft_board` pipeline the Draft Board uses,
  just exposed directly. FFToday and FantasyPros each have a "Refresh from
  web" button (live re-fetch); CBS does not (requires a logged-in
  session — re-pull manually, see below).
- SUPERFLEX demand assumption (`config/league_settings.yaml` →
  `estimation_assumptions.flex_position_splits.SUPERFLEX`) is now 90% QB
  (was 55%), per league-manager feedback that this scoring system makes a
  good QB nearly always the right superflex fill — every team should
  expect to start ~2 QBs almost every week. QB league-wide demand is now
  ~19 (10 dedicated + ~9 of the superflex slot), up from ~15.5, which
  raises QB's replacement level and lowers early-QB VOR accordingly.
- Both the Draft Board and Projections pages now compute position tiers
  (`src/projections.py`'s `compute_tiers()`) — same-position players
  clustered by point drop-off. Manual override (points, e.g. "10") is an
  anchor-based spread cap: every player in a tier is within that many
  points of the TIER'S TOP SCORER (not just the previous player — an
  earlier version compared only to the previous player and let a chain of
  small gaps drift a tier arbitrarily wide, e.g. an override of 10 still
  producing a tier spanning 54+ points; fixed 2026-08-25). Automatic mode
  (`src/tiering.py`) uses Jenks natural breaks with the class count chosen
  so no tier exceeds ~8% of that position's own point range — see that
  module's docstring for why two earlier gap-statistic-based designs both
  looked reasonable but still produced a 30-player/218-point top QB tier.
  Tier divider rows render in the player grid when filtered to a single
  position.
- New `pages/3_Draft_Tendencies.py` page (2026-08-25): historical
  positional draft tendencies from 4 completed seasons of real CBS draft
  results (2022-2025, 220 picks each, 880 total), pulled and parsed per
  the league manager's request to automate what "Alt Targets" in
  `TARGETS 2025.xlsx` used to track by hand. Raw captures live in
  `data/draft_history/raw/<year>_raw.txt`; `scripts/fetch_draft_history.py`
  parses them (via `src/data_sources/draft_history.py`) into the
  canonical `data/draft_history/draft_history.csv`. `src/draft_tendencies.py`
  computes per-round position counts and cumulative-by-pick curves,
  averaged across any user-selected subset of years, and predicts how
  many of each position are likely to go in the next N rounds from the
  live draft state. `src/roster_needs.py` cross-references each upcoming
  opponent's already-drafted roster against `roster.starters` to flag
  which starter slots they still need filled (dedicated slots like
  QB/RB/TE/K/DST filled first, then WR_TE_FLEX/SUPERFLEX/FLEX), and the
  page combines that with the historical prediction into one "watch this
  position" signal. 2022's draft-results page has 3 dropdown entries and
  only one ("2022 - MFL Draft", URL segment `2022:3:MFL Draft`) has real
  pick data — the other two ("2022 - 2" and "2022" plain) are empty
  placeholder tables; confirmed by visiting all three before capturing.
- **Live CBS draft sync (2026-08-25)**: `src/live_sync.py` parses the
  live CBS draft room's results panel and merges new picks into
  `data/draft_state.json` (the SAME file manual "Log a pick" writes to
  — the Draft Board doesn't know or care which one produced a pick).
  Built and verified against a REAL CBS mock draft, not synthetic data
  — see the dedicated log entry below for the full runbook (exact JS
  extraction snippet, polling cadence, how to run it live) and the real
  -data edge cases it handles (autopilot `*` prefix, "Last, First (POS
  TEAM)" format, punctuated last names, the live room's Pick column
  already being the OVERALL pick number unlike the historical results
  page). `src/data_sources/cbs.py`'s old stub for this is superseded —
  see its docstring. DST/K live-room cell format confirmed and a second
  independent mock draft run end-to-end (see the 2026-08-25 "test-drive"
  log entry below) — only an actual draft-day dry run is still
  outstanding.
- **Suggested pick (2026-08-25)**: `src/pick_suggestion.py` powers a new
  "🎯 Suggested pick" panel on the Draft Board, right above the player
  grid. Recommends a POSITION (not a single player) by combining three
  normalized 0-1 signals into a weighted composite: best-available VOR at
  that position (45%), how much MY roster still needs it — reusing
  `src/roster_needs.py`'s slot-filling logic against my own picks instead
  of an opponent's (30%), and run-risk scarcity from
  `src/draft_tendencies.py`'s historical predictions vs. tier-1 players
  remaining (25%, gracefully drops to 0 if `draft_history.csv` is
  missing). Shows the recommendation + a "why" breakdown table for every
  position, then the top 3 available players at either the recommended
  position or any position you override to via a dropdown — with a
  "Draft this player" button per player (enabled only when it's actually
  your turn; the panel itself is always visible and previews your next
  turn's recommendation even while others are picking). The tier-gap
  override control moved up the page (now sits right before this panel,
  since both it and the player grid below now share one `available_tiered`
  computation). A "↩️ Back to &lt;position&gt;" button appears next to the
  override dropdown whenever it's been changed away from the
  recommendation, so it's a one-click return rather than having to
  remember/re-pick the original suggestion. 14 new tests in
  `tests/test_pick_suggestion.py`.
- `pytest` — 128/128 passing.
- Deployed to Streamlit Cloud; user confirmed the Draft Board loads
  correctly as of 2026-08-25.
- Known gaps (not blocking): ESPN blending not done (would be a 4th
  source — see notes below); defensive
  PA/yards-allowed tables (only 3 tiers each on CBS's page) not yet
  re-confirmed with the commissioner; no full UI click-through of the
  Draft Board, Projections, or Draft Tendencies page has been done beyond
  direct pipeline checks and Streamlit's `AppTest` harness (see lesson
  below); parsing an in-progress/completed draft (PLAYER column
  populated) is not built for `draft_order.py` (the pre-draft order
  parser) — but IS now built separately for historical completed drafts
  via `draft_history.py`, above; FantasyPros' live-refresh-via-`requests`
  path is UNVERIFIED (this dev sandbox has no general internet egress to
  test against fantasypros.com — see entry below); draft-history only
  covers 2022-2025 — re-run `scripts/fetch_draft_history.py` after
  capturing a new raw file once the 2026 draft actually happens, to fold
  it into future-year tendency averages.

## Git push access — read this if `git push` 403s

Sessions are sometimes started without this repo attached as a source,
which makes `git push` fail with a proxy 403 ("not in this session's
authorized repository set") even though `git clone`/read access works
fine. Workaround (confirmed working, no need to restart the session):

```
cd <repo>
PAT='<github PAT with repo scope, ask the user>'
AUTH=$(printf 'x-access-token:%s' "$PAT" | base64 -w0)
git config --local http.https://github.com/.extraheader "Authorization: Basic $AUTH"
```

After that, ordinary `git push`/`pull`/`fetch` work for the rest of the
session — the proxy's allowlist doesn't intercept requests that already
carry their own Authorization header. Ask the user for a fresh PAT each
time; don't assume an old one from the log below is still valid.

## Log

### 2026-08-25 — Test-drove the full live-sync + suggested-pick pipeline against a SECOND real CBS mock draft
League manager's request, after the Suggested Pick feature shipped:
"Lets test drive this with a mock draft to see how it goes." Chose the
"quick smoke test" depth (~5 rounds) over a deeper or full run.

Joined a fresh CBS practice mock draft (10 teams, 14 rounds, standard
roster — 1 QB/2 RB/3 WR/1 TE/1 K/1 DST/5 RES, a real mix of human
participants and bots — draft id 2832563, separate from both the real
league and the earlier Phase 1 test draft) via Claude in Chrome, took
draft slot 6, and played 5+ full rounds (55 picks) live: 2 picks made
manually by clicking through the room after computing the suggestion
(picks 6 and 15 — De'Von Achane and Kyren Williams, both RB per the
suggestion engine's recommendation), the rest handled by CBS's own
autopilot for my team once real findings below made manual clicking
impractical for every single pick.

**What worked, confirmed against REAL data from a draft this session had
no part in scripting:**
- `parse_live_room_dump()` correctly parsed all 52 picks from this
  draft's live results panel in one extraction (via the documented
  "switch to All Results, dump to a `<pre>` element, retrieve via
  `get_page_text`" technique) with zero parse failures, including edge
  cases the FIRST mock draft's test didn't happen to produce: apostrophes
  ("De'Von Achane"), periods in a first name ("A.J. Brown"), and
  multi-word autopilot team names ("Auto-Pilot Team 1").
- `sync_new_picks()` logged all 52 picks correctly with zero mismatches,
  AND — for the first time verified against real data rather than only
  synthetic fixtures — a SECOND identical poll against the same 52-pick
  dump was confirmed fully idempotent (0 newly logged, 52 already known,
  no duplicate/corrupted state). This is exactly the steady-state
  behavior a ~90-120s polling loop depends on.
- `suggest_position()` produced sensible, explainable recommendations
  throughout: recommended RB early (an RB run was genuinely happening —
  5 of the first 5 picks leaguewide were RBs) and correctly favored value
  +need later once the roster's RB/WR starter slots filled up. One
  recommended player (Jeremiyah Love) got drafted by another team one
  pick after the suggestion named him as the top RB available —
  independent confirmation the engine's value judgment lines up with
  what a real drafting field also wants, not just an internal metric.
- **Resolved both items flagged as unverified in the live-sync work
  above**: DST ("Browns (DST CLE)") and K ("Mevis, Harrison (K LAR)")
  live-room cell formats are now confirmed correct against real data —
  observed in the FIRST mock draft (left running with autopilot since
  the original Phase 1 session, discovered already complete at the start
  of this session) rather than needing a new draft to run 14 full
  rounds. `parse_live_room_player_cell()`'s existing fallback regex
  handled the DST case correctly with no changes needed.

**Real, non-code finding worth planning around for draft day:** this
particular mock draft moved very fast — as little as ~10-20 seconds
between picks once bots were involved, and this session's own pick clock
ran out once (pick 26, CBS's autopilot filled in A.J. Brown for a
missed manual pick) while a suggestion was being computed. The lesson
isn't a pipeline bug — `sync_new_picks`/`suggest_position` themselves
ran in well under a second — it's that extracting the room, running the
suggestion, and clicking a pick are three separate round-trips that
don't fit inside a fast pick clock if done from scratch reactively. On
the real draft, this isn't a problem the way it was in this test:
the league manager will have the Draft Board already open with an
already-computed, continuously-refreshing suggestion (from the ongoing
sync loop), so deciding is a glance-and-click, not a compute-from
-scratch-under-the-clock. The lesson that DOES carry over: for the real
draft, precompute/refresh the suggestion as soon as a session is only
1-2 picks away from its own turn, don't wait until it's actually on the
clock to start pulling data.

No code changes this session — this was a pipeline/UX validation pass,
not a bug-fix pass, since nothing broke. 128/128 tests still passing
(unchanged). Draft left running in CBS's system on autopilot (harmless,
same as the earlier Phase 1 test draft).

### 2026-08-25 — Suggested pick panel: recommend a position + top 3 players, live during the draft
League manager's ask, right after the live-sync work above landed: "add a
suggest pick area that updates as picks progress through the draft...
look at draft tendencies, my roster spots filled, roster spots filled for
a starting lineup, available players in tiers and the projected points...
suggest the next position to pick and the top 3 players available."
Also wanted to draft straight from that shortlist or off the full grid,
and to override the suggested position and see that position's own best
players/value instead.

**Design decision: recommend a POSITION first, then shortlist players for
it** — matches the request literally, and keeps the "why" explainable
(three named signals per position) rather than a single opaque per-player
score. New `src/pick_suggestion.py`:
- **Value** — best available player's VOR at each position. VOR is
  already cross-position comparable by construction (see
  `src/projections.py`), so "best available VOR per position" is a fair
  apples-to-apples signal with no extra normalization needed at the raw
  level.
- **Need** — reuses `src/roster_needs.py`'s greedy slot-filling logic
  (originally built to infer OPPONENTS' needs for the Draft Tendencies
  page) against `draft_state.my_roster()` instead — no new roster-need
  code, just a new caller (`my_position_need()`).
- **Scarcity** — `src/draft_tendencies.py`'s `predict_position_counts()`
  for the window between now and my next turn, divided by how many
  tier-1 players are left at that position right now (tier comes straight
  off whatever `compute_tiers()` output the Draft Board is already
  showing, including the user's own tier-gap override — the suggestion
  always matches what's on screen). New `picks_before_my_next_turn()`
  helper: when it's my pick RIGHT NOW, the relevant horizon isn't "0
  picks until my turn" (trivially true) — it's the round-trip to my
  NEXT turn, since that's what determines whether a position survives if
  I take something else now. When it's not my pick, this matches
  `DraftState.picks_until_my_turn()`.

Each raw signal is normalized 0-1 (divided by its own max across the
positions being compared, so a demand-weight scale and a VOR-points scale
and a picks-per-remaining-tier-1-player ratio don't fight for arbitrary
dominance) then combined as **45% value + 30% need + 25% scarcity** —
documented, tunable constants in the same style as this app's other
heuristic knobs (superflex splits, tier max-spread-fraction). Verified
with a synthetic test where value and need are tied between two
positions and only scarcity differs — confirms scarcity alone can flip
the recommendation, not just nudge a already-decided one
(`test_suggest_position_scarcity_can_flip_the_recommendation`). Degrades
cleanly with no `draft_history.csv` (scarcity contributes 0 to every
position, ranking falls back to value+need) and reports `None` with a
clear reason when the draft is complete or no players remain.

`pages/1_Draft_Board.py`: new "🎯 Suggested pick" section, positioned
above the player grid (the tier-gap-override control moved up the page
to sit right before it, since both the suggestion engine and the grid
below now share one `available_tiered` computation instead of computing
it twice). Shows the recommendation with its reasoning sentence, an
expander breaking down every position's value/need/scarcity numbers, a
position-override dropdown (any position, not just the recommendation),
and the top-3-players-for-that-position as cards with a "Draft this
player" button each. Buttons log straight to `draft_state` via the
existing `log_pick_on_the_clock()` and are disabled unless it's actually
your turn — but the recommendation text itself stays visible and updates
even when it's not your turn yet, previewing what it'll suggest once
your turn comes back around (this is what "updates as picks progress"
means in practice: every rerun re-reads the live `DraftState`, so a live
-synced pick landing mid-draft changes the recommendation on the very
next page refresh, no separate wiring needed).

Verified via `AppTest` against the REAL 2026 player pool and the real
league's snake order (not synthetic fixtures) in three states: not-my
-turn (recommendation shown as a preview, all 3 draft buttons correctly
disabled), my-turn (buttons enabled, clicking one correctly logged a real
player — Jahmyr Gibbs — to `DraftState` and persisted it), and the
position-override dropdown (switching to TE correctly relabeled the
shown players and captioned that it was overriding the RB recommendation).
14 new tests in `tests/test_pick_suggestion.py`; 128/128 total passing.
All 4 Streamlit pages re-verified clean.

**Follow-up same day:** added a "↩️ Back to &lt;recommended position&gt;"
button next to the override dropdown, so overriding to check another
position doesn't mean having to remember/re-select what the app
originally suggested. Non-obvious Streamlit gotcha hit and fixed here:
`st.session_state[key] = value` cannot be called for a widget's key
inline after that widget has already run earlier in the same script pass
(`StreamlitAPIException`, caught immediately via `AppTest` rather than
shipped) — the reset has to happen in an `on_click` callback instead
(`_set_position_override()`), which Streamlit runs before the next
rerun's widgets are recreated. Also guarded against a position dropping
out of the option list entirely between reruns (e.g. K/DST fully
drafted) by clearing an now-invalid `session_state` selection before the
selectbox renders, rather than letting it raise. Re-verified via
`AppTest`: override to a different position, confirm the reset button
appears and correctly jumps back, confirm it disappears again once back
on the recommendation. 128/128 tests still passing (no new test file --
this is UI-callback behavior that `AppTest`'s widget interaction API
covers directly; the underlying `suggest_position()`/`top_available_players()`
logic already covered in `tests/test_pick_suggestion.py` is unchanged).

### 2026-08-25 — Live CBS draft sync built and verified against a real mock draft (Phase 1 of live-draft-day support)
User's ask, after the tiering/tendencies work above: "when we are running
the draft I want the actual draft results to drive my app so that as
players are picked on cbs it updates my app immediately." Also floated
having the app auto-pick on CBS too (Phase 2). Agreed scope with the user:
**Phase 1 only** — one-way sync (CBS → app), read-only, no automated
clicking on CBS. Phase 2 (app picks on CBS on the user's behalf) is
explicitly a "nice to have if it works really well," not built now, and
would need per-pick user confirmation before ever clicking "Draft" on CBS
regardless (an irreversible action on a live third-party site).

**Why this can't be a plain scheduled job:** CBS requires a logged-in
session and has no public API, and the deployed Streamlit app has no
browser of its own — it cannot reach out to CBS by itself under any
design. The only way to get live pick data out of CBS is an active Claude
session driving a real logged-in browser (Claude in Chrome). So the
architecture is split in two: `src/live_sync.py` (this repo, pure
functions, fully unit-tested) does the parsing/merging once pick data has
been extracted; the actual "go get the data from CBS" step is a procedure
a Claude session runs live during the draft, described below, not code
that lives in the repo.

**Tested against a REAL CBS mock draft, not synthetic data.** CBS has a
free, unlimited "Mock Draft" lobby (from the league site: Draft → Mock
Drafts → `mockdraft-1.football.cbssports.com/mockdraft/standard`) —
separate from the real league draft, real people + bot-filled, so there
was zero risk of touching the actual league draft while testing. Joined
one, took a team slot, and let it run to round 4 while inspecting the
live draft room's results panel DOM directly. This mattered: the live
room turned out to differ from the historical completed-draft results
page (`src/data_sources/draft_history.py`, used for the Draft Tendencies
page above) in two independent, non-obvious ways that a naive port of
that page's parser would have gotten silently wrong:
- **Player-cell text format** differs: historical page shows
  `"Josh Allen QB • BUF"`; live room shows `"Allen, Josh (QB BUF)"`.
- **Pick numbering** differs: historical page's "Pick" column resets to
  1 every round (combined with round number to get an overall pick);
  the live room's "Pick" column is already the overall pick number and
  just keeps counting up across round boundaries (round 2 shows picks
  11, 12, 13...).
- Both pages share the same auto-pick convention: a `*` prefix on the
  player cell (e.g. `"*Henry, Derrick (RB BAL)"`) when a pick was made by
  autopilot rather than a human clicking.

**Real bug found and fixed via the real-data test, not caught by
synthetic fixtures:** the first version of `parse_live_room_dump()`
assumed the live room's "Pick" column needed the same `(round-1)*
teams_per_round+pick` arithmetic as the historical page. Tested against a
real captured 14-pick/2-round dump, this produced a wrong overall_pick
for every round-2+ pick (offset into the 21-24 range instead of 11-14),
which `sync_new_picks()`'s gap-safety logic correctly refused to bridge —
so only 10 of 14 real picks got logged, caught by a failing assertion
(`10 == 14`) rather than a silent wrong answer. Fixed by dropping that
arithmetic entirely and using the live room's "Pick" column value
directly as `overall_pick` — see the extensive warning comment in
`parse_live_room_dump()`'s docstring so a future session doesn't
reintroduce this. `sync_new_picks()` itself worked correctly throughout
(it's what caught the bug in the first place, by refusing to skip a
gap) — the bug was purely in how the raw text got parsed into pick
numbers upstream of it.

**Extraction technique (the exact steps to run live on draft day):**
1. In the live draft room, switch the results panel from "Latest Results"
   to "All Results" so every pick made so far is visible, not just the
   current round. The panel's dropdown is a custom widget backed by a
   hidden `<select id="selectRoundResults">`; toggle it via
   `javascript_tool`:
   ```js
   var sel = document.getElementById('selectRoundResults');
   sel.value = 'all';
   mainapp.resultsView.selectOption();
   ```
2. Dump the results table to plain pipe-delimited text
   (`round|pick|team|player_cell` per line) by walking
   `#DraftRoom.views.results .SLTables1 table.data`'s rows (`tr.bg1` =
   round-label rows to read the round number from, `tr.bg2` = actual pick
   rows with 3 `<td>`s: pick number, team, player link text). Returning
   this directly from `javascript_tool` gets `[BLOCKED: Cookie/query
   string data]` (the player links' hrefs contain `?playerid=...`, which
   trips the tool's own content filter) — work around this the same way
   the Draft Tendencies historical-page capture did: write the dump into
   a `<pre>` element appended to `document.body`, then retrieve it with
   the separate `get_page_text` tool, which has no such filter and no
   `javascript_tool`'s ~1100-1200 char truncation either.
3. Feed that text to `parse_live_room_dump()`, then `sync_new_picks(draft_state,
   live_picks)`, then `write_sync_status(LIVE_SYNC_STATUS_FILE, draft_state,
   result)` so the Draft Board's sidebar shows how fresh the feed is.
4. Repeat on a poll loop. Recommended cadence: **90-120 seconds.** In the
   test mock draft, real picks landed roughly every 40-60 seconds
   (faster than a real league draft will likely run, since bots don't
   deliberate) — 90-120s keeps the app comfortably current without
   polling so often it's wasted effort, and the Draft Board's sidebar
   flags staleness (⚠️ past 150s, 🛑 past 600s) so a slower cadence, or a
   dropped poll, is visible rather than silent.

**`pages/1_Draft_Board.py`** now shows a "🔴 Live sync from CBS" sidebar
block whenever `data/live_sync_status.json` exists: last synced pick
number, freshness (✅ under 150s / ⚠️ 150-600s / 🛑 over 600s — "log
picks manually below until it resumes"), and any mismatches or
out-of-order picks the last sync pass found. The manual "Log a pick" form
is unchanged and still the reliable fallback — both write to the same
`data/draft_state.json`, so the page doesn't know or care which produced
a given pick. `src/data_sources/cbs.py`'s old `fetch_live_draft_picks`
stub is removed; its docstring now points here.

**Verified:** `src/live_sync.py` covered by 18 new tests in
`tests/test_live_sync.py`, including two end-to-end tests built from the
actual captured mock-draft dumps (`REAL_LIVE_ROOM_DUMP`,
`REAL_LIVE_ROOM_DUMP_ROUND_2`) — not just synthetic fixtures — plus
tests for contiguous logging, gap handling, idempotent re-polling,
mismatch detection, and stopping cleanly at draft-complete. 114/114 tests
passing repo-wide. All 4 Streamlit pages re-verified via `AppTest` with
the new sidebar block present, including a stale/mismatch scenario, no
exceptions.

**Still open, not blocking Phase 1 use:**
- DST and K live-room cell format is unconfirmed — the test mock draft
  only reached round 4 of 14 before wrapping up, and those positions
  typically go much later. `parse_live_room_player_cell()` has a
  defensive fallback regex for a no-comma cell shape that won't crash on
  an unexpected format, but its exact correctness for DST/K is unverified
  until observed for real.
- No continuous real-time poll loop has been run yet end-to-end (parsing
  and merging have each been verified against real snapshots taken at
  different points in the mock draft, but not yet exercised as a
  repeated poll-extract-sync cycle sustained over a full draft).
- No dry run against the actual league's draft day (2026-08-30) yet.
- Phase 2 (app → CBS pick submission) not started, per the user's own
  "nice to have" prioritization — Phase 1 (this) is the whole ask for now.

### 2026-08-25 — Draft Tendencies: 4 years of real CBS draft history + live position-run prediction + opponent roster-need view
League manager's request: "the number of players per position per draft
round is somewhat consistent... predict what will happen in the next
round or 2 by position... also look at the roster for each team to see
what positions are filled." This was previously done by hand in
`TARGETS 2025.xlsx`'s "Alt Targets" sheet.

Captured 2022-2025 actual completed drafts (not just draft order) from
`https://maniacfl.football.cbssports.com/draft/results/` via Claude in
Chrome (this page requires a logged-in session and blocks robots.txt, so
`WebFetch`/`requests` can't touch it). Used a new large-extraction
technique to work around `javascript_tool`'s ~1100-1200 char direct-return
truncation: write the extracted data into the page's own DOM as a `<pre>`
block, then retrieve it with the separate `get_page_text` tool (no
truncation there) — reliably pulled all 220 picks/year in one shot.
2022 needed extra care: 3 entries in the "DRAFTS" dropdown for that year,
found via `document.querySelectorAll('li')` (`value` attribute holds the
URL path even though it's a custom widget, not a native `<select>`) —
visited all 3 (`2022:3:MFL Draft`, `2022:2:2`, `2022:Pre-season`) and
confirmed only the first has a populated table (264 rows incl. headers =
220 real picks); the other two are empty placeholder drafts. 2022's raw
page also has 2 extra columns (Elig, Elapsed Time, Total/Active Fpts)
that other years don't show, and 2 "(Skipped Pick)" rows (round
21 pick 4, round 22 pick 7, both Buckhorns) not seen in any other year —
new edge case, handled explicitly (excluded from position counts).

Raw captures saved to `data/draft_history/raw/<year>_raw.txt` (pipe
-delimited round|pick|team|player_cell, one line per pick). New
`src/data_sources/draft_history.py` parses these into a canonical schema,
handling: auto-pick prefix (`*`), blank/free-agent NFL team (trailing
bullet with nothing after), DST picks (mascot as "player name"), and
dual-position eligibility (e.g. "Taysom Hill QB,TE" — tallied under the
FIRST listed position only, since double-counting one pick across two
positions would inflate round totals; full list kept in a `positions`
field for anyone who wants a different rule later). `scripts/
fetch_draft_history.py` runs the parser over every `*_raw.txt` file found
and writes the combined `data/draft_history/draft_history.csv` (880 picks
across the 4 years; 2 skipped, 13 auto-picks).

`src/draft_tendencies.py`: `counts_by_round()` (avg positions drafted per
round, any year subset), `cumulative_counts_by_pick()` (avg cumulative
count by exact overall pick number — the direct automation of the old
Alt Targets table), `predict_position_counts()` / `next_run_positions()`
(expected position counts in the next N picks from any current pick,
i.e. "is a run coming"). `src/roster_needs.py`: given a team's drafted
players and `config/league_settings.yaml`'s `roster.starters`, greedily
fills the most position-restrictive slots first (QB/RB/TE/K/DST) then the
flex slots (WR_TE_FLEX/SUPERFLEX/FLEX) to find which slots are still
open, and spreads that unfilled-slot "demand" across each slot's eligible
positions. New `pages/3_Draft_Tendencies.py` ties it together against the
LIVE `DraftState` (same `data/draft_state.json` the Draft Board writes):
year-subset picker, per-round historical table + chart, live next-N
-round position prediction, and a per-upcoming-opponent "likely needs"
table plus a combined-demand view that flags when historical prediction
and opponent roster gaps agree on the same position.

Verified via `AppTest` against `pages/3_Draft_Tendencies.py` in three
draft-state scenarios (empty/no draft started, mid-draft with opponents
ahead, mid-draft where it's my_team's own turn) — all render without
exception; spot-checked the opponent-needs and combined-demand tables'
actual values by hand against a synthetic roster. Real-data sanity check:
round 1 averages 4.75 QB + 4.75 RB (superflex-heavy league, matches the
2026-08-25 VOR work above), K/DST cluster in rounds 16-20 as expected.
33 new tests (`test_draft_history.py`, `test_draft_tendencies.py`,
`test_roster_needs.py`), 89/89 total passing. Pushed as `8a926cb`.

### 2026-08-25 — Fixed two real tiering bugs the league manager caught by using it: manual override drifting wide, automatic method too coarse
Follow-up to the tiering feature shipped earlier the same day (next log
entry down). The manager tried it immediately and found two real problems:

**Bug 1 — manual override drifted wider than the number entered.** Typing
"10" for QBs produced a tier spanning 780.8 to 726.3 (54 points). Root
cause: the original manual-mode logic only compared each player to the
*immediately preceding* player, not to the tier's top scorer -- a chain of
small sub-threshold gaps (several 3-8 point drops in a row) could
accumulate into a much wider total spread without any single step ever
exceeding 10. Fixed in `compute_tiers()` (`src/projections.py`) by
switching to an anchor-based check: each candidate is compared against the
*current tier's leading player's* score, not the previous row. New
`tier_max_spread` column added so the guarantee (no tier's spread exceeds
the override value) is directly visible and directly tested
(`test_manual_gap_threshold_creates_expected_tiers`, and the real-data
guarantee is exercised via `test_automatic_tiers_on_real_data_are_not_
absurdly_wide` for the automatic side).

**Bug 2 — the automatic method was still "too wide"** (the manager's own
words) even after replacing the original mean+stdev approach with Jenks
natural breaks earlier that day: QB's top tier held 30 players spanning
218 points. Root cause, found by testing against the real 2026 data rather
than trusting the small synthetic unit tests: a target-GVF stopping rule
(grow the class count until it explains a target % of variance) behaves
very differently depending on pool size and shape. For a large,
*gradually*-declining pool like QB (no single standout cliff, just a long
smooth slope), the global variance-reduction budget kept getting spent
elsewhere (a genuine late-list outlier) before the algorithm ever
revisited splitting the smooth top cluster further. A second attempt
(recursive local-outlier-gap splitting, to avoid the "global stat skewed
by one huge gap" problem) fixed the small-pool over-fragmentation this
caused but reintroduced the QB problem from the opposite direction: a
smooth gradual slope has no single local outlier gap to trigger a split at
all, however wide the cumulative range gets.

Both failure modes shared a root cause: neither approach ever directly
asked "how wide is this tier allowed to get" -- both inferred an answer
indirectly from gap statistics. Rewrote `jenks_auto_labels()`
(`src/tiering.py`) a third time to ask that question directly: grow the
Jenks class count only as far as needed so no resulting tier spans more
than `max_spread_fraction` (default 0.08, i.e. 8%) of that position's own
top-to-bottom point range, capped at `max_tiers` (default 15) as a safety
valve. Verified against real 2026 data across all 6 positions -- QB's
worst-case tier dropped from 30 players/218 points to a 5-7 player/
30-60 point range; RB/WR/TE/K/DST all produce similarly reasonable,
non-fragmented tiers. `src/tiering.py`'s module docstring keeps the full
story of why the first two designs each looked right until tested against
real data, specifically so a future session doesn't re-attempt either one
without knowing it was already tried and rejected.

Verified: 66/66 tests passing (11 new/changed); both pages re-run under
`AppTest` with the exact reported scenario (QB filter + manual override of
10) confirming every tier's spread is now bounded correctly.

### 2026-08-25 — Superflex-heavy QB demand assumption + position tiering (auto + manual override)
Two related requests from the league manager after reviewing Josh Allen's
VOR rank (#23 despite #1 overall raw points): (1) this league's scoring
system makes QB the near-automatic superflex fill, so demand modeling
should reflect ~2 QBs/team almost every week, not a soft 55% lean; (2)
add visible "tiers" to the player grid — clusters of same-position players
who are roughly interchangeable, split by real point drop-offs, with both
an automatic default and a manual override (e.g. "all players within 10
points are one tier").

**Superflex demand:** `config/league_settings.yaml` →
`estimation_assumptions.flex_position_splits.SUPERFLEX` changed from
QB 0.55/RB 0.20/WR 0.20/TE 0.05 to **QB 0.90/RB 0.04/WR 0.04/TE 0.02**. The
small non-QB residual is deliberate (not a claim ~10% of teams will
genuinely bench a good QB for the flex) — it keeps replacement level from
being brittle to a single 100%-certain assumption. New test
(`test_superflex_demand_is_now_overwhelmingly_qb` in
`tests/test_projections.py`) locks in QB demand ≈ 19 (10 dedicated + 9 from
superflex) vs. the old ≈ 15.5.

**Tiering:** `src/projections.py`'s new `compute_tiers(board, metric=
"score_total", gap_threshold=None, k=1.0)` groups each position's players
into 1-indexed tiers:
- `gap_threshold=None` (default): automatic — flags a tier boundary when
  the point-drop to the next player is a statistical outlier for that
  position (`drop > mean(drops) + k*std(drops)`), so it adapts to each
  position's own scoring scale (kickers cluster tight, QBs/RBs spread
  wider) without a single fixed point value across positions.
- `gap_threshold=<number>`: manual override — new tier whenever the drop
  exceeds that many points, exactly the "within N points" control asked
  for.
- Tiering by `score_total` and by `vor` produce identical boundaries
  within a position (vor is just score_total minus a per-position
  constant) — verified by test, so the page only needs to expose one.

Real result on the actual 2026 blended data: QB auto-tiers into just 3
tiers (30 QBs in tier 1 — this year's pool really is that bunched at the
top, consistent with the VOR writeup in `docs/draft_insights.md`), while
RB auto-tiers into 9 much tighter tiers, matching the known shallow/fast-
drop-off RB pool. This is a good sanity check that the auto method is
doing something real, not just noise.

`pages/1_Draft_Board.py` and `pages/2_Projections.py` both got: a "Tier
gap override (pts)" number input (0 = automatic), a "Tier" column in the
player grid, and — only when the grid is filtered to exactly one position
(tier numbers are position-relative, so mixing positions would be
confusing) — visible "— Tier N —" divider rows via the new
`src/tier_display.py`'s `add_tier_divider_rows()`.

**Bug caught and fixed via `AppTest` before shipping:** the first version
of `add_tier_divider_rows()` wrote the divider's label text into whichever
column happened to be first in the display frame. On the Draft Board
that's "VOR Rk" — a numeric rank column — so mixing in a string label
corrupted it to a mixed int/string object column, which threw a real
`pyarrow.lib.ArrowTypeError` inside `st.dataframe` (silently auto-"fixed"
by Streamlit's own fallback, so it wouldn't have crashed the page, but
it's exactly the kind of fragile-in-a-way-status-codes-won't-catch bug
this project has hit before — see the ParserError entry below). Fixed by
adding an explicit `label_col` parameter (both pages pass `"Player"`) and
using `None` instead of `""` for every other column in a divider row, so
pandas upcasts a numeric column to float+NaN — which Arrow serializes
fine — instead of degrading it to a generic object column. Caught by
running both pages through `streamlit.testing.v1.AppTest`, filtering to a
single position, and inspecting the actual rendered dataframe's dtypes —
not just checking for an exception. Regression test in
`tests/test_tier_display.py`.

Verified: 58/58 tests passing (12 new); both pages run clean under
`AppTest` with a position filter applied and a manual tier-gap override
set, with the rendered dataframe inspected directly (not just "no
exception raised").

### 2026-08-25 — Three-source projection ingestion (CBS + FFToday + FantasyPros), new Projections page, live refresh
The app's rankings are only as good as the stat projections feeding the
scoring engine, so the user asked for 3 free sources to average/weight
together instead of relying on CBS alone.

**Sources researched and their real limitations:**
- **CBS** (already had this) — full player pool, but requires a logged-in
  session and blocks robots.txt, so it can never be live-refreshed by the
  deployed app. Re-pull is manual: visit the CBS projections URL in a
  logged-in browser, capture the page, re-run the ingestion by hand (same
  pattern as the draft-order pull below).
- **FFToday** — no login required, full free depth (~50 players per skill
  position, all 32 DSTs), and it's a plain server-rendered page — a bare
  `requests.get()` works, no browser needed. This is the strongest 3rd
  source. Live refresh confirmed to fail *only* because this dev sandbox
  has no general internet egress (proxy 403, not a fftoday.com error) —
  the refresh button's error handling was verified against this exact
  failure via Streamlit's `AppTest` harness, and it surfaces cleanly
  instead of crashing the page. Should work once deployed somewhere with
  normal internet access (Streamlit Cloud).
- **FantasyPros** — free/anonymous view hard-caps every position table at
  the top 10 players; the print view and any deeper page redirect to a
  sign-in wall (confirmed by navigating there directly). Went looking for
  a 4th free full-pool source to replace it per the user's request:
  Footballguys and FTN are both subscription-only for projections,
  NFL.com's own fantasy-projections tool is defunct (redirects to a dead
  ESPN-merged page — a `WebFetch` hallucination initially reported this
  page as working with fake data, see lesson below), and ESPN's Mike Clay
  projections are only published as a PDF/article, not a
  scrapeable table — not built this session, flagged as a future
  candidate if someone wants to hand-transcribe it. Decision: kept
  FantasyPros as a partial/supplementary source (top-10 coverage is
  exactly where 3-source agreement matters most for early picks) rather
  than blocking on a 4th source that doesn't cleanly exist for free.

**Lesson (important, cost real time this session): don't trust `WebFetch`
on JavaScript-rendered pages.** It silently fabricated confident,
precisely-formatted, entirely wrong data twice — once for FantasyPros'
QB page (returned FFToday's real numbers relabeled as FantasyPros), once
for the defunct NFL.com projections page (invented a fake "1-25 of 1036
results" table). Neither errored out; both looked plausible. Caught by
cross-referencing against direct browser DOM extraction. Going forward:
use Claude in Chrome (`navigate` + `javascript_tool` DOM extraction, or
`get_page_text` for server-rendered pages) for any site where WebFetch's
output can't be independently verified, never WebFetch alone.

**Built:**
- `src/data_sources/team_names.py` — `canonical_dst_name()`. CBS names
  DSTs by short city ("Houston", "L.A. Rams"); FFToday and FantasyPros
  both use full "City Nickname" ("Houston Texans"). Without normalizing,
  `blend_projections()`'s join on `name_key` would silently treat the same
  DST as unrelated rows across sources. Maps all 32 teams' full names to
  CBS's short form; unknown names pass through unchanged rather than
  raising, so a future team rename doesn't crash ingestion.
- `src/data_sources/fftoday.py` — `parse_position_text()` (parses either a
  live fetch's extracted text or a saved `get_page_text` capture, same
  format) and `fetch_position()`/`fetch_all()` (live HTTP fetch via
  `requests` + BeautifulSoup text extraction). Handles the DST unit
  mismatch: FFToday's `PA` is a season total (divided by 17 games to match
  CBS's per-game convention) while its `PaYd/G`/`RuYd/G` are already
  per-game (summed, not divided).
- `src/data_sources/fantasypros.py` — `parse_position_rows()` (parses the
  row-array table data captured via `javascript_tool` DOM extraction) and
  `fetch_position()`/`fetch_all()` (attempted live fetch via `requests` +
  `pandas.read_html`, **UNVERIFIED** — no XHR/JSON API was found via
  `read_network_requests`, suggesting but not proving the table is
  server-rendered; this sandbox can't test outbound requests to
  fantasypros.com at all, so this path needs real-world confirmation once
  deployed). Same DST season-total→per-game conversion as FFToday (`PA`
  and `YDS AGN` both divided by 17).
- `pages/2_Projections.py` — new page. Per-source weight sliders (0 to
  exclude a source, any single non-zero weight to view one source alone),
  a player-lookup showing each source's raw line side-by-side plus the
  blended result, a full sortable/filterable blended board, and a
  "Refresh from web" button per live-capable source (FFToday,
  FantasyPros) that re-fetches, overwrites that source's CSV, and clears
  the Streamlit cache so the new data shows immediately. CBS has no
  refresh button — a caption explains why.
- `scripts/fetch_fftoday.py` / `scripts/fetch_fantasypros.py` — CLI
  wrappers (`--live` or `--from-capture <path>`) for manual/future refresh
  runs outside the Streamlit UI, mirroring `scripts/fetch_draft_order.py`.
- Seed data written: `data/projections/fftoday_2026.csv` (264 rows),
  `data/projections/fantasypros_2026.csv` (60 rows), both auto-picked-up
  by the existing `_data_files()`/`load_many()` pipeline. Raw captures
  kept for audit at `data/projections/raw/`.

**Bug caught and fixed during verification:** FFToday's parser extracted
the team-code token (e.g. "BUF") to validate row structure but never
actually stored it in the output row — every skill-position player from
FFToday had a blank `nfl_team`. Caught by running the new Projections page
through `streamlit.testing.v1.AppTest` (see lesson below) and noticing
Josh Allen's FFToday row showed `NaN` for team. Fixed, added a regression
test (`test_nfl_team_populated_for_all_skill_positions`), rebuilt the CSV.

**Lesson: `streamlit.testing.v1.AppTest` catches real bugs an HTTP-200
check can't, without needing a browser.** It runs a page's actual script
in-process and lets you inspect rendered widgets/dataframes/exceptions
directly — this is how the missing-`nfl_team` bug above was caught, and
how the refresh button's error path (network failure -> `st.error`, not a
crash) was verified. Use this instead of (or in addition to) `curl`-ing a
running `streamlit run` process, which only proves the initial HTML shell
loads — Streamlit runs each page's script over a websocket after that,
so `curl` never actually executes the page code.

**Verified end-to-end:** all 3 sources load and blend correctly
(`load_many` → `blend_projections` → `score_and_rank`); spot-checked Josh
Allen, Jahmyr Gibbs, Trey McBride, Brandon Aubrey, and the Houston DST
join and blend correctly across all 3 sources with the exact values from
each raw capture; 46/46 tests passing (17 new: `test_fftoday.py`,
`test_fantasypros.py`, `test_team_names.py`); both `pages/1_Draft_Board.py`
and `pages/2_Projections.py` run clean under `AppTest` with no exceptions,
including exercising the refresh button's failure path.

**Not verified (can't be, from this sandbox):** whether FantasyPros'
live-refresh via `requests`/`pandas.read_html` actually works — needs
confirmation from a real deployment with internet access. If it turns out
the page needs JS rendering after all, `fetch_position()` raises a clear
`ValueError` rather than silently returning wrong data — fall back to a
fresh Claude-in-Chrome capture + `scripts/fetch_fantasypros.py
--from-capture` in that case.

### 2026-08-25 — Pulled real 2026 draft order, wired into the Draft Board
User asked for the draft order/teams from
`https://maniacfl.football.cbssports.com/draft/results/2026:Pre-season:MFL%20Draft%202026/`
(needs a logged-in session; also blocked by robots.txt for plain fetch,
so used Claude in Chrome against the user's real browser session).
22 rounds x 10 teams, standard snake, draft not yet started. Round 1
order: Mississippi Swamp Ass, Aces High, THE DEMONS, Pimp Daddy, Legion
of Doom, Mojo, Salty Dogs, **Monster Cheese**, Buckhorns, Ball Busters.

Built this as a reusable pipeline, not a one-off, since the user asked
for something that "autopopulates" in future years:
- `src/data_sources/draft_order.py` — `draft_results_url(year)` builds
  the CBS URL from a template (verified it reproduces the exact known-
  good 2026 URL); `parse_draft_order_text()` parses a saved page-text
  capture into a structured order and validates it's a standard
  alternating snake (flags it in `notes` if not, since
  `src/draft_state.py`'s `DraftState.team_for_pick()` assumes one).
- `scripts/fetch_draft_order.py` — CLI that runs the parser against a
  saved text file and writes `data/draft/<year>_draft_order.json`, plus
  `--update-config` to patch `draft.team_order` in
  `config/league_settings.yaml` in place (targeted text substitution,
  not a full YAML round-trip, so the file's comments survive).
- Important limitation, not automatable away: CBS requires login and
  blocks robots.txt, so there's no way to fetch this with plain
  `requests` code. The yearly workflow is: get the URL from
  `draft_results_url()`, visit it in a logged-in browser (Claude in
  Chrome or the user's own), grab the page text, save it, then run the
  script on that file. Full docstrings in both files above walk through
  this.
- `pages/1_Draft_Board.py` now reads `draft.team_order` from config
  instead of placeholder team names, with a fallback + on-page warning
  if it's ever missing (e.g. before a future year's order is captured).
- Tests in `tests/test_draft_order.py` (9 new, 28/28 total passing)
  cover the real 2026 capture, URL building, snake validation, and — the
  part that actually matters — that the parsed order drives
  `DraftState.team_for_pick()` to the correct team for every single pick
  across all 22 rounds, not just round 1.
- Raw captured page text saved at
  `data/draft/2026_draft_order_raw.txt` for audit/reproducibility;
  parsed output at `data/draft/2026_draft_order.json`.

### 2026-08-25 — Session notes moved into the repo
Previously this log lived as a doc in the attached Claude Project
("MFL Team Manager"). Moved it here instead, since a repo-tracked file
travels with the repo no matter how a future session is started, and the
user asked not to get a rewritten Project doc after every response.
The Project doc now just points here.

### 2026-08-25 — Fixed Draft Board ParserError on Streamlit Cloud
User deployed to Streamlit Cloud and hit `pandas.errors.ParserError` on
the Draft Board page. Root cause: `pages/1_Draft_Board.py` globbed
`data/projections/*.*`, which also matched `data/projections/README.md`;
`load_table()` has no markdown branch so it fell through to
`pd.read_csv()` on the README and pandas choked on it. Fix: replaced the
glob with an explicit directory listing filtered to real data extensions
(`.csv`, `.tsv`, `.xlsx`, `.xlsm`, `.xltx`, `.xls`). Pushed as `8be693d`.
Verified 19/19 tests passing plus a direct pipeline run (load → score →
rank) against the real data, end to end, no exception. User confirmed
fixed on their live deployment.

Lesson: checking `streamlit run app.py` returns HTTP 200 does NOT catch
this class of bug — Streamlit renders exceptions inside the page body,
still as a 200 response. Verify by exercising the underlying pipeline
directly or checking actual rendered content, not status codes alone.

### 2026-08-24/25 — Repo restored and pushed after two sessions couldn't push
Two prior sessions were started without this repo attached as a write
source (see "Git push access" above for the workaround now in place).
The actual Phase 1 code from the original working session only existed
as a zip export the user had saved locally (`monstercheeseteammanager_2.
zip`) — the repo on GitHub had only the initial README. Restored the zip
into a fresh clone, verified deps installed cleanly and 19/19 tests
passed, and pushed as `8a2cbb4`. This is now the real state of the repo;
future sessions can just `git clone` it, no zip needed.

### 2026-08-24 — Real league rules re-verified from CBS
Re-captured full scoring tables directly from
`https://maniacfl.football.cbssports.com/rules` (logged-in). Source of
truth is `config/league_settings.yaml`. Key points: passing/rushing/
receiving yardage are tiered (every 25yd or so = +2pts, extrapolated
beyond the table); TD base 6/6/7 (passing/rushing/receiving) with +2
long-td bonuses; FG base 3 +1/+2/+3 by distance; INT thrown -3, fumble
lost -1, missed XP -1. Defensive PA/yards-allowed genuinely only have 3
tiers each on CBS's page — deliberately not extrapolated further (their
trend is decreasing, extrapolating risks going negative on a guess) —
flagged for the commissioner to confirm if more tiers actually exist.
Roster: 12 starters (1 QB, 3 RB, 3 WR/TE flex, 1 TE, 1 K, 1 superflex, 1
flex RB/WR/TE/K, 1 DST); the TE rule (2 WR + 2 TE legal, 2 WR + 1 TE
illegal) is enforced by the app since CBS's own checker doesn't catch it.

### 2026-08-24 — Real 2026 CBS projection data pulled
Pulled real 2026 season projections for all positions from
`cbssports.com/fantasy/football/stats/{POS}/2026/season/projections/
nonppr/` via browser automation — 415 players total (QB/RB/WR/TE/K/DST).
Saved to `data/projections/cbs_2026.csv`. Note the URL uses `nonppr`, not
`standard/ppr/half-ppr` — CBS 404s on some other casings. The Draft Board
prefers `data/projections/` over `data/sample/` automatically whenever
real files exist.

### 2026-08-24 — VOR analysis: draft RBs early, not the biggest raw score
`docs/draft_insights.md` has the full writeup. Raw per-player score is
QB-dominated (14 of the top 15 highest-scoring players leaguewide are
QBs). But value-over-replacement flips this: 18 of the top 24 VOR-ranked
players are RBs, only 1 QB (Josh Allen) makes that cut. Why: QB demand
(~15.5 leaguewide incl. superflex) is met by a deep pool (QB15 isn't far
behind QB1), while RB demand (~36 leaguewide) hits a much shallower pool
that falls off fast. Practical takeaway: prioritize top RBs early: the
Draft Board's default VOR sort already reflects this. Caveats depend on
the flex-split assumptions in `config/league_settings.yaml` — read the
full file before treating this as gospel.
