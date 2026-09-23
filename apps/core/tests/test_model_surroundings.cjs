const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const source = fs.readFileSync(path.join(__dirname, '../../../static/js/dashfy.js'), 'utf8');

async function harness() {
  const THREE = await import(pathToFileURL(path.join(__dirname, '../../../static/vendor/three/three.module.js')));
  // Imported GLB materials may already be transparent and double-sided.
  // Nearby context must override those flags without mutating the source.
  const original = new THREE.MeshStandardMaterial({
    color: 0xff0000, transparent: true, opacity: 0.28,
    depthWrite: false, depthTest: false, side: THREE.DoubleSide,
  });
  const model = new THREE.Group();
  model.add(new THREE.Mesh(new THREE.BoxGeometry(), original));
  model.add(new THREE.Mesh(new THREE.BoxGeometry(), [original, original]));
  const state = {THREE, model, scene: new THREE.Scene(), modelLoaded: true, currentModelMode: 'overview', surroundingsScale: 2,
    surroundings: true, surroundingsOriginals: [], surroundingsMaterials: new Map(), surroundingsHelper: null};
  const loads = [];
  const context = {state, selectedHierarchyNode: () => ({bbox: [0,0,0,2,2,2]}),
    boxFromBbox: () => new THREE.Box3(new THREE.Vector3(0,0,0), new THREE.Vector3(2,2,2)),
    modelUrls: {overview: '/overview.glb', detail: '/detail.glb'},
    loadModel: mode => {loads.push(mode);},
    applyIsolationVisibility() {}, setStatus() {}};
  vm.createContext(context);
  vm.runInContext(source.slice(source.indexOf('    const restoreSurroundings ='), source.indexOf('    const setIsolationMode =')) +
    '\nthis.update = updateSurroundings; this.restore = restoreSurroundings; this.setSurroundings = setSurroundings;', context);
  return {THREE, state, original, context, loads};
}

test('surrounding region has opaque exterior surfaces and clips only outside its box', async () => {
  const {THREE, state, original, context} = await harness();
  context.update();
  assert.equal(state.surroundingsMaterials.size, 1);
  const ghost = state.surroundingsMaterials.get(original);
  assert.equal(ghost.transparent, false);
  assert.equal(ghost.opacity, 1);
  assert.equal(ghost.depthWrite, true);
  assert.equal(ghost.depthTest, true);
  assert.equal(ghost.side, THREE.FrontSide);
  assert.equal(original.transparent, true);
  assert.equal(original.opacity, 0.28);
  assert.equal(original.depthWrite, false);
  assert.equal(original.depthTest, false);
  assert.equal(original.side, THREE.DoubleSide);
  assert.equal(original.color.getHex(), 0xff0000);
  assert.equal(original.clippingPlanes, null);
  assert.ok(ghost.clippingPlanes.every(plane => plane.distanceToPoint(new THREE.Vector3(1,1,1)) >= 0));
  for (const point of [[-100,1,1],[100,1,1],[1,-100,1],[1,100,1],[1,1,-100],[1,1,100]]) {
    assert.ok(ghost.clippingPlanes.some(plane => plane.distanceToPoint(new THREE.Vector3(...point)) < 0));
  }
});

test('adjusting the region reuses materials and restoring preserves original transparency', async () => {
  const {THREE, state, original, context} = await harness();
  let originalDisposed = false, cloneDisposed = false;
  original.addEventListener('dispose', () => { originalDisposed = true; });
  context.update();
  const ghost = state.surroundingsMaterials.get(original);
  ghost.addEventListener('dispose', () => { cloneDisposed = true; });
  const previousMax = state.surroundingsHelper.box.max.x;
  state.surroundingsScale = 5; context.update();
  assert.equal(state.surroundingsMaterials.get(original), ghost);
  assert.ok(state.surroundingsHelper.box.max.x > previousMax);
  context.restore();
  assert.equal(state.model.children[0].material, original);
  assert.equal(state.model.children[1].material[0], original);
  assert.equal(state.model.children[1].material[1], original);
  assert.equal(original.transparent, true);
  assert.equal(original.opacity, 0.28);
  assert.equal(original.depthWrite, false);
  assert.equal(original.depthTest, false);
  assert.equal(original.side, THREE.DoubleSide);
  assert.equal(original.clippingPlanes, null);
  assert.equal(cloneDisposed, true);
  assert.equal(originalDisposed, false);
  assert.equal(state.surroundingsMaterials.size, 0);
  assert.equal(state.surroundingsHelper, null);
});

test('clear markings retains selection and does not reframe or return to full model', () => {
  const node = {id: 'line-1', bbox: [0,0,0,1,1,1]};
  const state = {pickRequestId: 0, datafyRequestId: 0, selectedHierarchyId: node.id};
  let callback, selection;
  const context = {state, selectedHierarchyNode: () => node, setStatus() {},
    clearButton: {addEventListener: (event, fn) => {callback = fn;}},
    selectHierarchyNode: (item, origin) => {selection = {item, origin};}};
  vm.createContext(context);
  const start = source.indexOf("    clearButton?.addEventListener('click', () => {", source.indexOf('    surroundingsButton?.addEventListener'));
  vm.runInContext(source.slice(start, source.indexOf("    resetButton?.addEventListener", start)), context);
  callback();
  assert.equal(selection.item, node);
  assert.equal(selection.origin, 'viewer');
  assert.equal(state.selectedHierarchyId, node.id);
  assert.equal(state.isolateSelection, true);
});

