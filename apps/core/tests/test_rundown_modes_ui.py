"""Execute the shipped rundown controller with independent mode/discipline data."""
import json
from pathlib import Path
import shutil
import subprocess

from django.conf import settings
from django.test import SimpleTestCase


def rundown_modes_fixture():
    """Different scopes make accidental reuse of another curve observable."""
    modes = {}
    for mode in ("fabrication", "installation"):
        sample = mode == "installation"
        disciplines = {}
        for index, key in enumerate(("piping", "electrical", "structural")):
            available = sample or key != "electrical"
            scope = (30 if sample else 10) + index
            unit = {"piping": "spools", "electrical": "circuits", "structural": "packages"}[key]
            dates = ["2026-10-01", "2026-10-02"] if sample else ["2026-09-01", "2026-09-02"]
            disciplines[key] = {
                "available": available,
                "error": "" if available else "No electrical fabrication schedule is available.",
                "source": {
                    "mode": mode, "mode_label": mode.title(),
                    "discipline": key, "discipline_label": key.title(),
                    "data_kind": "sample" if sample else "real", "is_sample": sample,
                    "title": key.title() + " " + mode + " rundown",
                    "source_label": "Sample data" if sample else "DATAFY " + key + " schedule",
                    "unit": unit, "unit_label": unit,
                    "baseline_label": "Baseline" if sample or key == "piping" else "AVEON plan",
                    "lookahead_label": "Lookahead", "has_lookahead": sample or key == "piping",
                    "snapshot_date": "2026-09-15" if available else "",
                    "snapshot_label": "15 Sep 26" if available else "—",
                    "notice": "Sample installation data for demonstration only." if sample else "",
                },
                "kpis": {
                    "scope_total": scope if available else 0,
                    "baseline_finish_label": "02 Oct 26" if sample else "02 Sep 26",
                    "lookahead_finish_label": "03 Oct 26" if sample else "03 Sep 26",
                    "finish_variance_days": 1 if available else None,
                },
                "charts": {
                    "dates": dates if available else [],
                    "baseline_total": [scope, 0] if available else [],
                    "baseline_rundown": [scope, 0] if available else [],
                    "lookahead_total": [0, scope] if available else [],
                    "lookahead_rundown": [scope, scope] if available else [],
                },
            }
        modes[mode] = {"label": mode.title(), "disciplines": disciplines}
    return modes


