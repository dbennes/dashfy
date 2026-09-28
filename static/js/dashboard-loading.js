(function () {
  "use strict";
  const target = document.querySelector("[data-dashboard-target]");
  if (!target) return;
  const status = document.querySelector("[data-dashboard-status]");
  const retry = document.querySelector("[data-dashboard-retry]");
  const intro = document.querySelector("[data-dashboard-intro]");
  const heading = document.querySelector("[data-dashboard-heading]");
  const spinner = document.querySelector("[data-dashboard-spinner]");
  let busy = false, mounted = false;
  async function execute(source) {
    const script = document.createElement("script");
    for (const attribute of source.attributes) {
      if (!["defer", "async"].includes(attribute.name)) script.setAttribute(attribute.name, attribute.value);
    }
    script.async = false;
    script.textContent = source.textContent;
    if (source.src || source.type === "module") {
      await new Promise((resolve, reject) => {
        script.onload = resolve;
        script.onerror = () => reject(Error("A dashboard component could not load. Reload the page to retry."));
        target.append(script);
      });
    } else target.append(script);
  }
  async function load() {
    if (busy) return;
    if (mounted) { location.reload(); return; }
    busy = true; retry.hidden = true;
    heading.textContent = "Processing…";
    spinner.hidden = false;
    status.textContent = "Preparing your dashboard with current data.";
    try {
      const url = new URL(target.dataset.contentUrl, location.origin);
      url.search = location.search;
      const response = await fetch(url, {credentials:"same-origin", cache:"no-store"});
      if (response.redirected || response.headers.get("X-Dashboard-Content") !== "1")
        throw Error("Your session expired or the service is unavailable. Reload the page and sign in again.");
      if (!response.ok) throw Error("Current data could not be loaded. History remains available. Please try again.");
      const parsed = new DOMParser().parseFromString(await response.text(), "text/html");
      const panels = parsed.querySelector("[data-dashboard-panels]");
      if (!panels) throw Error("Current data could not be loaded. Please try again.");
      status.textContent = "Preparing charts and controls…";
      const scripts = Array.from(parsed.querySelectorAll("script")).filter(s => !s.type || ["module", "importmap", "text/javascript"].includes(s.type));
      scripts.forEach(s => s.remove());
      panels.querySelector(".sn-export")?.remove();
      // Keep the notes dialog outside this replacement, including unsaved text.
      target.replaceChildren(...Array.from(panels.childNodes));
      for (const child of Array.from(parsed.body.children)) {
        if (child !== panels && child.tagName !== "TEMPLATE") target.append(child);
      }
      mounted = true;
      const tickers = parsed.querySelector("[data-dashboard-tickers]");
      if (tickers) document.querySelector(".tb-tickers")?.replaceChildren(tickers.content);
      const horizon = parsed.querySelector("[data-dashboard-horizon]");
      if (horizon) document.querySelector(".tb-project .horiz")?.replaceChildren(horizon.content);
      // Base vendor scripts (Bootstrap/jQuery) must finish before app setup.
      if (document.readyState === "loading") await new Promise(resolve => document.addEventListener("DOMContentLoaded", resolve, {once:true}));
      for (const script of scripts) await execute(script);
      // Reveal in one step only after setup. The comments dialog lives outside
      // both containers so opening History or typing a draft survives the swap.
      target.removeAttribute("data-loading");
      target.removeAttribute("inert");
      target.setAttribute("aria-busy", "false");
      intro.remove();
      document.dispatchEvent(new CustomEvent("dashboard:panels-ready"));
      window.dispatchEvent(new Event("resize"));
      const anchor = location.hash && document.getElementById(location.hash.slice(1));
      if (anchor && !document.querySelector("dialog[open]")) anchor.scrollIntoView();
    } catch (error) {
      heading.textContent = "Unable to load dashboard";
      spinner.hidden = true;
      status.textContent = error.message;
      retry.hidden = false;
      retry.textContent = mounted ? "Reload page" : "Try again";
    } finally { busy = false; }
  }
  retry.addEventListener("click", load);
  // The light local history request gets a head start over external sources.
  Promise.race([
    window.dashfyNotesReady || new Promise(resolve => document.addEventListener("dashboard:history-ready", resolve, {once:true})),
    new Promise(resolve => setTimeout(resolve, 1500))
  ]).then(load);
}());
