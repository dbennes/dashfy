"""Run the shipped Skyline controller against its markup and distinct sources."""
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
import subprocess

from django.conf import settings
from django.test import SimpleTestCase


class _SkylineMarkupParser(HTMLParser):
    """Keep only the Skyline card and the two detail portals from the template."""
    void_tags = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__()
        self.roots = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if not self.stack and "data-fab-skyline" not in attrs and attrs.get("id") not in {"fabSkylineBoxDetail", "fabSkylineModal"}:
            return
        node = {"tag": tag, "attrs": attrs, "children": []}
        (self.stack[-1]["children"] if self.stack else self.roots).append(node)
        if tag not in self.void_tags:
            self.stack.append(node)

    def handle_endtag(self, tag):
        if self.stack and self.stack[-1]["tag"] == tag:
            self.stack.pop()

    def handle_data(self, value):
        if self.stack and value.strip():
            self.stack[-1]["children"].append({"text": value})


def skyline_modes_fixture():
    def segment(line, when, spools, status="forecast"):
        return {
            "line": line, "date": when, "dates": [when], "spools": spools,
            "line_spools": spools, "status": status,
            "progress_pct": 100 if status == "on_time" else 50,
            "fabrication_progress_pct": 100 if status == "on_time" else 50,
            "date_kind": "planned" if status == "forecast" else "actual",
            "actual_date_confirmed": status == "on_time",
        }

    def bucket(when, forecast=(), actual=()):
        return {
            "date": when, "forecast": list(forecast), "lookahead": list(actual),
            "forecast_total": sum(item["spools"] for item in forecast),
            "lookahead_total": sum(item["spools"] for item in actual),
            "performed_total": sum(item["spools"] for item in actual),
        }

    schedules = {}
    for key, cutoff, dates in (
        ("ros", "2026-09-03", ["2026-09-04", "2026-09-11"]),
        ("aveon", "2026-09-10", ["2026-09-04", "2026-09-11"]),
        ("installation", "2026-09-17", ["2026-09-11", "2026-09-18"]),
    ):
        sample = key == "installation"
        source = {
            "mode": key, "discipline": "piping", "discipline_label": "Piping",
            "data_kind": "sample" if sample else "real", "is_sample": sample,
            "as_of_date": cutoff, "as_of_label": {"ros": "03 Sep 26", "aveon": "10 Sep 26", "installation": "17 Sep 26"}[key],
            "snapshot_label": "15 Sep 26", "source_label": "Sample data" if sample else "DATAFY " + key,
            "workbook": "" if sample else key.upper() + " schedule.xlsx",
            "notice": "Real ROS lines and spool quantities; dates and installation progress are simulated." if sample else "",
            "date_rule": "Simulated planned and completed installation dates; real ROS scope." if sample else key + " source dates.",
        }
        if sample:
            source.update(
                scope_kind="real", scope_source="ROS", scope_workbook="ROS schedule.xlsx",
                scope_snapshot_label="15 Sep 26",
            )
        schedules[key] = {
            "available": True, "error": "", "source": source,
            "kpis": {
                "line_count": 2, "scope_spools": 3, "scheduled_line_count": 2,
                "scheduled_spools": 3, "performed_line_count": 1, "performed_spools": 2,
                "remaining_line_count": 1, "remaining_spools": 1,
                "confirmed_actual_line_count": 0 if sample else 1, "confirmed_actual_spools": 0 if sample else 2,
                "estimated_completion_line_count": 0, "estimated_completion_spools": 0,
                "on_time_line_count": 1, "on_time_spools": 2,
            },
            "charts": {
                "dates": [
                    bucket(dates[0], actual=[segment("LINE-1", dates[0], 2, "on_time")]),
                    bucket(dates[1], forecast=[segment("LINE-1", dates[1], 2), segment("LINE-2", dates[1], 1)]),
                ],
                "material_readiness": {},
            },
        }
    for bucket in schedules["installation"]["charts"]["dates"]:
        for segment in bucket["forecast"] + bucket["lookahead"]:
            segment.update(actual_date_confirmed=False, actual_finish="", date_kind="simulated")
    schedules["ros"]["charts"]["material_readiness"] = {
        "LINE-1": {
            category: {
                "status": state, "source": "DATAFY live evidence", "as_of_date": "2026-09-03",
                "counts": {"total_items": 2, "ready_items": 1, "items_with_po": 2, "items_without_po": 0},
            }
            for category, state in (("supports", "ready"), ("erection", "partial"), ("valves", "pending"))
        },
    }
    # AVEON shares the real ROS material map; the sample must never inherit it.
    del schedules["aveon"]["charts"]["material_readiness"]
    return schedules


