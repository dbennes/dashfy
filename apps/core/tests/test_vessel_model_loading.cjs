const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.join(__dirname, '../../../static/js/vessel-hologram.js'), 'utf8');
const hologramClass = source.slice(source.indexOf('class Hologram {'), source.indexOf('/* --------------------------------------------------------------- panel */'));

function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function element() {
  return {
    dataset: {}, attributes: {}, hidden: true, textContent: '', children: [],
    clientWidth: 340, clientHeight: 420, listeners: new Map(),
    appendChild(child) { this.children.push(child); return child; },
    setAttribute(name, value) { this.attributes[name] = value; },
    addEventListener(name, listener) { this.listeners.set(name, listener); },
    removeEventListener(name) { this.listeners.delete(name); },
    remove() {},
  };
}

function ui() {
  const mount = element(), note = element(), loading = element();
  const message = element(), retry = element();
  loading.querySelector = selector => ({
    '[data-vh-model-message]': message,
    '[data-vh-model-retry]': retry,
  })[selector] || null;
  return { mount, note, loading, message, retry };
}

function harness(options = {}) {
  const frames = new Map(), renders = [], modelRequests = [], renderers = [];
  let nextFrame = 1, libraryRequests = 0;
  class Vector {
    set(x, y, z) { Object.assign(this, { x, y, z }); return this; }
  }
  class Group {
    constructor() { this.position = new Vector(); this.children = []; }
    add(child) { this.children.push(child); }
    remove(child) { this.children = this.children.filter(item => item !== child); }
    traverse(fn) { fn(this); this.children.forEach(child => child.traverse?.(fn)); }
  }
  class Renderer {
    constructor() {
      if (options.webglError) throw new Error('WebGL unavailable');
      this.domElement = element(); renderers.push(this);
    }
    setPixelRatio() {} setClearColor() {} setSize() {}
    render(scene, camera) { renders.push({ scene, camera }); }
    dispose() { this.disposed = true; }
  }
  const THREE = {
    Group, Scene: Group, HemisphereLight: Group, DirectionalLight: Group,
    WebGLRenderer: Renderer,
    PerspectiveCamera: class {
      constructor(fov) { this.fov = fov; this.position = new Vector(); }
      lookAt() {} updateProjectionMatrix() {}
    },
    Box3: class {
      setFromObject() { return this; }
      getBoundingSphere(sphere) { sphere.radius = 1; return sphere; }
    },
    Sphere: class {}, MathUtils: { degToRad: degrees => degrees * Math.PI / 180 },
  };
  const context = {
    THREE, MODEL_STATE: { loading: null, url: null },
    loadThree() { libraryRequests += 1; return options.loadThree?.() || Promise.resolve(THREE); },
    loadModel(url) {
      const pending = deferred(); modelRequests.push({ url, ...pending }); return pending.promise;
    },
    frameObject: object => object,
    document: { hidden: false, addEventListener() {}, removeEventListener() {} },
    performance: { now: () => 1000 },
    ResizeObserver: class { observe() {} disconnect() {} },
    requestAnimationFrame(callback) { const id = nextFrame++; frames.set(id, callback); return id; },
    cancelAnimationFrame(id) { frames.delete(id); },
  };
  vm.createContext(context);
  vm.runInContext(hologramClass + '\nthis.Hologram = Hologram;', context);
  return {
    ...context, frames, renders, modelRequests, renderers,
    get libraryRequests() { return libraryRequests; },
    instance(nodes = ui()) { return { viewer: new context.Hologram(nodes.mount, nodes.note, nodes.loading), ...nodes }; },
    vessel() { const object = new Group(); return { clone: () => object, object }; },
    frame() {
      const [id, callback] = frames.entries().next().value;
      frames.delete(id); callback();
    },
  };
}

const flush = () => new Promise(resolve => setImmediate(resolve));

test('loading appears before Three loads; no schematic or animation runs while the real vessel is pending', async () => {
  const library = deferred();
  const env = harness({ loadThree: () => library.promise });
  const { viewer, mount, loading, message, retry } = env.instance();
  const started = viewer.start('/vessel.glb');
  assert.equal(loading.hidden, false);
  assert.match(message.textContent, /loading vessel model/i);
  assert.equal(mount.attributes['aria-busy'], 'true');
  assert.equal(retry.hidden, true);
  assert.equal(env.renderers.length, 0);

  library.resolve();
  await flush();
  assert.equal(env.modelRequests.length, 1);
  assert.equal(viewer.model, undefined, 'there must be no tube or other substitute model');
  assert.equal(env.frames.size, 0, 'the empty viewer must not consume animation frames');
  viewer.resize(); viewer.onVisibility();
  assert.equal(env.frames.size, 0, 'resize and visibility events cannot start an empty render loop');

  const vessel = env.vessel();
  env.modelRequests[0].resolve(vessel);
  await started;
  assert.equal(viewer.model, vessel.object);
  assert.equal(viewer.hasModel, true);
  assert.equal(loading.hidden, true);
  assert.equal(mount.attributes['aria-busy'], 'false');
  assert.equal(env.frames.size, 1);
  const yaw = viewer.orbit.yaw;
  env.frame();
  assert.equal(env.renders.length, 1);
  assert.ok(viewer.orbit.yaw > yaw, 'automatic rotation resumes with the actual vessel');
  viewer.stop();
  assert.equal(env.frames.size, 0);
});

