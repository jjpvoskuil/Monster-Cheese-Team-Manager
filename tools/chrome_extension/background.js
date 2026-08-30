// Runs in the extension's own background service-worker context, which is
// NOT subject to a web page's CORS / Private Network Access restrictions --
// that's the entire reason this extension exists. Confirmed live
// (2026-08-30) that a plain page fetch()/XHR/WebSocket from the CBS draft
// room to http://127.0.0.1:8765 hangs indefinitely (Chrome silently
// blocking cross-origin access from a public https page to a loopback
// address); this file is the fix -- it does the actual network call on the
// extension's behalf, using the "http://127.0.0.1:8765/*" host permission
// declared in manifest.json, which grants it the outright CORS bypass.
//
// content scripts (bridge.js) can't do this themselves because Manifest V3
// content scripts, even in the page's own MAIN world, still make their
// fetches as the PAGE's origin, not the extension's -- only requests
// literally issued from here (background.js) get the extension's exemption.

const RECEIVER_URL = "http://127.0.0.1:8765";

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (!message || message.type !== "mc-sync-post") return false;

  fetch(RECEIVER_URL + message.path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(message.body),
  })
    .then(async (res) => {
      const data = await res.json().catch(() => ({}));
      sendResponse({ ok: res.ok, status: res.status, data });
    })
    .catch((e) => {
      sendResponse({ ok: false, error: e.message });
    });

  return true; // keep the message channel open for the async sendResponse
});
