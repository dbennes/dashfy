const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../../../static/js/dashboard-loading.js'), 'utf8');

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}

async function until(predicate, message) {
  for (let count = 0; count < 100; count++) {
    if (predicate()) return;
    await new Promise(resolve => setImmediate(resolve));
  }
  assert.fail(message);
}

class Events {
  constructor() { this.listeners = new Map(); }
  addEventListener(type, callback, options = {}) {
    const listeners = this.listeners.get(type) || [];
    listeners.push({callback, once: options.once});
    this.listeners.set(type, listeners);
  }
  dispatchEvent(event) {
    const listeners = this.listeners.get(event.type) || [];
    this.listeners.set(event.type, listeners.filter(listener => !listener.once));
    listeners.forEach(listener => listener.callback(event));
  }
}

class Element extends Events {
  constructor(attributes = {}) {
    super();
    this.attrs = {...attributes};
    this.dataset = {};
    this.textContent = '';
    this.hidden = false;
    this.children = [];
    const classes = new Set();
    this.classList = {
      add: (...names) => names.forEach(name => classes.add(name)),
      remove: (...names) => names.forEach(name => classes.delete(name)),
      contains: name => classes.has(name),
    };
  }
  get attributes() { return Object.entries(this.attrs).map(([name, value]) => ({name, value})); }
  get childNodes() { return this.children; }
  get src() { return this.attrs.src || ''; }
  get type() { return this.attrs.type || ''; }
  get inert() { return Object.hasOwn(this.attrs, 'inert'); }
  set inert(value) { if (value) this.attrs.inert = ''; else delete this.attrs.inert; }
  setAttribute(name, value) { this.attrs[name] = value; }
  getAttribute(name) { return this.attrs[name] ?? null; }
  removeAttribute(name) { delete this.attrs[name]; }
  replaceChildren(...children) { this.children = children; }
  append(...children) { this.children.push(...children); }
  remove() { this.removed = true; }
  querySelector() { return null; }
}

function harness() {
  const requests = [], scripts = [], frames = [], events = [];
  const timers = new Map();
  let timerId = 0;
  const notes = deferred();
  const target = new Element({'data-loading': 'true', 'aria-busy': 'true', inert: ''});
  target.dataset.contentUrl = '/dashboard/content/';
  const status = new Element(), retry = new Element(), intro = new Element();
  const heading = new Element(), spinner = new Element(), shell = new Element({inert: ''});
  const body = new Element();
  body.classList.add('has-login-boot');
  let reloads = 0;
  const document = new Events();
  Object.assign(document, {
    readyState: 'complete', body,
    querySelector(selector) {
      const exact = new Map([
        ['[data-dashboard-target]', target], ['[data-dashboard-status]', status],
        ['[data-dashboard-retry]', retry], ['[data-dashboard-intro]', intro],
        ['[data-dashboard-heading]', heading], ['[data-dashboard-spinner]', spinner],
        ['.shell', shell], ['body > .shell', shell], ['[data-dashboard-boot]', intro],
      ]);
      return exact.get(selector) || null;
    },
    querySelectorAll(selector) { return selector === '.shell' ? [shell] : []; },
    createElement: () => new Element(),
    getElementById: () => null,
  });
  const dispatch = document.dispatchEvent.bind(document);
  document.dispatchEvent = event => { events.push(event.type); dispatch(event); };
  const window = new Events();
  window.dashfyNotesReady = Promise.resolve();
  document.addEventListener('dashboard:panels-ready', () => { window.dashfyPanelNotesReady = notes.promise; });
  const fragmentScript = new Element({src: '/static/js/dashboard-controls.js'});
  const panels = new Element();
  panels.children = [new Element()];
  const parsed = {
    body: {children: [panels]},
    querySelector: selector => selector === '[data-dashboard-panels]' ? panels : null,
    querySelectorAll: selector => selector === 'script' ? [fragmentScript] : [],
  };
  const context = {
    window, document, URL,
    location: {origin: 'http://dashboard.test', search: '?project=BN-EPC1', hash: '', reload() { reloads++; }},
    Event: class { constructor(type) { this.type = type; } },
    CustomEvent: class { constructor(type, options = {}) { this.type = type; this.detail = options.detail; } },
    DOMParser: class { parseFromString() { return parsed; } },
    setTimeout(callback, delay) { const id = ++timerId; timers.set(id, {callback, delay}); return id; },
    clearTimeout(id) { timers.delete(id); },
    requestAnimationFrame(callback) { frames.push(callback); },
    fetch(url, options) {
      const pending = deferred();
      requests.push({url, options, ...pending});
      return pending.promise;
    },
  };
  window.requestAnimationFrame = context.requestAnimationFrame;
  target.append = child => { target.children.push(child); if (child.src) scripts.push(child); };
  vm.createContext(context);
  vm.runInContext(source, context);
  return {
    requests, scripts, frames, events, notes, target, intro, heading, spinner, retry, body, shell, timers,
    document, get reloads() { return reloads; },
    respond(index = 0, options = {}) {
      requests[index].resolve({
        ok: options.ok !== false, redirected: !!options.redirected,
        headers: {get: () => options.header === undefined ? '1' : options.header},
        text: async () => 'dashboard fragment',
      });
    },
    frame() { assert.ok(frames.length, 'a rendering frame is pending'); frames.shift()(); },
  };
}

