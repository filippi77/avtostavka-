// Geocoding über OpenStreetMap Nominatim (kostenlos, max. 1 Anfrage/Sekunde).

import { geocodeQueries } from './address.js';

const NOMINATIM = 'https://nominatim.openstreetmap.org';
let last = 0;
const cache = new Map();

async function throttle() {
  const wait = last + 1100 - Date.now();
  if (wait > 0) await new Promise((r) => setTimeout(r, wait));
  last = Date.now();
}

async function search(q, { country, near, lang }) {
  const key = JSON.stringify([q, country, lang, near && [near.lat.toFixed(1), near.lon.toFixed(1)]]);
  if (cache.has(key)) return cache.get(key);
  await throttle();
  const p = new URLSearchParams({ q, format: 'jsonv2', limit: '5', 'accept-language': lang });
  if (country) p.set('countrycodes', country);
  if (near) {
    const d = 0.6;
    p.set('viewbox', [near.lon - d, near.lat + d, near.lon + d, near.lat - d].join(','));
  }
  const r = await fetch(`${NOMINATIM}/search?${p}`);
  if (!r.ok) throw new Error('HTTP ' + r.status);
  const res = (await r.json()).map((x) => ({
    lat: +x.lat,
    lon: +x.lon,
    label: x.display_name,
    type: x.addresstype || x.type,
  }));
  cache.set(key, res);
  return res;
}

/** Sucht Koordinaten einer Adresse; bis zu 5 Treffer. */
export async function geocode(address, { country = '', city = '', near = null, lang = 'de' } = {}) {
  for (const q of geocodeQueries(address, city)) {
    const res = await search(q, { country, near, lang });
    if (res.length) return res.map((r) => ({ ...r, query: q }));
  }
  return [];
}

export async function reverse(lat, lon, lang = 'de') {
  await throttle();
  const p = new URLSearchParams({ lat, lon, format: 'jsonv2', 'accept-language': lang, zoom: '18' });
  const r = await fetch(`${NOMINATIM}/reverse?${p}`);
  if (!r.ok) return '';
  const j = await r.json();
  return j.display_name || '';
}
