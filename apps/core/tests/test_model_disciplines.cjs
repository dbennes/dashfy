const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const root = path.join(__dirname, '../../..');
const context = {window: {}};
vm.createContext(context);
vm.runInContext(fs.readFileSync(path.join(root, 'static/js/model-review.js'), 'utf8'), context);
const review = context.window.DashfyModelReview;
const source = fs.readFileSync(path.join(root, 'static/js/dashfy.js'), 'utf8');

test('classification follows authored discipline ancestry, including parts, supports and unknowns', () => {
  const rows = JSON.parse(fs.readFileSync(path.join(root, 'static/models/bonga-2-hierarchy.json'))).nodes;
  const byId = new Map(rows.map(r => [String(r[0]), {id:String(r[0]),parent:String(r[1]),depth:r[2],name:r[3]}]));
  assert.equal(review.nodeDiscipline(byId.get('13212'), byId), 'piping');
  assert.equal(review.nodeDiscipline(byId.get('72067'), byId), 'piping');
  assert.equal(review.nodeDiscipline(byId.get('72195'), byId), 'piping');
  let tieInParts = 0;
  for (const row of rows.filter(row => row[4] === 1)) {
    let ancestor = byId.get(String(row[0]));
    while (ancestor && !['72067','72195'].includes(ancestor.id)) ancestor = byId.get(ancestor.parent);
    if (!ancestor) continue;
    assert.equal(review.nodeDiscipline(byId.get(String(row[0])), byId), 'piping');
    tieInParts++;
  }
  assert.equal(tieInParts,237);
  assert.equal(review.nodeDiscipline(byId.get('15782'), byId), 'supports');
  assert.equal(review.nodeDiscipline(byId.get('7507'), byId), 'equipment');
  assert.equal(review.nodeDiscipline(byId.get('0'), byId), 'other');
  for(const row of rows.filter(r => r[4] === 1)) {
    const id = review.nodeDiscipline(byId.get(String(row[0])), byId);
    assert.ok(review.visibilityDisciplines.some(d => d.id === id));
  }
  const line = {id:'line',name:'PIPE text does not override electrical ancestry',parent:'76',depth:4};
  byId.set(line.id,line);
  assert.equal(review.nodeDiscipline(line,byId),'electrical');
  assert.equal(review.nodeDiscipline({reviewNodeIds:['line']},byId),'electrical');
});

test('every authored model group appears exactly once in the matching visibility category', () => {
  const rows = JSON.parse(fs.readFileSync(path.join(root, 'static/models/bonga-2-hierarchy.json'))).nodes;
  const hierarchy = rows.map(r=>({id:String(r[0]),parent:String(r[1]),depth:r[2],name:r[3],mesh:!!r[4],bbox:r[6]}));
  const byId = new Map(hierarchy.map(node=>[node.id,node]));
  const expanded = new Set(review.visibilityDisciplines.flatMap(d=>[`discipline:${d.id}`,`groups:${d.id}`]));
  const html = review.renderTree({payload:{drawings:[],lines:[],available:true},hierarchy,expanded,selected:''});
  const groups = hierarchy.filter(node=>node.depth===3 || (node.depth<3 && node.mesh));
  const rendered = [...html.matchAll(/data-model-node-id="([^"]+)"/g)].map(match=>match[1]);
  assert.equal(rendered.length,groups.length);
  assert.equal(new Set(rendered).size,groups.length);
  for(const group of groups){
    const position=html.indexOf(`data-model-node-id="${group.id}"`);
    const category=[...html.slice(0,position).matchAll(/data-review-toggle="discipline:([^"]+)"/g)].at(-1)[1];
    assert.equal(category,review.nodeDiscipline(group,byId),group.name);
  }
  for(const name of ['BN-TIE-IN-POINTS','BN-TAM-26-TIE-IN-POINTS','BN-MR2-EQUI','BN-MR3-TELE','BN-MR2-PAUX','Cube'])assert.ok(html.includes(name),name);
});

test('filters affect main meshes, exact overlays and progress; restoring preserves camera/isolation', async () => {
  const THREE = await import(pathToFileURL(path.join(root, 'static/vendor/three/three.module.js')));
  const model = new THREE.Group();
  const meshes = new Map();
  for(const item of review.visibilityDisciplines) {
    const group = new THREE.Group();group.name=`discipline_${item.id}`;
    const mesh = new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshBasicMaterial());
    group.add(mesh);model.add(group);meshes.set(item.id,mesh);
  }
  const selected = {id:'line',parent:'pipe',name:'line',depth:4};
  const overlay = new THREE.Group();
  const part = new THREE.Mesh(new THREE.BoxGeometry(),new THREE.MeshBasicMaterial());
  part.userData.hierarchyNodeId='line';overlay.add(part);
  const state = {model, hiddenDisciplines:new Set(['piping']), hierarchyById:new Map([
    ['line',selected],['pipe',{id:'pipe',depth:3,name:'/BN-SS-PIPE'}]
  ]),selectionOverlay:overlay,datafyOverlay:overlay,progressLayer:new THREE.Group(),appearance:'progress',isolateSelection:false};
  const h={state,review,selectedHierarchyNode:()=>selected};vm.createContext(h);
  vm.runInContext(source.slice(source.indexOf('    const nodeIsDisciplineVisible ='),source.indexOf('    const syncDisciplineControls ='))+'\nthis.apply=applyDisciplineVisibility; this.pickable=nodeIsDisciplineVisible;',h);
  h.apply();
  assert.equal(meshes.get('piping').visible,false);
  assert.equal(meshes.get('electrical').visible,true);
  assert.equal(part.visible,false);
  assert.equal(state.progressLayer.visible,false);
  assert.equal(h.pickable(selected),false);
  state.hiddenDisciplines.clear();h.apply();
  assert.equal(part.visible,true);assert.equal(state.progressLayer.visible,true);
  state.isolateSelection=true;model.visible=false;h.apply();
  assert.equal(model.visible,false);assert.equal(state.progressLayer.visible,false);
  for(const item of review.visibilityDisciplines)state.hiddenDisciplines.add(item.id);
  h.apply();assert.ok([...meshes.values()].every(mesh=>!mesh.visible));
});

test('click fallback skips a hidden discipline even when its bounds are closest', () => {
  const hidden={id:'hidden',bbox:[1,0,0,2,1,1],mesh:true,depth:5};
  const visible={id:'visible',bbox:[3,0,0,4,1,1],mesh:true,depth:5};
  const h={state:{hierarchyItems:[hidden,visible]},nodeIsDisciplineVisible:node=>node.id!=='hidden',
    rayBboxDistance:(_,bbox)=>bbox[0],bboxVolume:()=>1,hierarchyChildrenOf:()=>[]};
  vm.createContext(h);
  vm.runInContext(source.slice(source.indexOf('    const findHierarchyNodeOnRay ='),source.indexOf('    const scrollSelectedHierarchyIntoView ='))+'\nthis.pick=findHierarchyNodeOnRay;',h);
  assert.equal(h.pick({}).id,'visible');
  h.nodeIsDisciplineVisible=()=>false;
  assert.equal(h.pick({}),null);
});
