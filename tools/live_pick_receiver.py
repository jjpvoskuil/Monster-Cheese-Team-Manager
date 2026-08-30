"""
Live pick receiver — punch-list item #5's "wire it more directly" follow-up.

WHY THIS EXISTS: the first working version of live CBS sync (src/live_sync.py)
depended on an active Claude session driving a real Chrome browser
(Claude in Chrome) to read the draft room and re-type picks into this app,
polling every few seconds. Proven correct across three full mock drafts
(2026-08-29/30, zero mismatches), but the league manager flagged three real
problems with that architecture: (1) picks landed in chunks, not the instant
they happened, because Claude was polling on an interval rather than being
pushed to; (2) it burned a large number of tokens per draft since a whole
browser-automation round-trip runs on every poll; (3) it's a single point of
failure — if the Chrome extension's connection drops (which happened live
during testing), the whole pipeline stops until a human notices and a Claude
session reconnects it.

THE FIX: cut Claude out of the live data path entirely. tools/cbs_console_hook.js
(paste once into the CBS draft room's browser console — see that file's own
header for the exact steps) hooks CBS's own real-time draft socket
(`mainapp.socket.eventPicksCompleted`) directly in the page, the instant CBS
fires it — no polling, no Claude, no browser automation. It resolves each
pick's player/position/team from CBS's own in-page data and POSTs it straight
to this local HTTP server, which is the ONLY thing standing between "CBS
socket event" and "data/draft_state.json is updated": it does not touch
Chrome, does not use any AI, and adds no meaningful latency (a local HTTP
POST + a JSON merge + a file write — this whole path is sub-100ms). Claude's
role during the actual draft becomes optional/supervisory rather than being
the mechanism itself.

Deliberately dependency-free (stdlib http.server only) — same reasoning as
src/live_refresh.py's choice to avoid streamlit-autorefresh: this needs to be
running correctly with zero setup friction in the hours before a draft, not
require a new `pip install` into a venv that might not go smoothly under
time pressure.

USAGE (run in a real Terminal, in this repo's venv, alongside `streamlit run
app.py` — NOT from a sandboxed/device_bash shell, same constraint as running
Streamlit itself):

    source venv/bin/activate   # or however you normally activate it
    python3 tools/live_pick_receiver.py

Leave it running in its own terminal tab for the whole draft. It prints one
line per pick as it lands, so you can watch it work without needing to check
the app or the browser console. Ctrl+C to stop.

Reuses the exact same merge logic already proven this session
(src.live_sync.sync_new_picks, unmodified) — this script only changes WHERE
the LivePick objects come from (an HTTP POST from the browser, instead of a
Claude session's periodic browser-scrape dump). A CBS teamid -> real team
name mapping is the one new piece: CBS's draft room addresses teams by a
small integer slot number (1-10), and config/league_settings.yaml's
draft.team_order is exactly that same slot order (round-1 snake order) --
so TEAM_ORDER[teamid - 1] gives the real team name directly, no lookup
table or name-matching needed. Confirmed true for every mock draft tested
this session (Monster Cheese was always CBS slot #8, matching its position
in team_order) and it's the SAME field CBS itself assigns for the real
draft too, so this holds on draft day without any changes.
"""

from __future__ import annotations

import json
import os
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from src.draft_state import DraftState  # noqa: E402
from src.live_sync import LivePick, sync_new_picks, write_sync_status  # noqa: E402
from src.scoring import load_config  # noqa: E402

CONFIG_PATH = os.path.join(ROOT, "config", "league_settings.yaml")
DRAFT_STATE_FILE = os.path.join(ROOT, "data", "draft_state.json")
LIVE_SYNC_STATUS_FILE = os.path.join(ROOT, "data", "live_sync_status.json")
HOST = "127.0.0.1"
PORT = 8765

config = load_config(CONFIG_PATH)
TEAM_ORDER: list[str] = config.get("draft", {}).get("team_order") or []
if not TEAM_ORDER:
    print(
        "ERROR: config/league_settings.yaml has no draft.team_order set — "
        "this script needs the real CBS slot order to map teamid -> team "
        "name. Run scripts/fetch_draft_order.py first.",
        file=sys.stderr,
    )
    sys.exit(1)

MY_TEAM = config["league"]["team_name"]
ROUNDS = config["draft"]["rounds"]
REVERSE_LAST_N_ROUNDS = config["draft"].get("reverse_last_n_rounds", 0)

draft_state = DraftState(
    teams=TEAM_ORDER,
    rounds=ROUNDS,
    my_team=MY_TEAM,
    state_file=DRAFT_STATE_FILE,
    reverse_last_n_rounds=REVERSE_LAST_N_ROUNDS,
)

# Every LivePick ever received this run, keyed by overall_pick -- passed to
# sync_new_picks() in full each time (see that function's docstring: it's a
# merge, not an append, so resending something already logged is harmless).
_live_picks: dict[int, LivePick] = {}
_lock = threading.Lock()


def _team_for_cbs_slot(teamid: int) -> str | None:
    if not isinstance(teamid, int) or not (1 <= teamid <= len(TEAM_ORDER)):
        return None
    return TEAM_ORDER[teamid - 1]


