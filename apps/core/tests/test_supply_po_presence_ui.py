from copy import deepcopy
from html.parser import HTMLParser
import json
from pathlib import Path
import shutil
import subprocess

from django.conf import settings
from django.template.loader import render_to_string
from django.test import SimpleTestCase


class _MaterialRowsParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "tr" and "data-grid-row" in attributes:
            self.rows.append(attributes)


class SupplyPoPresenceUITests(SimpleTestCase):
    def items(self):
        rows = []
        for item_id, gap in enumerate(("no_po", "no_balance", "not_allocated", "catalog_issue", "allocated"), 1):
            has_po = gap == "allocated"
            rows.append({
                "material_item_id": item_id, "document_id": 100,
                "drawing_number": "DWG-100", "drawing": "DWG-100",
                "original_filename": "DWG-100.pdf", "status": "missing", "po_gap_label": gap,
                "scope": "fabrication", "campaign": "1st", "line": '4"-DN-100001',
                "has_po": int(has_po), "po_gap_status": gap,
                "requested_qty": 10, "allocated_qty": 2 if has_po else 0,
                "missing_qty": 8 if has_po else 10,
                "stock_piece_count": 1 if gap in {"no_balance", "not_allocated"} else 0,
                "stock_free_qty": 12 if gap == "not_allocated" else 0,
                "stock_free_na": int(gap == "catalog_issue"),
                "po_numbers": "PO-100" if has_po else "",
                "po_delivery_date": "2026-10-01" if has_po else "",
                "yard_actual": 0, "is_finalized": 0,
            })
        return rows

    def render_material_rows(self, items):
        parser = _MaterialRowsParser()
        parser.feed(render_to_string("core/partials/material_rows.html", {"rows": items}))
        return parser.rows

    def dataset(self, attributes):
        result = {}
        for key, value in attributes.items():
            if not key.startswith("data-"):
                continue
            words = key[5:].split("-")
            result[words[0] + "".join(word.title() for word in words[1:])] = value
        return result

    def run_home_javascript(self, script, items=None):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to execute the actual Supply forecast code")
        source = (Path(settings.BASE_DIR) / "templates" / "core" / "home.html").read_text(encoding="utf-8")
        names = (
            "c3Norm", "c3Same", "c3Flag", "c3Number", "c3LocalIsoDate",
            "c3ForecastItems", "c3ForecastKey", "c3EmptyForecastMetric", "c3AddUnique",
            "c3ForecastPoPairs", "c3ForecastHasTrackingPo", "c3SplitForecastList",
            "c3BuildForecastMetrics", "c3ActiveForecastDate", "c3BuildForecastChartPayload",
            "c3ForecastMetricsForRow", "c3DatasetHas", "c3DatasetNumber",
            "c3StageItems", "c3DrawingStageMatches", "c3DrawingLinePoState",
        )
        functions = []
        for name in names:
            start = source.index("  function " + name + "(")
            end = source.find("\n  function ", start + 1)
            self.assertGreater(end, start)
            functions.append(source[start:end])
        program = "\n".join(functions) + "\nvar c3ForecastState = { date: '', metrics: null, items: "
        program += json.dumps(items or []) + " };\n" + script
        result = subprocess.run(
            [node, "-"], input=program, capture_output=True, text=True,
            encoding="utf-8", timeout=10, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_material_rows_include_no_balance_in_without_po_and_keep_reason_flags(self):
        rows = self.render_material_rows(self.items())
        self.assertEqual(len(rows), 5)
        for row in rows:
            has_po = row["data-has-po"] == "1"
            self.assertEqual(row["data-without-po"], "0" if has_po else "1")
            self.assertEqual(row["data-stage-no-po-items"], "0" if has_po else "1")
        balance = next(row for row in rows if row["data-po-gap-status"] == "no_balance")
        self.assertEqual(balance["data-no-balance"], "1")
        self.assertEqual(balance["data-stage-no-balance-items"], "1")

    def test_forecast_counts_all_unlinked_items_without_reclassifying_by_delivery_date(self):
        items = self.items()
        finalized = deepcopy(items[0])
        finalized.update(material_item_id=6, document_id=200, is_finalized=1)
        items.append(finalized)
        result = self.run_home_javascript("""
            var before = JSON.stringify(c3ForecastState.items);
            var output = ['2026-09-01', '2026-12-01'].map(function(day) {
              var metric = Object.values(c3BuildForecastMetrics(day))[0];
              return { day: day, total: metric.total, withPo: metric.withPo,
                noPo: metric.noPo, noBalance: metric.noBalance,
                notAllocated: metric.notAllocated, catalogIssue: metric.catalogIssue,
                noPoAssumption: metric.noPoAssumption };
            });
            console.log(JSON.stringify({ rows: output,
              sourceUnchanged: JSON.stringify(c3ForecastState.items) === before }));
        """, items)
        self.assertTrue(result["sourceUnchanged"])
        for row in result["rows"]:
            self.assertEqual((row["total"], row["withPo"], row["noPo"]), (5, 1, 4))
            self.assertEqual((row["noBalance"], row["notAllocated"], row["catalogIssue"]), (1, 1, 1))
            self.assertEqual(row["total"], row["withPo"] + row["noPo"])
        self.assertEqual([row["noPoAssumption"] for row in result["rows"]], [0, 1])

    def test_forecast_chart_keeps_balance_as_subset_across_scope_filters(self):
        items = self.items()
        erection = deepcopy(items[1])
        erection.update(material_item_id=6, document_id=200, scope="erection")
        items.append(erection)
        output = self.run_home_javascript("""
            c3ForecastState.date = '2026-12-01';
            var result = {};
            ['all', 'fabrication', 'erection'].forEach(function(scope) {
              result[scope] = c3BuildForecastChartPayload(scope, {
                scope: scope, campaigns: [{ label: '1st' }], totals: {}
              }).totals;
            });
            console.log(JSON.stringify(result));
        """, items)
        for scope, expected in {"all": (6, 1, 5, 2), "fabrication": (5, 1, 4, 1), "erection": (1, 0, 1, 1)}.items():
            with self.subTest(scope=scope):
                totals = output[scope]
                self.assertEqual(tuple(totals[key] for key in ("total", "po", "no_po", "no_balance")), expected)
                self.assertEqual(totals["total"], totals["po"] + totals["no_po"])
                self.assertLessEqual(totals["no_balance"], totals["no_po"])

    def test_without_po_selection_and_export_label_include_no_balance_material(self):
        attributes = self.render_material_rows([self.items()[1]])[0]
        dataset = json.dumps(self.dataset(attributes))
        output = self.run_home_javascript("""
            var row = { dataset: """ + dataset + """ };
            console.log(JSON.stringify({
              withoutPo: c3DrawingStageMatches(row, 'no_po'),
              noBalance: c3DrawingStageMatches(row, 'no_balance'),
              withPo: c3DrawingStageMatches(row, 'po'),
              state: c3DrawingLinePoState(row)
            }));
        """)
        self.assertTrue(output["withoutPo"])
        self.assertTrue(output["noBalance"])
        self.assertFalse(output["withPo"])
        self.assertEqual(output["state"], "Without PO · No Balance")

    def test_explicit_no_po_flag_wins_over_allocation_quantity_and_po_text(self):
        for gap in ("catalog_issue", "allocated"):
            with self.subTest(gap=gap):
                item = self.items()[3]
                item.update({
                    "material_item_id": 25571, "has_po": 0,
                    "requested_qty": 1, "allocated_qty": 1, "missing_qty": 0,
                    "po_gap_status": gap, "po_covering": "PO-OLD-ALLOCATION",
                    "po_numbers": "PO-OLD-ALLOCATION", "po_delivery_date": "2026-10-01",
                })
                attributes = self.render_material_rows([item])[0]
                self.assertEqual(attributes["data-has-po"], "0")
                self.assertEqual(attributes["data-with-po"], "0")
                self.assertEqual(attributes["data-without-po"], "1")
                dataset = json.dumps(self.dataset(attributes))
                output = self.run_home_javascript("""
                    var row = { dataset: """ + dataset + """ };
                    var metric = Object.values(c3BuildForecastMetrics('2026-12-01'))[0];
                    console.log(JSON.stringify({
                      withoutPoSelected: c3DrawingStageMatches(row, 'no_po'),
                      withPoSelected: c3DrawingStageMatches(row, 'po'),
                      noPo: metric.noPo, withPo: metric.withPo,
                      allocated: c3ForecastState.items[0].allocated_qty,
                      state: c3DrawingLinePoState(row)
                    }));
                """, [item])
                self.assertTrue(output["withoutPoSelected"])
                self.assertFalse(output["withPoSelected"])
                self.assertEqual((output["noPo"], output["withPo"]), (1, 0))
                self.assertEqual(output["allocated"], 1)
                self.assertEqual(output["state"], "Without PO")
