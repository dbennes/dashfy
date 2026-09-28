const test = require('node:test');
const assert = require('node:assert/strict');
const ui = require('../../../static/js/vessel-tracking.js');

test('water paths retain channel bends and fade old history independently of AIS sampling gaps', () => {
  const now = Date.parse('2026-09-28T12:00:00Z');
  const older = [[4.794, 6.942], [4.71, 7.02], [4.615, 7.168]];
  const recent = [[4.615, 7.168], [4.542, 7.203]];
  const route = {kind: 'estimated_water_route', segments: [
    {timestamp: '2026-09-18T15:07:00Z', coordinates: older},
    {timestamp: '2026-09-28T11:00:00Z', coordinates: recent},
    {timestamp: 'invalid', coordinates: recent},
    {timestamp: '2026-09-28T11:00:00Z', coordinates: [[200, 7], [4, 7]]},
  ]};
  assert.deepEqual(ui.waterRouteParts(route, now), {older: [older], recent: [recent]});
  assert.deepEqual(ui.waterRouteParts(null, now), {older: [], recent: []});
});

function point(latitude, longitude, timestamp, extra = {}) {
  return {latitude, longitude, timestamp, source: 'AIS', ...extra};
}

test('unknown AIS measurements remain unknown while true zero is preserved', () => {
  for (const value of [null, undefined, '', ' ', false, NaN, Infinity]) {
    assert.equal(ui.number(value), null);
    assert.equal(ui.measurement(value, ' kn'), '—');
  }
  assert.equal(ui.measurement(0, ' kn'), '0 kn');
  assert.equal(ui.measurement('0', '°'), '0°');
});

test('positions require real AIS source, bounded coordinates and an explicit timezone', () => {
  const valid = point(0, 0, '2026-09-15T09:30:00Z');
  assert.equal(ui.position(valid).latitude, 0);
  for (const invalid of [
    {...valid, latitude: null}, {...valid, longitude: false}, {...valid, latitude: 91},
    {...valid, longitude: -181}, {...valid, timestamp: '2026-09-15T09:30:00'},
    {...valid, source: 'PREDICTED'}, {...valid, timestamp: 'not a date'}
  ]) assert.equal(ui.position(invalid), null);
});

test('heading takes precedence and unavailable AIS direction falls back to COG', () => {
  assert.equal(ui.bearing({heading: 0, cog: 245}), 0);
  assert.equal(ui.bearing({heading: 511, cog: 245}), 245);
  assert.equal(ui.bearing({heading: null, cog: 360}), null);
  assert.equal(ui.bearing({heading: null, cog: null}), null);
});

test('real track is chronological, deduplicates repeats and retains original coordinates', () => {
  const a = point(4.18, 6.82, '2026-09-15T09:00:00Z');
  const b = point(4.19, 6.81, '2026-09-15T09:10:00Z');
  const input = [b, {...a}, a, {...b, source: 'PREDICTED'}];
  const before = JSON.stringify(input);
  const result = ui.trackPoints(input);
  assert.deepEqual(result.map(p => [p.latitude, p.longitude]), [[4.18, 6.82], [4.19, 6.81]]);
  assert.equal(JSON.stringify(input), before);
  assert.deepEqual(ui.trackPoints([]), []);
});

test('date-line crossing never creates a fictitious line across zero longitude', () => {
  const points = ui.trackPoints([
    point(5, 179, '2026-09-15T09:00:00Z'),
    point(5.1, -179, '2026-09-15T09:10:00Z'),
    point(5.1001, -179.001, '2026-09-15T09:20:00Z')
  ]);
  assert.deepEqual(ui.trackParts(points), [[[5, 179]], [[5.1, -179], [5.1001, -179.001]]]);
});

test('sparse Eastern Ursinia imports never draw shortcuts across the delta', () => {
  const fixes = [
    point(4.7942467, 6.9417582, '2026-09-16T14:57:03Z'),
    point(4.615082, 7.168013, '2026-09-18T15:07:00Z'),
    point(4.541847, 7.203438, '2026-09-18T15:41:00Z')
  ];
  const original = JSON.stringify(fixes);
  const parts = ui.trackParts(ui.trackPoints(fixes));
  assert.deepEqual(parts, fixes.map(p => [[p.latitude, p.longitude]]));
  assert.equal(JSON.stringify(fixes), original);
});

