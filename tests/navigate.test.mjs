import test from 'node:test';
import assert from 'node:assert/strict';
import { navLink, appsFor, platformOf, defaultApp, isAppScheme } from '../js/navigate.js';

const A = { lat: 51.1902, lon: 6.4401, address: 'Daimlerring 2, 41065 Mönchengladbach' };
const B = { lat: 52.5291, lon: 13.4015, address: 'Torstraße 101, 10119 Berlin' };
const exactOnlyB = (s) => s === B;

test('Plattformen', () => {
  assert.equal(platformOf('Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)'), 'ios');
  assert.equal(platformOf('Mozilla/5.0 (Linux; Android 14; Pixel 8)'), 'android');
  assert.ok(appsFor('ios').includes('apple') && !appsFor('ios').includes('geo'));
  assert.ok(appsFor('android').includes('geo') && !appsFor('android').includes('apple'));
  assert.ok(!appsFor('ios').includes('tomtom') && !appsFor('android').includes('tomtom'));
  assert.equal(defaultApp('ios'), 'apple');
  assert.equal(defaultApp('android'), 'google');
});

test('Apple / Waze: ungenaue Punkte als Adresse, genaue als Koordinaten', () => {
  const a = decodeURIComponent(navLink('apple', [A], { exact: exactOnlyB }).url);
  assert.match(a, /daddr=Daimlerring\+2,\+41065\+Mönchengladbach/);
  assert.match(a, /sll=51\.1902,6\.4401/);
  assert.match(navLink('apple', [B], { exact: exactOnlyB }).url, /daddr=52\.5291%2C13\.4015/);
  assert.match(navLink('waze', [A], { exact: exactOnlyB }).url, /^https:\/\/waze\.com\/ul\?q=Daimlerring/);
  assert.equal(navLink('waze', [B], { exact: exactOnlyB }).url, 'https://waze.com/ul?ll=52.5291,13.4015&navigate=yes');
});

test('Google: mehrere Stopps als Zwischenziele (max. 10)', () => {
  const pts = Array.from({ length: 12 }, (_, i) => ({ lat: 52 + i / 100, lon: 13, address: `X ${i}` }));
  const r = navLink('google', pts);
  const u = new URL(r.url);
  assert.equal(r.count, 10);
  assert.equal(u.searchParams.get('destination'), '52.09,13');
  assert.equal(u.searchParams.get('waypoints').split('|').length, 9);
});

test('HERE, Sygic, Yandex: Koordinaten', () => {
  assert.equal(navLink('sygic', [B]).url, 'com.sygic.aura://coordinate|13.4015|52.5291|drive');
  assert.equal(navLink('yandex', [B]).url, 'yandexnavi://build_route_on_map?lat_to=52.5291&lon_to=13.4015');
  assert.match(navLink('here', [B]).url, /^https:\/\/share\.here\.com\/r\/mylocation\/52\.5291,13\.4015,Torstra/);
  assert.equal(navLink('sygic', [A, B]).count, 1);
  assert.equal(navLink('sygic', [A]).coordsOnly, true);
});

test('Android-Auswahl (geo:)', () => {
  assert.match(navLink('geo', [B]).url, /^geo:52\.5291,13\.4015\?q=52\.5291,13\.4015\(Torstra/);
  assert.match(navLink('geo', [A], { exact: exactOnlyB }).url, /^geo:0,0\?q=Daimlerring/);
  assert.equal(isAppScheme('geo:1,2'), true);
  assert.equal(isAppScheme('https://maps.apple.com/'), false);
});

