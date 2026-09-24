/* Rundown import stays in the dashboard; the server validates every step. */
(function () {
  "use strict";
  var dialog = document.getElementById("rundownImportDialog");
  var opener = document.querySelector("[data-rundown-import-open]");
  if (!dialog || !opener || !dialog.showModal) return;
  var section = opener.closest("section");
  if (section) section.appendChild(dialog);
  var body = dialog.querySelector("[data-rundown-import-body]");
  var status = dialog.querySelector("[data-rundown-import-status]");
  var close = dialog.querySelector("[data-rundown-import-close]");
  var busy = false;
  async function request(form) {
    if (busy) return;
    busy = true;
    close.disabled = true;
    body.setAttribute("aria-busy", "true");
    var data = form ? new FormData(form) : null;
    var applying = data && data.get("action") === "apply";
    status.textContent = applying ? "Applying changes…" : form ? "Checking workbook…" : "Loading import…";
    body.querySelectorAll("button, input").forEach(function (el) { el.disabled = true; });
    try {
      var response = await fetch(opener.href, {
        method: form ? "POST" : "GET", body: data, credentials: "same-origin",
        headers: { "X-Rundown-Modal": "1" }, cache: "no-store"
      });
      if (response.redirected || response.status === 403) throw new Error("Your session expired or access was denied. Reload the dashboard and sign in again.");
      if ((response.headers.get("Content-Type") || "").includes("application/json")) {
        var result = await response.json();
        if (!response.ok || !result.ok) throw new Error("Import could not be completed. Reload the dashboard to check the latest data.");
        var card = document.querySelector("[data-fab-rundown]");
        if (card) card.dispatchEvent(new CustomEvent("rundown:updated", { detail: result.payloads }));
        body.replaceChildren();
        var done = document.createElement("p");
        done.textContent = "The chart has been refreshed. You can close this window to view the updated rundown.";
        var again = document.createElement("button");
        again.type = "button"; again.className = "ob-btn"; again.textContent = "Import another workbook / View history";
        again.addEventListener("click", function () { request(); });
        body.append(done, again);
        status.textContent = result.message;
      } else {
        var html = await response.text();
        var parsed = new DOMParser().parseFromString(html, "text/html");
        var content = parsed.querySelector("[data-rundown-import-content]");
        if (!content) throw new Error("Import is unavailable. Reload the dashboard and try again.");
        body.replaceChildren(document.importNode(content, true));
        status.textContent = response.ok ? "" : "Please correct the issue shown below.";
      }
    } catch (error) {
      status.textContent = applying ? error.message + " Check the latest data before retrying." : error.message;
      if (!body.childElementCount) {
        var retry = document.createElement("button");
        retry.type = "button"; retry.className = "ob-btn"; retry.textContent = "Try again";
        retry.addEventListener("click", function () { request(); });
        body.append(retry);
      }
    } finally {
      busy = false;
      close.disabled = false;
      body.removeAttribute("aria-busy");
      body.querySelectorAll("button, input").forEach(function (el) { el.disabled = false; });
    }
  }
  opener.addEventListener("click", function (event) {
    event.preventDefault(); dialog.showModal();
    document.documentElement.classList.add("rundown-modal-open");
    request();
  });
  close.addEventListener("click", function () { if (!busy) dialog.close(); });
  dialog.addEventListener("cancel", function (event) { if (busy) event.preventDefault(); });
  dialog.addEventListener("close", function () {
    document.documentElement.classList.remove("rundown-modal-open"); opener.focus();
  });
  body.addEventListener("submit", function (event) {
    event.preventDefault(); request(event.target);
  });
  body.addEventListener("click", function (event) {
    if (event.target.closest("[data-rundown-reset]")) { event.preventDefault(); request(); }
  });
}());