test('nearby frequent fixes stay connected, but time gaps and jumps break the line', () => {
  const fixes = ui.trackPoints([
    point(4.5, 7.1, '2026-09-15T09:00:00Z'),
    point(4.501, 7.101, '2026-09-15T09:01:00Z'),
    point(4.5011, 7.1011, '2026-09-15T10:00:00Z'),
    point(4.55, 7.15, '2026-09-15T10:01:00Z'),
    point(4.555, 7.15, '2026-09-15T10:01:01Z')
  ]);
  assert.deepEqual(ui.trackRuns(fixes).map(run => run.length), [2, 1, 1, 1]);
  assert.equal(ui.trackRuns(fixes).flat().length, fixes.length);
});

test('conflicting simultaneous fixes are kept without connecting them', () => {
  const fixes = ui.trackPoints([
    point(4.5, 7.1, '2026-09-15T09:00:00Z'),
    point(4.5001, 7.1001, '2026-09-15T09:00:00Z')
  ]);
  assert.equal(ui.trackRuns(fixes).length, 2);
  assert.deepEqual(ui.trackRuns([]), []);
});

test('history fades against actual time rather than making old imports look recent', () => {
  const now = Date.parse('2026-09-28T12:00:00Z');
  const older = ui.trackStyle(Date.parse('2026-09-18T15:41:00Z'), now);
  const recent = ui.trackStyle(now, now);
  assert.equal(older.color, '#94a3b8');
  assert.equal(recent.color, '#3b82f6');
  assert.ok(older.weight < recent.weight && recent.weight < 2);
  assert.ok(older.opacity < recent.opacity && older.opacity >= .5);
  assert.equal(older.dashArray, '3 6');
  assert.equal(ui.trackStyle(now - 86400000, now).color, recent.color);
});

test('ETA does not invent a year or midnight for unavailable time fields', () => {
  assert.equal(ui.etaLabel({month: 9, day: 16, hour: 18, minute: 0}), '16 Sep · 18:00 UTC');
  assert.equal(ui.etaLabel({month: 9, day: 16, hour: 24, minute: 60}), '16 Sep');
  assert.equal(ui.etaLabel({month: 0, day: 0, hour: 24, minute: 60}), '—');
  assert.equal(ui.etaLabel({month: 0, day: 0, hour: 0, minute: 0}), '00:00 UTC');
  assert.equal(ui.etaLabel({}), '—');
});

test('custom history ranges are UTC and reject reversed or ambiguous timestamps', () => {
  assert.deepEqual(ui.customRange('2026-09-14T12:30', '2026-09-15T12:30'), {
    start: '2026-09-14T12:30:00Z', end: '2026-09-15T12:30:00Z'
  });
  assert.throws(() => ui.customRange('2026-09-15T12:30', '2026-09-14T12:30'));
  assert.throws(() => ui.customRange('', '2026-09-15T12:30'));
  assert.equal(ui.utcLabel('2026-09-15T11:30:00+02:00'), '15/09/2026 09:30 UTC');
});

const aveon = {id: 'aveon_jetty_ph', name: 'AVEON JETTY PH', latitude: 4.7942467, longitude: 6.9417582, radius_m: 3000};
const bonga = {id: 'bonga_north', name: 'BONGA NORTH', latitude: 4.5575266, longitude: 4.6164432, radius_m: 3000};

test('arrival circles retain real metre radii and reject invalid geometry', () => {
  assert.deepEqual(ui.geofence(aveon), aveon);
  assert.deepEqual(ui.geofence(bonga), bonga);
  for (const invalid of [null, {...aveon, radius_m: 0}, {...aveon, radius_m: false},
    {...aveon, latitude: 91}, {...aveon, longitude: null}, {...aveon, name: ''}]) {
    assert.equal(ui.geofence(invalid), null);
  }
});

test('arrival uses the recognized port and hides a stale declared ETA', () => {
  const view = ui.voyageDisplay({status: 'RECENT', destination: 'OLD PORT',
    eta: {month: 9, day: 20, hour: 18, minute: 0},
    last_position: point(4.7942467, 6.9417582, '2026-09-18T09:00:00Z'),
    voyage: {status: 'arrived', current_port: aveon, destination: aveon,
      arrived_at: '2026-09-18T08:00:00Z', origin: {name: 'PREVIOUS PORT'}}});
  assert.equal(view.status_label, 'Arrived');
  assert.equal(view.current_port, 'AVEON JETTY PH');
  assert.equal(view.origin, 'PREVIOUS PORT');
  assert.equal(view.destination, 'AVEON JETTY PH');
  assert.equal(view.eta, '—');
  assert.equal(view.observed_at, '2026-09-18T09:00:00Z');
});

