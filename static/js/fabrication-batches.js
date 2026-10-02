(function () {
  "use strict";
  window.DashfyBatchChart = {
    init: function () {
      var canvas = document.getElementById("fabCampChart");
      var dataNode = document.getElementById("fabBatchData");
      if (!canvas || !dataNode || canvas.dataset.ready) return;
      var payload = JSON.parse(dataNode.textContent || "null");
      var card = canvas.closest(".fab-batches-card");
      if (!payload || !payload.labels || !payload.labels.length) {
        canvas.parentElement.innerHTML = '<div class="fab-chart-empty">No batch workbook imported yet.</div>';
        card.querySelectorAll("[data-batch-scope]").forEach(function (button) { button.disabled = true; });
        return;
      }
      canvas.dataset.ready = "1";
      var chart = new Chart(canvas, {
        type: "bar",
        data: { labels: payload.labels.map(function (label) { return label.replace("Batch ", ""); }), datasets: [
          { label: "Listed", data: [], backgroundColor: "rgba(255,255,255,.12)", borderColor: "rgba(255,255,255,.3)", borderWidth: 1 },
          { label: "Fabricated", data: [], backgroundColor: "rgba(34,197,94,.8)" }
        ] },
        options: {
          maintainAspectRatio: false,
          plugins: { legend: { position: "top", align: "end", labels: { boxWidth: 9, boxHeight: 8 } },
            tooltip: { callbacks: { title: function (items) { return payload.labels[items[0].dataIndex]; },
              afterBody: function (items) {
                var i = items[0].dataIndex, total = chart.data.datasets[0].data[i], done = chart.data.datasets[1].data[i];
                return total ? (100 * done / total).toFixed(1) + "% fabricated" : "No listed items";
              } } } },
          scales: { y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: "rgba(255,255,255,.08)" } },
            x: { grid: { display: false }, title: { display: true, text: "Batch" } } }
        }
      });
      function select(scope) {
        var data = payload.scopes[scope];
        chart.data.datasets[0].data = data.total;
        chart.data.datasets[1].data = data.done;
        chart.update();
        document.getElementById("fabBatchSummary").textContent = data.done_count + " / " + data.item_count + " listed items fabricated · " + (data.item_count ? (100 * data.done_count / data.item_count).toFixed(1) : "0.0") + "%";
        canvas.setAttribute("aria-label", payload.labels.map(function (label, i) { return label + ": " + data.done[i] + " fabricated / " + data.total[i] + " listed"; }).join("; "));
        card.querySelectorAll("[data-batch-scope]").forEach(function (button) { button.setAttribute("aria-pressed", String(button.dataset.batchScope === scope)); });
      }
      card.querySelectorAll("[data-batch-scope]").forEach(function (button) { button.addEventListener("click", function () { select(button.dataset.batchScope); }); });
      select("all");
    }
  };
})();
