/* The dossier module must initialise and open on demand.
 *
 * It has broken twice during refactors: a function removed while still called
 * made initDossier throw, so the "vt:open-dossier" listener was never
 * registered and clicking a vessel silently did nothing. Neither `node --check`
 * nor the Python suite can see that, because the failure is a runtime
 * ReferenceError inside a browser-only code path.
 *
 * A hand-rolled DOM keeps this dependency-free; it only needs to be faithful
 * enough for the module to wire itself up.
 *
 *   node --test apps/core/tests/test_vessel_dossier_boot.mjs
 */
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));
const MODULE = path.resolve(here, "../../../static/js/vessel-hologram.js");
const TEMPLATE = path.resolve(here, "../../../templates/vessels/_dashboard.html");

/** Every data-vh-* hook the template declares, so querySelector can serve them. */
function hooksInTemplate() {
  const html = readFileSync(TEMPLATE, "utf8");
  return new Set([...html.matchAll(/data-vh-([a-z-]+)/g)].map((m) => m[1]));
}

function makeElement(name = "div") {
  const listeners = new Map();
  return {
    nodeName: name,
    hidden: true,
    disabled: false,
    textContent: "",
    children: [],
    value: "",
    style: {},
    dataset: {},
    files: [],
    elements: {},
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    listeners,
    addEventListener(type, fn) { listeners.set(type, [...(listeners.get(type) || []), fn]); },
    removeEventListener() {},
    dispatchEvent(event) {
      // Surface listener errors: a browser would swallow them, and a swallowed
      // error here is exactly the failure this file exists to catch.
      (listeners.get(event.type) || []).forEach((fn) => fn(event));
      return true;
    },
    contains: () => false,
    appendChild(child) { this.children.push(child); return child; },
    replaceChildren(...children) { this.children = children; },
    remove() {},
    focus() {},
    setAttribute() {},
    getAttribute: () => null,
    querySelector: () => null,
    querySelectorAll: () => [],
    getBoundingClientRect: () => ({ top: 0, left: 0, width: 300, height: 200, bottom: 200, right: 300 }),
    scrollIntoView() {},
    click() {},
  };
}

function buildDom() {
  const hooks = hooksInTemplate();
  const nodes = new Map();
  for (const hook of hooks) nodes.set(hook, makeElement());

  const root = makeElement("section");
  root.dataset.apiBase = "/vessels/api/";
  root.dataset.vesselModel = "";
  root.querySelector = (selector) => {
    const match = /\[data-vh-([a-z-]+)\]/.exec(selector);
    return match ? nodes.get(match[1]) || null : null;
  };
  root.querySelectorAll = () => [];

  const document = {
    readyState: "complete",
    body: makeElement("body"),
    documentElement: makeElement("html"),
    createElement: (tag) => makeElement(tag),
    createElementNS: (_ns, tag) => makeElement(tag),
    createTextNode: (value) => ({ nodeName: "#text", textContent: String(value) }),
    addEventListener() {},
    querySelector: (s) => (s === "[data-vessel-tracking]" ? root : root.querySelector(s)),
    querySelectorAll: (s) => (s === "[data-vessel-tracking]" ? [root] : []),
  };

  class FakeEvent {
    constructor(type, init = {}) { this.type = type; this.detail = init.detail; this.target = null; }
  }

  return { root, nodes, document, FakeEvent };
}

function install() {
  const dom = buildDom();
  globalThis.document = dom.document;
  globalThis.CustomEvent = dom.FakeEvent;
  globalThis.window = globalThis;
  globalThis.requestAnimationFrame = (fn) => setTimeout(fn, 0);
  globalThis.ResizeObserver = class { observe() {} disconnect() {} };
  globalThis.fetch = async () => ({ ok: true, json: async () => ({ containers: [], totals: {} }) });
  return dom;
}

