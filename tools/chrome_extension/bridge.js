// Runs in the ISOLATED world (Manifest V3's default for a plain content
// script) -- this is the only place `chrome.runtime.sendMessage` is
// callable. main_world_hook.js runs in the page's own MAIN world instead
// (so it can see CBS's own `mainapp` object), which means it can't call
// chrome.runtime.* directly -- these two scripts bridge that gap purely
// through window CustomEvents on the shared DOM, which both worlds can see.
window.addEventListener("mc-sync-request", (event) => {
  const { id, path, body } = event.detail;
  chrome.runtime.sendMessage({ type: "mc-sync-post", path, body }, (response) => {
    window.dispatchEvent(new CustomEvent("mc-sync-response", {
      detail: { id, response: response || { ok: false, error: "no response from background" } },
    }));
  });
});
