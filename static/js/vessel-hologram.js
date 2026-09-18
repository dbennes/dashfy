/* Vessel dossier: holographic 3D stage plus the Trackfy cargo it is carrying.
 *
 * Opened from the map by vessel-tracking.js, which dispatches `vt:open-dossier`
 * with the vessel payload it already holds. Everything shown here is real: AIS
 * observations for the vessel, Trackfy rows for the cargo. Nothing is invented,
 * and the 3D model is decoration for data that stands on its own — if the model
 * or WebGL is unavailable the dossier still works.
 */
/* three.js is loaded on demand, never at module scope: the dossier is mostly
 * data, and a 3D library that fails to fetch must not stop the panel opening.
 * Vendored locally because an import map has to be parsed before the first
 * module and the CDN is not reachable from every network. */
const THREE_URL = "/static/vendor/three/three.module.js";
let THREE = null;

async function loadThree() {
  if (!THREE) THREE = await import(THREE_URL);
  return THREE;
}

const MODEL_STATE = { loading: null, scene: null };
const CARD_STAGGER_MS = 45;

function num(value) {
  if (value === null || value === undefined || value === "" || typeof value === "boolean") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function utcLabel(value) {
  if (typeof value !== "string" || !/(?:Z|[+-]\d{2}:\d{2})$/i.test(value)) return "—";
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return "—";
  const dt = new Date(parsed);
  const pad = (n) => String(n).padStart(2, "0");
  return `${pad(dt.getUTCDate())}/${pad(dt.getUTCMonth() + 1)}/${dt.getUTCFullYear()} ${pad(dt.getUTCHours())}:${pad(dt.getUTCMinutes())} UTC`;
}

function measure(value, unit, digits = 1) {
  const parsed = num(value);
  return parsed === null ? "—" : `${parsed.toLocaleString("en-GB", { maximumFractionDigits: digits })}${unit || ""}`;
}

/* ------------------------------------------------------------ hologram */

/** A stylised hull, shown until a real model is supplied and if one fails. */
function placeholderHull() {
  const group = new THREE.Group();
  const material = new THREE.MeshStandardMaterial({ color: 0x64748b, metalness: 0.1, roughness: 0.8 });
  const hull = new THREE.Mesh(new THREE.CapsuleGeometry(0.62, 3.1, 6, 16).rotateZ(Math.PI / 2), material);
  group.add(hull);
  const deck = new THREE.Mesh(new THREE.BoxGeometry(1.15, 0.55, 0.95), material);
  deck.position.set(-0.85, 0.6, 0);
  group.add(deck);
  return group;
}

function frameObject(object, targetSize = 4.1) {
  const box = new THREE.Box3().setFromObject(object);
  if (box.isEmpty()) return object;
  const size = box.getSize(new THREE.Vector3());
  const centre = box.getCenter(new THREE.Vector3());
  const largest = Math.max(size.x, size.y, size.z) || 1;
  object.position.sub(centre);
  const wrap = new THREE.Group();
  wrap.add(object);
  wrap.scale.setScalar(targetSize / largest);
  return wrap;
}

async function loadModel(url) {
  if (!url) return null;
  await loadThree();
  const lower = url.split("?")[0].toLowerCase();
  if (lower.endsWith(".glb") || lower.endsWith(".gltf")) {
    const { GLTFLoader } = await import("/static/vendor/three/loaders/GLTFLoader.js");
    const loader = new GLTFLoader();
    // Web-optimised models are usually meshopt- or Draco-compressed; without the
    // decoders the load fails with an opaque error rather than a missing model.
    try {
      const { DRACOLoader } = await import("/static/vendor/three/loaders/DRACOLoader.js");
      const draco = new DRACOLoader();
      draco.setDecoderPath("/static/vendor/three/libs/draco/gltf/");
      loader.setDRACOLoader(draco);
    } catch { /* uncompressed models still load */ }
    const gltf = await loader.loadAsync(url);
    return gltf.scene;
  }
  // Only glTF is vendored; convert other formats to .glb before publishing.
  throw new Error("Unsupported model format: use .glb or .gltf");
}

class Hologram {
  constructor(mount, note) {
    this.mount = mount;
    this.note = note;
    this.alive = false;
    this.frame = null;
  }

  async start(modelUrl) {
    if (this.alive || this.starting) return;
    this.starting = true;
    try {
      await loadThree();
    } catch {
      this.note.textContent = "3D viewer could not be loaded. Vessel data is unaffected.";
      return;
    }
    if (this.stopped) return;
    try {
      this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "low-power" });
    } catch {
      this.note.textContent = "3D view unavailable on this device. Vessel data is unaffected.";
      return;
    }
    this.renderer.setPixelRatio(Math.min(globalThis.devicePixelRatio || 1, 1.25));
    this.renderer.setClearColor(0x000000, 0);
    this.mount.appendChild(this.renderer.domElement);

    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(42, 1, 0.1, 100);
    this.camera.position.set(4.6, 2.2, 5.4);
    this.camera.lookAt(0, 0, 0);
    this.pivot = new THREE.Group();
    this.scene.add(this.pivot);
    // Only the solid view reads these; the hologram shader is unlit.
    this.lights = new THREE.Group();
    this.lights.add(new THREE.HemisphereLight(0xbfe9ff, 0x12202c, 2.1));
    const key = new THREE.DirectionalLight(0xffffff, 2.4);
    key.position.set(4, 6, 5);
    this.lights.add(key);
    const fill = new THREE.DirectionalLight(0x9bd8ff, 1.1);
    fill.position.set(-5, 2, -4);
    this.lights.add(fill);
    this.scene.add(this.lights);

    this.alive = true;
    this.resize();
    this.observer = new ResizeObserver(() => this.resize());
    this.observer.observe(this.mount);
    // Orbit with the pointer and dolly with the wheel: the projection is
    // free to rotate automatically again when the pointer is released.
    this.orbit = { yaw: -0.5, pitch: 0.26, distance: 7, fitted: false, dragging: false, lastX: 0, lastY: 0 };
    this.onDown = (event) => {
      this.orbit.dragging = true;
      this.orbit.lastX = event.clientX; this.orbit.lastY = event.clientY;
      this.mount.setPointerCapture?.(event.pointerId);
    };
    this.onMove = (event) => {
      if (!this.orbit.dragging) return;
      this.orbit.yaw -= (event.clientX - this.orbit.lastX) * 0.007;
      this.orbit.pitch = Math.max(-0.9, Math.min(1.25, this.orbit.pitch + (event.clientY - this.orbit.lastY) * 0.005));
      this.orbit.lastX = event.clientX; this.orbit.lastY = event.clientY;
      this.loop();
    };
    this.onUp = (event) => {
      this.orbit.dragging = false;
      this.mount.releasePointerCapture?.(event.pointerId);
    };
    this.onWheel = (event) => {
      event.preventDefault();
      this.orbit.touched = true;
      const step = this.orbit.distance * 0.12;
      this.orbit.distance = Math.max(0.6, Math.min(60, this.orbit.distance + Math.sign(event.deltaY) * step));
      this.loop();
    };
    this.mount.addEventListener("pointerdown", this.onDown);
    this.mount.addEventListener("pointermove", this.onMove);
    this.mount.addEventListener("pointerup", this.onUp);
    this.mount.addEventListener("pointercancel", this.onUp);
    this.mount.addEventListener("wheel", this.onWheel, { passive: false });

    this.onVisibility = () => {
      if (document.hidden) { cancelAnimationFrame(this.frame); this.frame = null; }
      else this.loop();
    };
    document.addEventListener("visibilitychange", this.onVisibility);
    this.note.textContent = modelUrl ? "Loading vessel model…" : "Schematic view · upload a model to replace it";
    this.attach(placeholderHull());
    if (modelUrl) this.loadInto(modelUrl);
    this.loop();
  }

  async loadInto(url) {
    try {
      if (!MODEL_STATE.loading) MODEL_STATE.loading = loadModel(url);
      const source = await MODEL_STATE.loading;
      if (!this.alive || !source) return;
      this.attach(source.clone(true));
      this.hasModel = true;
      this.note.textContent = "Vessel model";
    } catch {
      MODEL_STATE.loading = null;
      if (!this.alive) return;
      // A missing or broken model must never blank the dossier.
      this.note.textContent = "Model could not be loaded · showing schematic";
    }
  }

  attach(object) {
    if (this.model) this.pivot.remove(this.model);
    this.model = frameObject(object);
    this.pivot.add(this.model);
    this.fitToModel();
    this.loop();
  }

  /** Pull the camera back just far enough for the whole hull to sit in frame.
   *  The stage is tall and narrow, so the horizontal field of view is usually
   *  the binding constraint; a fixed distance crops a long vessel. */
  fitToModel() {
    if (!this.model || !this.camera) return;
    const sphere = new THREE.Box3().setFromObject(this.model).getBoundingSphere(new THREE.Sphere());
    if (!(sphere.radius > 0)) return;
    const vertical = THREE.MathUtils.degToRad(this.camera.fov);
    const horizontal = 2 * Math.atan(Math.tan(vertical / 2) * this.camera.aspect);
    const field = Math.min(vertical, horizontal);
    // Extra headroom so a long hull never clips as it turns broadside.
    this.orbit.distance = (sphere.radius / Math.sin(field / 2)) * 1.45;
    this.orbit.fitted = true;
  }

  resize() {
    if (!this.alive) return;
    const width = this.mount.clientWidth || 1;
    const height = this.mount.clientHeight || 1;
    this.renderer.setSize(width, height, false);
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    if (this.orbit && !this.orbit.touched) this.fitToModel();
    this.loop();
  }

  // Animate while open and visible; manual dragging takes priority over rotation.
  loop() {
    if (!this.alive || this.frame || document.hidden) return;
    this.frame = requestAnimationFrame(() => {
      this.frame = null;
      if (!this.alive || document.hidden || !this.orbit) return;
      if (!this.orbit.dragging) this.orbit.yaw += 0.0026;
      const { yaw, pitch, distance } = this.orbit;
      this.camera.position.set(
        Math.sin(yaw) * Math.cos(pitch) * distance,
        Math.sin(pitch) * distance,
        Math.cos(yaw) * Math.cos(pitch) * distance,
      );
      this.camera.lookAt(0, 0, 0);
      if (this.model) this.pivot.position.y = Math.sin(performance.now() / 1000 * 0.9) * 0.07;
      this.renderer.render(this.scene, this.camera);
      this.loop();
    });
  }

  stop() {
    // start() may still be awaiting the library; tell it not to build a scene.
    this.stopped = true;
    if (!this.alive) return;
    this.alive = false;
    cancelAnimationFrame(this.frame);
    this.frame = null;
    document.removeEventListener("visibilitychange", this.onVisibility);
    this.observer?.disconnect();
    this.mount.removeEventListener("pointerdown", this.onDown);
    this.mount.removeEventListener("pointermove", this.onMove);
    this.mount.removeEventListener("pointerup", this.onUp);
    this.mount.removeEventListener("pointercancel", this.onUp);
    this.mount.removeEventListener("wheel", this.onWheel);
    this.scene?.traverse((node) => {
      if (node.isMesh || node.isLineSegments) node.geometry?.dispose?.();
    });
    this.renderer?.dispose();
    this.renderer?.domElement?.remove();
    this.renderer = null;
  }
}

