const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function harness() {
  const frames = new Map();
  let id = 0, renders = 0;
  const context = {
    document: {hidden: false, removeEventListener() {}},
    requestAnimationFrame(fn) { frames.set(++id, fn); return id; },
    cancelAnimationFrame(id) { frames.delete(id); },
    updateDatafyCallouts() {},
    state: {viewerVisible: true, renderFrame: null, scene: {}, camera: {},
      renderer: {render() { renders++; }, dispose() {}}, controls: {update() {}}},
  };
  vm.createContext(context);
  return {context, frames, renders: () => renders, tick() {
    const current = [...frames];
    frames.clear();
    current.forEach(([, fn]) => fn());
  }};
}

function project() {
  const h = harness();
  const source = fs.readFileSync(path.join(__dirname, '../../../static/js/dashfy.js'), 'utf8').replace(/\r\n/g, '\n');
  vm.runInContext(source.slice(source.indexOf('    const startRenderLoop ='),
    source.indexOf('    const requestIdle =')) +
    '\nthis.draw = renderOnce; this.stop = stopRenderLoop;', h.context);
  return h;
}

test('idle project renders once and coalesces repeated changes', () => {
  const h = project();
  h.context.draw(); h.context.draw(); h.context.draw();
  assert.equal(h.frames.size, 1);
  h.tick();
  assert.equal(h.renders(), 1);
  assert.equal(h.frames.size, 0);
});

test('camera damping continues until changes stop, then rendering sleeps', () => {
  const h = project();
  let changes = 3;
  h.context.state.controls.update = () => { if (changes-- > 0) h.context.draw(); };
  h.context.draw();
  for (let i = 0; i < 10; i++) h.tick();
  assert.equal(h.renders(), 4);
  assert.equal(h.frames.size, 0);
});

test('offscreen and hidden project does no rendering and can resume', () => {
  const h = project();
  h.context.state.viewerVisible = false; h.context.draw();
  assert.equal(h.frames.size, 0);
  h.context.state.viewerVisible = true; h.context.draw();
  h.context.document.hidden = true; h.tick();
  assert.equal(h.renders(), 0);
  h.context.document.hidden = false; h.context.draw(); h.tick();
  assert.equal(h.renders(), 1);
  h.context.draw(); h.context.stop();
  assert.equal(h.frames.size, 0);
});

test('vessel rotates automatically, yields to dragging and pauses when hidden or closed', () => {
  const h = harness();
  const source = fs.readFileSync(path.join(__dirname, '../../../static/js/vessel-hologram.js'), 'utf8').replace(/\r\n/g, '\n');
  const start = source.indexOf('class Hologram {');
  const end = source.indexOf('\n}\n', start) + 2;
  vm.runInContext(source.slice(start, end) + '\nthis.Hologram = Hologram;', h.context);
  const view = new h.context.Hologram({removeEventListener() {}}, {});
  Object.assign(view, {alive: true, orbit: {yaw: 0, pitch: 0, distance: 7},
    camera: {position: {set() {}}, lookAt() {}}, renderer: h.context.state.renderer});
  view.loop(); view.loop(); h.tick();
  assert.equal(h.renders(), 1);
  assert.equal(h.frames.size, 1);
  assert.ok(view.orbit.yaw > 0);
  view.orbit.yaw = 1; view.orbit.dragging = true; view.loop(); h.tick();
  assert.equal(view.orbit.yaw, 1);
  assert.equal(h.renders(), 2);
  h.context.document.hidden = true; h.tick(); view.loop();
  assert.equal(h.frames.size, 0);
  h.context.document.hidden = false; view.loop(); view.stop(); h.tick();
  assert.equal(h.renders(), 2);
});