class RundownModesUITests(SimpleTestCase):
    def test_today_marker_advances_without_changing_snapshot_or_curves(self):
        result = self.run_controller("""
            const RealDate = Date;
            let now = new RealDate(2026, 8, 24, 12).getTime();
            globalThis.Date = class extends RealDate {
              constructor(...args) { super(...(args.length ? args : [now])); }
            };
            let onFocus, onMidnight;
            window.addEventListener = (name, fn) => { if(name === 'focus') onFocus = fn; };
            window.setTimeout = fn => { onMidnight = fn; };
            fabRundownInit(); visibleCallback();
            const config = liveChart.config;
            const initial = root.dataset.todayDate;
            const before = JSON.stringify(config.data.datasets);
            let marker, label, updates = 0;
            const ctx = new Proxy({}, {get: (_target,key) => key === 'measureText' ? () => ({width:120}) : (...args) => {if(key === 'fillText') label=args[0];}});
            const mock = {ctx, chartArea:{left:0,right:1000,top:0,bottom:300},scales:{x:{getPixelForValue(value){marker=value;return 100;}}}};
            const plugin = config.plugins.find(p => p.id === 'fabRundownDataDate');
            plugin.beforeDatasetsDraw(mock); plugin.afterDatasetsDraw(mock);
            liveChart.options = config.options;
            liveChart.update = () => updates++;
            now = new RealDate(2026,8,25,12).getTime(); onMidnight(); onFocus();
            console.log(JSON.stringify({initial,next:root.dataset.todayDate,marker,label,updates,
              max:config.options.scales.x.max,snapshot:root.dataset.snapshotDate,
              unchanged:before===JSON.stringify(config.data.datasets)}));
        """)
        self.assertEqual(result["initial"], "2026-09-24")
        self.assertEqual(result["next"], "2026-09-25")
        self.assertEqual(result["snapshot"], "2026-09-15")
        self.assertEqual(result["marker"], 1790208000000)
        self.assertIn("TODAY", result["label"])
        self.assertEqual(result["updates"], 1)
        self.assertTrue(result["unchanged"])
        self.assertGreater(result["max"], result["marker"])

    def run_controller(self, scenario):
        node = shutil.which("node")
        if not node:
            self.skipTest("Node.js is required to execute the shipped rundown controller")
        source = (Path(settings.BASE_DIR) / "templates/core/home.html").read_text(encoding="utf-8")
        start = source.index("  function fabRundownInit(")
        end = source.index("\n  function ", start + 1)
        controller = source[start:end]
        modes = rundown_modes_fixture()
        harness = r"""
            class Element {
              constructor() {
                this.dataset = {}; this.attributes = {}; this.listeners = {};
                this.hidden = false; this.value = ''; this.clientWidth = 1000;
                this._text = ''; this.children = [];
              }
              set textContent(value) { this._text = String(value); this.children = []; }
              get textContent() { return this._text + this.children.map(n => n.textContent).join(''); }
              appendChild(node) { this.children.push(node); return node; }
              setAttribute(key, value) { this.attributes[key] = String(value); }
              addEventListener(event, handler) { (this.listeners[event] ||= []).push(handler); }
              fire(event) { (this.listeners[event] || []).forEach(handler => handler({target: this})); }
            }
            const root = new Element(), nodes = {}, ids = {}, queries = [];
            const selectors = [
              '#fabRundownProgress', '#fabRundownTitle', '#fabRundownSample', '#fabRundownEmpty',
              '#fabRundownDataDate', '#fabRundownNotice', '#fabRundownSummary',
              '.fab-rundown-kicker', '.fab-rundown-title p', '.is-scope', '.is-scope dd',
              '.is-baseline', '.is-baseline dt', '.is-baseline dd', '.is-lookahead',
              '.is-lookahead dt', '.is-lookahead dd', '.is-variance dd',
              '.fab-rundown-legend', '.fab-rundown-data-date', '.fab-rundown-source'
            ];
            selectors.forEach(selector => {
              nodes[selector] = new Element();
              if (selector.startsWith('#')) ids[selector.slice(1)] = nodes[selector];
            });
            const buttons = ['fabrication', 'installation'].map(mode => {
              const button = new Element(); button.dataset.rundownMode = mode; return button;
            });
            const groups = {};
            ['[data-rundown-actual]', '[data-rundown-lookahead]', '[data-rundown-baseline-label]',
             '[data-rundown-lookahead-label]', '.fab-rundown-legend-label'].forEach(selector => {
              groups[selector] = [new Element(), new Element()];
            });
            root.querySelector = selector => {
              if (!(selector in nodes)) throw Error('Unexpected rundown selector: ' + selector);
              return nodes[selector];
            };
            root.querySelectorAll = selector => {
              if (selector === '[data-rundown-mode]') return buttons;
              if (!(selector in groups)) throw Error('Unexpected rundown group: ' + selector);
              return groups[selector];
            };
            ['fabRundownData', 'fabRundownModes', 'fabRundownDisciplines',
             'fabRundownDiscipline', 'fabRundownChart'].forEach(id => ids[id] = new Element());
            ids.fabRundownData.textContent = JSON.stringify(modes.fabrication.disciplines.piping.charts);
            ids.fabRundownModes.textContent = JSON.stringify(modes);
            ids.fabRundownDisciplines.textContent = JSON.stringify(modes.fabrication.disciplines);
            ids.fabRundownDiscipline.value = 'piping';
            const skyline = new Element();
            skyline.dataset = {skylineSchedule: 'aveon', skylineView: 'compact'};
            skyline.textContent = 'Independent fabrication skyline';
            const skylineBefore = JSON.stringify(skyline);
            const document = {
              getElementById(id) {
                queries.push(id);
                if (id.startsWith('fabSkyline')) return skyline;
                if (!(id in ids)) throw Error('Unexpected document id: ' + id);
                return ids[id];
              },
              querySelector(selector) {
                queries.push(selector);
                if (selector === '[data-fab-skyline]') return skyline;
                if (selector !== '[data-fab-rundown]') throw Error('Unexpected document selector: ' + selector);
                return root;
              },
              createElement() { return new Element(); },
              createTextNode(text) { const node = new Element(); node.textContent = text; return node; }
            };
            const window = {
              innerWidth: 1000,
              getComputedStyle() { return {getPropertyValue() { return ''; }}; },
              matchMedia() { return {matches: true}; }
            };
            let liveChart = null, chartCount = 0, destroyedCount = 0, visibleCallback = null;
            class Chart {
              constructor(canvas, config) { this.config = config; liveChart = this; chartCount++; }
              destroy() { if (liveChart === this) liveChart = null; destroyedCount++; }
            }
            function c3WhenVisible(element, callback) {
              if (element !== root) throw Error('Rundown must observe its own card');
              visibleCallback = callback;
            }
            function chooseDiscipline(key) {
              ids.fabRundownDiscipline.value = key; ids.fabRundownDiscipline.fire('change');
            }
            function chooseMode(key) { buttons.find(button => button.dataset.rundownMode === key).fire('click'); }
            function state() {
              const config = liveChart && liveChart.config;
              const daily = config && config.data.datasets.find(dataset => dataset.metricKey === 'baselineDaily');
              return {
                mode: root.dataset.rundownMode, discipline: root.dataset.rundownDiscipline,
                selected: ids.fabRundownDiscipline.value, title: nodes['#fabRundownTitle'].textContent,
                scope: nodes['.is-scope dd'].textContent, source: nodes['.fab-rundown-source'].textContent,
                sampleHidden: nodes['#fabRundownSample'].hidden,
                notice: nodes['#fabRundownNotice'].textContent, noticeHidden: nodes['#fabRundownNotice'].hidden,
                summary: nodes['#fabRundownSummary'].textContent,
                emptyHidden: ids.fabRundownEmpty.hidden, error: ids.fabRundownEmpty.textContent,
                canvasHidden: ids.fabRundownChart.hidden,
                aria: ids.fabRundownChart.attributes['aria-label'],
                pressed: buttons.map(button => button.attributes['aria-pressed']),
                datasets: config ? config.data.datasets : [],
                dailyAxis: config && config.options.scales.yDaily.title.text,
                remainingMax: config && config.options.scales.yRemaining.suggestedMax,
                remainingStep: config && (config.options.scales.yRemaining.ticks.stepSize ?? null),
                dailyMax: config && (config.options.scales.yDaily.suggestedMax ?? null),
                dailyStep: config && (config.options.scales.yDaily.ticks.stepSize ?? null),
                dailyTooltip: config && config.options.plugins.tooltip.callbacks.label({
                  dataset: daily, parsed: {y: 1}
                }),
                chartCount: chartCount, destroyedCount: destroyedCount,
                skylineUnchanged: JSON.stringify(skyline) === skylineBefore,
                skylineAccessed: queries.some(query => /skyline/i.test(query))
              };
            }
        """
        program = "const modes = " + json.dumps(modes) + ";\n" + harness + "\n" + controller + "\n" + scenario
        result = subprocess.run(
            [node, "-"], input=program, capture_output=True, text=True,
            encoding="utf-8", timeout=10, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_imported_actual_progress_is_visible_and_clears_when_switching(self):
        result = self.run_controller(r"""
          const piping = modes.fabrication.disciplines.piping;
          piping.source.has_actual = true;
          piping.kpis.actual_progress_pct = 30;
          piping.charts.actual_rundown = [7, null];
          ids.fabRundownModes.textContent = JSON.stringify(modes);
          fabRundownInit(); visibleCallback();
          const actual = state();
          const progress = nodes['#fabRundownProgress'].textContent;
          const shown = groups['[data-rundown-actual]'].every(node => !node.hidden);
          chooseMode('installation');
          console.log(JSON.stringify({actual, progress, shown, next:state(), hidden:groups['[data-rundown-actual]'].every(node=>node.hidden)}));
        """)
        self.assertEqual(result["progress"], "30%")
        self.assertTrue(result["shown"])
        actual = next(ds for ds in result["actual"]["datasets"] if ds["metricKey"] == "actualRemaining")
        self.assertEqual([point["y"] for point in actual["data"]], [7, None])
        self.assertTrue(result["hidden"])
        self.assertFalse(any(ds["metricKey"] == "actualRemaining" for ds in result["next"]["datasets"]))

    def assert_skyline_untouched(self, state):
        self.assertTrue(state["skylineUnchanged"])
        self.assertFalse(state["skylineAccessed"])

    def test_default_is_real_fabrication_piping_with_original_curve(self):
        state = self.run_controller("fabRundownInit(); visibleCallback(); console.log(JSON.stringify(state()));")
        self.assertEqual((state["mode"], state["discipline"], state["selected"]), ("fabrication", "piping", "piping"))
        self.assertEqual(state["pressed"], ["true", "false"])
        self.assertEqual(state["scope"], "10 spools")
        self.assertEqual(state["title"], "Piping fabrication rundown")
        self.assertEqual(state["source"], "Source · DATAFY piping schedule")
        self.assertTrue(state["sampleHidden"])
        self.assertTrue(state["noticeHidden"])
        self.assertFalse(state["canvasHidden"])
        baseline = next(series for series in state["datasets"] if series["metricKey"] == "baselineRemaining")
        self.assertEqual([point["y"] for point in baseline["data"]], [10, 0])
        self.assertEqual(len(state["datasets"]), 4)
        self.assert_skyline_untouched(state)

    def test_mode_buttons_preserve_structural_and_restore_its_real_schedule(self):
        before, sample, after = self.run_controller("""
            fabRundownInit(); visibleCallback(); chooseDiscipline('structural'); const before = state();
            chooseMode('installation'); const sample = state();
            chooseMode('fabrication'); console.log(JSON.stringify([before, sample, state()]));
        """)
        self.assertEqual(before["scope"], "12 packages")
        self.assertEqual(len(before["datasets"]), 2)
        self.assertEqual((sample["mode"], sample["selected"]), ("installation", "structural"))
        self.assertEqual(sample["pressed"], ["false", "true"])
        self.assertEqual(sample["scope"], "32 packages")
        self.assertEqual(sample["title"], "Structural installation rundown")
        self.assertEqual(sample["source"], "Source · Sample data")
        self.assertFalse(sample["sampleHidden"])
        self.assertFalse(sample["noticeHidden"])
        self.assertIn("demonstration", sample["notice"])
        self.assertIn("Sample installation data", sample["summary"])
        self.assertIn("sample data", sample["aria"])
        self.assertNotEqual(before["datasets"], sample["datasets"])
        for key in ("mode", "selected", "title", "scope", "source", "datasets", "sampleHidden", "noticeHidden"):
            self.assertEqual(after[key], before[key], key)
        self.assertEqual(after["destroyedCount"], 3)
        self.assertEqual(after["chartCount"], 4)
        for state in (before, sample, after):
            self.assert_skyline_untouched(state)

    def test_empty_electrical_never_keeps_another_discipline_or_sample_curve(self):
        empty, sample, restored = self.run_controller("""
            fabRundownInit(); visibleCallback(); chooseDiscipline('electrical'); const empty = state();
            chooseMode('installation'); const sample = state();
            chooseMode('fabrication'); console.log(JSON.stringify([empty, sample, state()]));
        """)
        for state in (empty, restored):
            self.assertEqual((state["mode"], state["selected"]), ("fabrication", "electrical"))
            self.assertEqual(state["title"], "Electrical fabrication rundown")
            self.assertTrue(state["sampleHidden"])
            self.assertTrue(state["canvasHidden"])
            self.assertFalse(state["emptyHidden"])
            self.assertIn("No electrical fabrication schedule", state["error"])
            self.assertEqual(state["datasets"], [])
            self.assertNotIn("31", state["scope"])
            self.assert_skyline_untouched(state)
        self.assertEqual((sample["mode"], sample["selected"]), ("installation", "electrical"))
        self.assertEqual(sample["scope"], "31 circuits")
        self.assertFalse(sample["canvasHidden"])
        self.assertTrue(sample["emptyHidden"])
        self.assertFalse(sample["sampleHidden"])

    def test_installation_discipline_changes_keep_sample_context_and_completion_labels(self):
        states = self.run_controller("""
            fabRundownInit(); visibleCallback(); chooseMode('installation');
            const states = [state()];
            ['electrical', 'structural', 'piping'].forEach(key => { chooseDiscipline(key); states.push(state()); });
            console.log(JSON.stringify(states));
        """)
        self.assertEqual([state["scope"] for state in states], ["30 spools", "31 circuits", "32 packages", "30 spools"])
        for state in states:
            self.assertEqual(state["mode"], "installation")
            self.assertFalse(state["sampleHidden"])
            self.assertIn("Sample", state["notice"])
            self.assertIn("COMPLETIONS", state["dailyAxis"])
            self.assertNotIn("releases", state["dailyTooltip"].lower())
            self.assertNotIn("released", state["dailyTooltip"].lower())
            self.assert_skyline_untouched(state)
        self.assertEqual(states[0]["datasets"], states[-1]["datasets"])

    def test_latest_mode_and_discipline_are_used_when_deferred_chart_becomes_visible(self):
        before, rendered = self.run_controller("""
            fabRundownInit(); chooseMode('installation'); chooseDiscipline('electrical');
            const before = state(); visibleCallback(); console.log(JSON.stringify([before, state()]));
        """)
        self.assertEqual(before["chartCount"], 0)
        self.assertEqual(rendered["chartCount"], 1)
        self.assertEqual((rendered["mode"], rendered["selected"]), ("installation", "electrical"))
        self.assertEqual(rendered["scope"], "31 circuits")
        self.assertEqual(rendered["destroyedCount"], 0)
        self.assert_skyline_untouched(rendered)

    def test_installation_piping_scales_fit_its_own_scope_and_restore_ros_axes(self):
        real, sample, restored = self.run_controller("""
            fabRundownInit(); visibleCallback(); const real = state();
            chooseMode('installation'); const sample = state();
            chooseMode('fabrication'); console.log(JSON.stringify([real, sample, state()]));
        """)
        remaining = next(series for series in sample['datasets'] if series['metricKey'] == 'baselineRemaining')
        maximum = max(point['y'] for point in remaining['data'])
        self.assertGreaterEqual(sample['remainingMax'], maximum)
        self.assertLessEqual(sample['remainingMax'], maximum * 1.2)
        self.assertIsNone(sample['remainingStep'])
        self.assertIsNone(sample['dailyMax'])
        self.assertIsNone(sample['dailyStep'])
        for key in ('remainingMax', 'remainingStep', 'dailyMax', 'dailyStep'):
            self.assertEqual(restored[key], real[key])
        self.assertEqual(real['remainingMax'], 700)

    def test_import_refresh_preserves_selected_mode_and_discipline(self):
        updated = self.run_controller("""
            fabRundownInit(); visibleCallback(); chooseMode('installation'); chooseDiscipline('electrical');
            const payload = JSON.parse(JSON.stringify(modes.installation.disciplines.electrical));
            payload.kpis.scope_total = 99;
            root.listeners['rundown:updated'].forEach(fn => fn({detail: {'installation:electrical': payload}}));
            console.log(JSON.stringify(state()));
        """)
        self.assertEqual(updated["mode"], "installation")
        self.assertEqual(updated["selected"], "electrical")
        self.assertEqual(updated["scope"], "99 circuits")
        self.assert_skyline_untouched(updated)
