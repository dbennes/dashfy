/* Discipline navigation and exact-geometry fabrication colours for the 3D review. */
(function () {
  const key = value => String(value || '').trim().replace(/^\/+/, '').replace(/\s+/g, '').toUpperCase();
  const labels = {not_started: 'Not started', started: 'Started', completed: 'Completed', unlinked: 'No fabrication link'};
  const colors = {not_started: 0x94a3b8, started: 0xf59e0b, completed: 0x38bdf8, unlinked: 0x94a3b8};
  const authError = () => Object.assign(new Error('Session unavailable. Sign in again to load the 3D geometry.'), {code: 'AUTH_REQUIRED'});
  async function fetchGeometry(url) {
    const response = await fetch(url, {cache: 'no-store', credentials: 'same-origin', headers: {Accept: 'model/gltf-binary'}});
    if (response.status === 401 || /\/accounts\/login\//.test(response.url || '')) throw authError();
    if (!response.ok) throw new Error(response.status === 413 ? 'This group is too large. Select a smaller line or component.' : `Geometry request failed (HTTP ${response.status}).`);
    if ((response.headers.get('content-type') || '').includes('text/html')) throw new Error('The server returned a web page instead of 3D geometry. Reload and try again.');
    const buffer = await response.arrayBuffer();
    const header = new DataView(buffer);
    if (buffer.byteLength < 20 || header.getUint32(0, true) !== 0x46546c67 || header.getUint32(4, true) !== 2 || header.getUint32(8, true) !== buffer.byteLength) {
      throw new Error('Invalid or incomplete 3D file received. Please retry.');
    }
    return buffer;
  }
  const escape = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;', "'":'&#39;'}[c]));
  const visibilityDisciplines = [
    {id: 'piping', name: 'Piping', codes: ['PIPE']},
    {id: 'structural', name: 'Structural', codes: ['STRU', 'WIT', 'FRMW']},
    {id: 'electrical', name: 'Electrical', codes: ['ELEC']},
    {id: 'instrumentation', name: 'Instrumentation', codes: ['INST']},
    {id: 'equipment', name: 'Equipment', codes: ['EQUI']},
    {id: 'supports', name: 'Supports', codes: ['PSUP', 'PUSP']},
    {id: 'telecom', name: 'Telecom', codes: ['TELE']},
    {id: 'auxiliary', name: 'Auxiliary', codes: ['PAUX']},
    {id: 'other', name: 'Other items', codes: []},
  ];
  function nodeDiscipline(node, byId) {
    if (node?.reviewNodeIds?.length) return nodeDiscipline(byId.get(node.reviewNodeIds[0]), byId);
    while (node && node.depth !== 3) node = byId.get(node.parent);
    if (node?.name.toUpperCase().endsWith('-TIE-IN-POINTS')) return 'piping';
    const code = node?.name.split('-').pop().toUpperCase();
    return visibilityDisciplines.find(discipline => discipline.codes.includes(code))?.id || 'other';
  }
  function objectDiscipline(object) {
    for (let current = object; current; current = current.parent) {
      if (current.name?.startsWith('discipline_')) return current.name.slice('discipline_'.length);
    }
    return null;
  }
  function matchLines(lines, hierarchy) {
    const index = new Map();
    hierarchy.forEach(node => {
      if (!node.bbox || !node.name.startsWith('/')) return;
      const tag = key(node.name);
      if (!index.has(tag)) index.set(tag, []);
      index.get(tag).push(node);
    });
    return lines.map(line => ({...line, nodes: index.get(key(line.tag)) || []}));
  }
  function drawingSelection(doc, lines, hierarchy) {
    const tags = new Set(doc.lines.map(key));
    const matches = matchLines(lines.filter(line => tags.has(key(line.tag))), hierarchy);
    const nodes = Array.from(new Map(matches.flatMap(line => line.nodes).map(node => [node.id, node])).values());
    // Never silently select only part of a drawing, or infer a nearby node.
    if (!nodes.length || matches.length !== tags.size || matches.some(line => !line.nodes.length)) return null;
    return {id: `drawing:${doc.id}`, name: doc.name, parent: '', depth: 0, mesh: false, children: 0,
      reviewNodeIds: nodes.map(node => node.id),
      bbox: [0,1,2].map(axis => Math.min(...nodes.map(node => node.bbox[axis])))
        .concat([3,4,5].map(axis => Math.max(...nodes.map(node => node.bbox[axis]))))};
  }
  function renderTree({payload, hierarchy, expanded, selected, query = ''}) {
    const lines = matchLines(payload.lines || [], hierarchy);
    const byTag = new Map(lines.map(line => [key(line.tag), line]));
    const term = query.toLowerCase().trim();
    const byId = new Map(hierarchy.map(node => [node.id, node]));
    // Share exactly the same classification as the visibility checkboxes.
    // Include standalone geometry outside authored discipline groups as Other.
    const modelGroups = hierarchy.filter(node => node.depth === 3 || (node.depth < 3 && node.mesh));
    const nodeButton = (node, depth = 2) => `<button type="button" class="dx-project-tree-item ${selected === node.id ? 'is-selected' : ''}" data-model-node-id="${escape(node.id)}" style="--level:${depth}"><span class="dx-project-tree-caret">↗</span><span class="dx-project-tree-text"><strong>${escape(node.name.replace(/^\//,''))}</strong><small>Model group · select to inspect</small></span></button>`;
    const toggle = (id, name, meta, depth) => `<button type="button" class="dx-project-tree-item" data-review-toggle="${escape(id)}" aria-expanded="${expanded.has(id) || !!term}" style="--level:${depth}"><span class="dx-project-tree-caret">${expanded.has(id) || term ? '−' : '+'}</span><span class="dx-project-tree-text"><strong>${escape(name)}</strong><small>${escape(meta)}</small></span></button>`;
    let html = '';
    visibilityDisciplines.forEach(discipline => {
      const docs = (payload.drawings || []).filter(doc => doc.discipline === discipline.id && (!term || `${doc.name} ${doc.title} ${doc.lines.join(' ')}`.toLowerCase().includes(term)));
      // Level 3 is the authored discipline grouping; never infer drawing links from its name.
      const groups = modelGroups.filter(node => nodeDiscipline(node, byId) === discipline.id && (!term || node.name.toLowerCase().includes(term)));
      if (term && !docs.length && !groups.length && !discipline.name.toLowerCase().includes(term)) return;
      const id = `discipline:${discipline.id}`;
      html += toggle(id, discipline.name, `${docs.length} drawings · ${groups.length} model groups`, 0);
      if (!expanded.has(id) && !term) return;
      if (!docs.length) html += `<div class="dx-project-review-note">${payload.available === false ? 'Drawing data unavailable.' : 'Drawings and lines not linked yet.'}</div>`;
      docs.forEach(doc => {
        const id = `drawing:${doc.id}`;
        html += `<div class="dx-project-drawing-row">
          <button type="button" class="dx-project-drawing-toggle" data-review-toggle="${escape(id)}" aria-expanded="${expanded.has(id) || !!term}" aria-label="Expand lines for ${escape(doc.name)}">${expanded.has(id) || term ? '−' : '+'}</button>
          <button type="button" class="dx-project-tree-item ${selected === id ? 'is-selected' : ''}" data-review-drawing="${escape(doc.id)}" title="${doc.lines.length ? 'Select and isolate this drawing\'s linked lines' : 'View drawing details; 3D link pending'}"><span class="dx-project-tree-text"><strong>${escape(doc.name)}</strong><small>${doc.lines.length ? `${doc.lines.length} line(s)` : '3D link pending'} · ${labels[doc.status] || labels.unlinked}</small></span></button>
        </div>`;
        if (!expanded.has(id) && !term) return;
        if (!doc.lines.length) html += `<div class="dx-project-review-note">${doc.title ? `${escape(doc.title)}<br>` : ''}Drawing registered. Geometry association pending.</div>`;
        doc.lines.forEach(tag => {
          const line = byTag.get(key(tag));
          const status = line?.status || 'unlinked';
          if (!line?.nodes.length) {
            html += `<div class="dx-project-review-note">${escape(tag)} · no exact 3D match</div>`;
            return;
          }
          line.nodes.forEach(node => {
            html += `<button type="button" class="dx-project-tree-item ${selected === node.id ? 'is-selected' : ''}" data-model-node-id="${escape(node.id)}" style="--level:2"><span class="dx-project-progress-dot is-${status}"></span><span class="dx-project-tree-text"><strong>${escape(tag)}</strong><small>${escape(labels[status])}${line.unlinked ? ' · incomplete fabrication coverage' : ''}</small></span></button>`;
          });
        });
      });
      const groupId = `groups:${discipline.id}`;
      if (groups.length) {
        html += toggle(groupId, 'Model groups', 'Geometry without drawing association', 1);
        if (expanded.has(groupId) || term) groups.forEach(node => { html += nodeButton(node); });
      }
    });
    return html || '<div class="dx-project-tree-empty">No drawing or line found.</div>';
  }

  async function buildProgressLayer({THREE, loader, lines, selectionUrl, isCurrent, onUpdate}) {
    const {mergeGeometries} = await import('three/addons/utils/BufferGeometryUtils.js');
    const jobs = lines.filter(line => ['started', 'completed'].includes(line.status)).flatMap(line => line.nodes.map(node => ({node, status: line.status})));
    const buckets = {started: [], completed: []};
    const ranges = {started: [], completed: []};
    const triangles = {started: 0, completed: 0};
    const failures = [];
    let authenticationError = null;
    let next = 0, done = 0;
    const disposeScene = scene => {
      const materials = new Set();
      scene.traverse(child => {
        child.geometry?.dispose();
        (Array.isArray(child.material) ? child.material : [child.material]).filter(Boolean).forEach(material => materials.add(material));
      });
      materials.forEach(material => material.dispose());
    };
    const worker = async () => {
      while (next < jobs.length && isCurrent() && !authenticationError) {
        const {node, status} = jobs[next++];
        let scene;
        try {
          const buffer = await fetchGeometry(selectionUrl.replace(/0\.glb(?=($|\?))/, `${encodeURIComponent(node.id)}.glb`));
          if (!isCurrent()) break;
          const gltf = await new Promise((resolve, reject) => loader.parse(buffer, '', resolve, reject));
          scene = gltf.scene;
          if (!isCurrent()) break;
          scene.updateMatrixWorld(true);
          const start = triangles[status];
          scene.traverse(child => {
            if (!child.isMesh || !child.geometry?.attributes.position) return;
            const geometry = child.geometry.index ? child.geometry.toNonIndexed() : child.geometry.clone();
            Object.keys(geometry.attributes).filter(name => name !== 'position').forEach(name => geometry.deleteAttribute(name));
            geometry.clearGroups();
            geometry.applyMatrix4(child.matrixWorld);
            triangles[status] += geometry.attributes.position.count / 3;
            buckets[status].push(geometry);
          });
          ranges[status].push({nodeId: node.id, start, end: triangles[status]});
        } catch (error) {
          if (error.code === 'AUTH_REQUIRED') authenticationError = error;
          failures.push(node.id);
        } finally {
          if (scene) disposeScene(scene);
          done++;
          if (isCurrent()) onUpdate(done, jobs.length);
        }
      }
    };
    await Promise.all([worker(), worker(), worker()]);
    if (authenticationError) {
      Object.values(buckets).flat().forEach(geometry => geometry.dispose());
      throw authenticationError;
    }
    const group = new THREE.Group();
    for (const status of ['started', 'completed']) {
      if (isCurrent() && buckets[status].length) {
        const geometry = mergeGeometries(buckets[status], false);
        geometry.computeVertexNormals();
        const material = new THREE.MeshStandardMaterial({color: colors[status], roughness: 0.75, metalness: 0, polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2});
        const mesh = new THREE.Mesh(geometry, material);
        mesh.userData.progressRanges = ranges[status];
        group.add(mesh);
      }
      buckets[status].forEach(geometry => geometry.dispose());
    }
    return {group, failures, total: jobs.length};
  }
  window.DashfyModelReview = {key, labels, colors, authError, fetchGeometry, matchLines, drawingSelection, renderTree, buildProgressLayer,
    visibilityDisciplines, nodeDiscipline, objectDiscipline};
})();
