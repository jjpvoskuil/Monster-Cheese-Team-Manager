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
- `pytest` — 89/89 passing.
- Deployed to Streamlit Cloud; user confirmed the Draft Board loads
  correctly as of 2026-08-25.
- Known gaps (not blocking): ESPN blending not done (would be a 4th
  source — see notes below); `src/data_sources/cbs.py` live draft sync is
  still a stub, manual pick entry is the reliable path; defensive
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
