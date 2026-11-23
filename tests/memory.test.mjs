import test from 'node:test';
import assert from 'node:assert/strict';
import { normKey, remember, lookup, searchBook, frequent, updatePosition, autosaveTour, saveNamedTour, restoreStops, today } from '../js/memory.js';

test('Adressen gleich trotz Schreibweise', () => {
  assert.equal(normKey('Hauptstraße 12, 10115 Berlin'), normKey('HAUPTSTRASSE 12 10115 berlin'));
  assert.equal(normKey('Berliner Str. 4'), normKey('Berliner Straße 4'));
});

test('Adressbuch: merken, zählen, suchen', () => {
  const book = {};
  remember(book, { address: 'Daimlerring 2, 41065 Mönchengladbach', name: 'Max', lat: 51.19, lon: 6.44, precision: 'street' });
  remember(book, { address: 'DAIMLERRING 2, 41065 MÖNCHENGLADBACH' });
  remember(book, { address: 'Torstraße 101, 10119 Berlin', lat: 52.5, lon: 13.4, precision: 'house' });
  const e = lookup(book, 'Daimlerring 2, 41065 Mönchengladbach');
  assert.equal(e.count, 2);
  assert.equal(e.name, 'Max'); // bleibt erhalten
  assert.equal(e.lat, 51.19);
  assert.equal(searchBook(book, 'daim 2')[0].address, 'DAIMLERRING 2, 41065 MÖNCHENGLADBACH');
  assert.equal(searchBook(book, 'xyz').length, 0);
  assert.equal(frequent(book)[0].count, 2);
  updatePosition(book, { address: 'Daimlerring 2, 41065 Mönchengladbach', lat: 51.2, lon: 6.45, precision: 'manual' });
  assert.equal(lookup(book, 'daimlerring 2 41065 mönchengladbach').precision, 'manual');
});

test('Touren: automatisch pro Tag, eigene Namen, Wiederherstellen', () => {
  const stops = [
    { id: 'a', address: 'A 1, 10115 Berlin', status: 'delivered', service: 'express', tracking: '1Z1', lat: 1, lon: 2, precision: 'house' },
    { id: 'b', address: 'B 2, 10115 Berlin', status: 'pending', lat: 3, lon: 4 },
  ];
  let tours = [];
  tours = autosaveTour(tours, stops, { date: '2026-11-23' });
  tours = autosaveTour(tours, stops.slice(0, 1), { date: '2026-11-23' }); // gleicher Tag → überschrieben
  assert.equal(tours.length, 1);
  assert.equal(tours[0].stops.length, 1);
  assert.equal(autosaveTour(tours, []).length, 1); // leere Tour überschreibt nichts
  for (let d = 1; d <= 35; d++) tours = autosaveTour(tours, stops, { date: `2026-10-${String(d).padStart(2, '0')}` });
  assert.equal(tours.filter((t) => t.auto).length, 30);
  assert.ok(tours.some((t) => t.date === '2026-11-23'));
  tours = saveNamedTour(tours, stops, 'Montag A');
  tours = saveNamedTour(tours, stops, 'montag a ');
  assert.equal(tours.filter((t) => !t.auto).length, 1);
  const r = restoreStops(tours[0]);
  assert.equal(r.length, 2);
  assert.ok(r.every((s) => s.status === 'pending' && s.service === '' && s.tracking === '' && s.id));
  assert.equal(r[0].lat, 1);
  assert.match(today(), /^\d{4}-\d{2}-\d{2}$/);
});
