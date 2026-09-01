# Live draft sync — setup checklist

Use this every time you run a mock draft test, and again right before the
real draft (2026-08-30, 2:30pm ET). It's the same steps both times — the
only difference is which CBS draft room you join at step 5.

## 0. One-time setup (skip if already done)

Load the Chrome extension once — it stays loaded across restarts of Chrome,
so you shouldn't need to repeat this:

1. Open `chrome://extensions` in Chrome.
2. Turn on **Developer mode** (top-right toggle).
3. Click **Load unpacked**.
4. Select the `tools/chrome_extension` folder inside this repo.
5. Confirm it shows up as **"Monster Cheese Live Draft Sync"** with no
   errors. If Chrome shows a red "Errors" button on the card, click it and
   send me what it says.

## 1. Reset the pick log

Every pick log carries over between runs, so a leftover mock draft (or an
earlier test) will make the app think the draft is further along than it
is. In a Terminal, from the repo folder:

```bash
rm -f data/draft_state.json data/live_sync_status.json
```

Do this before **every** mock draft test, and one final time right before
the real draft starts.

## 2. Start the app

```bash
streamlit run app.py
```

Leave this terminal running. Open `http://localhost:8501/Draft_Board` in
Chrome (a normal tab is fine — it doesn't need to be the same tab as the
draft room).

## 3. Start the live pick receiver

In a **second** terminal tab, same repo folder:

```bash
python3 tools/live_pick_receiver.py
```

The receiver only needs one third-party package (PyYAML). **Already fixed
as of the 2026-08-30 mock draft test** — `pip install` installs it
permanently for that `python3`, on disk, not just for that terminal
session, so it's still there after closing the terminal, opening a new
one, or restarting your Mac. No need to redo this for the real draft
unless you're on a different machine or a freshly reinstalled Python.

If it ever comes back (you'll see `ModuleNotFoundError: No module named
'yaml'` and the receiver won't actually start — the `curl` check in step 4
will then fail too, since nothing is listening): if your normal setup uses
a virtualenv, activate it first in this terminal the same way you would
before `streamlit run app.py`. Otherwise, fix it directly for this
terminal's `python3`:

```bash
python3 -m pip install pyyaml
```

(If that errors with `externally-managed-environment`, use
`python3 -m pip install --user pyyaml` instead.) Then re-run the receiver
command above — it should print a startup line like
`Serving on http://127.0.0.1:8765`.

Leave this running too — it prints one line per pick as it lands, so you
can watch it work without checking anything else. `Ctrl+C` to stop it when
you're done. You should see it start up with something like:

```
Serving on http://127.0.0.1:8765 ...
```

## 4. Sanity-check the receiver is reachable

Optional but reassuring — in a third terminal:

```bash
curl http://127.0.0.1:8765/status
```

Should return something like
`{"next_overall_pick": 1, "on_the_clock": "...", ...}`. If this fails,
the receiver isn't running — go back to step 3.

## 5. Join the draft room in Chrome

- **For a mock draft test:** go to CBS's mock draft lobby, join any open
  room, and wait for it to start.
- **For the real draft:** go to your league's draft room directly at
  2:30pm ET.

Once the draft room itself has loaded (not the lobby — the actual room
with the pick clock and player grid), the extension should show a small
badge in the top-right corner of the page:

- **"MC sync: hook installed — waiting for picks"** (gray/green) = good,
  it's watching.
- If you don't see a badge at all after ~10 seconds on the draft room
  page, refresh the page once.

## 6. Watch it work

As picks land in the draft room:

- The extension's badge updates to **"synced #N — on the clock: ..."**
  after each pick.
- The receiver's terminal prints a line per pick.
- The Draft Board's sidebar shows a **"🔴 Live sync from CBS"** panel with
  the last synced pick number and how recently it updated. If it ever
  shows a mismatch warning there, stop and check with me before trusting
  the board — don't draft off of it until that's resolved.
- The board's "On the clock" / player grid update on their own every few
  seconds — no need to refresh the page.

## 7. If something looks wrong

- Badge says **"receiver unreachable"** → the receiver (step 3) isn't
  running, or crashed. Check its terminal for an error. (This wording now
  ONLY appears for a genuine connection failure — see the incident note
  below for why that distinction matters.)
- Badge says **"receiver rejected"** or **"SYNC FAILED"** for a specific
  pick → the receiver IS running and reachable, it just couldn't match
  that one pick (almost always a team-name mismatch). It gives up after a
  few retries and moves on to the NEXT pick automatically — it no longer
  gets stuck. Log that one pick manually on the Draft Board and keep
  going; run `console.table(window.__mcSyncFailures)` in DevTools any
  time to see every pick that failed this way.
- Badge never appears at all → the extension likely isn't matching this
  page; refresh once, and if it still doesn't show up, tell me the exact
  URL you're on.
- Sidebar shows a mismatch → stop, don't keep drafting off the board, and
  flag it to me with the pick number involved.
- Nothing else works → the Draft Board's player grid still lets you log
  picks manually by clicking a row, regardless of whether live sync is
  working. That's always the fallback.

## Incident from the 2026-08-30 real draft (fixed, but re-verify before trusting it again)

Live sync effectively stopped working partway through the real draft.
Root cause: the receiver identified teams by treating CBS's numeric
`teamid` as a small 1..N slot number matching `team_order` — true for
every MOCK draft room tested (CBS numbers those fresh, 1..N, every time)
but false for this real, long-running league, whose teams carry
persistent CBS ids that aren't 1..10 at all. One pick's teamid fell
outside that range, the receiver correctly rejected it, and the OLD code
treated "rejected" exactly like "can't reach the receiver at all" —
retrying that one pick forever and silently blocking every pick after it
for the rest of the draft (the badge kept saying "retrying #99" while
~120 later picks piled up behind it, unsynced).

Both parts are fixed: team identification now resolves the real team
NAME directly from CBS's own page data instead of guessing from a slot
number, and a rejected pick is retried a few times, then skipped (loudly,
with a running failure count and `window.__mcSyncFailures` for the full
list) instead of blocking everything behind it.

**This has NOT been re-verified against a live CBS draft room yet** (only
against the test suite and isolated logic tests) — run one more mock
draft before trusting it again next year, the same way every fix this
season was verified before relying on it live.

## Before the real draft specifically

Repeat steps 1–4 one more time right before the draft starts, even if you
tested earlier — step 1 (resetting the pick log) is the one that matters
most, since an earlier mock draft test will otherwise still be sitting in
`data/draft_state.json`.