test('departure never restores an obsolete raw destination or ETA', () => {
  const vessel = {status: 'RECENT', destination: 'AVEON JETTY PH',
    eta: {month: 9, day: 20, hour: 18, minute: 0},
    last_position: point(4.7, 6.9, '2026-09-18T10:00:00Z'),
    voyage: {status: 'underway', origin: aveon, destination: null, departed_at: '2026-09-18T10:00:00Z'}};
  const view = ui.voyageDisplay(vessel);
  assert.equal(view.status_label, 'Underway');
  assert.equal(view.origin, 'AVEON JETTY PH');
  assert.equal(view.destination_label, 'Next destination not reported');
  assert.equal(view.current_port, '');
  assert.equal(view.eta, '—');
  const newReport = ui.voyageDisplay({...vessel, voyage: {...vessel.voyage, destination: {name: 'BONGA'}}});
  assert.equal(newReport.destination_label, 'BONGA');
  assert.equal(newReport.eta, '20 Sep · 18:00 UTC');
});

test('old positions qualify arrival as last report, while missing positions cannot confirm arrival', () => {
  const vessel = {status: 'NO_RECENT_AIS', last_position: point(4.79, 6.94, '2026-09-15T09:00:00Z'),
    voyage: {status: 'arrived', current_port: aveon, destination: aveon}};
  assert.equal(ui.voyageDisplay(vessel).status_label, 'Arrived · last report');
  assert.equal(ui.voyageDisplay({...vessel, status: 'STALE'}).status_label, 'Arrived · last report');
  const missing = ui.voyageDisplay({...vessel, last_position: null});
  assert.equal(missing.status_label, 'Arrival not confirmed');
  assert.equal(missing.current_port, '');
  assert.equal(missing.observed_at, null);
  assert.equal(ui.voyageDisplay(null).origin, '');
});

test('an arrived shuttle names the opposite port as next destination without inventing a departure', () => {
  const vessel = {status: 'NO_RECENT_AIS', destination: 'AVEON JETTY PH',
    eta: {month: 9, day: 20, hour: 18, minute: 0},
    last_position: point(aveon.latitude, aveon.longitude, '2026-09-18T09:00:00Z'),
    voyage: {status: 'arrived', origin: null, current_port: aveon, destination: aveon,
      next_destination: bonga, destination_source: 'arrival'}};
  const view = ui.voyageDisplay(vessel);
  assert.equal(view.current_port, 'AVEON JETTY PH');
  assert.equal(view.destination_title, 'Next destination');
  assert.equal(view.destination_label, 'BONGA NORTH');
  assert.equal(view.regular_route, true);
  assert.equal(view.origin, '');
  assert.equal(view.departed_at, null);
  assert.equal(view.status_label, 'Arrived · last report');
  assert.equal(view.eta, '—');

  const returned = ui.voyageDisplay({...vessel,
    last_position: point(bonga.latitude, bonga.longitude, '2026-09-19T09:00:00Z'),
    voyage: {...vessel.voyage, current_port: bonga, destination: bonga, next_destination: aveon, origin: aveon}});
  assert.equal(returned.current_port, 'BONGA NORTH');
  assert.equal(returned.destination_label, 'AVEON JETTY PH');
  assert.equal(returned.destination_title, 'Next destination');
});

test('underway scheduled destinations never inherit an ETA from an older AIS declaration', () => {
  const view = ui.voyageDisplay({status: 'RECENT', destination: 'AVEON JETTY PH',
    eta: {month: 9, day: 20, hour: 18, minute: 0},
    last_position: point(4.7, 6.9, '2026-09-18T10:00:00Z'),
    voyage: {status: 'underway', origin: aveon, destination: bonga,
      next_destination: null, destination_source: 'scheduled_route', departed_at: '2026-09-18T10:00:00Z'}});
  assert.equal(view.destination_title, 'Destination');
  assert.equal(view.destination_label, 'BONGA NORTH');
  assert.equal(view.origin, 'AVEON JETTY PH');
  assert.equal(view.regular_route, true);
  assert.equal(view.status_label, 'Underway');
  assert.equal(view.eta, '—');
});
