const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');
const context = {window: {}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(__dirname, '../../../static/js/model-review.js'), 'utf8'), context);
const review = context.window.DashfyModelReview;
const hierarchy = [{id:'1', name:'/4"-DN-123-STD-H', bbox:[0,0,0,1,1,1], depth:5},
  {id:'2', name:'/4"-DN-123-STD-H/B1', bbox:[0,0,0,1,1,1], depth:6},
  {id:'3', name:'/BN-MR2-INST', bbox:[0,0,0,1,1,1], depth:3}];
const payload = {available:true, drawings:[{id:'1',name:'DWG <1>',discipline:'piping',lines:['4"-DN-123-STD-H'],status:'started'}],
  lines:[{tag:'4"-DN-123-STD-H',status:'started'}]};
test('geometry loader rejects expired sessions, legacy login HTML and corrupt binary before parsing', async () => {
  for (const response of [
    {status:401,ok:false,url:'/model-node/1.glb'},
    {status:200,ok:true,url:'http://127.0.0.1:9000/accounts/login/?next=/model-node/1.glb'},
  ]) {
    context.fetch = async () => response;
    await assert.rejects(review.fetchGeometry('/model-node/1.glb'), error => error.code === 'AUTH_REQUIRED');
  }
  context.fetch = async () => new Response('<!DOCTYPE html><html>login</html>', {headers:{'content-type':'text/html'}});
  await assert.rejects(review.fetchGeometry('/model-node/1.glb'), /web page instead/);
  context.fetch = async () => new Response(new Uint8Array([1,2,3]), {headers:{'content-type':'model/gltf-binary'}});
  await assert.rejects(review.fetchGeometry('/model-node/1.glb'), /Invalid or incomplete/);
});
test('geometry fetch bypasses cached login pages and sends the current session cookie', async () => {
  const buffer = new ArrayBuffer(24), header = new DataView(buffer);
  header.setUint32(0,0x46546c67,true); header.setUint32(4,2,true); header.setUint32(8,24,true);
  let options;
  context.fetch = async (url, value) => {options=value; return new Response(buffer,{headers:{'content-type':'model/gltf-binary'}});};
  assert.equal((await review.fetchGeometry('/model-node/1.glb')).byteLength,24);
  assert.equal(options.cache,'no-store');
  assert.equal(options.credentials,'same-origin');
});
test('line matches are exact, not branch/substring guesses', () => {
  const matches = review.matchLines([...payload.lines,{tag:'DN-123'}],hierarchy);
  assert.equal(matches[0].nodes.length,1);
  assert.equal(matches[0].nodes[0].id,'1');
  assert.equal(matches[1].nodes.length,0);
});

test('quoted numeric classes match while inch marks, fractions and other tag parts stay significant', () => {
  for (const [quoted, plain] of [
    ['/4"-PG-313047-"750"-FFLT-1H', '4"-PG-313047-750-FFLT-1H'],
    ['/4"-PG-313050-"750"-FFLT-1H', '4"-PG-313050-750-FFLT-1H'],
    ['/1-1/2"-CM-423050-"281"-J2', '1-1/2"-CM-423050-281-J2'],
    ['/3/4"-CM-423050-"281"-J2/B1', '3/4"-CM-423050-281-J2/B1'],
    ['4"-PG-313050-"750"', '4"-PG-313050-750'],
  ]) assert.equal(review.key(quoted), plain);

  const canonical = review.key('4"-PG-313050-"750"-FFLT-1H');
  for (const distinct of ['4-PG-313050-750-FFLT-1H', '6"-PG-313050-750-FFLT-1H',
    '4"-PG-313050-750-FFLT-2H', '4"-PG-313050-750-FFLT-1H/B1', 'PG-313050', '3050']) {
    assert.notEqual(review.key(distinct), canonical, distinct);
  }
  for (const unchanged of ['4"-PG-313050-"750A"-FFLT-1H', '4"-PG-313050-"750-FFLT-1H',
    '4"-PG-313050-750"-FFLT-1H']) {
    assert.equal(review.key(unchanged), unchanged);
  }
});

test('lines 313047 and 313050 select their quoted roots without matching branches or similar tags', () => {
  const nodes = [
    {id:'52361', name:'/4"-PG-313047-"750"-FFLT-1H', bbox:[0,0,0,1,1,1]},
    {id:'52648', name:'/4"-PG-313050-"750"-FFLT-1H', bbox:[2,2,2,3,3,3]},
    {id:'52621', name:'/4"-PG-313050-"750"-FFLT-1H/B1', bbox:[2,2,2,3,3,3]},
    {id:'other-size', name:'/6"-PG-313050-"750"-FFLT-1H', bbox:[4,4,4,5,5,5]},
    {id:'other-suffix', name:'/4"-PG-313050-"750"-FFLT-2H', bbox:[6,6,6,7,7,7]},
  ];
  const lines = ['4"-PG-313047-750-FFLT-1H', '4"-PG-313050-750-FFLT-1H',
    'PG-313050', '3047', '3050'].map(tag => ({tag}));
  const matches = review.matchLines(lines, nodes);
  assert.deepEqual(Array.from(matches, line => Array.from(line.nodes, node => node.id)),
    [['52361'], ['52648'], [], [], []]);
});

