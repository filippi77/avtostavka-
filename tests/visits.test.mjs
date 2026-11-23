import test from 'node:test';
import assert from 'node:assert/strict';
import { DwellTracker, pruneVisits, visitsCsv } from '../js/visits.js';

const stops = [
  { id: 'a', address: 'Torstraße 101, 10119 Berlin', name: 'Jonas', lat: 52.5291, lon: 13.4015 },
  { id: 'b', address: 'Invalidenstraße 50, 10557 Berlin', lat: 52.5302, lon: 13.378 },
];
const at = (s, dLat = 0) => ({ lat: s.lat + dLat, lon: s.lon, acc: 10 });
const T0 = Date.UTC(2026, 10, 24, 9, 0, 0);

test('Aufenthalt erst nach 30 s, dann verlängert und beim Verlassen beendet', () => {
  const tr = new DwellTracker();
  assert.deepEqual(tr.update({ ...at(stops[0]), time: T0 }, stops), {});
  assert.deepEqual(tr.update({ ...at(stops[0], 0.0002), time: T0 + 20000 }, stops), {}); // ~22 m, erst 20 s
  const e1 = tr.update({ ...at(stops[0]), time: T0 + 31000 }, stops);
  assert.equal(e1.started.stopId, 'a');
  assert.equal(e1.started.from, T0);
  assert.equal(tr.presentAt().stopId, 'a');
  const e2 = tr.update({ ...at(stops[0]), time: T0 + 90000 }, stops);
  assert.equal(e2.updated.to, T0 + 90000);
  const e3 = tr.update({ lat: 52.52, lon: 13.40, acc: 10, time: T0 + 100000 }, stops); // weg
  assert.equal(e3.ended.to, T0 + 90000);
  assert.equal(tr.presentAt(), null);
});

test('Kurzer Halt (< 30 s) zählt nicht', () => {
  const tr = new DwellTracker();
  tr.update({ ...at(stops[1]), time: T0 }, stops);
  tr.update({ ...at(stops[1]), time: T0 + 15000 }, stops);
  const e = tr.update({ lat: 52.52, lon: 13.40, acc: 10, time: T0 + 20000 }, stops);
  assert.deepEqual(e, {});
});

test('Wechsel direkt zum nächsten Stopp und GPS-Lücke', () => {
  const tr = new DwellTracker();
  tr.update({ ...at(stops[0]), time: T0 }, stops);
  tr.update({ ...at(stops[0]), time: T0 + 40000 }, stops);
  const e = tr.update({ ...at(stops[1]), time: T0 + 60000 }, stops);
  assert.equal(e.ended.stopId, 'a');
  // App 10 Minuten im Hintergrund, wieder am selben Ort → neuer Aufenthalt
  tr.update({ ...at(stops[1]), time: T0 + 100000 }, stops);
  const g = tr.update({ ...at(stops[1]), time: T0 + 700000 }, stops);
  assert.equal(g.ended.stopId, 'b');
  assert.equal(g.ended.to, T0 + 100000);
});

test('Ungenaue Positionen werden ignoriert', () => {
  const tr = new DwellTracker();
  assert.deepEqual(tr.update({ ...at(stops[0]), acc: 500, time: T0 }, stops), {});
  assert.equal(tr.cur, null);
});

test('Aufbewahrung und CSV', () => {
  const now = T0;
  const v = [{ from: now - 40 * 86400000, to: now - 40 * 86400000 }, { from: now - 1000, to: now, address: 'A "1"', name: 'X', lat: 52.5, lon: 13.4, dist: 12 }];
  assert.equal(pruneVisits(v, 30, now).length, 1);
  const csv = visitsCsv(pruneVisits(v, 30, now));
  assert.ok(csv.startsWith('﻿"Typ";"Von"'));
  assert.match(csv, /"A ""1""";"X";"52\.500000";"13\.400000";"12"/);
});
