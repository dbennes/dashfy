(function () {
  "use strict";
  const monitor = document.querySelector("[data-mdr-monitor]");
  if (!monitor || monitor.dataset.mdrReady) return;
  monitor.dataset.mdrReady = "true";
  const buttons = Array.from(monitor.querySelectorAll("[data-mdr-scope]"));
  function select(button) {
    if (button.disabled) return;
    const scope = button.dataset.mdrScope;
    buttons.forEach(item => item.setAttribute("aria-pressed", String(item === button)));
    monitor.querySelectorAll("[data-mdr-scope-panel]").forEach(panel => {
      panel.hidden = panel.dataset.mdrScopePanel !== scope;
    });
    monitor.querySelectorAll("[data-mdr-total]").forEach(node => { node.textContent = button.dataset.total; });
    monitor.querySelectorAll("[data-mdr-scope-label]").forEach(node => { node.textContent = button.dataset.label; });
    monitor.dataset.mdrScope = scope;
  }
  buttons.forEach(button => button.addEventListener("click", () => select(button)));
}());
