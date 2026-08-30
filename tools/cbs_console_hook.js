/**
 * CBS live-draft console hook — pairs with tools/live_pick_receiver.py.
 *
 * WHAT THIS DOES: hooks CBS's own real-time draft socket callback
 * (mainapp.socket.eventPicksCompleted) directly inside the CBS draft room
 * page. The instant CBS fires a pick event, this resolves the player's
 * name/position/team from CBS's own in-page data (mainapp.players) and
 * POSTs it straight to a local receiver (tools/live_pick_receiver.py)
 * running on your machine, which writes it into data/draft_state.json.
 * No polling, no Claude, no browser automation in the loop at all --
 * Claude is not involved in this data path once this script is running.
 * It also draws a small status badge in the corner of the page so you can
 * see at a glance that picks are syncing, with no need to check anything
 * else.
 *
 * SETUP (do this once per draft, in this order):
 *   1. In a real Terminal (not this browser), start the receiver:
 *        python3 tools/live_pick_receiver.py
 *      Leave that terminal open for the whole draft.
 *   2. Join the CBS draft room in Chrome, BEFORE the draft starts if at
 *      all possible (see the backfill note below for why).
 *   3. Open DevTools (Cmd+Option+J on Mac), click the Console tab, paste
 *      this entire file's contents, press Enter.
 *   4. Look for the green badge in the top-right corner of the page
 *      saying "Hook installed". That's it -- leave the tab open and let
 *      the draft run. The badge updates live as picks sync.
 *
 * IF THE TAB GETS RELOADED OR CLOSED MID-DRAFT: this script's state lives
 * only in that tab's JS memory, so a reload means pasting it again. On
 * install it makes a best-effort attempt to catch up on anything it
 * missed (see backfillFromResultsTable below) by reading CBS's own
 * results table on the page -- but that table's exact layout has not been
 * re-verified live for this draft, so treat it as a safety net, not the
 * plan: joining before the draft starts and never reloading the tab is
 * the reliable path. If the badge shows a backfill warning, or picks stop
 * advancing, tell your league manager -- there's a documented manual
 * fallback (Claude re-attaching via browser automation) that was used
 * and validated earlier in testing.
 */