test('keeps the entry animation until fresh data, scripts, History and layout are ready', async () => {
  const h = harness();
  await until(() => h.requests.length === 1, 'dashboard data request starts');
  assert.equal(h.requests[0].options.cache, 'no-store');
  assert.equal(h.requests[0].url.search, '?project=BN-EPC1');
  assert.equal(h.body.classList.contains('has-login-boot'), true);
  assert.equal(h.shell.inert, true);
  h.intro.dispatchEvent({type: 'click'});
  for (const key of ['Escape', 'Enter', ' ']) h.intro.dispatchEvent({type: 'keydown', key});
  assert.equal(h.intro.removed, undefined, 'clicks and old skip keys cannot bypass data readiness');

  h.respond();
  await until(() => h.scripts.length === 1, 'dashboard control script is requested');
  assert.equal(h.intro.removed, undefined, 'data alone must not reveal uninitialised controls');
  h.scripts[0].onload();
  await until(() => h.events.includes('dashboard:panels-ready'), 'History is mounted');
  assert.equal(h.intro.removed, undefined, 'History is still pending');
  assert.equal(h.shell.inert, true);
  h.notes.resolve();
  await until(() => h.frames.length > 0, 'first chart layout frame');
  h.frame();
  await until(() => h.frames.length > 0, 'second chart layout frame');
  assert.equal(h.intro.removed, undefined, 'wait for layout before entry');
  h.frame();
  await until(() => h.events.includes('dashboard:ready'), 'dashboard is ready');
  assert.equal(h.intro.removed, true);
  assert.equal(h.shell.inert, false);
  assert.equal(h.target.inert, false);
  assert.equal(h.target.getAttribute('data-loading'), null);
  assert.equal(h.target.getAttribute('aria-busy'), 'false');
  assert.equal(h.body.classList.contains('has-login-boot'), false);
  assert.equal(h.body.classList.contains('login-boot-ready'), true);
});

test('a data failure stays behind the animation and retries without a partial dashboard', async () => {
  const h = harness();
  await until(() => h.requests.length === 1, 'first data request');
  h.respond(0, {ok: false});
  await until(() => h.retry.hidden === false && h.heading.textContent.includes('Unable'), 'retry is offered');
  assert.equal(h.intro.removed, undefined);
  assert.equal(h.shell.inert, true);
  assert.equal(h.body.classList.contains('has-login-boot'), true);
  assert.equal(h.events.includes('dashboard:ready'), false);
  h.retry.dispatchEvent({type: 'click'});
  h.retry.dispatchEvent({type: 'click'});
  await until(() => h.requests.length === 2, 'retry data request');
  assert.equal(h.requests.length, 2, 'a repeated click cannot start concurrent retries');
  assert.equal(h.reloads, 0);
  h.respond(1);
  await until(() => h.scripts.length === 1, 'controls after retry');
  h.scripts[0].onload();
  h.notes.resolve();
  await until(() => h.frames.length > 0, 'first retry layout frame');
  h.frame();
  await until(() => h.frames.length > 0, 'second retry layout frame');
  h.frame();
  await until(() => h.events.includes('dashboard:ready'), 'retry enters dashboard');
  assert.equal(h.events.filter(type => type === 'dashboard:ready').length, 1);
  assert.equal(h.scripts.length, 1, 'controls are initialised only once after successful retry');
  assert.equal(h.shell.inert, false);
});

test('a component failure offers reload and never exposes half-initialised panels', async () => {
  const h = harness();
  await until(() => h.requests.length === 1, 'data request');
  h.respond();
  await until(() => h.scripts.length === 1, 'control script request');
  h.scripts[0].onerror();
  await until(() => h.retry.textContent === 'Reload page', 'reload is offered');
  assert.equal(h.shell.inert, true);
  assert.equal(h.intro.removed, undefined);
  assert.equal(h.events.includes('dashboard:ready'), false);
  h.retry.dispatchEvent({type: 'click'});
  assert.equal(h.reloads, 1);
  assert.equal(h.requests.length, 1, 'a mounted partial fragment must not be initialised twice');
});

test('an expired session never mounts login HTML as dashboard data', async () => {
  const h = harness();
  await until(() => h.requests.length === 1, 'data request');
  h.respond(0, {redirected: true});
  await until(() => h.retry.hidden === false && h.heading.textContent.includes('Unable'), 'session error is displayed');
  assert.equal(h.scripts.length, 0);
  assert.equal(h.target.children.length, 0);
  assert.equal(h.shell.inert, true);
  assert.equal(h.events.includes('dashboard:ready'), false);
});

test('a History request that never returns offers recovery instead of waiting forever', async () => {
  const h = harness();
  await until(() => h.requests.length === 1, 'data request');
  h.respond();
  await until(() => h.scripts.length === 1, 'control script request');
  h.scripts[0].onload();
  await until(() => Array.from(h.timers.values()).some(timer => timer.delay === 20000), 'History deadline');
  const deadline = Array.from(h.timers.values()).find(timer => timer.delay === 20000);
  deadline.callback();
  await until(() => h.retry.textContent === 'Reload page', 'deadline recovery');
  assert.equal(h.intro.removed, undefined);
  assert.equal(h.shell.inert, true);
  assert.equal(h.events.includes('dashboard:ready'), false);
  assert.equal(h.frames.length, 0, 'entry is not scheduled after the History deadline');
});
