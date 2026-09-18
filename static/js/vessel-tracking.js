/* AIS positions stay authoritative. No prediction or location extrapolation. */
(function (global) {
  "use strict";

  var STATUS_LABELS = { RECENT: "RECENT", STALE: "STALE", NO_RECENT_AIS: "NO RECENT AIS" };
  var NAVIGATION = {
    0: "Under way using engine", 1: "At anchor", 2: "Not under command",
    3: "Restricted manoeuvrability", 4: "Constrained by draught", 5: "Moored",
    6: "Aground", 7: "Engaged in fishing", 8: "Under way sailing",
    9: "Reserved for HSC", 10: "Reserved for WIG", 11: "Towing astern",
    12: "Pushing ahead or towing alongside", 14: "AIS-SART active", 15: "Not defined"
  };
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  // Mirrors the AIS_STALE_SECONDS default the API uses to tag an imported observation.
  var STALE_SECONDS = 3600;
  var MAX_IMPORT_BYTES = 32 * 1024 * 1024;
  // Close enough to tell a berth from the next one along the quay.
  var VESSEL_ZOOM = 12;

  function number(value) {
    if (value === null || value === undefined || value === "" || typeof value === "boolean") return null;
    if (typeof value !== "number" && typeof value !== "string") return null;
    if (typeof value === "string" && !value.trim()) return null;
    var result = Number(value);
    return Number.isFinite(result) ? result : null;
  }
  function measurement(value, unit, digits) {
    var parsed = number(value);
    return parsed === null ? "—" : parsed.toLocaleString("en-GB", { maximumFractionDigits: digits === undefined ? 1 : digits }) + (unit || "");
  }
  function timestamp(value) {
    if (typeof value !== "string" || !value || !/(?:Z|[+-]\d{2}:\d{2})$/i.test(value)) return null;
    var parsed = Date.parse(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  function utcLabel(value) {
    var parsed = timestamp(value);
    if (parsed === null) return "—";
    var dt = new Date(parsed);
    function pad(part) { return String(part).padStart(2, "0"); }
    return pad(dt.getUTCDate()) + "/" + pad(dt.getUTCMonth() + 1) + "/" + dt.getUTCFullYear() + " " + pad(dt.getUTCHours()) + ":" + pad(dt.getUTCMinutes()) + " UTC";
  }
  function ageLabel(value, now) {
    var parsed = timestamp(value);
    if (parsed === null) return "No position";
    var seconds = Math.max(0, Math.floor(((now === undefined ? Date.now() : now) - parsed) / 1000));
    if (seconds < 60) return "Less than a minute ago";
    if (seconds < 3600) return Math.floor(seconds / 60) + " min ago";
    if (seconds < 86400) return Math.floor(seconds / 3600) + " h ago";
    return Math.floor(seconds / 86400) + " d ago";
  }
  function etaLabel(eta) {
    if (!eta || typeof eta !== "object") return "—";
    var month = number(eta.month), day = number(eta.day), hour = number(eta.hour), minute = number(eta.minute);
    var hasDate = Number.isInteger(month) && month >= 1 && month <= 12 && Number.isInteger(day) && day >= 1 && day <= 31;
    var hasTime = Number.isInteger(hour) && hour >= 0 && hour <= 23 && Number.isInteger(minute) && minute >= 0 && minute <= 59;
    var parts = [];
    if (hasDate) parts.push(String(day).padStart(2, "0") + " " + MONTHS[month - 1]);
    if (hasTime) parts.push(String(hour).padStart(2, "0") + ":" + String(minute).padStart(2, "0") + " UTC");
    return parts.length ? parts.join(" · ") : "—";
  }
  function position(value) {
    if (!value || value.source !== "AIS") return null;
    var lat = number(value.latitude), lon = number(value.longitude), time = timestamp(value.timestamp);
    if (lat === null || lon === null || time === null || Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
    return { latitude: lat, longitude: lon, timestamp: value.timestamp, time: time, original: value };
  }
  function bearing(value) {
    if (!value) return null;
    var heading = number(value.heading), cog = number(value.cog);
    if (heading !== null && heading >= 0 && heading < 360) return heading;
    return cog !== null && cog >= 0 && cog < 360 ? cog : null;
  }
  function trackPoints(values) {
    var seen = new Set();
    return (Array.isArray(values) ? values : []).map(position).filter(Boolean).sort(function (a, b) {
      return a.time - b.time || (number(a.original.id) || 0) - (number(b.original.id) || 0);
    }).filter(function (point) {
      var key = point.time + ":" + point.latitude + ":" + point.longitude;
      if (seen.has(key)) return false;
      seen.add(key);
      return true;
    });
  }
  function trackParts(points) {
    var parts = [], current = [];
    points.forEach(function (point) {
      // Do not draw a globe-spanning line through zero longitude at the date line.
      if (current.length && Math.abs(current[current.length - 1][1] - point.longitude) > 180) {
        parts.push(current);
        current = [];
      }
      current.push([point.latitude, point.longitude]);
    });
    if (current.length) parts.push(current);
    return parts;
  }
  function customRange(start, end) {
    function utc(value) {
      if (!/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2})?$/.test(value || "")) return null;
      return value + (value.length === 16 ? ":00Z" : "Z");
    }
    var first = utc(start), last = utc(end);
    if (!first || !last || timestamp(first) === null || timestamp(last) === null) throw new Error("Enter a start and end date in UTC.");
    if (timestamp(first) >= timestamp(last)) throw new Error("The end date must be after the start date.");
    return { start: first, end: last };
  }
  function statusKey(vessel) { return vessel && STATUS_LABELS[vessel.status] ? vessel.status : "NO_RECENT_AIS"; }
  function geofence(value) {
    if (!value || typeof value.name !== "string" || !value.name.trim()) return null;
    var lat = number(value.latitude), lon = number(value.longitude), radius = number(value.radius_m);
    if (lat === null || lon === null || radius === null || Math.abs(lat) > 90 || Math.abs(lon) > 180 || radius <= 0) return null;
    return { id: value.id, name: value.name, latitude: lat, longitude: lon, radius_m: radius };
  }
  function voyageDisplay(vessel) {
    vessel = vessel || {};
    var voyage = vessel.voyage && typeof vessel.voyage === "object" ? vessel.voyage : null;
    var current = position(vessel.last_position);
    var status = current && voyage && ["arrived", "underway"].indexOf(voyage.status) >= 0 ? voyage.status : "unknown";
    var label = { arrived: "Arrived", underway: "Underway", unknown: "Arrival not confirmed" }[status];
    if (status !== "unknown" && statusKey(vessel) !== "RECENT") label += " · last report";
    var nextDestination = status === "arrived" && voyage.next_destination && voyage.next_destination.name;
    var regularRoute = !!nextDestination || !!(voyage && voyage.destination_source === "scheduled_route");
    var destination = nextDestination || (voyage ? (voyage.destination && voyage.destination.name || "") : (vessel.destination || ""));
    return { status: status, status_label: label,
      origin: voyage && voyage.origin ? voyage.origin.name : "",
      current_port: status === "arrived" && voyage.current_port ? voyage.current_port.name : "",
      destination: destination,
      destination_title: nextDestination ? "Next destination" : "Destination",
      destination_label: destination || (status === "underway" ? "Next destination not reported" : "Not reported"),
      regular_route: regularRoute,
      eta: status === "arrived" || regularRoute || !destination ? "—" : etaLabel(vessel.eta),
      observed_at: current ? current.timestamp : null,
      arrived_at: voyage && voyage.arrived_at || null,
      departed_at: voyage && voyage.departed_at || null };
  }
  function navigationLabel(value) {
    var parsed = number(value);
    return parsed !== null && Object.prototype.hasOwnProperty.call(NAVIGATION, parsed) ? NAVIGATION[parsed] : "—";
  }
  function apiError(data, fallback) {
    if (data && typeof data.detail === "string") return data.detail;
    if (data && typeof data === "object") {
      var messages = Object.keys(data).filter(function (key) { return Array.isArray(data[key]); }).map(function (key) {
        return key.replace(/_/g, " ") + ": " + data[key].filter(function (value) { return typeof value === "string"; }).join(" ");
      });
      if (messages.length) return messages.join(" · ");
    }
    return fallback;
  }

  function attachmentName(header) {
    if (typeof header !== "string") return null;
    var match = /filename\*\s*=\s*utf-8''([^;\s]+)/i.exec(header), raw = "";
    if (match) { try { raw = decodeURIComponent(match[1]); } catch (_error) { raw = ""; } }
    if (!raw) {
      match = /filename\s*=\s*"([^"]+)"/i.exec(header) || /filename\s*=\s*([^;]+)/i.exec(header);
      raw = match ? match[1] : "";
    }
    // A server-supplied name is only trusted as a plain file name, never as a path.
    raw = String(raw).trim().replace(/^.*[\\/]/, "");
    return /^[A-Za-z0-9](?:[A-Za-z0-9._ -]*[A-Za-z0-9])?$/.test(raw) ? raw : null;
  }

  var helpers = { number: number, measurement: measurement, timestamp: timestamp, utcLabel: utcLabel,
    ageLabel: ageLabel, etaLabel: etaLabel, position: position, bearing: bearing,
    trackPoints: trackPoints, trackParts: trackParts, customRange: customRange, apiError: apiError,
    attachmentName: attachmentName, geofence: geofence, voyageDisplay: voyageDisplay };
  if (typeof module === "object" && module.exports) module.exports = helpers;
  if (!global.document) return;

  function init(root) {
    if (root.dataset.vtInitialized) return;
    root.dataset.vtInitialized = "1";
    var doc = global.document;
    function query(name) { return root.querySelector("[data-vt-" + name + "]"); }
    function text(node, value) { if (node) node.textContent = value === null || value === undefined || value === "" ? "—" : String(value); }
    function element(tag, className, value) {
      var node = doc.createElement(tag);
      if (className) node.className = className;
      if (value !== undefined) text(node, value);
      return node;
    }
    var config = {};
    try { config = JSON.parse((doc.getElementById("vesselTrackingConfig") || {}).textContent || "{}"); } catch (_error) { config = {}; }
    var pollMs = Math.min(30, Math.max(10, number(config.poll_seconds) || 20)) * 1000;
    var base = root.dataset.apiBase || "/vessels/api/";
    var map = null, tiles = null, markers = new Map(), lineLayer = null, geofenceLayer = null;
    var state = { vessels: [], selected: null, canManage: false, range: "all", custom: {}, points: [],
      active: false, visible: false, busy: false, timer: null, controllers: new Set(), generation: 0,
      historyController: null, editing: null, saving: false, mapFitted: false, loaded: false, refreshQueued: false,
      containers: [], containersLoading: false,
      exporting: false, importing: false };
    var fleetList = query("fleet"), dialog = query("dialog"), form = query("form");
    var importDialog = query("import-dialog"), importForm = query("import-form");
    var fleetButtons = new Map();

    async function request(path, options) {
      options = options || {};
      var controller = options.controller || new AbortController(), timedOut = false;
      // Visibility changes cancel polling, never a submitted fleet change.
      if (!options.body) state.controllers.add(controller);
      var timeout = global.setTimeout(function () { timedOut = true; controller.abort(); }, 15000);
      var headers = { Accept: "application/json" };
      if (options.body) {
        headers["Content-Type"] = "application/json";
        headers["X-CSRFToken"] = (form.querySelector('[name="csrfmiddlewaretoken"]') || {}).value || "";
      }
      try {
        var response = await global.fetch(base + path, { method: options.method || "GET", headers: headers,
          credentials: "same-origin", signal: controller.signal, body: options.body ? JSON.stringify(options.body) : undefined });
        var data;
        try { data = await response.json(); } catch (_error) { data = {}; }
        if (!response.ok) throw new Error(apiError(data, response.status === 403 || response.status === 401 ? "Your session or permissions do not allow this request. Refresh the page to sign in again." : "Vessel data could not be loaded. Try again."));
        if (response.redirected || String(response.headers.get("content-type") || "").indexOf("application/json") < 0) throw new Error("Your session has expired. Refresh the page to sign in again.");
        return data;
      } catch (error) {
        if (timedOut) throw new Error("The AIS data request timed out. Try again.");
        throw error;
      } finally {
        global.clearTimeout(timeout);
        state.controllers.delete(controller);
      }
    }
    function selectedVessel() { return state.vessels.find(function (item) { return item.id === state.selected; }) || null; }
    function errorMessage(message) { text(query("error-text"), message); query("error").hidden = !message; }
    function collectionStatus(collection) {
      collection = collection || {};
      var label, status = collection.status;
      if (!collection.configured || status === "not_configured") label = "AIS collection is not configured. An administrator must connect AISStream on the server.";
      else label = {
        connected: "AIS collector connected · Positions appear when a vessel is within reception coverage.",
        connecting: "AIS collector connecting…", reconnecting: "AIS collector reconnecting · Last received positions are retained.",
        idle: "AIS collector ready · Add or activate a vessel to begin tracking.",
        stopped: "AIS collector stopped · Previously received positions remain available.",
        unavailable: "AIS collector heartbeat is overdue · Last received positions are retained.",
        configuration_error: "AIS collection needs an administrator to check the server configuration."
      }[status] || "AIS collector status is unavailable · Last received positions are retained.";
      text(query("collection-text"), label);
      query("collection").dataset.state = status === "connected" && collection.configured ? "connected" : "warning";
      query("collection").title = collection.last_heartbeat ? "Collector heartbeat: " + utcLabel(collection.last_heartbeat) : "";
    }
    function popup(vessel) {
      var content = element("div", "vt-popup"), pos = vessel.last_position || {}, voyage = voyageDisplay(vessel);
      content.appendChild(element("strong", "", vessel.name));
      content.appendChild(element("small", "", "MMSI " + vessel.mmsi + " · " + STATUS_LABELS[statusKey(vessel)]));
      var rows = [ ["Last AIS position", utcLabel(pos.timestamp)], ["Journey", voyage.status_label],
        ["Origin", voyage.origin || "Not recorded"], ["Speed", measurement(pos.sog, " kn")],
        ["Course", measurement(pos.cog, "°")], [voyage.destination_title, voyage.destination_label], ["ETA · declared", voyage.eta] ];
      var list = element("dl");
      rows.forEach(function (row) { list.appendChild(element("dt", "", row[0])); list.appendChild(element("dd", "", row[1])); });
      content.appendChild(list);
      content.appendChild(element("small", "", (voyage.regular_route ? "Next port follows the regular route. " : "") + "Arrival is based on the last position inside a port radius. AIS ETA has no year."));
      return content;
    }
    function boatIcon(vessel) {
      var wrap = element("div", "vt-boat" + (vessel.id === state.selected ? " is-selected" : ""));
      wrap.dataset.status = statusKey(vessel);
      wrap.setAttribute("aria-hidden", "true");
      wrap.appendChild(element("span", "vt-boat-dot"));
      return global.L.divIcon({ html: wrap, className: "vt-boat-icon", iconSize: [28, 28], iconAnchor: [14, 14], popupAnchor: [0, -16] });
    }
    function ensureMap() {
      if (map) { map.invalidateSize({ pan: false }); return; }
      if (!global.L) {
        text(query("map-empty-title"), "Map unavailable");
        text(query("map-empty-text"), "The map library could not load. Vessel details are still available.");
        return;
      }
      map = global.L.map(query("map"), { center: [4, 5], zoom: 5, minZoom: 2, preferCanvas: true, scrollWheelZoom: true, zoomAnimation: false, markerZoomAnimation: false });
      var tileUrl = typeof config.tile_url === "string" && config.tile_url.indexOf("https://") === 0 ? config.tile_url : "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
      // Attribution is a fixed public-source link; no API or vessel text is inserted as HTML.
      var attribution = '&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">OpenStreetMap</a> contributors';
      if (config.tile_attribution && tileUrl.indexOf("tile.openstreetmap.org/") < 0) attribution = element("span", "", config.tile_attribution).outerHTML;
      tiles = global.L.tileLayer(tileUrl, { maxZoom: 19, attribution: attribution,
        className: "vt-tiles-base", referrerPolicy: "strict-origin-when-cross-origin" }).addTo(map);
      // Place names ride on their own transparent layer above the recoloured
      // basemap, so the sea/land filter never touches the lettering.
      var labelsUrl = typeof config.labels_url === "string" && config.labels_url.indexOf("https://") === 0 ? config.labels_url : "";
      if (labelsUrl) {
        global.L.tileLayer(labelsUrl, { maxZoom: 19, className: "vt-tiles-labels", pane: "overlayPane",
          referrerPolicy: "strict-origin-when-cross-origin" }).addTo(map);
      }
      tiles.on("tileerror", function () { query("tile-error").hidden = false; });
      tiles.on("tileload", function () { query("tile-error").hidden = true; });
      map.on("dragstart", function () { query("follow").checked = false; });
      syncWheelZoom();
      global.L.control.scale({ imperial: false }).addTo(map);
      global.requestAnimationFrame(function () { map.invalidateSize({ pan: false }); });
    }
    function renderMarkers() {
      if (!map) return;
      renderGeofences();
      var retained = new Set();
      state.vessels.forEach(function (vessel) {
        var pos = position(vessel.last_position);
        if (!pos) return;
        retained.add(vessel.id);
        var marker = markers.get(vessel.id);
        if (!marker) {
          marker = global.L.marker([pos.latitude, pos.longitude], { icon: boatIcon(vessel), title: vessel.name + " · MMSI " + vessel.mmsi, keyboard: true }).addTo(map);
          marker.on("click", function () {
            selectVessel(vessel.id, false);
            // The dossier module listens on the section root and owns the modal.
            var current = state.vessels.find(function (item) { return item.id === vessel.id; }) || vessel;
            root.dispatchEvent(new global.CustomEvent("vt:open-dossier", { detail: current }));
          });
          marker.bindPopup(popup(vessel), { maxWidth: 310 });
          markers.set(vessel.id, marker);
        } else {
          marker.setLatLng([pos.latitude, pos.longitude]);
          marker.setIcon(boatIcon(vessel));
          marker.setPopupContent(popup(vessel));
        }
        marker.setZIndexOffset(vessel.id === state.selected ? 1000 : 0);
        var markerElement = marker.getElement();
        if (markerElement) {
          var markerLabel = vessel.name + " · MMSI " + vessel.mmsi + " · " + STATUS_LABELS[statusKey(vessel)] + (bearing(vessel.last_position) === null ? " · Heading unavailable" : "");
          markerElement.setAttribute("title", markerLabel);
          markerElement.setAttribute("aria-label", markerLabel);
        }
      });
      markers.forEach(function (marker, id) { if (!retained.has(id)) { marker.remove(); markers.delete(id); } });
      query("map-empty").hidden = retained.size > 0;
      if (!retained.size) {
        text(query("map-empty-title"), state.vessels.length ? "No AIS positions yet" : "No vessels tracked");
        text(query("map-empty-text"), state.vessels.length ? "The collector is waiting for a position from a tracked MMSI." : "Register a vessel by MMSI to begin collecting its track history.");
      }
      var current = selectedVessel(), selected = current && position(current.last_position);
      var hasPorts = geofenceLayer && geofenceLayer.getBounds().isValid();
      query("fit").disabled = !state.points.length && !selected && !hasPorts;
      if (!state.mapFitted && hasPorts) {
        // Start with both route ends visible; following or zooming remains an explicit action.
        fitTrack();
      } else if (selected && query("follow").checked) {
        map.setView([selected.latitude, selected.longitude], state.mapFitted ? map.getZoom() : VESSEL_ZOOM, { animate: false });
        state.mapFitted = true;
      }
    }
    function renderFleet() {
      var search = query("search").value.trim().toLowerCase();
      var visible = state.vessels.filter(function (item) { return !search || String(item.name + " " + item.mmsi).toLowerCase().indexOf(search) >= 0; });
      text(query("fleet-count"), state.vessels.filter(function (item) { return item.is_active; }).length + " tracked · " + state.vessels.length + " total");
      var keep = new Set();
      visible.forEach(function (vessel) {
        keep.add(vessel.id);
        var button = fleetButtons.get(vessel.id);
        if (!button) {
          button = element("button", "vt-vessel"); button.type = "button";
          var top = element("span", "vt-vessel-top"), bottom = element("span", "vt-vessel-bottom");
          top.appendChild(element("span", "vt-vessel-name")); top.appendChild(element("span", "vt-status"));
          bottom.appendChild(element("span", "vt-vessel-mmsi")); bottom.appendChild(element("span", "vt-vessel-age"));
          button.appendChild(top); button.appendChild(bottom);
          button.addEventListener("click", function () { selectVessel(vessel.id, true); });
          fleetButtons.set(vessel.id, button);
        }
        text(button.querySelector(".vt-vessel-name"), vessel.name);
        text(button.querySelector(".vt-vessel-mmsi"), vessel.mmsi + (vessel.is_active ? "" : " · Paused"));
        text(button.querySelector(".vt-vessel-age"), ageLabel((vessel.last_position || {}).timestamp));
        var badge = button.querySelector(".vt-status"); badge.dataset.status = statusKey(vessel); text(badge, STATUS_LABELS[statusKey(vessel)]);
        button.setAttribute("aria-pressed", String(vessel.id === state.selected));
        button.setAttribute("aria-label", vessel.name + ", MMSI " + vessel.mmsi + ", " + STATUS_LABELS[statusKey(vessel)] + (vessel.is_active ? "" : ", tracking paused"));
        if (!button.parentNode) fleetList.appendChild(button);
      });
      fleetButtons.forEach(function (button, id) { if (!keep.has(id)) { button.remove(); fleetButtons.delete(id); } });
      var empty = fleetList.querySelector(".vt-empty-copy");
      if (empty) empty.remove();
      if (!visible.length) fleetList.appendChild(element("p", "vt-empty-copy", search ? "No vessels match your search." : "No vessels registered. Add a vessel to begin tracking."));
    }
    function renderDetails() {
      var vessel = selectedVessel(), pos = vessel && position(vessel.last_position), raw = pos ? pos.original : {}, voyage = voyageDisplay(vessel);
      text(query("name"), vessel ? vessel.name : "Select a vessel");
      text(query("identity"), "MMSI " + (vessel ? vessel.mmsi : "—"));
      query("status").dataset.status = statusKey(vessel); text(query("status"), STATUS_LABELS[statusKey(vessel)]);
      text(query("last-seen"), "Last AIS position: " + (pos ? utcLabel(pos.timestamp) + " · " + ageLabel(pos.timestamp) : "—"));
      var values = { position: pos ? pos.latitude.toFixed(5) + ", " + pos.longitude.toFixed(5) : "—",
        sog: measurement(raw.sog, " kn"), cog: measurement(raw.cog, "°"), heading: measurement(raw.heading, "°"),
        navigation: navigationLabel(raw.navigational_status), draught: measurement(vessel && vessel.draught, " m"),
        journey: vessel ? voyage.status_label : "—", origin: vessel ? voyage.origin || "Not recorded" : "—",
        destination: vessel ? voyage.destination_label : "—", eta: voyage.eta, type: vessel && vessel.vessel_type, imo: vessel && vessel.imo };
      root.querySelectorAll("[data-vt-detail]").forEach(function (node) { text(node, values[node.dataset.vtDetail]); });
      text(query("destination-label"), voyage.destination_title);
      text(query("destination-source"), voyage.regular_route ? "Regular route" : "");
      if (query("destination-source")) query("destination-source").hidden = !voyage.regular_route;
      var journeyNode = root.querySelector('[data-vt-detail="journey"]');
      if (journeyNode) journeyNode.dataset.state = voyage.status;
      endpointSummary();
      query("edit").hidden = !state.canManage || !vessel;
      query("add").hidden = !state.canManage;
      query("import").hidden = !state.canManage;
      query("export-track").disabled = !vessel || state.exporting;
      query("zoom-vessel").disabled = !position((vessel || {}).last_position);
    }
    function clearTrack() {
      state.points = [];
      if (lineLayer) { lineLayer.remove(); lineLayer = null; }
      var node = query("endpoints");
      if (node) endpointSummary();
    }
    function renderGeofences() {
      if (geofenceLayer) { geofenceLayer.remove(); geofenceLayer = null; }
      var vessel = selectedVessel(), voyage = vessel && vessel.voyage;
      var sites = voyage && Array.isArray(voyage.geofences) ? voyage.geofences.map(geofence).filter(Boolean) : [];
      if (!map || !sites.length) return;
      // Port radii belong to the voyage, independently of the selected history period.
      geofenceLayer = global.L.featureGroup().addTo(map);
      sites.forEach(function (site) {
        var content = element("div", "vt-popup");
        content.appendChild(element("strong", "", site.name));
        content.appendChild(element("small", "", "Arrival radius · " + measurement(site.radius_m / 1000, " km", 2)));
        content.appendChild(element("small", "", "A received position inside this area records arrival."));
        global.L.circle([site.latitude, site.longitude], { radius: site.radius_m,
          color: "#22d3ee", weight: 2, opacity: .8, dashArray: "6 5", fillColor: "#22d3ee", fillOpacity: .07 })
          .bindPopup(content, { maxWidth: 280 }).addTo(geofenceLayer);
        global.L.circleMarker([site.latitude, site.longitude], { radius: 4,
          color: "#22d3ee", weight: 2, fillColor: "#0f172a", fillOpacity: 1 })
          .bindTooltip(element("span", "", site.name + " · " + measurement(site.radius_m / 1000, " km", 2)),
            { permanent: true, direction: "top", className: "vt-port-label", offset: [0, -8] })
          .bindPopup(content, { maxWidth: 280 }).addTo(geofenceLayer);
      });
    }
    function endpointMarker(point, kind) {
      // Labelled ends of the stored track: the oldest observation in the period and
      // the newest. Both are received AIS positions, never an inferred port call.
      var origin = kind === "origin";
      var wrap = element("div", "vt-endpoint" + (origin ? " is-origin" : " is-latest"), origin ? "1" : "");
      var icon = global.L.divIcon({ html: wrap, className: "vt-endpoint-icon", iconSize: [22, 22], iconAnchor: [11, 11], popupAnchor: [0, -14] });
      var marker = global.L.marker([point.latitude, point.longitude], { icon: icon, keyboard: false,
        title: (origin ? "First stored position" : "Latest stored position") + " · " + utcLabel(point.timestamp) });
      var content = element("div", "vt-popup");
      content.appendChild(element("strong", "", origin ? "First stored position" : "Latest stored position"));
      content.appendChild(element("small", "", utcLabel(point.timestamp)));
      var list = element("dl");
      list.appendChild(element("dt", "", "Position"));
      list.appendChild(element("dd", "", point.latitude.toFixed(5) + ", " + point.longitude.toFixed(5)));
      list.appendChild(element("dt", "", "Received"));
      list.appendChild(element("dd", "", ageLabel(point.timestamp)));
      content.appendChild(list);
      marker.bindPopup(content, { maxWidth: 260 });
      return marker;
    }
    function drawEndpoints() {
      if (!lineLayer || state.points.length < 1) return;
      var first = state.points[0], latest = position((selectedVessel() || {}).last_position);
      // Keep the blue vessel dot unobstructed when it is still at the origin.
      if (!latest || first.latitude !== latest.latitude || first.longitude !== latest.longitude) {
        endpointMarker(first, "origin").addTo(lineLayer);
      }
    }
    function endpointSummary() {
      var node = query("endpoints"), vessel = selectedVessel();
      if (!node) return;
      node.replaceChildren();
      node.hidden = !vessel;
      if (!vessel) return;
      var current = position(vessel.last_position), voyage = voyageDisplay(vessel);
      function coordinates(point) { return point ? point.latitude.toFixed(5) + ", " + point.longitude.toFixed(5) : "No position received"; }
      var entries = [
        ["A", "is-origin", "Origin", voyage.origin || "Not recorded", voyage.departed_at ? "Departure observed · " + utcLabel(voyage.departed_at) : "Awaiting a recorded departure", "Last port left according to received positions; independent of the history period."],
        ["", "is-latest" + (voyage.status === "arrived" ? " is-arrived" : ""), voyage.status === "unknown" ? "Last position" : voyage.status_label, voyage.current_port || coordinates(current), current ? "Observed · " + utcLabel(current.timestamp) : "Awaiting AIS", "Arrival and departure use the last received position and the configured port radius."],
        ["B", "is-destination", voyage.destination_title, voyage.destination_label, voyage.regular_route ? "Regular route" : voyage.status === "arrived" ? "Arrival observed · " + utcLabel(voyage.arrived_at || voyage.observed_at) : voyage.destination ? "ETA · " + voyage.eta : "Awaiting a new destination", voyage.regular_route ? "Next port on the configured regular route; arrival and departure require received positions." : "A destination equal to the port just left is cleared until a new destination is reported."]
      ];
      entries.forEach(function (entry) {
        var row = element("div", "vt-endpoint-row");
        row.title = entry[5];
        row.appendChild(element("span", "vt-endpoint " + entry[1], entry[0] || undefined));
        var copy = element("div", "vt-endpoint-copy");
        copy.appendChild(element("small", "", entry[2]));
        copy.appendChild(element("strong", "", entry[3]));
        copy.appendChild(element("span", "", entry[4]));
        row.appendChild(copy);
        node.appendChild(row);
      });
    }
    function renderTrack(data) {
      clearTrack();
      state.points = trackPoints(data.positions);
      if (map && state.points.length) {
        query("map-empty").hidden = true;
        lineLayer = global.L.layerGroup().addTo(map);
        trackParts(state.points).forEach(function (part) {
          if (part.length > 1) global.L.polyline(part, { color: "#3b82f6", weight: 3, opacity: .9, dashArray: "5 7", smoothFactor: 0, interactive: false }).addTo(lineLayer);
          if (part.length === 1) global.L.circleMarker(part[0], { radius: 3, color: "#0284c7", fillOpacity: .8, interactive: false }).addTo(lineLayer);
        });
        drawEndpoints();
      }
      var total = number(data.total_count), count = state.points.length;
      var label = count ? count.toLocaleString("en-GB") + (data.simplified && total !== null ? " of " + total.toLocaleString("en-GB") : "") + " stored positions" + (data.simplified ? " · Simplified track" : " · Real track") : "No stored AIS positions in this period.";
      text(query("track-meta"), label);
      query("track-meta").title = data.start && data.end ? utcLabel(data.start) + " to " + utcLabel(data.end) : "";
      query("fit").disabled = !count && !position((selectedVessel() || {}).last_position) && !(geofenceLayer && geofenceLayer.getBounds().isValid());
      endpointSummary();
      if (count && !state.mapFitted) fitTrack();
    }
    async function loadTrack() {
      if (state.historyController) state.historyController.abort();
      if (state.selected === null) {
        clearTrack(); text(query("track-meta"), "Choose a vessel to view its stored history.");
        query("track-meta").title = ""; query("fit").disabled = true; return;
      }
      if (!state.active) { clearTrack(); return; }
      var id = state.selected, generation = state.generation;
      var params = historyParams();
      var controller = new AbortController(); state.historyController = controller;
      try {
        var data = await request("vessels/" + encodeURIComponent(id) + "/positions/?" + params.toString(), { controller: controller });
        if (state.active && state.selected === id && state.generation === generation) renderTrack(data);
      } catch (error) {
        if (error.name !== "AbortError" && state.active && state.selected === id && generation === state.generation) {
          text(query("track-meta"), "Track history could not be refreshed."); errorMessage(error.message);
        }
      }
    }
    function selectVessel(id, center) {
      if (id !== state.selected) {
        state.selected = id; state.generation += 1; clearTrack();
        text(query("track-meta"), "Loading stored track…");
        renderFleet(); renderDetails(); renderMarkers(); loadTrack();
      }
      var vessel = selectedVessel(), pos = vessel && position(vessel.last_position);
      if (center && map && pos) { map.setView([pos.latitude, pos.longitude], Math.max(map.getZoom(), 8), { animate: false }); state.mapFitted = true; }
    }
    function fitTrack() {
      if (!map) return;
      var coords = state.points.map(function (point) { return [point.latitude, point.longitude]; });
      if (!coords.length) {
        var pos = position((selectedVessel() || {}).last_position);
        if (pos) coords.push([pos.latitude, pos.longitude]);
      }
      var bounds = global.L.latLngBounds(coords);
      // Keep the full arrival area visible even when several reports share one berth.
      if (geofenceLayer && geofenceLayer.getBounds().isValid()) bounds.extend(geofenceLayer.getBounds());
      if (!bounds.isValid()) return;
      query("follow").checked = false;
      map.fitBounds(bounds, { padding: [30, 30], maxZoom: 13, animate: false });
      state.mapFitted = true;
    }
    function syncWheelZoom() {
      if (!map || !map.scrollWheelZoom) return;
      // Off by default: an unguarded wheel over a full-width map hijacks page scrolling.
      if (query("scroll") && query("scroll").checked) map.scrollWheelZoom.enable();
      else map.scrollWheelZoom.disable();
    }
    function zoomToVessel() {
      var pos = position((selectedVessel() || {}).last_position);
      if (!map || !pos) return;
      map.setView([pos.latitude, pos.longitude], Math.max(map.getZoom(), VESSEL_ZOOM), { animate: false });
      state.mapFitted = true;
    }
    function itemRow(item) {
      var row = element("li", "vt-item");
      var state = element("span", "vt-item-state", item.status_label);
      state.dataset.state = item.status;
      row.appendChild(state);
      var body = element("span", "vt-item-body");
      body.appendChild(element("strong", "", item.description));
      var code = [item.code, item.rfid].filter(Boolean).join(" · ");
      if (code) body.appendChild(element("small", "", code));
      row.appendChild(body);
      var qty = number(item.quantity);
      var received = number(item.received_quantity);
      var label = (qty === null ? "—" : qty.toLocaleString("en-GB", { maximumFractionDigits: 3 }))
        + (item.unit ? " " + item.unit : "");
      if (received !== null && received !== qty) {
        label += " (got " + received.toLocaleString("en-GB", { maximumFractionDigits: 3 }) + ")";
      }
      row.appendChild(element("span", "vt-item-qty", label));
      return row;
    }
    async function loadItems(shipment, panel, button) {
      if (panel.dataset.loaded === "1") return;
      panel.replaceChildren(element("p", "vt-item-note", "Loading contents…"));
      try {
        var data = await request("shipments/" + encodeURIComponent(shipment.id) + "/items/");
        panel.replaceChildren();
        var items = Array.isArray(data.items) ? data.items : [];
        if (data.available === false) {
          panel.appendChild(element("p", "vt-item-note", data.detail || "Trackfy is unavailable."));
          return;
        }
        if (!items.length) {
          panel.appendChild(element("p", "vt-item-note", "This shipment has no item listed in Trackfy."));
        } else {
          var list = element("ul", "vt-item-list");
          items.forEach(function (item) { list.appendChild(itemRow(item)); });
          panel.appendChild(list);
          var total = number(data.total_count), shown = items.length;
          if (total !== null && total > shown) {
            panel.appendChild(element("p", "vt-item-note", "Showing " + shown + " of " + total + " items."));
          }
        }
        panel.dataset.loaded = "1";
      } catch (error) {
        if (error.name !== "AbortError") {
          panel.replaceChildren(element("p", "vt-item-note", error.message || "Contents could not be loaded."));
        }
      } finally {
        if (button) button.disabled = false;
      }
    }
    function shipmentRow(shipment) {
      var row = element("div", "vt-shipment");
      var head = element("button", "vt-shipment-head");
      head.type = "button";
      head.setAttribute("aria-expanded", "false");
      var top = element("span", "vt-shipment-top");
      top.appendChild(element("strong", "", shipment.report));
      var state = element("span", "vt-shipment-state", shipment.status_label);
      state.dataset.state = shipment.status;
      top.appendChild(state);
      head.appendChild(top);
      head.appendChild(element("span", "vt-shipment-route", shipment.origin + " → " + shipment.destination));
      var meta = element("span", "vt-shipment-meta");
      var days = number(shipment.days_open) || 0;
      var age = element("span", "vt-shipment-age", days + (days === 1 ? " day open" : " days open"));
      if (days >= 15) age.dataset.state = "late";
      meta.appendChild(age);
      var count = number(shipment.items) || 0;
      meta.appendChild(element("span", "vt-shipment-items", count + (count === 1 ? " item" : " items")));
      if (number(shipment.issues)) meta.appendChild(element("span", "vt-shipment-issues", shipment.issues + " with issues"));
      meta.appendChild(element("span", "", "Sent " + (shipment.sent || "—")));
      head.appendChild(meta);
      head.appendChild(element("span", "vt-shipment-more", count ? "View contents" : "No contents listed"));
      row.appendChild(head);
      var panel = element("div", "vt-items");
      panel.hidden = true;
      row.appendChild(panel);
      head.addEventListener("click", function () {
        var opening = panel.hidden;
        panel.hidden = !opening;
        head.setAttribute("aria-expanded", String(opening));
        row.classList.toggle("is-open", opening);
        text(query("containers") ? head.querySelector(".vt-shipment-more") : null,
             opening ? "Hide contents" : (count ? "View contents" : "No contents listed"));
        if (opening) { head.disabled = true; loadItems(shipment, panel, head); }
      });
      return row;
    }
    function containerRow(container, expanded) {
      // Every field here comes from Trackfy; it is written as text, never as markup.
      var item = element("div", "vt-container");
      var head = element("button", "vt-container-head");
      head.type = "button";
      var identity = element("span", "vt-container-identity");
      identity.appendChild(element("strong", "", container.number));
      identity.appendChild(element("small", "", container.owner + " · " + container.status));
      head.appendChild(identity);
      var count = number(container.open_count) || 0;
      var badge = element("span", "vt-container-badge", count ? count + (count === 1 ? " open" : " open") : "None open");
      badge.dataset.state = count ? (number(container.oldest_days_open) >= 15 ? "late" : "open") : "idle";
      head.appendChild(badge);
      head.appendChild(element("i", "bi bi-chevron-down vt-container-caret"));
      var body = element("div", "vt-container-body");
      body.hidden = !expanded;
      head.setAttribute("aria-expanded", String(!!expanded));
      if (expanded) item.classList.add("is-open");
      head.addEventListener("click", function () {
        var open = body.hidden;
        body.hidden = !open;
        head.setAttribute("aria-expanded", String(open));
        item.classList.toggle("is-open", open);
      });
      if (!count) {
        body.appendChild(element("p", "vt-container-empty", "No open shipment for this container."));
      } else {
        (container.open_shipments || []).forEach(function (shipment) {
          body.appendChild(shipmentRow(shipment));
        });
      }
      item.appendChild(head);
      item.appendChild(body);
      return item;
    }
    function renderContainers() {
      var list = query("containers-list");
      var search = (query("containers-search").value || "").trim().toLowerCase();
      var matches = state.containers.filter(function (container) {
        if (!search) return true;
        var haystack = [container.number, container.owner, container.status]
          .concat((container.open_shipments || []).map(function (s) { return s.report + " " + s.origin + " " + s.destination; }))
          .join(" ").toLowerCase();
        return haystack.indexOf(search) >= 0;
      });
      list.replaceChildren();
      if (!matches.length) {
        list.appendChild(element("p", "vt-container-empty", state.containers.length
          ? "No container matches this search." : "No container was returned by Trackfy."));
        return;
      }
      matches.forEach(function (container, index) {
        // With a short list the shipments are the point; hiding them behind a
        // second click makes the panel look empty.
        list.appendChild(containerRow(container, matches.length <= 8 || index === 0));
      });
    }
    async function loadContainers() {
      if (state.containersLoading) return;
      state.containersLoading = true;
      text(query("containers-summary"), "Loading containers…");
      try {
        var data = await request("containers/");
        state.containers = Array.isArray(data.containers) ? data.containers : [];
        var totals = data.totals || {};
        var withOpen = number(totals.with_open) || 0, fleet = number(totals.fleet) || 0;
        text(query("containers-summary"), data.available === false
          ? (data.detail || "Trackfy is unavailable.")
          : withOpen === 0
            ? "No container has an open shipment" + (fleet ? " · fleet of " + fleet : "")
            : withOpen + (withOpen === 1 ? " container" : " containers") + " awaiting receipt · "
              + (number(totals.open_shipments) || 0) + " open shipment"
              + ((number(totals.open_shipments) || 0) === 1 ? "" : "s")
              + (fleet ? " · fleet of " + fleet : ""));
        renderContainers();
      } catch (error) {
        if (error.name !== "AbortError") {
          state.containers = [];
          text(query("containers-summary"), error.message || "Containers could not be loaded.");
          renderContainers();
        }
      } finally { state.containersLoading = false; }
    }
    function openContainers() {
      query("containers").hidden = false;
      query("containers-open").setAttribute("aria-expanded", "true");
      loadContainers();
    }
    function closeContainers() {
      query("containers").hidden = true;
      query("containers-open").setAttribute("aria-expanded", "false");
    }
    function scheduleRefresh() {
      global.clearTimeout(state.timer);
      if (state.active) state.timer = global.setTimeout(refresh, state.refreshQueued ? 0 : pollMs);
      state.refreshQueued = false;
    }
    async function refresh() {
      if (!state.active || state.busy) return;
      state.busy = true; query("retry").disabled = true;
      try {
        var data = await request("vessels/");
        if (!state.active) return;
        state.vessels = Array.isArray(data.vessels) ? data.vessels : [];
        state.canManage = data.can_manage === true; state.loaded = true;
        if (!selectedVessel()) {
          var first = state.vessels.find(function (item) { return item.is_active; }) || state.vessels[0];
          state.selected = first ? first.id : null; state.generation += 1; clearTrack();
        }
        errorMessage(""); collectionStatus(data.collection); renderFleet(); renderDetails(); renderMarkers();
        text(query("refreshed"), "Updated " + utcLabel(new Date().toISOString()));
        if (state.selected !== null) await loadTrack();
        else text(query("track-meta"), "Choose a vessel to view its stored history.");
      } catch (error) {
        if (error.name !== "AbortError" && state.active) {
          errorMessage(error.message || "Vessel data could not be loaded.");
          if (!state.loaded) { fleetList.replaceChildren(element("p", "vt-empty-copy", "Fleet data is unavailable. Use Retry to reconnect.")); text(query("collection-text"), "AIS collection status could not be loaded."); }
        }
      } finally {
        state.busy = false; query("retry").disabled = false; scheduleRefresh();
      }
    }
    function setActive(active) {
      if (state.active === active) return;
      state.active = active;
      if (active) { ensureMap(); refresh(); }
      else {
        global.clearTimeout(state.timer); state.generation += 1;
        state.controllers.forEach(function (controller) { controller.abort(); });
      }
    }
    function openForm(vessel) {
      if (!state.canManage || state.saving || !dialog || typeof dialog.showModal !== "function") return;
      state.editing = vessel || null; form.reset();
      ["name", "mmsi", "imo", "vessel_type"].forEach(function (key) { form.elements[key].value = vessel && vessel[key] ? vessel[key] : ""; });
      form.elements.mmsi.readOnly = !!vessel;
      text(root.querySelector("#vt-dialog-title"), vessel ? "Edit vessel" : "Add vessel");
      text(query("save"), vessel ? (vessel.is_active ? "Save changes" : "Resume tracking") : "Start tracking");
      query("stop").hidden = !vessel || !vessel.is_active; query("form-error").hidden = true;
      dialog.showModal(); form.elements.name.focus();
    }
    async function saveVessel(stop) {
      if (state.saving || !state.canManage || (!stop && !form.reportValidity())) return;
      var editing = state.editing;
      if (stop && !editing) return;
      var data = stop ? { is_active: false } : { name: form.elements.name.value.trim(), imo: form.elements.imo.value.trim(), vessel_type: form.elements.vessel_type.value.trim(), is_active: true };
      if (!editing) data.mmsi = form.elements.mmsi.value.trim();
      state.saving = true; query("save").disabled = true; query("stop").disabled = true; query("form-error").hidden = true;
      try {
        var result = await request(editing ? "vessels/" + encodeURIComponent(editing.id) + "/" : "vessels/", { method: editing ? "PATCH" : "POST", body: data });
        if (result.vessel) {
          state.selected = result.vessel.id;
          var existingIndex = state.vessels.findIndex(function (item) { return item.id === result.vessel.id; });
          if (existingIndex >= 0) state.vessels[existingIndex] = result.vessel;
          else state.vessels.push(result.vessel);
          renderFleet(); renderDetails(); renderMarkers();
        }
        dialog.close(); state.generation += 1; clearTrack();
        if (state.busy) state.refreshQueued = true;
        await refresh();
      } catch (error) {
        if (error.name !== "AbortError") { text(query("form-error"), error.message || "The vessel could not be saved."); query("form-error").hidden = false; }
      } finally { state.saving = false; query("save").disabled = false; query("stop").disabled = false; }
    }

    function historyParams() {
      var params = new URLSearchParams({ range: state.range, limit: "2000" });
      if (state.range === "custom") { params.set("start", state.custom.start); params.set("end", state.custom.end); }
      return params;
    }
    function utcStamp() {
      var now = new Date();
      return String(now.getUTCFullYear()) + String(now.getUTCMonth() + 1).padStart(2, "0") + String(now.getUTCDate()).padStart(2, "0");
    }
    async function downloadCsv(path, fallbackName) {
      // The CSV endpoints answer with a file, so the JSON request helper cannot be reused here.
      var response = await global.fetch(base + path, { credentials: "same-origin" });
      if (!response.ok) throw new Error(response.status === 401 || response.status === 403
        ? "Your session or permissions do not allow this download. Refresh the page to sign in again."
        : "The CSV file could not be generated. Try again.");
      var blob = await response.blob();
      var url = global.URL.createObjectURL(blob), link = doc.createElement("a");
      link.href = url;
      link.download = attachmentName(response.headers.get("Content-Disposition")) || fallbackName;
      link.rel = "noopener";
      doc.body.appendChild(link);
      link.click();
      link.remove();
      global.setTimeout(function () { global.URL.revokeObjectURL(url); }, 0);
    }
    async function exportCsv(button, path, fallbackName) {
      if (state.exporting) return;
      state.exporting = true; button.disabled = true;
      try { await downloadCsv(path, fallbackName); errorMessage(""); }
      catch (error) { errorMessage(error.message || "The CSV file could not be downloaded."); }
      finally { state.exporting = false; button.disabled = false; renderDetails(); }
    }
    function importError(message) {
      text(query("import-error"), message);
      query("import-error").hidden = !message;
    }
    function openImport() {
      if (!state.canManage || state.importing || !importDialog || typeof importDialog.showModal !== "function") return;
      importForm.reset(); importError("");
      var panel = query("import-result");
      panel.replaceChildren(); panel.hidden = true;
      syncImportButton();
      importDialog.showModal(); importForm.elements.file.focus();
    }
    function observationAge(observation) {
      var label = ageLabel(observation.timestamp), seconds = number(observation.age_seconds);
      if (label === "No position" && seconds !== null) label = ageLabel(new Date(Date.now() - seconds * 1000).toISOString());
      return label;
    }
    function importRow(observation) {
      var row = element("li", "vt-import-row"), key = statusKey(observation);
      var badge = element("span", "vt-status", STATUS_LABELS[key]);
      badge.dataset.status = key;
      row.appendChild(badge);
      var identity = element("span", "vt-import-identity");
      identity.appendChild(element("strong", "", "MMSI " + (observation.mmsi === null || observation.mmsi === undefined ? "" : observation.mmsi)));
      if (observation.name) identity.appendChild(element("small", "", observation.name));
      row.appendChild(identity);
      var lat = number(observation.latitude), lon = number(observation.longitude);
      row.appendChild(element("span", "vt-import-coords", lat === null || lon === null ? "" : lat.toFixed(5) + ", " + lon.toFixed(5)));
      row.appendChild(element("span", "vt-import-when", utcLabel(observation.timestamp) + " \u00b7 " + observationAge(observation)));
      return row;
    }
    function countLabel(value) {
      var parsed = number(value);
      return parsed === null ? "" : parsed.toLocaleString("en-GB");
    }
    function renderImportResult(result, dryRun) {
      // Every value here comes from an uploaded file, so it is only ever written as text.
      var panel = query("import-result");
      panel.replaceChildren(); panel.hidden = false;
      panel.appendChild(element("p", "vt-import-mode", dryRun
        ? "Checked only. Nothing was saved yet."
        : "Import finished. Stored positions were updated."));
      var counts = element("dl", "vt-import-counts");
      [["Rows read", result.parsed], ["Saved", result.created], ["Duplicates", result.duplicates],
        ["Skipped", result.skipped], ["Vessels advanced", result.vessels_advanced]].forEach(function (row) {
        counts.appendChild(element("dt", "", row[0]));
        counts.appendChild(element("dd", "", countLabel(row[1])));
      });
      panel.appendChild(counts);
      var freshest = number(result.freshest_age_seconds);
      if (freshest !== null && freshest > STALE_SECONDS) {
        panel.appendChild(element("p", "vt-import-warning", "The newest position in this report is "
          + ageLabel(new Date(Date.now() - freshest * 1000).toISOString())
          + ". The provider has no recent fix for this fleet, so importing it does not make the position current."));
      }
      var observations = Array.isArray(result.observations) ? result.observations : [];
      if (observations.length) {
        panel.appendChild(element("h4", "vt-import-subhead", "Positions read"));
        var list = element("ul", "vt-import-list");
        observations.forEach(function (observation) { list.appendChild(importRow(observation)); });
        panel.appendChild(list);
        var parsed = number(result.parsed);
        if (parsed !== null && parsed > observations.length) {
          panel.appendChild(element("p", "vt-import-note", "Showing " + countLabel(observations.length) + " of " + countLabel(parsed) + " positions read."));
        }
      } else {
        panel.appendChild(element("p", "vt-import-note", "No usable position was read from this report."));
      }
      var issues = (Array.isArray(result.issues) ? result.issues : []).filter(function (issue) { return typeof issue === "string" && issue; });
      if (issues.length) {
        panel.appendChild(element("h4", "vt-import-subhead", "Rows that were not imported"));
        var problems = element("ul", "vt-import-issues");
        issues.forEach(function (issue) { problems.appendChild(element("li", "", issue)); });
        panel.appendChild(problems);
      }
      if (typeof panel.scrollIntoView === "function") panel.scrollIntoView({ block: "nearest" });
    }
    function dryRunChecked() {
      var box = importForm.elements.dry_run;
      return !!(box && box.checked);
    }
    function syncImportButton() {
      // The label must say what the click will actually do, not what the dialog is called.
      text(query("import-submit"), dryRunChecked() ? "Check file" : "Save positions");
    }
    function offerSave() {
      var panel = query("import-result");
      var action = element("button", "vt-button vt-primary vt-import-save", "Save these positions");
      action.type = "button";
      action.addEventListener("click", function () {
        var box = importForm.elements.dry_run;
        if (box) box.checked = false;
        syncImportButton();
        runImport();
      });
      panel.appendChild(action);
    }
    async function runImport() {
      if (state.importing || !state.canManage || !importForm.reportValidity()) return;
      var input = importForm.elements.file, file = input && input.files && input.files.length ? input.files[0] : null;
      if (!file) { importError("Choose a CSV or TSV report to import."); return; }
      if (file.size > MAX_IMPORT_BYTES) { importError("This file is larger than 32 MB. Split the report and import it in parts."); return; }
      var dryRun = !!(importForm.elements.dry_run && importForm.elements.dry_run.checked);
      var payload = new global.FormData();
      payload.append("file", file);
      payload.append("dry_run", dryRun ? "true" : "false");
      var submit = query("import-submit");
      var controller = new AbortController(), timedOut = false;
      var timeout = global.setTimeout(function () { timedOut = true; controller.abort(); }, 120000);
      state.importing = true; submit.disabled = true; importError("");
      text(submit, dryRun ? "Checking\u2026" : "Importing\u2026");
      try {
        // FormData supplies its own multipart boundary, so Content-Type is never set by hand.
        var response = await global.fetch(base + "vessels/import/", { method: "POST", credentials: "same-origin",
          signal: controller.signal, body: payload, headers: { Accept: "application/json",
            "X-CSRFToken": (importForm.querySelector('[name="csrfmiddlewaretoken"]') || {}).value || "" } });
        var data;
        try { data = await response.json(); } catch (_error) { data = {}; }
        if (!response.ok) throw new Error(apiError(data, response.status === 401 || response.status === 403
          ? "Your session or permissions do not allow this import. Refresh the page to sign in again."
          : "The report could not be imported. Check the file and try again."));
        renderImportResult(data, dryRun);
        if (!dryRun && (number(data.created) || 0) > 0) {
          if (state.busy) state.refreshQueued = true;
          await refresh();
        }
        // A check that found usable positions must offer the save outright: leaving the
        // user to find the checkbox is how a successful check reads as a failed import.
        if (dryRun && (number(data.parsed) || 0) > 0) offerSave();
      } catch (error) {
        if (timedOut) importError("The import timed out. Try again with a smaller report.");
        else if (error.name !== "AbortError") importError(error.message || "The report could not be imported.");
      } finally {
        global.clearTimeout(timeout);
        state.importing = false; submit.disabled = false; syncImportButton();
      }
    }

    query("search").addEventListener("input", renderFleet);
    query("fit").addEventListener("click", fitTrack);
    query("zoom-vessel").addEventListener("click", zoomToVessel);
    root.addEventListener("vt:zoom-vessel", function (event) {
      if (event.detail && event.detail.id !== undefined) selectVessel(event.detail.id, true);
      zoomToVessel();
    });
    query("scroll").addEventListener("change", syncWheelZoom);
    query("containers-open").addEventListener("click", function () {
      if (query("containers").hidden) openContainers();
      else closeContainers();
    });
    query("containers-close").addEventListener("click", closeContainers);
    query("containers-search").addEventListener("input", renderContainers);
    query("follow").addEventListener("change", function () { if (query("follow").checked) renderMarkers(); });
    query("retry").addEventListener("click", function () { ensureMap(); refresh(); });
    query("add").addEventListener("click", function () { openForm(null); });
    query("export").addEventListener("click", function () {
      exportCsv(query("export"), "vessels/export/", "fleet-positions-" + utcStamp() + ".csv");
    });
    query("export-track").addEventListener("click", function () {
      var vessel = selectedVessel();
      if (!vessel) return;
      exportCsv(query("export-track"), "vessels/" + encodeURIComponent(vessel.id) + "/positions/export/?" + historyParams().toString(),
        vessel.mmsi + "-track-" + utcStamp() + ".csv");
    });
    query("import").addEventListener("click", openImport);
    if (importForm.elements.dry_run) importForm.elements.dry_run.addEventListener("change", syncImportButton);
    importForm.addEventListener("submit", function (event) { event.preventDefault(); runImport(); });
    root.querySelectorAll("[data-vt-import-cancel]").forEach(function (button) {
      button.addEventListener("click", function () { importDialog.close(); });
    });
    query("edit").addEventListener("click", function () { openForm(selectedVessel()); });
    query("stop").addEventListener("click", function () { saveVessel(true); });
    form.addEventListener("submit", function (event) { event.preventDefault(); saveVessel(false); });
    root.querySelectorAll("[data-vt-cancel]").forEach(function (button) { button.addEventListener("click", function () { dialog.close(); }); });
    function changeRange(range, custom) {
      state.range = range; state.custom = custom || {}; state.generation += 1; clearTrack();
      root.querySelectorAll("[data-vt-range]").forEach(function (button) { button.setAttribute("aria-pressed", String(button.dataset.vtRange === range)); });
      text(query("track-meta"), "Loading stored track…"); loadTrack();
    }
    root.querySelectorAll("[data-vt-range]").forEach(function (button) {
      button.addEventListener("click", function () {
        var range = button.dataset.vtRange; query("custom").hidden = range !== "custom";
        if (range !== "custom") changeRange(range);
        else {
          var customForm = query("custom");
          if (!customForm.elements.end.value) {
            customForm.elements.end.value = new Date().toISOString().slice(0, 16);
            customForm.elements.start.value = new Date(Date.now() - 86400000).toISOString().slice(0, 16);
          }
          customForm.elements.start.focus();
        }
      });
    });
    query("custom").addEventListener("submit", function (event) {
      event.preventDefault(); query("range-error").textContent = "";
      try { changeRange("custom", customRange(event.currentTarget.elements.start.value, event.currentTarget.elements.end.value)); }
      catch (error) { text(query("range-error"), error.message); }
    });
    doc.addEventListener("visibilitychange", function () { setActive(state.visible && !doc.hidden); });
    var intersection = typeof global.IntersectionObserver === "function" ? new global.IntersectionObserver(function (entries) {
      state.visible = entries[0].isIntersecting; setActive(state.visible && !doc.hidden);
    }, { threshold: 0 }) : null;
    if (intersection) intersection.observe(root);
    else { state.visible = true; setActive(!doc.hidden); }
    var resize = typeof global.ResizeObserver === "function" ? new global.ResizeObserver(function () {
      if (map && state.active) map.invalidateSize({ pan: false });
    }) : null;
    if (resize) resize.observe(query("map-frame") || query("map").parentElement);
    global.addEventListener("pagehide", function (event) {
      setActive(false);
      if (!event.persisted) { if (intersection) intersection.disconnect(); if (resize) resize.disconnect(); if (map) map.remove(); }
    });
    global.addEventListener("pageshow", function (event) { if (event.persisted) setActive(state.visible && !doc.hidden); });
  }
  function bootstrap() { global.document.querySelectorAll("[data-vessel-tracking]").forEach(init); }
  if (global.document.readyState === "loading") global.document.addEventListener("DOMContentLoaded", bootstrap);
  else bootstrap();
})(typeof window !== "undefined" ? window : globalThis);