test('showing overview surroundings requests detail on demand without reloading an already refined model', async () => {
  const {state, context, loads} = await harness();
  const overview = state.model;
  context.setSurroundings(false);
  assert.equal(state.surroundings, false);
  assert.deepEqual(loads, []);

  context.setSurroundings(true);
  assert.deepEqual(loads, ['detail']);
  assert.equal(state.surroundings, true);
  assert.equal(state.isolateSelection, true);
  assert.equal(state.model, overview);

  state.currentModelMode = 'detail';
  context.setSurroundings(true);
  assert.deepEqual(loads, ['detail']);
  context.setSurroundings(false);
  assert.equal(state.surroundings, false);
  assert.deepEqual(loads, ['detail']);

  state.currentModelMode = 'overview';
  context.modelUrls.detail = context.modelUrls.overview;
  context.setSurroundings(true);
  assert.deepEqual(loads, ['detail']);
});

test('exact selection geometry stays opaque and depth-tested with coplanar surface offset', async () => {
  const THREE = await import(pathToFileURL(path.join(__dirname, '../../../static/vendor/three/three.module.js')));
  const imported = new THREE.MeshStandardMaterial({
    transparent: true, opacity: 0.28, depthTest: false, depthWrite: false, side: THREE.DoubleSide,
  });
  const selectedScene = new THREE.Group();
  const mesh = new THREE.Mesh(new THREE.BoxGeometry(), [imported, imported]);
  selectedScene.add(mesh);
  const node = {id: 'selected-line', name: 'Selected line', bbox: [0,0,0,1,1,1]};
  let frames = 0;
  const state = {
    THREE, scene: new THREE.Scene(), selectionRequestId: 0, hierarchyByName: new Map(),
    hierarchyById: new Map(), isolateSelection: true,
    loader: {parse: (_buffer, _path, resolve) => resolve({scene: selectedScene})},
  };
  const context = {
    state, selectColor: {three: 0x3b82f6, emissive: 0x010812},
    selectionUrlFor: () => '/selected.glb',
    review: {fetchGeometry: async () => new ArrayBuffer(0)}, authNotice: null,
    showModelAuthError: () => false,
    fetch: async () => ({ok: true, arrayBuffer: async () => new ArrayBuffer(0)}),
    resetHighlights() {}, applyIsolationVisibility() {}, renderOnce() {}, setStatus() {},
    frameBox: () => {frames += 1;}, disposeObject() {},
  };
  vm.createContext(context);
  const materialSource = source.slice(source.indexOf('    const createOpaqueSelectionMaterial ='), source.indexOf('    const highlightObjects ='));
  const selectionSource = source.slice(source.indexOf('    const loadSelectionGeometry ='), source.indexOf('    const datafyItemNumber ='));
  vm.runInContext(materialSource + selectionSource + '\nthis.loadSelection = loadSelectionGeometry;', context);

  assert.equal(await context.loadSelection(node), true);
  assert.equal(state.selectionOverlay, selectedScene);
  assert.ok(state.scene.children.includes(selectedScene));
  assert.equal(mesh.userData.hierarchyNodeId, node.id);
  for (const material of mesh.material) {
    assert.notEqual(material, imported);
    assert.equal(material.transparent, false);
    assert.equal(material.opacity, 1);
    assert.equal(material.depthTest, true);
    assert.equal(material.depthWrite, true);
    assert.equal(material.side, THREE.FrontSide);
    assert.equal(material.polygonOffset, true);
    assert.ok(material.polygonOffsetFactor < 0);
    assert.ok(material.polygonOffsetUnits < 0);
  }
  assert.equal(imported.polygonOffset, false);
  assert.equal(imported.transparent, true);
  assert.equal(imported.opacity, 0.28);
  assert.equal(frames, 0);
});

test('DATAFY refinement retains focus overlays without reframing when requested', async () => {
  for (const frame of [false, undefined]) {
    const line = {id: 'line-1', bbox: [0,0,0,1,1,1]};
    const components = [{id: 'component-1', bbox: [0,0,0,0.5,0.5,0.5]}];
    const calls = {highlight: [], isolation: [], boxes: [], callouts: [], lines: [], components: []};
    let finish;
    const completed = new Promise(resolve => {finish = resolve;});
    const state = {modelLoaded: true, datafyLineNode: line, datafyComponentNodes: components};
    const context = {
      state,
      highlightHierarchyNode: (node, options) => calls.highlight.push({node, options}),
      setIsolationMode: (active, options) => calls.isolation.push({active, options}),
      createDatafyBoxOverlay: nodes => calls.boxes.push(nodes),
      createDatafyCallouts: (node, nodes, tokens) => calls.callouts.push({node, nodes, tokens}),
      loadSelectionGeometry: async node => {calls.lines.push(node); return true;},
      loadDatafyComponentGeometry: async nodes => {calls.components.push(nodes); return true;},
      setStatus: text => finish(text),
    };
    vm.createContext(context);
    vm.runInContext(source.slice(source.indexOf('    const renderDatafyFocusOverlays ='), source.indexOf('    const bboxVolume =')) +
      '\nthis.restoreFocus = renderDatafyFocusOverlays;', context);

    assert.equal(context.restoreFocus(line, components, ['VALVE'], '', {frame}), true);
    assert.match(await completed, /line surface.*VALVE surface/);
    assert.equal(calls.highlight[0].node, line);
    assert.equal(calls.highlight[0].options.frame, frame !== false);
    assert.equal(calls.isolation[0].active, true);
    assert.equal(calls.isolation[0].options.frame, frame !== false);
    assert.deepEqual(calls.boxes, [components, components]);
    assert.equal(calls.callouts[0].node, line);
    assert.equal(calls.callouts[0].nodes, components);
    assert.deepEqual(calls.lines, [line]);
    assert.deepEqual(calls.components, [components]);
  }
});