(function () {
  if (window.__mcHookInstalled) {
    console.log("[MC sync] already installed in this tab.");
    return;
  }

  const RECEIVER_URL = "http://127.0.0.1:8765";
  // Cosmetic only (badge text) -- the receiver does its own teamid -> team
  // name mapping from config/league_settings.yaml, so this list being
  // slightly stale would never cause a wrong pick to be logged, only a
  // wrong NAME shown in this tab's own badge.
  const TEAM_ORDER = [
    "Mississippi Swamp Ass", "Aces High", "THE DEMONS", "Pimp Daddy",
    "Legion of Doom", "Mojo", "Salty Dogs", "Monster Cheese", "Buckhorns",
    "Ball Busters",
  ];

  // ---------------------------------------------------------------
  // Status badge
  // ---------------------------------------------------------------
  const badge = document.createElement("div");
  badge.style.cssText = [
    "position:fixed", "top:8px", "right:8px", "z-index:999999",
    "font:12px/1.4 -apple-system,sans-serif", "padding:8px 12px",
    "border-radius:6px", "color:#fff", "background:#555",
    "box-shadow:0 2px 8px rgba(0,0,0,.3)", "max-width:320px",
  ].join(";");
  badge.textContent = "MC sync: starting…";
  document.body.appendChild(badge);

  function updateBadge(state, text) {
    const colors = { ok: "#1a7f37", error: "#c0392b", warn: "#b8860b", info: "#555" };
    badge.style.background = colors[state] || colors.info;
    badge.textContent = "MC sync: " + text;
  }

  // ---------------------------------------------------------------
  // Send queue (fire-and-forget with retry, so a receiver that hasn't
  // started yet -- or a momentary network hiccup -- doesn't drop a pick)
  // ---------------------------------------------------------------
  const queue = [];
  let sending = false;

  function enqueue(payload) {
    queue.push(payload);
    flush();
  }

  async function flush() {
    if (sending) return;
    sending = true;
    while (queue.length) {
      const payload = queue[0];
      try {
        const res = await fetch(RECEIVER_URL + "/pick", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!res.ok) throw new Error("HTTP " + res.status);
        const data = await res.json();
        queue.shift();
        if (data.mismatches && data.mismatches.length) {
          updateBadge("error", "MISMATCH reported by receiver — check its terminal");
        } else {
          updateBadge(
            "ok",
            `synced #${payload.overall_pick} — on the clock: ${data.on_the_clock || "—"}`
          );
        }
      } catch (e) {
        updateBadge("error", `receiver unreachable — retrying #${payload.overall_pick} (is live_pick_receiver.py running?)`);
        await new Promise((r) => setTimeout(r, 2000));
      }
    }
    sending = false;
  }

  async function sendBatch(payloads) {
    if (!payloads.length) return;
    try {
      const res = await fetch(RECEIVER_URL + "/picks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ picks: payloads }),
      });
      const data = await res.json().catch(() => ({}));
      updateBadge("ok", `backfilled through #${payloads[payloads.length - 1].overall_pick}`);
    } catch (e) {
      updateBadge("warn", "backfill failed — receiver may not be running yet");
    }
  }

  // ---------------------------------------------------------------
  // Resolve a CBS playerid into {name, pos, team} using CBS's own
  // in-page player data. mainapp.players.getPlayer() returns name as
  // "Last, First" (confirmed live during mock-draft testing) -- convert
  // to "First Last" to match this app's projection data everywhere else.
  // ---------------------------------------------------------------
  function resolvePlayer(playerid) {
    try {
      const p = mainapp.players.getPlayer(playerid);
      if (!p) return { name: "Unknown", pos: "", team: "" };
      let name = p.name || "";
      if (name.includes(",")) {
        const [last, first] = name.split(",").map((s) => s.trim());
        name = `${first} ${last}`;
      }
      return { name, pos: p.pripos || "", team: p.proteam || "" };
    } catch (e) {
      return { name: "Unknown", pos: "", team: "" };
    }
  }

  // ---------------------------------------------------------------
  // Best-effort backfill from the draft room's own results table, for
  // picks that happened before this script was installed (e.g. you
  // joined mid-draft, or the tab got reloaded). NOT re-verified live for
  // this draft session -- if it doesn't find rows, it just skips
  // silently and you start syncing live from whatever pick comes next
  // (meaning anything before that stays un-synced in the app until
  // manually reconciled).
  // ---------------------------------------------------------------
  function backfillFromResultsTable(expectedUpTo) {
    try {
      const sel = document.querySelector("#selectRoundResults");
      if (sel) {
        sel.value = "all";
        sel.dispatchEvent(new Event("change", { bubbles: true }));
      }
      const rows = document.querySelectorAll(
        "#DraftRoom .views.results .SLTables1 table.data tr"
      );
      if (!rows || !rows.length) {
        updateBadge("warn", "no history table found — starting fresh from live picks only");
        return;
      }
      // Build a name -> CBS teamid map from mainapp so the scraped
      // display names (not teamids) can still be sent in the same
      // {overall_pick, teamid, ...} shape the receiver expects.
      const nameToTeamId = {};
      Object.values(mainapp.teams.teams || {}).forEach((t) => {
        if (t && t.teamid != null && t.name) nameToTeamId[t.name.trim()] = t.teamid;
      });

      const batch = [];
      rows.forEach((row) => {
        const cells = row.querySelectorAll("td");
        if (cells.length < 3) return;
        // Layout assumed from earlier live verification: Round | Pick | Team | Player.
        // If CBS's markup differs this draft, this silently produces no
        // usable rows rather than sending garbage (each row is skipped
        // unless a known team name AND a plausible overall pick are found).
        const text = Array.from(cells).map((c) => c.textContent.trim());
        const teamCellIdx = text.findIndex((t) => nameToTeamId[t] != null);
        if (teamCellIdx === -1) return;
        const teamid = nameToTeamId[text[teamCellIdx]];
        const playerCell = text[teamCellIdx + 1] || "";
        const m = playerCell.match(/^\*?(.+?),\s*(.+?)\s*\(([A-Z]+)\s*([A-Z]*)\)$/);
        const noComma = playerCell.match(/^\*?(.+?)\s*\(([A-Z]+)\s*([A-Z]*)\)$/);
        let name, pos, team;
        if (m) {
          name = `${m[2].trim()} ${m[1].trim()}`;
          pos = m[3];
          team = m[4];
        } else if (noComma) {
          name = noComma[1].trim();
          pos = noComma[2];
          team = noComma[3];
        } else {
          return;
        }
        const pickNum = parseInt(text[0], 10);
        if (!pickNum) return;
        batch.push({ overall_pick: pickNum, teamid, player_name: name, position: pos, nfl_team: team });
      });

      const usable = batch.filter((b) => b.overall_pick < expectedUpTo);
      if (usable.length) {
        usable.sort((a, b) => a.overall_pick - b.overall_pick);
        updateBadge("info", `backfilling ${usable.length} pick(s)…`);
        sendBatch(usable);
      } else {
        updateBadge("warn", "history table present but no usable rows parsed");
      }
    } catch (e) {
      console.error("[MC sync] backfill error", e);
      updateBadge("warn", "backfill failed (see console) — starting fresh from live picks only");
    }
  }

  // ---------------------------------------------------------------
  // Install the hook
  // ---------------------------------------------------------------
  function installHook() {
    if (typeof mainapp === "undefined" || !mainapp.socket || !mainapp.socket.eventPicksCompleted) {
      updateBadge("info", "waiting for draft room to load…");
      setTimeout(installHook, 500);
      return;
    }
    window.__mcHookInstalled = true;

    const orig = mainapp.socket.eventPicksCompleted.bind(mainapp.socket);
    mainapp.socket.eventPicksCompleted = function (payload) {
      try {
        const picks = (payload && payload.picks) || [];
        const nextOpick = payload && payload.newstate && payload.newstate.opick;
        if (picks.length && nextOpick) {
          const startOverall = nextOpick - picks.length; // overall_pick of picks[0] - 1
          picks.forEach((pk, i) => {
            const overall = startOverall + i + 1;
            const info = resolvePlayer(pk.playerid);
            enqueue({
              overall_pick: overall,
              teamid: pk.teamid,
              player_name: info.name,
              position: info.pos,
              nfl_team: info.team,
            });
          });
        }
      } catch (e) {
        console.error("[MC sync] hook error", e);
        updateBadge("error", "hook error — see console");
      }
      return orig(payload);
    };

    updateBadge("ok", "hook installed — waiting for picks");

    const opickNow = mainapp.summaryState && mainapp.summaryState.opick;
    if (opickNow && opickNow > 1) {
      backfillFromResultsTable(opickNow);
    }
  }

  installHook();
})();
