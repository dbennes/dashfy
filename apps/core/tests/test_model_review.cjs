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