test('a failed model offers retry and a replacement viewer can finish successfully', async () => {
  const env = harness(), nodes = ui();
  const first = env.instance(nodes).viewer;
  const started = first.start('/vessel.glb');
  await flush();
  env.modelRequests[0].reject(new Error('download failed'));
  await started;
  assert.equal(nodes.loading.hidden, false);
  assert.equal(nodes.mount.dataset.modelState, 'error');
  assert.equal(nodes.retry.hidden, false);
  assert.equal(nodes.mount.attributes['aria-busy'], 'false');
  assert.equal(env.frames.size, 0);

  first.stop();
  const retry = env.instance(nodes).viewer;
  const retried = retry.start('/vessel.glb');
  assert.equal(nodes.retry.hidden, true);
  await flush();
  assert.equal(env.modelRequests.length, 2, 'the rejected download must not be reused');
  env.modelRequests[1].resolve(env.vessel());
  await retried;
  assert.equal(nodes.loading.hidden, true);
  assert.equal(nodes.mount.dataset.modelState, 'ready');
  retry.stop();
});

test('closing during Three loading prevents its late failure from replacing a newer loading state', async () => {
  const oldLibrary = deferred(), newLibrary = deferred();
  let attempt = 0;
  const env = harness({ loadThree: () => (++attempt === 1 ? oldLibrary : newLibrary).promise });
  const nodes = ui(), oldViewer = env.instance(nodes).viewer;
  const oldStart = oldViewer.start('/vessel.glb');
  oldViewer.stop();
  const newViewer = env.instance(nodes).viewer;
  const newStart = newViewer.start('/vessel.glb');
  oldLibrary.reject(new Error('late library failure'));
  await oldStart;
  assert.equal(nodes.mount.dataset.modelState, 'loading');
  assert.equal(nodes.retry.hidden, true);
  assert.equal(env.renderers.length, 0);
  newViewer.stop();
  newLibrary.resolve();
  await newStart;
  assert.equal(env.renderers.length, 0, 'a closed viewer must never initialise WebGL');
});

test('reopening shares the pending real model while the closed instance cannot attach it', async () => {
  const env = harness(), nodes = ui();
  const oldViewer = env.instance(nodes).viewer;
  const oldStart = oldViewer.start('/vessel.glb');
  await flush();
  oldViewer.stop();
  const newViewer = env.instance(nodes).viewer;
  const newStart = newViewer.start('/vessel.glb');
  await flush();
  assert.equal(env.modelRequests.length, 1);
  env.modelRequests[0].resolve(env.vessel());
  await Promise.all([oldStart, newStart]);
  assert.equal(oldViewer.model, undefined);
  assert.equal(newViewer.hasModel, true);
  assert.equal(nodes.mount.dataset.modelState, 'ready');
  assert.equal(env.frames.size, 1);
  assert.equal(env.renderers[0].disposed, true);
  newViewer.stop();
});

test('an older rejected URL cannot clear the newer model request or alter its UI', async () => {
  const env = harness(), nodes = ui();
  const oldViewer = env.instance(nodes).viewer;
  const oldStart = oldViewer.start('/old.glb');
  await flush();
  oldViewer.stop();
  const newViewer = env.instance(nodes).viewer;
  const newStart = newViewer.start('/new.glb');
  await flush();
  const pending = env.MODEL_STATE.loading;
  env.modelRequests[0].reject(new Error('old download failure'));
  await oldStart;
  assert.equal(env.MODEL_STATE.loading, pending);
  assert.equal(nodes.mount.dataset.modelState, 'loading');
  env.modelRequests[1].resolve(env.vessel());
  await newStart;
  assert.equal(nodes.mount.dataset.modelState, 'ready');
  newViewer.stop();
});

test('missing model URL and unavailable WebGL show bounded fallback states without animation', async () => {
  const missing = harness(), noModel = missing.instance();
  await noModel.viewer.start('');
  assert.equal(missing.libraryRequests, 0);
  assert.equal(noModel.mount.dataset.modelState, 'unavailable');
  assert.equal(noModel.retry.hidden, true);
  assert.equal(noModel.mount.attributes['aria-busy'], 'false');
  assert.equal(missing.frames.size, 0);

  const blocked = harness({ webglError: true }), noWebGL = blocked.instance();
  await noWebGL.viewer.start('/vessel.glb');
  assert.equal(noWebGL.mount.dataset.modelState, 'error');
  assert.equal(noWebGL.retry.hidden, false);
  assert.equal(noWebGL.mount.attributes['aria-busy'], 'false');
  assert.equal(blocked.modelRequests.length, 0);
  assert.equal(blocked.frames.size, 0);
});
