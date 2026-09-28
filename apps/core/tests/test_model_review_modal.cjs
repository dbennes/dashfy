const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../../../static/js/model-review-modal.js'), 'utf8');

function fixture() {
  let doc;
  class Element {
    constructor() {
      this.dataset = {}; this.attrs = {}; this.listeners = {}; this.children = [];
      this.classes = new Set(); this.values = {}; this.priorities = {};
      this.classList = {contains: key => this.classes.has(key), toggle: (key, value) => value ? this.classes.add(key) : this.classes.delete(key)};
      this.style = {getPropertyValue: key => this.values[key] || '', getPropertyPriority: key => this.priorities[key] || '',
        setProperty: (key, value, priority) => {this.values[key] = value; this.priorities[key] = priority || '';}};
    }
    addEventListener(type, callback, options) { (this.listeners[type] ||= []).push({callback, options}); }
    dispatchEvent(event) { for (const listener of this.listeners[event.type] || []) listener.callback(event); }
    setAttribute(key, value) { this.attrs[key] = value; }
    appendChild(child) {
      if (child.parent) child.parent.children.splice(child.parent.children.indexOf(child), 1);
      this.children.push(child); child.parent = this;
    }
    before(child) {const index = this.parent.children.indexOf(this); this.parent.children.splice(index, 0, child); child.parent = this.parent;}
    replaceWith(child) {
      if (child.parent) child.parent.children.splice(child.parent.children.indexOf(child), 1);
      this.parent.children[this.parent.children.indexOf(this)] = child; child.parent = this.parent; this.parent = null;
    }
    getBoundingClientRect() { return {height: 560, top: 100, bottom: 660}; }
    focus() {doc.activeElement = this;}
    get isConnected() {return true;}
  }
  const card = new Element(), original = new Element(), root = new Element(), canvas = new Element();
  const dialog = new Element(), expand = new Element(), close = new Element(), host = new Element(), tree = new Element(), query = new Element();
  const before = new Element(), after = new Element(), body = new Element();
  original.appendChild(before); original.appendChild(root); original.appendChild(after); root.appendChild(canvas);
  root.camera = {position: [2, 3, 4]}; root.selection = {id: 'pipe-42'};
  card.querySelector = selector => ({'[data-project-3d]': root, '[data-model-review-expand]': expand}[selector]);
  dialog.closest = () => card;
  dialog.querySelector = selector => ({'[data-model-review-dialog-body]': host, '[data-model-review-close]': close, '[data-model-review-tree-toggle]': tree}[selector]);
  root.querySelector = () => query;
  dialog.showModal = () => {dialog.open = true;};
  dialog.close = () => {dialog.open = false; dialog.dispatchEvent({type: 'close'});};
  doc = new Element(); Object.assign(doc, {body, readyState: 'complete', activeElement: expand, documentElement: {clientWidth: 980},
    createElement: () => new Element(), querySelectorAll: () => [dialog]});
  const win = new Element(); Object.assign(win, {innerWidth: 1000, innerHeight: 800, requestAnimationFrame: callback => callback(), getComputedStyle: () => ({paddingRight: '5px'})});
  const context = {document: doc, window: win, Event: class {constructor(type) {this.type = type;}},
    CustomEvent: class {constructor(type, init = {}) {this.type = type; this.detail = init.detail;}}};
  vm.runInNewContext(source, context);
  return {root, canvas, dialog, expand, close, original, before, after, host, tree, query, doc, body,
    click: el => el.dispatchEvent({type: 'click'})};
}

test('expanded review reuses the live canvas, selection and camera through repeated open/close', () => {
  const f = fixture(); const selection = f.root.selection; const camera = f.root.camera;
  const visibility = []; f.root.addEventListener('model-review:visibility', event => visibility.push(event.detail.expanded));
  for (let count = 0; count < 3; count++) {
    f.click(f.expand);
    assert.equal(f.root.parent, f.host); assert.equal(f.root.children[0], f.canvas);
    assert.equal(f.dialog.open, true); assert.equal(f.body.values.overflow, 'hidden');
    f.click(f.close);
    assert.deepEqual(f.original.children, [f.before, f.root, f.after]);
    assert.equal(f.root.selection, selection); assert.equal(f.root.camera, camera);
    assert.equal(f.root.children[0], f.canvas); assert.equal(f.doc.activeElement, f.expand);
  }
  assert.deepEqual(visibility, [true, false, true, false, true, false]);
});

test('restores existing body scroll styles and avoids duplicate handlers after panel remount', () => {
  const f = fixture();
  f.body.style.setProperty('overflow', 'auto', 'important'); f.body.style.setProperty('padding-right', '5px');
  f.doc.dispatchEvent({type: 'dashboard:panels-ready'});
  assert.equal(f.expand.listeners.click.length, 1);
  f.click(f.expand); assert.equal(f.body.values['padding-right'], '25px');
  f.click(f.close);
  assert.equal(f.body.values.overflow, 'auto'); assert.equal(f.body.priorities.overflow, 'important');
  assert.equal(f.body.values['padding-right'], '5px');
});

test('Escape is captured before canvas clear-selection and restores the viewer', () => {
  const f = fixture(); f.click(f.expand);
  let prevented = false, stopped = false;
  const handler = f.dialog.listeners.keydown[0]; assert.equal(handler.options, true);
  handler.callback({key: 'Escape', preventDefault() {prevented = true;}, stopPropagation() {stopped = true;}});
  assert.equal(prevented, true); assert.equal(stopped, true);
  assert.equal(f.dialog.open, false); assert.equal(f.root.parent, f.original);
  assert.equal(f.root.selection.id, 'pipe-42');
});

test('mobile tree remains operable and a failed dialog opening leaves inline review intact', () => {
  const f = fixture(); f.click(f.expand); f.click(f.tree);
  assert.equal(f.dialog.classList.contains('is-tree-open'), true); assert.equal(f.doc.activeElement, f.query);
  f.click(f.close); assert.equal(f.tree.attrs['aria-expanded'], 'false');
  f.dialog.showModal = () => {throw new Error('Dialog unavailable');}; f.click(f.expand);
  assert.equal(f.root.parent, f.original); assert.equal(f.body.values.overflow, '');
  assert.equal(f.expand.attrs['aria-expanded'], 'false');
});
