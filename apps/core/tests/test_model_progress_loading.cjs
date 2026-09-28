const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const filename = path.join(__dirname, '../../../static/js/model-review.js');
const source = fs.readFileSync(filename, 'utf8');
const importStatement = "const {mergeGeometries} = await import('three/addons/utils/BufferGeometryUtils.js');";
assert.ok(source.includes(importStatement), 'keep the test seam limited to the Three module import');

async function until(predicate, description) {
  for (let attempt = 0; attempt < 1000; attempt++) {
    if (predicate()) return;
    await new Promise(resolve => setImmediate(resolve));
  }
  assert.fail(`Timed out waiting for ${description}`);
}

function line(id, status = 'started') {
  return {tag: `LINE-${id}`, status, nodes: [{id: String(id)}]};
}

function harness(t, lines) {
  const controller = new AbortController();
  const requests = [];
  const geometries = [];
  const materials = [];
  const scenes = [];
  const updates = [];
  const trianglesFor = id => Number(id) % 3 + 1;
  let promise, readyGroup, settled = false;

  class Geometry {
    constructor(triangles, kind = 'imported') {
      this.attributes = {position: {count: triangles * 3}, normal: {}, uv: {}};
      this.index = null;
      this.kind = kind;
      this.disposed = 0;
      geometries.push(this);
    }
    clone() { return new Geometry(this.attributes.position.count / 3, 'copy'); }
    toNonIndexed() { return this.clone(); }
    deleteAttribute(name) { delete this.attributes[name]; }
    clearGroups() {}
    applyMatrix4() {}
    computeVertexNormals() {}
    dispose() { this.disposed++; }
  }
  class Material {
    constructor(options) { this.options = options; this.disposed = 0; materials.push(this); }
    dispose() { this.disposed++; }
  }
  class Group {
    constructor() { this.children = []; this.userData = {}; }
    add(child) { this.children.push(child); }
    updateMatrixWorld() {}
    traverse(visitor) { visitor(this); this.children.forEach(child => child.traverse(visitor)); }
  }
  class Mesh {
    constructor(geometry, material) {
      this.geometry = geometry; this.material = material; this.isMesh = true;
      this.userData = {}; this.matrixWorld = {};
    }
    traverse(visitor) { visitor(this); }
  }

  const context = {
    window: {}, AbortController, setTimeout, clearTimeout,
    mergeGeometries(parts) {
      assert.ok(parts.length);
      assert.ok(parts.every(part => Object.keys(part.attributes).join(',') === 'position'));
      return new Geometry(parts.reduce((sum, part) => sum + part.attributes.position.count / 3, 0), 'merged');
    },
    fetch(url, options) {
      const id = /\/(\d+)\.glb/.exec(url)[1];
      return new Promise((resolve, reject) => {
        const request = {id, signal: options.signal, finished: false};
        const abort = () => { request.aborted = true; reject(Object.assign(new Error('Aborted'), {name: 'AbortError'})); };
        request.finish = status => {
          request.finished = true;
          options.signal.removeEventListener('abort', abort);
          const buffer = new ArrayBuffer(24);
          const header = new DataView(buffer);
          header.setUint32(0, 0x46546c67, true);
          header.setUint32(4, 2, true);
          header.setUint32(8, 24, true);
          header.setUint32(20, Number(id), true);
          resolve(new Response(buffer, {status, headers: {'content-type': 'model/gltf-binary'}}));
        };
        options.signal.addEventListener('abort', abort, {once: true});
        requests.push(request);
        if (options.signal.aborted) abort();
      });
    },
  };
  vm.createContext(context);
  vm.runInContext(source.replace(importStatement, 'const mergeGeometries = globalThis.mergeGeometries;'), context);
  const loader = {
    parse(buffer, base, resolve) {
      const id = new DataView(buffer).getUint32(20, true);
      const scene = new Group();
      // Two source meshes exercise per-node ranges as well as merged batches.
      const material = new Material({source: id});
      scene.add(new Mesh(new Geometry(trianglesFor(id)), material));
      scene.add(new Mesh(new Geometry(1), material));
      scenes.push(scene);
      resolve({scene});
    },
  };
  const api = {
    requests, geometries, materials, scenes, updates, controller, trianglesFor,
    get group() { return readyGroup; },
    get settled() { return settled; },
    start() {
      promise = context.window.DashfyModelReview.buildProgressLayer({
        THREE: {Group, Mesh, MeshStandardMaterial: Material}, loader, lines,
        selectionUrl: '/geometry/0.glb?detail=1', isCurrent: () => true,
        signal: controller.signal, onReady: group => { readyGroup = group; },
        onUpdate: (done, total) => updates.push({done, total}),
      });
      promise.then(() => { settled = true; }, () => { settled = true; });
      return promise;
    },
    async finish(id, status = 200) {
      await until(() => requests.some(request => request.id === String(id)), `request ${id}`);
      requests.find(request => request.id === String(id)).finish(status);
    },
  };
  t.after(async () => { controller.abort(); if (promise) await promise.catch(() => {}); });
  return api;
}

