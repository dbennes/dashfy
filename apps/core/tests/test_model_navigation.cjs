const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const source = fs.readFileSync(path.join(__dirname, '../../../static/js/dashfy.js'), 'utf8');

function gestures() {
  const listeners = {}, picks = [], actions = [];
  let now = 100;
  const canvas = { addEventListener(name, fn) { listeners[name] = fn; }, focus() {}, classList: {add() {}, remove() {}} };
  const context = { state: {pickRequestId: 0}, performance: {now: () => now}, console,
    handleViewerClick: async event => picks.push(event), setStatus() {},
    focusSelection: () => actions.push('focus'), setNavigationMode: mode => actions.push(mode),
    fitButton: {click: () => actions.push('fit')}, clearButton: {click: () => actions.push('clear')} };
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('    const bindViewerGestures ='), source.indexOf('    const ensureViewer =')) + '\nthis.bind = bindViewerGestures;', context);
  context.bind(canvas);
  return {picks, actions, emit(name, extras = {}) {
    now += 20;
    listeners[name]({pointerId: 1, button: 0, clientX: 10, clientY: 10, preventDefault() {}, ...extras});
  }};
}
test('click selects; second click requests explicit focus', () => {
  const h = gestures();
  h.emit('pointerdown'); h.emit('pointerup');
  h.emit('pointerdown'); h.emit('pointerup');
  assert.equal(h.picks.length, 2);
  assert.equal(h.picks[0].focusSelection, false);
  assert.equal(h.picks[1].focusSelection, true);
});
test('drag returning to its starting point never selects', () => {
  const h = gestures();
  h.emit('pointerdown'); h.emit('pointermove', {clientX: 80});
  h.emit('pointermove'); h.emit('pointerup');
  assert.equal(h.picks.length, 0);
});
test('right/middle drag and modifier clicks never select', () => {
  for (const extras of [{button: 1}, {button: 2}, {shiftKey: true}, {ctrlKey: true}]) {
    const h = gestures(); h.emit('pointerdown', extras); h.emit('pointerup', extras);
    assert.equal(h.picks.length, 0);
  }
});
test('two fingers and cancelled gestures never select and next tap recovers', () => {
  const h = gestures();
  h.emit('pointerdown'); h.emit('pointerdown', {pointerId: 2});
  h.emit('pointerup', {pointerId: 2}); h.emit('pointerup');
  h.emit('pointerdown'); h.emit('pointercancel'); h.emit('pointerup');
  assert.equal(h.picks.length, 0);
  h.emit('pointerdown'); h.emit('pointerup');
  assert.equal(h.picks.length, 1);
});
test('keyboard shortcuts operate only on the focused canvas', () => {
  const h = gestures();
  for (const key of ['f', 'Home', 'Escape', 'p', 'r']) h.emit('keydown', {key});
  h.emit('keydown', {key: 'f', ctrlKey: true});
  assert.deepEqual(h.actions, ['focus', 'fit', 'clear', 'pan', 'orbit']);
});