const VESSEL = {
  id: 1, name: "EASTERN URSINIA", mmsi: "636023616", imo: "9698458",
  status: "STALE", vessel_type: "OSV", destination: "AVEON", draught: null, eta: {},
  last_position: {
    latitude: 4.79425, longitude: 6.94176, source: "AIS",
    timestamp: "2026-09-16T14:57:03Z", sog: 0, cog: 85, heading: 154,
  },
};

/* One import, one assertion pass: the module registers globals at import time,
   so importing it twice in a process would leave the second instance bound to
   the first DOM. */
test("the dossier initialises and opens when the map asks for it", async () => {
  const dom = install();
  // A ReferenceError here means something is called but no longer defined.
  await import(pathToFileURL(MODULE).href);

  assert.ok(dom.root.listeners.has("vt:open-dossier"),
    "initDossier must register the vt:open-dossier listener; if it threw, it never got this far");

  dom.root.dispatchEvent(new dom.FakeEvent("vt:open-dossier", { detail: VESSEL }));
  await new Promise((resolve) => setTimeout(resolve, 20));

  assert.equal(dom.nodes.get("overlay").hidden, false, "the overlay must be revealed");
  assert.equal(dom.nodes.get("name").textContent, "EASTERN URSINIA");
  assert.match(dom.nodes.get("subtitle").textContent, /636023616/);

  const facts = () => Object.fromEntries(dom.nodes.get("facts").children.map(
    cell => [cell.children[0].textContent, cell.children[1].textContent]));
  const port = { name: "AVEON JETTY PH" };
  dom.root.dispatchEvent(new dom.FakeEvent("vt:open-dossier", { detail: {
    ...VESSEL, voyage: { status: "arrived", current_port: port, destination: port, origin: null,
      next_destination: { name: "BONGA NORTH" } },
  } }));
  assert.equal(facts()["Voyage status"], "Arrived · AVEON JETTY PH");
  assert.equal(facts()["Arrival location"], "AVEON JETTY PH");
  assert.equal(facts()["Next destination"], "BONGA NORTH");
  assert.equal(facts()["ETA"], "—");

  dom.root.dispatchEvent(new dom.FakeEvent("vt:open-dossier", { detail: {
    ...VESSEL, voyage: { status: "underway", current_port: null, destination: null, origin: port },
  } }));
  assert.equal(facts()["Origin"], "AVEON JETTY PH");
  assert.equal(facts()["Destination"], "Next destination not reported");
  assert.equal(facts()["Voyage status"], "Underway");

  dom.root.dispatchEvent(new dom.FakeEvent("vt:open-dossier", { detail: {
    ...VESSEL, voyage: { status: "underway", destination: { name: "BONGA" }, origin: port },
  } }));
  assert.equal(facts()["Destination"], "BONGA");

  dom.root.dispatchEvent(new dom.FakeEvent("vt:open-dossier", { detail: {
    ...VESSEL, eta: { month: 9, day: 18, hour: 14, minute: 0 },
    voyage: { status: "underway", destination: { name: "BONGA NORTH" }, origin: port,
      destination_source: "scheduled_route" },
  } }));
  assert.equal(facts()["Destination"], "BONGA NORTH");
  assert.equal(facts()["ETA"], "—", "an ETA declared for another target is not a regular-route ETA");
});

test("every data-vh hook the module queries exists in the template", () => {
  const source = readFileSync(MODULE, "utf8");
  const hooks = hooksInTemplate();
  const queried = new Set([...source.matchAll(/q\("([a-z-]+)"\)/g)].map((m) => m[1]));
  const missing = [...queried].filter((name) => !hooks.has(name));
  assert.deepEqual(missing, [], `module queries hooks absent from the template: ${missing.join(", ")}`);
});

test("cargo text is never written as markup", () => {
  const source = readFileSync(MODULE, "utf8");
  // Trackfy rows are uploaded content; they must only ever become text nodes.
  assert.equal(/\.innerHTML\s*=/.test(source), false, "no innerHTML assignment is allowed in the dossier");
});