test('publishes the first colored line while later requests are still pending', async t => {
  const h = harness(t, [line(1), line(2, 'completed'), line(3)]);
  const pending = h.start();
  await until(() => h.requests.length === 2, 'two initial workers');
  assert.ok(h.group, 'onReady attaches the live group before a geometry download finishes');
  assert.equal(h.group.children.length, 0);
  await h.finish(1);
  await until(() => h.group.children.length === 1, 'the first visible line');
  assert.equal(h.settled, false);
  assert.equal(h.requests.find(request => request.id === '2').finished, false);
  assert.equal(h.group.children[0].userData.progressRanges[0].nodeId, '1');
  await h.finish(2);
  await h.finish(3);
  const result = await pending;
  assert.equal(result.group, h.group);
  assert.equal(result.cancelled, false);
  assert.equal(result.total, 3);
});

test('deduplicates exact node jobs and skips lines without started or completed fabrication', async t => {
  const h = harness(t, [line(1), line(1), {...line(2, 'completed'), nodes: [{id: '2'}, {id: '2'}]}, line(3, 'not_started'), line(4, 'unlinked')]);
  const pending = h.start();
  await h.finish(1);
  await h.finish(2);
  const result = await pending;
  assert.equal(result.total, 2);
  assert.deepEqual(h.requests.map(request => request.id).sort(), ['1', '2']);
  assert.equal(h.scenes.length, 2);
});

test('cancelling aborts pending fetches, stops new jobs and disposes the partial layer', async t => {
  const h = harness(t, Array.from({length: 6}, (_, index) => line(index + 1)));
  const pending = h.start();
  await h.finish(1);
  await until(() => h.group.children.length === 1 && h.requests.length === 3, 'visible line and replacement worker');
  h.controller.abort();
  const result = await pending;
  assert.equal(result.cancelled, true);
  assert.deepEqual(h.requests.map(request => request.id), ['1', '2', '3']);
  assert.ok(h.requests.filter(request => !request.finished).every(request => request.aborted));
  assert.equal(h.scenes.length, 1);
  assert.ok(h.geometries.every(geometry => geometry.disposed === 1));
  assert.ok(h.materials.every(material => material.disposed === 1), 'shared source material is disposed only once');
  assert.equal(h.updates.length, 1, 'no progress updates arrive after cancellation');
});

test('a failed line does not prevent other lines from loading', async t => {
  const h = harness(t, [line(1), line(2), line(3, 'completed')]);
  const pending = h.start();
  await h.finish(1, 500);
  await h.finish(2);
  await h.finish(3);
  const result = await pending;
  assert.deepEqual(Array.from(result.failures), ['1']);
  assert.equal(result.total, 3);
  assert.equal(result.cancelled, false);
  assert.deepEqual(h.group.children.flatMap(mesh => Array.from(mesh.userData.progressRanges, range => range.nodeId)).sort(), ['2', '3']);
  assert.deepEqual(h.updates.at(-1), {done: 3, total: 3});
});