class SkylineModesUITests(SimpleTestCase):
    def run_controller(self, scenario, *, empty_ros=False):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to execute the shipped Skyline controller")
        source = (Path(settings.BASE_DIR) / "templates/core/home.html").read_text(encoding="utf-8")
        start = source.index("  function fabSkylineInit(")
        end = source.index("\n  function ", start + 1)
        controller = re.sub(r"{%.*?%}", "", source[start:end], flags=re.DOTALL)
        parser = _SkylineMarkupParser()
        parser.feed(source)
        self.assertEqual(len(parser.roots), 3)
        schedules = skyline_modes_fixture()
        if empty_ros:
            schedules["ros"].update(available=False, error="ROS dates unavailable")
            schedules["ros"]["charts"]["dates"] = []
            schedules["installation"].update(available=False, error="Real ROS line scope is unavailable.")
            schedules["installation"]["charts"]["dates"] = []
            schedules["installation"]["kpis"] = {key: 0 for key in schedules["installation"]["kpis"]}
        harness = r"""
            function dataKey(key) { return key.replace(/[A-Z]/g, letter => '-' + letter.toLowerCase()); }
            class Element {
              constructor(tag = 'div', attrs = {}) {
                this.tagName = tag.toUpperCase(); this.attrs = {...attrs}; this.children = [];
                this.parentElement = null; this.listeners = {}; this._text = '';
                this.hidden = 'hidden' in attrs; this.disabled = 'disabled' in attrs;
                this.style = {setProperty(key, value) { this[key] = String(value); }};
                this.dataset = new Proxy({}, {
                  get: (_, key) => this.attrs['data-' + dataKey(key)],
                  set: (_, key, value) => { this.attrs['data-' + dataKey(key)] = String(value); return true; },
                  deleteProperty: (_, key) => { delete this.attrs['data-' + dataKey(key)]; return true; }
                });
                this.classList = {
                  contains: value => this.className.split(/\s+/).includes(value),
                  add: (...values) => { this.className = Array.from(new Set(this.className.split(/\s+/).filter(Boolean).concat(values))).join(' '); },
                  remove: (...values) => { this.className = this.className.split(/\s+/).filter(value => !values.includes(value)).join(' '); },
                  toggle: (value, force) => { const on = force === undefined ? !this.classList.contains(value) : force;
                    if (on) this.classList.add(value); else this.classList.remove(value); return on; }
                };
              }
              get className() { return this.attrs.class || ''; }
              set className(value) { this.attrs.class = value; }
              set textContent(value) { this._text = String(value); this.children = []; }
              get textContent() { return this._text + this.children.map(child => child.textContent).join(''); }
              appendChild(child) {
                if (child.parentElement) child.parentElement.children = child.parentElement.children.filter(item => item !== child);
                child.parentElement = this; this.children.push(child); return child;
              }
              replaceChildren(...children) { this._text = ''; this.children = []; children.forEach(child => this.appendChild(child)); }
              setAttribute(key, value) { this.attrs[key] = String(value); }
              getAttribute(key) { return this.attrs[key] ?? null; }
              removeAttribute(key) { delete this.attrs[key]; }
              addEventListener(event, callback) { (this.listeners[event] ||= []).push(callback); }
              fire(event) { (this.listeners[event] || []).forEach(callback => callback({target: this, preventDefault() {}})); }
              focus() { document.activeElement = this; }
              contains(node) { return this === node || this.children.some(child => child.contains(node)); }
              getBoundingClientRect() { return {left: 20, top: 20, right: 160, width: 140, height: 80}; }
              getClientRects() { return this.hidden ? [] : [this.getBoundingClientRect()]; }
              matches(selector) {
                if (selector === ':hover') return false;
                const parts = selector.trim().split(/\s+/);
                const own = parts.pop();
                const tag = own.match(/^[a-zA-Z][\w-]*/);
                if (tag && this.tagName !== tag[0].toUpperCase()) return false;
                for (const match of own.matchAll(/#([\w-]+)|\.([\w-]+)|\[([\w-]+)(?:=["']?([^\]"']+)["']?)?\]/g)) {
                  if (match[1] && this.attrs.id !== match[1]) return false;
                  if (match[2] && !this.classList.contains(match[2])) return false;
                  if (match[3] && (!(match[3] in this.attrs) || (match[4] !== undefined && this.attrs[match[3]] !== match[4]))) return false;
                }
                if (!parts.length) return true;
                for (let parent = this.parentElement; parent; parent = parent.parentElement) {
                  if (parent.matches(parts.join(' '))) return true;
                }
                return false;
              }
              querySelectorAll(selector) {
                const matches = [], alternatives = selector.split(',');
                function walk(node) { node.children.forEach(child => {
                  if (alternatives.some(choice => child.matches(choice))) matches.push(child);
                  walk(child);
                }); }
                walk(this); return matches;
              }
              querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
            }
            const body = new Element('body');
            function fromMarkup(value) {
              const element = new Element(value.tag || '#text', value.attrs || {});
              if ('text' in value) element.textContent = value.text;
              (value.children || []).forEach(child => element.appendChild(fromMarkup(child)));
              return element;
            }
            markup.forEach(value => body.appendChild(fromMarkup(value)));
            const document = {
              body, activeElement: null,
              getElementById(id) { return body.querySelector('#' + id); },
              querySelector(selector) { return body.querySelector(selector); },
              createElement(tag) { return new Element(tag); },
              createTextNode(text) { const node = new Element('#text'); node.textContent = text; return node; },
              addEventListener() {}
            };
            const root = document.querySelector('[data-fab-skyline]');
            root.dataset.asOfDate = schedules.ros.source.as_of_date;
            const data = new Element('script', {id: 'fabSkylineData'});
            data.textContent = JSON.stringify(schedules.ros.charts); body.appendChild(data);
            const modes = new Element('script', {id: 'fabSkylineSchedules'});
            modes.textContent = JSON.stringify(schedules); body.appendChild(modes);
            const window = {
              innerWidth: 1200, innerHeight: 900, clearTimeout() {},
              setTimeout(callback) { callback(); return 1; }, addEventListener() {},
              getComputedStyle() { const styles = []; styles.getPropertyValue = () => ''; return styles; }
            };
            const Node = Element;
            const rundown = new Element('article', {'data-fab-rundown': '', 'data-rundown-mode': 'fabrication'});
            rundown.textContent = 'Independent rundown'; body.appendChild(rundown);
            const rundownBefore = rundown.textContent + JSON.stringify(rundown.attrs);
            function visible(element) {
              for (let current = element; current; current = current.parentElement) {
                if (current.hidden) return false;
              }
              return Boolean(element);
            }
            function text(id) { return document.getElementById(id)?.textContent || ''; }
            function choose(key) { root.querySelector('[data-skyline-schedule="' + key + '"]').fire('click'); }
            function state() {
              const matrix = document.getElementById('fabSkylinePlot');
              const sample = document.getElementById('fabSkylineSample');
              const marker = matrix.querySelector('.is-as-of time');
              return {
                source: root.dataset.scheduleSource, asOf: root.dataset.asOfDate,
                title: text('fabSkylineTitle'), caption: text('fabSkylineScheduleCaption'),
                sourceText: text('fabSkylineScheduleSource'), summary: text('fabSkylineSummary'),
                cutoff: text('fabSkylineCutoffDate'), markedDate: marker && marker.dateTime,
                sampleVisible: visible(sample), sampleText: sample && sample.textContent,
                materialLegendVisible: visible(root.querySelector('.fab-skyline-material-legend')),
                rosActionsVisible: visible(root.querySelector('.fab-ros-actions')),
                pressed: root.querySelectorAll('[data-skyline-schedule]').map(button => button.getAttribute('aria-pressed')),
                viewportVisible: visible(root.querySelector('.fab-skyline-viewport')),
                emptyVisible: visible(document.getElementById('fabSkylineEmpty')),
                emptyText: text('fabSkylineEmpty'),
                forecastBand: text('fabSkylineForecastBand'), actualBand: text('fabSkylineActualBand'),
                plannedScope: matrix.querySelectorAll('.is-forecast .fab-skyline-item').map(box => ({
                  line: box.dataset.skylineLine, spools: box.querySelector('.fab-skyline-qty').textContent
                })),
                boxes: matrix.querySelectorAll('.fab-skyline-item').map(box => ({
                  line: box.dataset.skylineLine, classes: box.className, label: box.getAttribute('aria-label'),
                  lights: box.querySelectorAll('.fab-material-light').map(light => light.className)
                })),
                lower: matrix.querySelectorAll('.is-lookahead .fab-skyline-item').map(box => box.className),
                rundownUnchanged: rundown.textContent + JSON.stringify(rundown.attrs) === rundownBefore,
              };
            }
        """
        program = "const schedules = " + json.dumps(schedules) + ";\nconst markup = " + json.dumps(parser.roots) + ";\n"
        program += harness + "\n" + controller + "\n" + scenario
        result = subprocess.run(
            [node, "-"], input=program, capture_output=True, text=True,
            encoding="utf-8", timeout=10, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_mode_switches_restore_live_materials_source_dates_and_wooden_box_actions(self):
        ros, fabrication, sample, restored = self.run_controller("""
            fabSkylineInit(); const ros = state(); choose('aveon'); const fabrication = state();
            choose('installation'); const sample = state(); choose('ros');
            console.log(JSON.stringify([ros, fabrication, sample, state()]));
        """)
        self.assertEqual(ros["source"], "ros")
        self.assertEqual(ros["pressed"], ["false", "true", "false"])
        self.assertTrue(ros["rosActionsVisible"])
        self.assertTrue(ros["materialLegendVisible"])
        self.assertFalse(ros["sampleVisible"])
        self.assertTrue(any(box["lights"] for box in ros["boxes"]))
        self.assertEqual(fabrication["source"], "aveon")
        self.assertEqual(fabrication["pressed"], ["true", "false", "false"])
        self.assertFalse(fabrication["rosActionsVisible"])
        self.assertTrue(fabrication["materialLegendVisible"])
        self.assertEqual(sample["source"], "installation")
        self.assertEqual(sample["pressed"], ["false", "false", "true"])
        self.assertTrue(sample["sampleVisible"])
        self.assertIn("Sample data", sample["sampleText"])
        self.assertFalse(sample["materialLegendVisible"])
        self.assertFalse(sample["rosActionsVisible"])
        self.assertIn("ROS", sample["sourceText"])
        self.assertIn("Sample data: installation dates and progress", sample["sourceText"])
        self.assertEqual(sample["caption"], "Installation · Real lines and spools · Simulated dates and progress")
        self.assertIn("real", sample["summary"].lower())
        self.assertIn("simulated", sample["summary"].lower())
        self.assertNotIn("quantities in this view are simulated", sample["summary"])
        self.assertEqual(sample["plannedScope"], ros["plannedScope"])
        self.assertTrue(sample["viewportVisible"])
        self.assertTrue(sample["boxes"])
        for box in sample["boxes"]:
            self.assertEqual(box["lights"], [])
            self.assertNotIn("Supports:", box["label"])
            self.assertNotIn("Bolts & gaskets:", box["label"])
        self.assertEqual(len(sample["lower"]), 1)
        self.assertIn("is-on-time", sample["lower"][0])
        self.assertIn("Completed", sample["actualBand"])
        self.assertEqual(restored, ros)
        for state in (ros, fabrication, sample, restored):
            self.assertTrue(state["rundownUnchanged"])

    def test_source_switch_updates_cutoff_label_and_highlighted_week(self):
        states = self.run_controller("""
            fabSkylineInit(); const states = [state()];
            ['aveon', 'installation', 'ros'].forEach(key => { choose(key); states.push(state()); });
            console.log(JSON.stringify(states));
        """)
        self.assertEqual([state["asOf"] for state in states], ["2026-09-03", "2026-09-10", "2026-09-17", "2026-09-03"])
        self.assertEqual([state["markedDate"] for state in states], ["2026-09-04", "2026-09-11", "2026-09-18", "2026-09-04"])
        self.assertEqual([state["cutoff"] for state in states], ["03 Sep 26", "10 Sep 26", "17 Sep 26", "03 Sep 26"])

    def test_status_colors_follow_execution_in_both_bands_without_marking_unstarted_as_late(self):
        result = self.run_controller("""
            const forecast = schedules.aveon.charts.dates[1].forecast;
            forecast[1].progress_pct = 0;
            forecast[1].fabrication_progress_pct = 0;
            forecast.push({...forecast[1], line:'WORKING', progress_pct:45, fabrication_progress_pct:45});
            forecast.push({...forecast[1], line:'LATE', progress_pct:100, fabrication_progress_pct:100});
            schedules.aveon.charts.dates[0].lookahead.push({
              ...schedules.aveon.charts.dates[0].lookahead[0], line:'LATE', status:'late'
            });
            modes.textContent = JSON.stringify(schedules);
            fabSkylineInit(); choose('aveon'); console.log(JSON.stringify(state()));
        """)
        classes = {}
        for box in result["boxes"]:
            classes.setdefault(box["line"], []).append(box["classes"])
        self.assertTrue(all("is-on-time" in value for value in classes["LINE-1"]))
        self.assertTrue(all("is-upcoming" in value for value in classes["LINE-2"]))
        self.assertTrue(all("is-partial" in value for value in classes["WORKING"]))
        self.assertTrue(all("is-late" in value for value in classes["LATE"]))
        self.assertEqual(len(result["lower"]), 2)

    def test_missing_ros_scope_keeps_installation_unavailable_and_mode_switches_stable(self):
        empty, sample, restored = self.run_controller("""
            fabSkylineInit(); const empty = state(); choose('installation'); const sample = state();
            choose('ros'); console.log(JSON.stringify([empty, sample, state()]));
        """, empty_ros=True)
        for state in (empty, sample, restored):
            self.assertFalse(state["viewportVisible"])
            self.assertTrue(state["emptyVisible"])
            self.assertEqual(state["boxes"], [])
            self.assertTrue(state["rundownUnchanged"])
        self.assertEqual(sample["source"], "installation")
        self.assertEqual(sample["pressed"], ["false", "false", "true"])
        self.assertIn("ROS", sample["emptyText"])
        self.assertEqual(restored, empty)

    def test_sample_box_and_period_details_do_not_claim_live_po_or_material_evidence(self):
        result = self.run_controller("""
            fabSkylineInit(); choose('installation');
            document.getElementById('fabSkylinePlot').querySelector('.is-lookahead .fab-skyline-item').fire('click');
            const box = document.getElementById('fabSkylineBoxDetail');
            const output = {
              boxVisible: visible(box), source: text('fabSkylineBoxSource'),
              schedule: text('fabSkylineBoxSchedule'),
              categoriesVisible: visible(document.getElementById('fabSkylineBoxCategories')),
              footnoteVisible: visible(document.getElementById('fabSkylineBoxFootnote'))
            };
            document.getElementById('fabSkylineBoxPeriod').fire('click');
            const modal = document.getElementById('fabSkylineModal');
            output.modalVisible = visible(modal);
            output.note = text('fabSkylineModalScheduleNote');
            output.materialCells = modal.querySelectorAll('.fab-skyline-material-cell').filter(visible).length;
            output.headers = modal.querySelectorAll('th').filter(visible).map(node => node.textContent);
            output.cells = document.getElementById('fabSkylineModalBody').querySelectorAll('td').filter(visible).map(node => node.textContent);
            console.log(JSON.stringify(output));
        """)
        self.assertTrue(result["boxVisible"])
        self.assertIn("ROS", result["source"])
        self.assertIn("real", result["source"].lower())
        self.assertIn("Sample data: installation dates and progress", result["source"])
        self.assertNotIn("DATAFY", result["source"])
        self.assertFalse(result["categoriesVisible"])
        self.assertFalse(result["footnoteVisible"])
        self.assertTrue(result["modalVisible"])
        self.assertIn("Sample", result["note"])
        self.assertIn("real", result["note"].lower())
        self.assertIn("ROS", result["note"])
        self.assertIn("simulated", result["note"].lower())
        self.assertNotIn("quantities are simulated", result["note"])
        self.assertEqual(result["materialCells"], 0)
        self.assertNotIn("Supports", result["headers"])
        self.assertNotIn("Valves", result["headers"])
        self.assertEqual(len(result["cells"]), 4)