test('drawing 10113 selects and renders its quoted 313050 model line', () => {
  const node = {id:'52648', name:'/4"-PG-313050-"750"-FFLT-1H',
    bbox:[-28.514,-13.71,-30.193,14.421,-7.803,-22.928], depth:5};
  const doc = {id:'10113', name:'10113', discipline:'piping',
    lines:['4"-PG-313050-750-FFLT-1H'], status:'started'};
  const lines = [{tag:'4"-PG-313050-750-FFLT-1H', status:'started'}];
  const selection = review.drawingSelection(doc, lines, [node]);
  assert.ok(selection);
  assert.equal(selection.id, 'drawing:10113');
  assert.deepEqual(Array.from(selection.reviewNodeIds), ['52648']);
  assert.deepEqual(Array.from(selection.bbox), node.bbox);
  // A second drawing can retain the quoted spelling while the backend exposes one line.
  const quotedDoc = {...doc, lines:[node.name.slice(1)]};
  assert.deepEqual(Array.from(review.drawingSelection(quotedDoc, lines, [node]).reviewNodeIds), ['52648']);
  const html = review.renderTree({payload:{available:true, drawings:[quotedDoc], lines}, hierarchy:[node],
    expanded:new Set(['discipline:piping', 'drawing:10113']), selected:'52648', query:'10113'});
  assert.ok(html.includes('data-review-drawing="10113"'));
  assert.ok(html.includes('data-model-node-id="52648"'));
  assert.ok(html.includes('is-started'));
  assert.ok(!html.includes('no exact 3D match'));
  assert.equal(review.drawingSelection({...doc, lines:[...doc.lines, 'MISSING']}, lines, [node]), null);
});
test('disciplines contain drawings and selectable line nodes with escaped labels', () => {
  const html = review.renderTree({payload,hierarchy,expanded:new Set(['discipline:piping','drawing:1']),selected:'1'});
  for(const label of ['Electrical','Instrumentation','Structural','Piping','DWG &lt;1&gt;','is-started','data-model-node-id="1"']) assert.ok(html.includes(label),label);
  assert.ok(!html.includes('DWG <1>'));
});
test('drawing search includes associated line tags and excludes unrelated drawings', () => {
  const render = query => review.renderTree({payload,hierarchy,expanded:new Set(),selected:'',query});
  assert.ok(render('DN-123').includes('DWG &lt;1&gt;'));
  assert.ok(!render('ZZZZZ').includes('DWG &lt;1&gt;'));
});
test('opening a discipline lists drawings even without a 3D line association', () => {
  const docs = ['electrical','instrumentation','structural'].map(discipline => ({id:discipline,name:`DRAWING-${discipline}`,discipline,lines:[],status:'unlinked',title:'Drawing title'}));
  const html = review.renderTree({payload:{available:true,drawings:docs,lines:[]},hierarchy,selected:'',
    expanded:new Set(docs.flatMap(doc=>[`discipline:${doc.discipline}`,`drawing:${doc.id}`]))});
  for (const doc of docs) assert.ok(html.includes(`data-review-drawing="${doc.id}"`));
  assert.ok(html.includes('Geometry association pending.'));
  assert.ok(!html.includes('Drawings and lines not linked yet.</div><div class="dx-project-drawing-row"'));
});
test('drawing names select while their separate caret only expands', () => {
  const html = review.renderTree({payload,hierarchy,expanded:new Set(['discipline:piping']),selected:'drawing:1'});
  assert.ok(html.includes('data-review-drawing="1"'));
  assert.ok(html.includes('data-review-toggle="drawing:1"'));
  assert.ok(html.includes('dx-project-tree-item is-selected" data-review-drawing="1"'));
});
test('drawing selection contains exactly its linked lines and their combined bounds', () => {
  const other = {id:'4',name:'/LINE-OTHER',bbox:[10,10,10,12,12,12],depth:5};
  const result = review.drawingSelection({...payload.drawings[0],lines:[...payload.drawings[0].lines,'LINE-OTHER']},
    [...payload.lines,{tag:'LINE-OTHER'}],[...hierarchy,other]);
  assert.deepEqual(Array.from(result.reviewNodeIds),['1','4']);
  assert.deepEqual(Array.from(result.bbox),[0,0,0,12,12,12]);
  assert.equal(result.id,'drawing:1');
  assert.equal(review.drawingSelection({...payload.drawings[0],lines:['MISSING']},payload.lines,hierarchy),null);
});
test('tree selection replaces surroundings and isolates, without changing canvas-click behaviour', () => {
  const source=fs.readFileSync(path.join(__dirname,'../../../static/js/dashfy.js'),'utf8');
  const state={selectionRequestId:0,datafyRequestId:0,modelLoaded:true,isolateSelection:false,surroundings:true};
  const calls=[];
  const scope={state,restoreSurroundings(){state.surroundings=false;},clearDatafyFocus(){},revealHierarchyNode(){},setSelection(){},
    updateIsolationControls(){},setStatus(){},renderOnce(){},nodeIsDisciplineVisible(){return true;},
    highlightHierarchyNode(node,options){calls.push(options.frame);},loadSelectionGeometry(){}};
  vm.createContext(scope);
  vm.runInContext(source.slice(source.indexOf('    const selectHierarchyNode ='),source.indexOf('    const supplyLineCandidates ='))+'\nthis.select=selectHierarchyNode;',scope);
  scope.select({id:'1'},'tree');
  assert.equal(state.isolateSelection,true);
  assert.equal(state.surroundings,false);
  assert.equal(calls[0],true);
  state.isolateSelection=false;
  scope.select({id:'2'},'viewer');
  assert.equal(state.isolateSelection,false);
  assert.equal(calls[1],false);
});