test('the first successful line becomes visible even when the first download failed', async t => {
  const h = harness(t, Array.from({length: 10}, (_, index) => line(index + 1)));
  h.start();
  await h.finish(1, 500);
  await until(() => h.requests.length === 3, 'replacement after failure');
  await h.finish(2);
  await until(() => h.updates.length === 2, 'second completion');
  assert.equal(h.group.children.length, 1, 'do not wait for a full batch before the first visible line');
});

test('each merged mesh preserves local picking ranges across status groups and batch flushes', async t => {
  const h = harness(t, Array.from({length: 10}, (_, index) => line(index + 1, index % 2 ? 'completed' : 'started')));
  const pending = h.start();
  for (let id = 1; id <= 10; id++) {
    await h.finish(id);
    await until(() => h.updates.length >= id, `completion ${id}`);
  }
  await pending;
  const ids = [];
  assert.ok(h.group.children.length > 2, 'the layer contains more than one flush');
  for (const mesh of h.group.children) {
    let cursor = 0;
    const ranges = mesh.userData.progressRanges;
    assert.ok(ranges.length);
    for (const range of ranges) {
      ids.push(Number(range.nodeId));
      assert.equal(range.start, cursor, 'face indices restart at zero for every merged mesh');
      cursor += h.trianglesFor(range.nodeId) + 1;
      assert.equal(range.end, cursor, 'the range includes both source meshes for this exact node');
      const expectedColor = Number(range.nodeId) % 2 ? 0xf59e0b : 0x38bdf8;
      assert.equal(mesh.material.options.color, expectedColor);
    }
    assert.equal(cursor, mesh.geometry.attributes.position.count / 3);
  }
  assert.deepEqual(ids.sort((a, b) => a - b), Array.from({length: 10}, (_, index) => index + 1));
  assert.ok(h.geometries.filter(geometry => geometry.kind !== 'merged').every(geometry => geometry.disposed === 1));
  assert.ok(h.geometries.filter(geometry => geometry.kind === 'merged').every(geometry => geometry.disposed === 0));
});

test('expired authentication aborts remaining work and disposes already visible geometry', async t => {
  const h = harness(t, [line(1), line(2), line(3), line(4)]);
  const pending = h.start();
  const rejected = assert.rejects(pending, error => error.code === 'AUTH_REQUIRED');
  await h.finish(1);
  await until(() => h.group.children.length === 1 && h.requests.length === 3, 'visible line and outstanding worker');
  await h.finish(2, 401);
  await until(() => h.settled, 'auth failure without waiting for unrelated geometry');
  await rejected;
  assert.deepEqual(h.requests.map(request => request.id), ['1', '2', '3']);
  assert.equal(h.requests[2].aborted, true);
  assert.ok(h.geometries.every(geometry => geometry.disposed === 1));
  assert.ok(h.materials.every(material => material.disposed === 1));
});