/* --------------------------------------------------------------- panel */

function el(tag, className, textContent) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (textContent !== undefined) node.textContent = textContent === "" ? "—" : String(textContent);
  return node;
}

function initDossier(root) {
  const overlay = root.querySelector("[data-vh-overlay]");
  if (!overlay) return;
  const q = (name) => root.querySelector(`[data-vh-${name}]`);
  const base = root.dataset.apiBase || "/vessels/api/";
  const modelUrl = root.dataset.vesselModel || "";
  const state = { open: false, vessel: null, containers: [], activeBox: null,
                activeShipment: null, items: [], restoreFocus: null };
  let hologram = null;

  async function api(path) {
    const response = await fetch(base + path, {
      headers: { Accept: "application/json" }, credentials: "same-origin",
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || "Trackfy data could not be loaded.");
    return data;
  }

  function renderFacts(vessel) {
    const position = vessel.last_position || {};
    const voyage = vessel.voyage || null;
    const arrived = voyage && voyage.status === "arrived";
    const destination = voyage ? voyage.destination && voyage.destination.name : vessel.destination;
    const nextDestination = voyage && voyage.next_destination && voyage.next_destination.name;
    const scheduledRoute = voyage && voyage.destination_source === "scheduled_route";
    const voyageLabel = arrived ? `Arrived · ${(voyage.current_port || {}).name || destination || "Port"}`
      : voyage && voyage.status === "underway" ? "Underway" : "Not established";
    const eta = vessel.eta && typeof vessel.eta === "object" ? vessel.eta : {};
    const pad = (v) => String(v).padStart(2, "0");
    const etaLabel = Number.isInteger(eta.month) && Number.isInteger(eta.day)
      ? `${pad(eta.day)}/${pad(eta.month)}${Number.isInteger(eta.hour) ? ` ${pad(eta.hour)}:${pad(eta.minute ?? 0)} UTC` : ""}`
      : "—";
    const lat = num(position.latitude), lon = num(position.longitude);
    const rows = [
      ["Position · lat, lon", lat === null || lon === null ? "—" : `${lat.toFixed(5)}, ${lon.toFixed(5)}`, true],
      ["Speed over ground", measure(position.sog, " kn")],
      ["Course over ground", measure(position.cog, "°")],
      ["Heading", measure(position.heading, "°")],
      ["Draught", measure(vessel.draught, " m", 2)],
      ["Voyage status", voyageLabel, true, "at last AIS position"],
      ["Origin", voyage && voyage.origin ? voyage.origin.name : "Not recorded", true],
      [arrived ? "Arrival location" : "Destination", destination || "Next destination not reported", true,
        arrived ? "within arrival radius" : scheduledRoute ? "Regular route" : "AIS declared"],
      ...(nextDestination ? [["Next destination", nextDestination, true, "Regular route"]] : []),
      ["ETA", arrived || !destination || scheduledRoute ? "—" : etaLabel, false, "no year in AIS"],
      ["Last AIS", utcLabel(position.timestamp)],
      ["Vessel type", vessel.vessel_type || "—", true],
      ["MMSI", vessel.mmsi],
      ["IMO", vessel.imo || "—"],
    ];
    const grid = q("facts");
    grid.replaceChildren();
    rows.forEach(([label, value, wide, hint]) => {
      const cell = el("div", wide ? "vh-wide" : "");
      const dt = el("dt", "", label);
      if (hint) { dt.appendChild(document.createTextNode(" ")); dt.appendChild(el("em", "", hint)); }
      cell.appendChild(dt);
      cell.appendChild(el("dd", "", value));
      grid.appendChild(cell);
    });
    const specs = q("specs");
    specs.replaceChildren();
    // Only fields the AIS feed actually provides; no invented dimensions.
    [["SOG", measure(position.sog, " kn")], ["COG", measure(position.cog, "°")],
     ["DRAUGHT", measure(vessel.draught, " m", 2)],
     ["HEADING", measure(position.heading, "°", 0), "vh-spec-hdg"]].forEach(([label, value, cls]) => {
      const cell = el("div", cls || "");
      cell.appendChild(el("dt", "", label));
      cell.appendChild(el("dd", "", value));
      specs.appendChild(cell);
    });
  }

  /* Colour carries the shipment state; being overdue is a separate signal, so a
     fleet that is entirely late still shows which shipments are drafts. */
  let mini = null;
  function showMiniMap(vessel) {
    const wrap = q("mini-wrap");
    const mount = q("mini");
    const position = vessel.last_position || {};
    const lat = num(position.latitude), lon = num(position.longitude);
    const L = globalThis.L;
    if (lat === null || lon === null || !L) {
      wrap.hidden = true;
      return;
    }
    wrap.hidden = false;
    const config = root.dataset.miniTile || "";
    if (!mini) {
      mini = L.map(mount, {
        center: [lat, lon], zoom: 7, zoomControl: false, attributionControl: false,
        dragging: false, scrollWheelZoom: false, doubleClickZoom: false,
        boxZoom: false, keyboard: false, touchZoom: false,
      });
      if (config.indexOf("https://") === 0) {
        L.tileLayer(config, { maxZoom: 19, className: "vt-tiles-base" }).addTo(mini);
      }
      // A divIcon so the ping can be a CSS animation; an SVG circleMarker cannot
      // animate its radius without redrawing every frame.
      const beacon = document.createElement("span");
      beacon.className = "vh-ping";
      beacon.appendChild(document.createElement("i"));
      beacon.appendChild(document.createElement("b"));
      mini.marker = L.marker([lat, lon], {
        icon: L.divIcon({ html: beacon, className: "vh-ping-icon", iconSize: [34, 34], iconAnchor: [17, 17] }),
        keyboard: false, interactive: false,
      }).addTo(mini);
    } else {
      mini.setView([lat, lon], 7, { animate: false });
      mini.marker.setLatLng([lat, lon]);
    }
    // Leaflet measures a hidden container as zero, so the first centre lands off
    // target; re-centre once the element actually has a size.
    requestAnimationFrame(() => {
      mini.invalidateSize({ pan: false });
      mini.setView([lat, lon], 7, { animate: false });
    });
  }

  function boxState(container) {
    const first = (container.open_shipments || [])[0];
    return first && first.status === "draft" ? "draft" : "sent";
  }
  function isLate(container) {
    return (num(container.oldest_days_open) || 0) >= 15;
  }

  function renderBoxes(containers) {
    const rail = q("boxes");
    rail.replaceChildren();
    const shipments = containers.reduce((sum, c) => sum + (num(c.open_count) || 0), 0);
    q("boxes-count").textContent = containers.length
      ? `${containers.length} units · ${shipments} open`
      : "0 units";
    if (!containers.length) {
      rail.appendChild(el("p", "vh-hint", "No container is awaiting receipt."));
      return;
    }
    const busiest = Math.max(...containers.map((c) => num((c.open_shipments || [])[0]?.items) || 0), 1);
    containers.forEach((container, index) => {
      const shipment = (container.open_shipments || [])[0];
      const items = num(shipment?.items) || 0;
      const days = num(container.oldest_days_open) || 0;
      const button = el("button", "vh-box");
      button.type = "button";
      button.dataset.state = boxState(container);
      if (isLate(container)) button.dataset.late = "1";
      button.style.animationDelay = `${index * CARD_STAGGER_MS}ms`;
      button.title = shipment
        ? `${shipment.report} · ${shipment.origin} → ${shipment.destination}`
        : container.number;

      const can = el("span", "vh-can");
      // Fill height reads as how loaded the box is, relative to the biggest one.
      const load = el("span", "vh-can-load");
      load.style.height = `${Math.max(6, Math.round((items / busiest) * 100))}%`;
      can.appendChild(load);
      can.appendChild(el("span", "vh-can-id", container.number.slice(0, 12)));
      button.appendChild(can);

      const meta = el("span", "vh-box-meta");
      meta.appendChild(el("strong", "vh-box-name", container.number));
      meta.appendChild(el("span", "vh-box-owner", container.owner));
      const facts = el("span", "vh-box-facts");
      facts.appendChild(el("span", "", `${items} ${items === 1 ? "item" : "items"}`));
      const age = el("span", isLate(container) ? "vh-box-late" : "");
      age.textContent = `${days}d open`;
      facts.appendChild(age);
      meta.appendChild(facts);
      if (shipment) {
        meta.appendChild(el("span", "vh-box-route", `${shipment.origin} → ${shipment.destination}`));
      }
      button.appendChild(meta);
      button.addEventListener("click", () => selectBox(container, button));
      rail.appendChild(button);
    });
  }

  function itemsTable(items) {
    const table = el("table", "vh-table");
    const head = el("thead");
    const headRow = el("tr");
    [["#", "vh-col-n"], ["Description", ""], ["Code · RFID", "vh-col-code"],
     ["Qty", "vh-col-num"], ["Received", "vh-col-num"], ["Status", "vh-col-status"]]
      .forEach(([label, cls]) => headRow.appendChild(el("th", cls, label)));
    head.appendChild(headRow);
    table.appendChild(head);
    const body = el("tbody");
    items.forEach((item, index) => {
      const row = el("tr");
      row.style.animationDelay = `${Math.min(index, 30) * 14}ms`;
      row.appendChild(el("td", "vh-col-n", String(index + 1).padStart(2, "0")));
      row.appendChild(el("td", "", item.description));
      row.appendChild(el("td", "vh-col-code", [item.code, item.rfid].filter(Boolean).join(" · ") || "—"));
      const qty = num(item.quantity);
      const qtyCell = el("td", "vh-col-num",
        qty === null ? "—" : qty.toLocaleString("en-GB", { maximumFractionDigits: 3 }));
      if (item.unit) {
        qtyCell.appendChild(document.createTextNode(" "));
        qtyCell.appendChild(el("span", "vh-col-unit", item.unit));
      }
      row.appendChild(qtyCell);
      const got = num(item.received_quantity);
      row.appendChild(el("td", "vh-col-num",
        got === null ? "—" : got.toLocaleString("en-GB", { maximumFractionDigits: 3 })));
      const statusCell = el("td", "vh-col-status");
      const tag = el("span", "vh-tag", item.status_label);
      tag.dataset.state = item.status;
      statusCell.appendChild(tag);
      row.appendChild(statusCell);
      body.appendChild(row);
    });
    table.appendChild(body);
    return table;
  }

  function setProgress(checked, total) {
    const fill = q("progress");
    const pct = total ? Math.round((checked / total) * 100) : 0;
    fill.style.width = `${pct}%`;
    fill.dataset.complete = total && checked >= total ? "1" : "0";
    q("progress-num").textContent = `${checked} / ${total}`;
  }

  async function selectBox(container, button) {
    root.querySelectorAll(".vh-box.is-active").forEach((node) => node.classList.remove("is-active"));
    button.classList.add("is-active");
    state.activeBox = container;
    state.items = [];
    q("manifest").disabled = true;
    const shipment = (container.open_shipments || [])[0];
    const head = q("items-head");
    const body = q("items");
    head.hidden = false;
    q("items-dot").dataset.state = boxState(container);
    q("items-title").textContent = container.number;
    q("items-tag").textContent = container.owner;
    q("items-sub").textContent = shipment
      ? `${shipment.report} · ${shipment.origin} → ${shipment.destination} · ${shipment.days_open}d open`
      : "No open shipment";
    setProgress(0, 0);
    if (!shipment) {
      body.replaceChildren(el("p", "vh-hint", "This container has no open shipment."));
      return;
    }
    body.replaceChildren(el("p", "vh-hint", "Reading manifest…"));
    try {
      const data = await api(`shipments/${encodeURIComponent(shipment.id)}/items/`);
      const items = Array.isArray(data.items) ? data.items : [];
      body.replaceChildren();
      if (data.available === false) {
        body.appendChild(el("p", "vh-hint", data.detail || "Trackfy is unavailable."));
        return;
      }
      setProgress(num(data.checked) || 0, num(data.total_count) || items.length);
      if (!items.length) {
        body.appendChild(el("p", "vh-hint", `${shipment.report} has no item listed in Trackfy.`));
        return;
      }
      state.items = items;
      state.activeShipment = shipment;
      q("manifest").disabled = false;
      body.appendChild(itemsTable(items));
      const total = num(data.total_count);
      if (total !== null && total > items.length) {
        body.appendChild(el("p", "vh-items-note", `Showing ${items.length} of ${total} items.`));
      }
    } catch (error) {
      body.replaceChildren(el("p", "vh-hint", error.message || "Contents could not be loaded."));
    }
  }

  async function loadContainers() {
    try {
      const data = await api("containers/");
      state.containers = Array.isArray(data.containers) ? data.containers : [];
      renderBoxes(state.containers);
      // Open the most overdue container straight away: that is the one to chase.
      const first = root.querySelector(".vh-box");
      if (first && state.containers.length) selectBox(state.containers[0], first);
    } catch (error) {
      q("boxes").replaceChildren(el("p", "vh-hint", error.message || "Containers could not be loaded."));
    }
  }

  function open(vessel) {
    if (!vessel) return;
    state.vessel = vessel;
    state.restoreFocus = document.activeElement;
    q("name").textContent = vessel.name || "Unnamed vessel";
    q("subtitle").textContent = `MMSI ${vessel.mmsi}`;
    const status = q("status");
    const key = ["RECENT", "STALE", "NO_RECENT_AIS"].includes(vessel.status) ? vessel.status : "NO_RECENT_AIS";
    status.dataset.status = key;
    status.textContent = key.replace(/_/g, " ");
    renderFacts(vessel);
    showMiniMap(vessel);
    q("items-head").hidden = true;
    q("manifest").disabled = true;
    state.items = [];
    q("items").replaceChildren(el("p", "vh-hint", "Pick a container above to reveal what is inside it."));
    overlay.hidden = false;
    state.open = true;
    document.body.style.overflow = "hidden";
    hologram = new Hologram(q("stage"), q("stage-note"));
    // Fire and forget: a 3D failure must never block the dossier from opening.
    hologram.start(modelUrl).catch(() => {
      q("stage-note").textContent = "3D viewer could not be loaded. Vessel data is unaffected.";
    });
    q("close").focus();
    loadContainers();
  }

  function close() {
    if (!state.open) return;
    state.open = false;
    overlay.hidden = true;
    document.body.style.overflow = "";
    hologram?.stop();
    hologram = null;
    state.restoreFocus?.focus?.();
  }

  function csvCell(value) {
    const text = value === null || value === undefined ? "" : String(value);
    // A leading =, +, - or @ is read as a formula by spreadsheets; neutralise it.
    const guarded = /^[=+\-@]/.test(text) ? `'${text}` : text;
    return /[";\r\n]/.test(guarded) ? `"${guarded.replace(/"/g, '""')}"` : guarded;
  }

  function exportManifest() {
    const shipment = state.activeShipment;
    if (!state.items.length || !shipment) return;
    const columns = ["#", "CONTAINER", "REPORT", "DESCRIPTION", "CODE", "RFID", "QTY", "UNIT", "RECEIVED", "STATUS"];
    const lines = ["sep=;", columns.join(";")];
    state.items.forEach((item, index) => {
      lines.push([index + 1, state.activeBox?.number, shipment.report, item.description,
        item.code, item.rfid, item.quantity, item.unit, item.received_quantity, item.status_label]
        .map(csvCell).join(";"));
    });
    const blob = new Blob(["﻿" + lines.join("\r\n") + "\r\n"], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `${shipment.report}-manifest.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
  }

  q("locate").addEventListener("click", () => {
    close();
    // vessel-tracking.js owns the map; ask it to centre rather than reaching in.
    root.dispatchEvent(new CustomEvent("vt:zoom-vessel", { detail: state.vessel }));
  });
  q("manifest").addEventListener("click", exportManifest);
  q("close").addEventListener("click", close);
  overlay.addEventListener("mousedown", (event) => { if (event.target === overlay) close(); });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape" && state.open) close(); });
  root.addEventListener("vt:open-dossier", (event) => open(event.detail));
}

function bootstrap() {
  document.querySelectorAll("[data-vessel-tracking]").forEach(initDossier);
}
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", bootstrap);
else bootstrap();
