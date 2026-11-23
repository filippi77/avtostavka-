import test from 'node:test';
import assert from 'node:assert/strict';
import { suggest, bboxAround, prepareQuery } from '../js/autocomplete.js';

const center = { lat: 52.52, lon: 13.405 }; // Berlin Mitte
const feat = (props, lat, lon) => ({ type: 'Feature', geometry: { type: 'Point', coordinates: [lon, lat] }, properties: props });

function mockFetch(features) {
  const calls = [];
  globalThis.fetch = async (url) => {
    calls.push(new URL(url));
    return { ok: true, json: async () => ({ features }) };
  };
  return calls;
}

test('Umkreis-Box ~50 km', () => {
  const [minLon, minLat, maxLon, maxLat] = bboxAround(center, 50);
  assert.ok(Math.abs((maxLat - minLat) / 2 - 0.449) < 0.01);
  assert.ok(maxLon - minLon > maxLat - minLat); // Längengrade sind in Berlin schmaler
});

test('Abkürzungen in der Eingabe', () => {
  assert.equal(prepareQuery('Hauptstr. 5'), 'Hauptstraße 5');
  assert.equal(prepareQuery('Berliner Str. 4'), 'Berliner Straße 4');
  assert.equal(prepareQuery('  Torstr  '), 'Torstraße');
});

test('Vorschläge: nur im Umkreis, nächste zuerst, Straßen und Häuser', async () => {
  const calls = mockFetch([
    feat({ osm_key: 'highway', name: 'Hauptstraße', postcode: '10827', city: 'Berlin', district: 'Schöneberg' }, 52.488, 13.357),
    feat({ osm_key: 'highway', name: 'Hauptstraße', postcode: '14469', city: 'Potsdam' }, 52.41, 13.03),
    feat({ osm_key: 'highway', name: 'Hauptstraße', postcode: '80331', city: 'München' }, 48.137, 11.575), // 500 km weg
    feat({ osm_key: 'highway', name: 'Hauptstraße', postcode: '10827', city: 'Berlin', district: 'Schöneberg' }, 52.488, 13.357), // Dublette
  ]);
  const r = await suggest('Hauptstr', { center, radiusKm: 50 });
  assert.equal(r.length, 2);
  assert.equal(r[0].city, 'Berlin');
  assert.equal(r[0].kind, 'street');
  assert.equal(r[0].address, 'Hauptstraße, 10827 Berlin');
  assert.ok(r[0].dist < r[1].dist);
  const u = calls[0];
  assert.equal(u.searchParams.get('q'), 'Hauptstraße');
  assert.ok(u.searchParams.get('bbox'));
  assert.equal(u.searchParams.get('lat'), '52.52000');
});

test('Mit Hausnummer: Häuser vor Straßen', async () => {
  mockFetch([
    feat({ osm_key: 'highway', name: 'Torstraße', postcode: '10119', city: 'Berlin' }, 52.529, 13.401),
    feat({ osm_key: 'building', street: 'Torstraße', housenumber: '101', postcode: '10119', city: 'Berlin' }, 52.5291, 13.4015),
  ]);
  const r = await suggest('Torstraße 101', { center, radiusKm: 50 });
  assert.equal(r[0].kind, 'house');
  assert.equal(r[0].address, 'Torstraße 101, 10119 Berlin');
  assert.equal(r[0].main, 'Torstraße 101');
});

test('Zu kurze Eingabe → keine Anfrage', async () => {
  const calls = mockFetch([]);
  assert.deepEqual(await suggest('Ha', { center }), []);
  assert.equal(calls.length, 0);
});

test('Genaue Hausnummer vor ähnlichen (12 vor 12A)', async () => {
  mockFetch([
    feat({ osm_key: 'building', street: 'Hauptstraße', housenumber: '12A', postcode: '10827', city: 'Berlin' }, 52.52, 13.405),
    feat({ osm_key: 'building', street: 'Hauptstraße', housenumber: '12', postcode: '10827', city: 'Berlin' }, 52.53, 13.41),
  ]);
  const r = await suggest('Hauptstraße 12, 10827 Berlin', { center, radiusKm: 50 });
  assert.equal(r[0].main, 'Hauptstraße 12');
});
