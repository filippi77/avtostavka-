import test from 'node:test';
import assert from 'node:assert/strict';
import { precisionOf, toCandidate } from '../js/geocode.js';

test('Genauigkeit von Nominatim-Treffern', () => {
  // Ringstraße ohne Hausnummer in OSM → nur Straße
  assert.equal(precisionOf({ category: 'highway', type: 'residential', addresstype: 'road', address: { road: 'Daimlerring', postcode: '41065', city: 'Mönchengladbach' } }), 'street');
  assert.equal(precisionOf({ category: 'building', type: 'yes', addresstype: 'building', address: { road: 'Daimlerring', house_number: '2' } }), 'house');
  assert.equal(precisionOf({ category: 'place', type: 'house', addresstype: 'place', address: { road: 'Torstraße', house_number: '101' } }), 'house');
  assert.equal(precisionOf({ category: 'shop', type: 'bakery', addresstype: 'shop', address: { road: 'Torstraße' } }), 'house');
  assert.equal(precisionOf({ category: 'place', type: 'suburb', addresstype: 'suburb', address: { suburb: 'Mitte' } }), 'area');
});

test('Kandidat enthält PLZ und Ort', () => {
  const c = toCandidate({ lat: '51.2', lon: '6.4', display_name: 'Daimlerring, …', category: 'highway', addresstype: 'road', address: { road: 'Daimlerring', postcode: '41065', town: 'Mönchengladbach' } });
  assert.equal(c.precision, 'street');
  assert.equal(c.postcode, '41065');
  assert.equal(c.city, 'Mönchengladbach');
  assert.equal(c.lat, 51.2);
});
