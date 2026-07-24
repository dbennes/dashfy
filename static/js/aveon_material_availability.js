(function () {
  "use strict";

  var root = document.getElementById("aveon-material-root");
  var dataNode = document.getElementById("aveon-material-data");
  if (!root || !dataNode) return;

  if (!window.React || !window.ReactDOM) {
    root.innerHTML = '<div class="c3-msg" style="border-left-color: var(--signal-red);">React runtime could not be loaded.</div>';
    return;
  }

  var React = window.React;
  var ReactDOM = window.ReactDOM;
  var h = React.createElement;
  var useMemo = React.useMemo;
  var useState = React.useState;

  var payload = JSON.parse(dataNode.textContent || "{}");
  var sheets = Array.isArray(payload.sheets) ? payload.sheets : [];
  var numberFmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 8 });
  var integerFmt = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
  var moneyFmt = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  var months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  function text(value) {
    if (value === null || value === undefined) return "";
    return String(value);
  }

  function pad2(value) {
    return String(value).padStart(2, "0");
  }

  function formatDate(value, format) {
    var raw = text(value);
    var match = raw.match(/^(\d{4})-(\d{2})-(\d{2})/);
    if (!match) return raw;
    var year = Number(match[1]);
    var month = Number(match[2]);
    var day = Number(match[3]);
    var yy = String(year).slice(-2);
    var fmt = text(format).toLowerCase();
    if (fmt.indexOf("mm-dd-yy") >= 0) return pad2(month) + "-" + pad2(day) + "-" + yy;
    if (fmt.indexOf("mmm") >= 0) return String(day) + "-" + months[month - 1] + "-" + yy;
    return year + "-" + pad2(month) + "-" + pad2(day);
  }

  function decimalPlaces(format) {
    var fmt = text(format);
    var match = fmt.match(/0\.(0+)/);
    return match ? match[1].length : 0;
  }

  function formatNumber(value, format) {
    if (typeof value !== "number" || !Number.isFinite(value)) return text(value);
    var fmt = text(format);
    if (fmt.indexOf("%") >= 0) {
      var places = decimalPlaces(fmt);
      return value.toLocaleString("en-US", {
        minimumFractionDigits: places,
        maximumFractionDigits: places
      }) + "%";
    }
    if (fmt.indexOf("#,##0.00") >= 0 || fmt.indexOf("0.00") >= 0) return moneyFmt.format(value);
    if (fmt.indexOf("#,##0") >= 0) return integerFmt.format(value);
    return numberFmt.format(value);
  }

  function displayValue(cell) {
    if (!cell || cell.skip) return "";
    if (cell.displayValue !== undefined && cell.displayValue !== null) return text(cell.displayValue);
    if (cell.value === null || cell.value === undefined) return "";
    if (cell.type === "date") return formatDate(cell.value, cell.numberFormat);
    if (cell.type === "number") return formatNumber(cell.value, cell.numberFormat);
    return text(cell.value);
  }

  function cellTitle(cell) {
    if (!cell || cell.skip) return "";
    var parts = [cell.address];
    var value = displayValue(cell);
    if (value) parts.push(value);
    return parts.join(" | ");
  }

  function Cell(props) {
    var cell = props.cell;
    if (!cell || cell.skip) return null;
    var classes = ["aveon-cell", "type-" + (cell.type || "blank")].concat(cell.classes || []);
    if (displayValue(cell) === "") classes.push("is-empty");
    var style = {};
    if (cell.fill) style["--sheet-fill"] = cell.fill;
    return h("td", {
      className: classes.join(" "),
      colSpan: cell.colspan || 1,
      rowSpan: cell.rowspan || 1,
      title: cellTitle(cell),
      style: style
    }, h("span", null, displayValue(cell)));
  }

  function SheetGrid(props) {
    var sheet = props.sheet;
    if (!sheet) {
      return h("div", { className: "card aveon-empty-workbook" },
        h("div", { className: "card-body" }, "No workbook sheets found.")
      );
    }

    return h("div", { className: "aveon-sheet-frame" },
      h("div", { className: "aveon-sheet-scroll" },
        h("table", { className: "aveon-workbook-grid", "aria-label": sheet.displayName || sheet.name },
          h("colgroup", null,
            h("col", { className: "aveon-row-number-col" }),
            sheet.columns.map(function (column) {
              return h("col", {
                key: column.letter,
                style: { "--sheet-col-width": String(column.width || 90) + "px" }
              });
            })
          ),
          h("thead", null,
            h("tr", null,
              h("th", { className: "aveon-corner-cell" }),
              sheet.columns.map(function (column) {
                return h("th", { key: column.letter, className: "aveon-column-letter" }, column.letter);
              })
            )
          ),
          h("tbody", null,
            sheet.rows.map(function (row) {
              var rowStyle = row.height ? { "--sheet-row-height": String(row.height) + "px" } : {};
              return h("tr", { key: row.index, style: rowStyle },
                h("th", { className: "aveon-row-number" }, row.index),
                row.cells.map(function (cell, index) {
                  return h(Cell, { key: cell && cell.address ? cell.address : row.index + "-" + index, cell: cell });
                })
              );
            })
          )
        )
      )
    );
  }

  function WorkbookApp() {
    var initialIndex = sheets.length ? 0 : -1;
    var state = useState(initialIndex);
    var activeIndex = state[0];
    var setActiveIndex = state[1];
    var activeSheet = useMemo(function () {
      if (activeIndex < 0) return null;
      return sheets[activeIndex] || sheets[0] || null;
    }, [activeIndex]);

    return h("div", { className: "aveon-workbook" },
      h("div", { className: "aveon-sheet-tabs", role: "tablist", "aria-label": "Workbook sheets" },
        sheets.map(function (sheet, index) {
          var active = activeIndex === index;
          return h("button", {
            key: sheet.name || index,
            type: "button",
            role: "tab",
            "aria-selected": active ? "true" : "false",
            className: "aveon-sheet-tab" + (active ? " is-active" : ""),
            onClick: function () { setActiveIndex(index); }
          }, sheet.displayName || sheet.name || ("Sheet " + (index + 1)));
        })
      ),
      h(SheetGrid, { sheet: activeSheet })
    );
  }

  ReactDOM.createRoot(root).render(h(WorkbookApp));
})();
