const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const read = name => fs.readFileSync(path.join(__dirname, '../../../static/js/', name), 'utf8');

test('3D download reports decoded bytes without percentages from compressed Content-Length', () => {
  const source = read('dashfy.js');
  const callback = source.slice(source.indexOf('event => {', source.indexOf('const gltf = await state.loader.loadAsync(url')),
    source.indexOf('\n        const replacingModel'));
  const statuses = [];
  const update = vm.runInNewContext(`(${callback.trim().replace(/\);$/, '')})`, {
    label: '3D fast preview', setStatus: value => statuses.push(value),
  });
  for (const event of [
    {loaded: 1.5 * 1024 * 1024, total: 1024 * 1024}, // 150% with the old formula
    {loaded: 2 * 1024 * 1024, total: 0}, // chunked response
    {loaded: 3 * 1024 * 1024, total: 3 * 1024 * 1024},
    {loaded: NaN, total: 100}, {loaded: Infinity, total: 100},
  ]) update(event);
  assert.deepEqual(statuses, [
    'Loading 3D fast preview... 1.5 MB received',
    'Loading 3D fast preview... 2.0 MB received',
    'Loading 3D fast preview... 3.0 MB received',
  ]);
});

function libraryHarness() {
  const source = read('vessel-tracking.js');
  const scripts = [], timers = new Map();
  let id = 0;
  const global = {
    document: {
      createElement: () => ({remove() { this.removed = true; }}),
      head: {appendChild: script => scripts.push(script)},
    },
    setTimeout: callback => { timers.set(++id, callback); return id; },
    clearTimeout: key => timers.delete(key),
  };
  const load = vm.runInNewContext(source.slice(source.indexOf('  var mapLibraryPromise'),
    source.indexOf('  function init(root)')) + '\nloadMapLibrary;', {global});
  return {load, global, scripts, timers};
}

test('map waits for its library and concurrent requests share one download', async () => {
  const h = libraryHarness();
  const pending = h.load('/static/vendor/leaflet/leaflet.hash.js');
  assert.equal(h.load('/static/vendor/leaflet/leaflet.hash.js'), pending);
  assert.equal(h.scripts.length, 1);
  assert.equal(h.scripts[0].src, '/static/vendor/leaflet/leaflet.hash.js');
  h.global.L = {map() {}};
  h.scripts[0].onload();
  await pending;
  await h.load('/static/vendor/leaflet/leaflet.hash.js');
  assert.equal(h.scripts.length, 1);
  assert.equal(h.timers.size, 0);
});

for (const failure of ['network', 'timeout', 'initialisation']) {
  test(`map can retry after ${failure} failure`, async () => {
    const h = libraryHarness();
    const pending = h.load('/leaflet.js');
    const rejected = assert.rejects(pending, /Map library/);
    if (failure === 'network') h.scripts[0].onerror();
    else if (failure === 'timeout') [...h.timers.values()][0]();
    else h.scripts[0].onload();
    await rejected;
    assert.equal(h.scripts[0].removed, true);
    assert.equal(h.timers.size, 0);
    const retry = h.load('/leaflet.js');
    h.global.L = {map() {}};
    h.scripts[1].onload();
    await retry;
    assert.equal(h.scripts.length, 2);
  });
}
