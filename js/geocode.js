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

async function search(q, { country, near, lang, radiusKm = 60 }) {
  const key = JSON.stringify([q, country, lang, radiusKm, near && [near.lat.toFixed(1), near.lon.toFixed(1)]]);
  if (cache.has(key)) return cache.get(key);
  await throttle();
  const p = new URLSearchParams({ q, format: 'jsonv2', limit: '5', addressdetails: '1', 'accept-language': lang });
  if (country) p.set('countrycodes', country);
  if (near) {
    const d = radiusKm / 111;
    p.set('viewbox', [near.lon - d, near.lat + d, near.lon + d, near.lat - d].join(','));
  }
  const r = await fetch(`${NOMINATIM}/search?${p}`);
  if (!r.ok) throw new Error('HTTP ' + r.status);
  const res = (await r.json()).map(toCandidate);
  cache.set(key, res);
  return res;
}

/**
 * Genauigkeit eines Treffers:
 * 'house'  – genau dieses Gebäude / diese Hausnummer
 * 'street' – nur die Straße (Punkt liegt irgendwo auf/neben der Straße, bei Ringstraßen sogar mittendrin)
 * 'area'   – nur Ort / Stadtteil / PLZ-Gebiet
 */
export function precisionOf(x) {
  const a = x.address || {};
  if (a.house_number || x.addresstype === 'building' || x.type === 'house' || x.category === 'building') return 'house';
  if (x.category === 'highway' || x.addresstype === 'road' || a.road && !a.house_number && ['road', 'street'].includes(x.addresstype)) return 'street';
  if (['place', 'boundary'].includes(x.category) && !a.road) return 'area';
  // POIs (Geschäfte, Firmen …) mit Adresse gelten als Gebäude
  return a.road ? 'house' : 'area';
}

export function toCandidate(x) {
  const a = x.address || {};
  return {
    lat: +x.lat,
    lon: +x.lon,
    label: x.display_name,
    type: x.addresstype || x.type,
    precision: precisionOf(x),
    postcode: a.postcode || '',
    city: a.city || a.town || a.village || a.municipality || '',
    road: a.road || '',
    houseNumber: a.house_number || '',
  };
}

const RANK = { house: 0, street: 1, area: 2 };

/** Sucht Koordinaten einer Adresse; bis zu 5 Treffer, genaue Häuser zuerst. */
export async function geocode(address, { country = '', city = '', near = null, lang = 'de', radiusKm = 60 } = {}) {
  let fallback = [];
  for (const q of geocodeQueries(address, city)) {
    const res = await search(q, { country, near, lang, radiusKm });
    if (!res.length) continue;
    const sorted = res.map((r) => ({ ...r, query: q })).sort((a, b) => RANK[a.precision] - RANK[b.precision]);
    // Genaues Haus gefunden → fertig; sonst weitere Varianten probieren, Straße als Rückfall merken
    if (sorted[0].precision === 'house' || !/\d/.test(address)) return sorted;
    if (!fallback.length) fallback = sorted;
  }
  return fallback;
}

export async function reverse(lat, lon, lang = 'de') {
  await throttle();
  const p = new URLSearchParams({ lat, lon, format: 'jsonv2', 'accept-language': lang, zoom: '18' });
  const r = await fetch(`${NOMINATIM}/reverse?${p}`);
  if (!r.ok) return '';
  const j = await r.json();
  return j.display_name || '';
}