def _apply_pick(payload: dict) -> dict:
    """Turn one {overall_pick, teamid, player_name, position, nfl_team}
    payload from the browser hook into a LivePick, merge it in, and return
    a small JSON-able status dict for the browser badge to display."""
    overall = payload.get("overall_pick")
    teamid = payload.get("teamid")
    if not isinstance(overall, int) or overall < 1:
        raise ValueError(f"bad overall_pick: {overall!r}")
    team = _team_for_cbs_slot(teamid)
    if team is None:
        raise ValueError(f"teamid {teamid!r} out of range for team_order ({len(TEAM_ORDER)} teams)")

    with _lock:
        _live_picks[overall] = LivePick(
            overall_pick=overall,
            team=team,
            player_name=str(payload.get("player_name") or ""),
            position=str(payload.get("position") or ""),
            nfl_team=str(payload.get("nfl_team") or ""),
        )
        result = sync_new_picks(draft_state, list(_live_picks.values()))
        write_sync_status(LIVE_SYNC_STATUS_FILE, draft_state, result)

        for pick in result.newly_logged:
            print(
                f"[{datetime.now().strftime('%H:%M:%S')}] #{pick.overall_pick} "
                f"(Rd{pick.round}.{pick.pick_in_round}) {pick.team}: "
                f"{pick.player_name} ({pick.position} {pick.nfl_team})"
            )
        if result.mismatches:
            for m in result.mismatches:
                print(f"  !! MISMATCH: {m}", file=sys.stderr)

        return {
            "ok": not result.mismatches,
            "newly_logged": len(result.newly_logged),
            "mismatches": result.mismatches,
            "next_overall_pick": draft_state.next_overall_pick,
            "on_the_clock": draft_state.on_the_clock,
            "is_draft_complete": draft_state.is_draft_complete,
        }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # quiet the default per-request access log
        pass

    def _cors_headers(self):
        origin = self.headers.get("Origin", "*")
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        # Chrome's Private Network Access preflight (a public https page
        # like CBS's fetching a private/loopback address) requires this
        # explicit opt-in on top of ordinary CORS, or the request never
        # reaches here at all -- see tools/cbs_console_hook.js's header for
        # what to do if a request still doesn't arrive despite this.
        self.send_header("Access-Control-Allow-Private-Network", "true")
        self.send_header("Access-Control-Max-Age", "600")

    def _send_json(self, status: int, payload: dict):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self._cors_headers()
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_GET(self):
        if self.path == "/status":
            self._send_json(200, {
                "next_overall_pick": draft_state.next_overall_pick,
                "on_the_clock": draft_state.on_the_clock,
                "is_draft_complete": draft_state.is_draft_complete,
                "total_picks_logged": len(draft_state.picks),
            })
        else:
            self._send_json(200, {"ok": True, "service": "live_pick_receiver"})

    def do_POST(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            data = json.loads(raw or b"{}")
        except (ValueError, json.JSONDecodeError) as e:
            self._send_json(400, {"ok": False, "error": f"bad request body: {e}"})
            return

        try:
            if self.path == "/pick":
                result = _apply_pick(data)
                self._send_json(200, result)
            elif self.path == "/picks":
                items = data.get("picks") if isinstance(data, dict) else data
                if not isinstance(items, list):
                    raise ValueError("expected {\"picks\": [...]}")
                total_new = 0
                all_mismatches: list[str] = []
                result = {
                    "ok": True, "newly_logged": 0, "mismatches": [],
                    "next_overall_pick": draft_state.next_overall_pick,
                    "on_the_clock": draft_state.on_the_clock,
                    "is_draft_complete": draft_state.is_draft_complete,
                }
                for item in items:
                    result = _apply_pick(item)
                    total_new += result["newly_logged"]
                    all_mismatches.extend(result["mismatches"])
                # Report the batch's TOTAL newly-logged count and every
                # mismatch seen across the whole batch, not just the last
                # item's -- the badge/console script only reads this final
                # response, so per-item results from earlier in the loop
                # would otherwise be silently lost.
                result = {**result, "newly_logged": total_new, "mismatches": all_mismatches}
                self._send_json(200, result)
            else:
                self._send_json(404, {"ok": False, "error": "unknown endpoint"})
        except Exception as e:  # noqa: BLE001 -- never let one bad request kill the server
            self._send_json(400, {"ok": False, "error": str(e)})


def main():
    print("=" * 70)
    print("Monster Cheese live pick receiver")
    print(f"Listening on http://{HOST}:{PORT}")
    print(f"State file:  {DRAFT_STATE_FILE}")
    print(f"Team order:  {TEAM_ORDER}")
    print(f"Currently:   next pick #{draft_state.next_overall_pick} "
          f"({'draft complete' if draft_state.is_draft_complete else draft_state.on_the_clock})")
    print()
    print("Now paste tools/cbs_console_hook.js into the CBS draft room's")
    print("browser console (see that file's header for exact steps).")
    print("Leave this running for the whole draft. Ctrl+C to stop.")
    print("=" * 70)
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping.")


if __name__ == "__main__":
    main()