function appearanceHarness(t) {
  const dashboardSource = fs.readFileSync(path.join(__dirname, '../../../static/js/dashfy.js'), 'utf8');
  const start = dashboardSource.indexOf('    const setAppearance = async mode => {');
  const end = dashboardSource.indexOf('    const setIsolationMode =', start);
  assert.ok(start !== -1 && end > start);
  const visibleGroups = new Set();
  const jobs = [];
  const calls = [];
  const state = {
    appearance: 'normal', appearanceRequest: 0, surroundings: false,
    modelLoaded: true, model: {}, progressLayer: null, progressJob: null,
    progressIncomplete: false, hierarchyItems: [{id: '1'}],
    scene: {add: group => visibleGroups.add(group), remove: group => visibleGroups.delete(group)},
  };
  const context = {
    AbortController, state, appearanceButtons: [], progressLegend: {hidden: true}, reviewStatus: {},
    modelUrls: {selection: '/geometry/0.glb'},
    review: {
      matchLines: lines => lines,
      buildProgressLayer(options) {
        const group = {children: [], visible: true};
        const job = {options, group};
        jobs.push(job);
        options.onReady(group);
        return new Promise(resolve => {
          job.finish = (failures = []) => resolve({group, failures, total: 1, cancelled: options.signal.aborted});
        });
      },
    },
    loadReview: async () => ({lines: [line(1)]}), loadHierarchy: async () => {},
    restoreSurroundings() {}, restoreProgressMaterials() {}, tintProgressBase() {},
    colorProgressSelection() {}, renderOnce() {}, showModelAuthError() { return false; },
    disposeObject(group) { group.disposed = true; },
    applyIsolationVisibility() { if (state.progressLayer) state.progressLayer.visible = state.appearance === 'progress'; },
  };
  vm.createContext(context);
  vm.runInContext(dashboardSource.slice(start, end) + '\nthis.setAppearance = setAppearance;', context);
  const set = mode => { const call = context.setAppearance(mode); calls.push(call); return call; };
  t.after(async () => {
    state.progressJob?.controller.abort();
    jobs.forEach(job => job.finish());
    await Promise.allSettled(calls);
  });
  return {context, state, jobs, visibleGroups, set};
}

test('repeated Progress activation preserves the active job during model refinement', async t => {
  const h = appearanceHarness(t);
  const pending = h.set('progress');
  await until(() => h.jobs.length === 1, 'initial progress job');
  const request = h.state.appearanceRequest;
  const job = h.state.progressJob;
  // Refinement replaces the base model while the independent exact layer loads.
  h.state.model = {quality: 'detail'};
  await h.set('progress');
  await h.set('progress');
  assert.equal(h.jobs.length, 1);
  assert.equal(h.state.progressJob, job);
  assert.equal(h.state.appearanceRequest, request);
  assert.equal(job.controller.signal.aborted, false);
  h.jobs[0].finish();
  await pending;
  assert.equal(h.state.progressJob, null);
});

test('Normal aborts an incomplete progress job and immediately removes its partial layer', async t => {
  const h = appearanceHarness(t);
  const pending = h.set('progress');
  await until(() => h.jobs.length === 1, 'progress job');
  const job = h.jobs[0];
  assert.ok(h.visibleGroups.has(job.group));
  await h.set('normal');
  assert.equal(job.options.signal.aborted, true);
  assert.equal(h.state.progressJob, null);
  assert.equal(h.state.progressLayer, null);
  assert.equal(h.visibleGroups.has(job.group), false);
  assert.equal(h.context.progressLegend.hidden, true);
  job.finish();
  await pending;
  assert.equal(h.state.progressLayer, null);
});

test('a completed progress layer is reused when switching back from Normal', async t => {
  const h = appearanceHarness(t);
  const pending = h.set('progress');
  await until(() => h.jobs.length === 1, 'progress job');
  const group = h.jobs[0].group;
  h.jobs[0].finish();
  await pending;
  await h.set('normal');
  assert.equal(group.visible, false);
  assert.equal(h.state.progressLayer, group);
  await h.set('progress');
  assert.equal(h.jobs.length, 1, 'completed geometry must not download again');
  assert.equal(h.state.progressLayer, group);
  assert.equal(group.visible, true);
  assert.equal(group.disposed, undefined);
});

test('a cancelled job finishing later cannot remove a newly started progress layer', async t => {
  const h = appearanceHarness(t);
  const oldPending = h.set('progress');
  await until(() => h.jobs.length === 1, 'first progress job');
  await h.set('normal');
  const newPending = h.set('progress');
  await until(() => h.jobs.length === 2, 'new progress job');
  const activeJob = h.state.progressJob;
  h.jobs[0].finish();
  await oldPending;
  assert.equal(h.state.progressLayer, h.jobs[1].group);
  assert.equal(h.state.progressJob, activeJob);
  assert.equal(h.visibleGroups.has(h.jobs[1].group), true);
  h.jobs[1].finish();
  await newPending;
  assert.equal(h.state.progressLayer, h.jobs[1].group);
});
