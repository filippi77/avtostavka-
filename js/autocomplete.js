// Adress-Vorschläge beim Tippen (Photon / OpenStreetMap), begrenzt auf einen Umkreis.

import { haversine } from './route.js';

const PHOTON = 'https://photon.komoot.io/api/';

/** Umkreis (km) → Bounding-Box [minLon, minLat, maxLon, maxLat] */
export function bboxAround(center, radiusKm) {
  const dLat = radiusKm / 111.32;
  const dLon = radiusKm / (111.32 * Math.cos((center.lat * Math.PI) / 180));
  return [center.lon - dLon, center.lat - dLat, center.lon + dLon, center.lat + dLat];
}

/** Eingabe für die Suche vorbereiten: "Hauptstr. 5" → "Hauptstraße 5" */
export function prepareQuery(q) {
  return String(q || '')
    .replace(/(\p{Ll})str\.?(?=\s|\d|,|$)/gu, '$1straße')
    .replace(/(^|\s)str\.(?=\s)/giu, '$1Straße')
    .replace(/\s+/g, ' ')
    .trim();
}

// Nur echte Straßen (keine Bushaltestellen, Ampeln, Wege-Punkte …)
const ROAD_TYPES = new Set(['residential', 'primary', 'secondary', 'tertiary', 'unclassified', 'living_street', 'service', 'pedestrian', 'trunk', 'road', 'primary_link', 'secondary_link', 'tertiary_link', 'track', 'busway', 'cycleway', 'footway', 'path']);

/** Photon-Feature → Vorschlag */
export function toSuggestion(f, center) {
  const p = f.properties || {};
  const [lon, lat] = f.geometry?.coordinates || [];
  if (lat == null) return null;
  const city = p.city || p.town || p.village || p.district || p.county || '';
  const plzCity = [p.postcode, city].filter(Boolean).join(' ');
  let kind = 'place';
  let main = p.name || '';
  if (p.housenumber && (p.street || p.name)) {
    kind = 'house';
    main = `${p.street || p.name} ${p.housenumber}`;
  } else if (p.type === 'street' || (p.osm_key === 'highway' && ROAD_TYPES.has(p.osm_value))) {
    kind = 'street';
    main = p.name || p.street || '';
  } else if (p.osm_key === 'highway' || p.osm_key === 'public_transport' || p.osm_key === 'railway') {
    return null; // Haltestellen, Kreuzungen usw. sind keine Lieferadressen
  } else if (p.street) {
    // benanntes Objekt (Firma, Geschäft) mit Adresse
    main = p.name ? `${p.name}, ${p.street}${p.housenumber ? ' ' + p.housenumber : ''}` : p.street;
  }
  if (!main) return null;
  if (kind === 'place' && !p.street) return null; // Orte/POIs ohne Straße sind keine Lieferadresse
  const address = [kind === 'place' && p.street ? `${p.street}${p.housenumber ? ' ' + p.housenumber : ''}` : main, plzCity]
    .filter(Boolean)
    .join(', ');
  return {
    kind,
    main,
    hnr: String(p.housenumber || '').toLowerCase().replace(/\s/g, ''),
    sub: [plzCity, kind === 'street' && p.district && p.district !== city ? p.district : ''].filter(Boolean).join(' · '),
    address,
    street: kind === 'street' ? main : p.street || '',
    postcode: p.postcode || '',
    city,
    lat,
    lon,
    dist: center ? haversine(center, { lat, lon }) : null,
  };
}

/**
 * Vorschläge für die Eingabe q im Umkreis radiusKm um center.
 * Liefert höchstens `limit` Einträge, nächstgelegene zuerst, ohne Dubletten.
 */
export async function suggest(q, { center = null, radiusKm = 50, lang = 'de', limit = 7, signal } = {}) {
  const query = prepareQuery(q);
  if (query.length < 3) return [];
  const wantsHouse = /\d/.test(query);
  const typedNr = (query.match(/(\d+\s?[a-z]?)(?=\s*(,|$))/i)?.[1] || '').toLowerCase().replace(/\s/g, '');
  const p = new URLSearchParams({ q: query, limit: String(limit * 2), lang: lang === 'ru' ? 'de' : lang });
  if (center) {
    p.set('lat', center.lat.toFixed(5));
    p.set('lon', center.lon.toFixed(5));
    p.set('location_bias_scale', '0.5');
    p.set('bbox', bboxAround(center, radiusKm).map((v) => v.toFixed(5)).join(','));
  }
  const r = await fetch(`${PHOTON}?${p}`, { signal });
  if (!r.ok) throw new Error('HTTP ' + r.status);
  const j = await r.json();
  const seen = new Set();
  return (j.features || [])
    .map((f) => toSuggestion(f, center))
    .filter((s) => s && (s.dist == null || s.dist <= radiusKm * 1000))
    .filter((s) => {
      const k = s.address.toLowerCase();
      if (seen.has(k)) return false;
      seen.add(k);
      return true;
    })
    .sort((a, b) => {
      // Mit Hausnummer in der Eingabe: Häuser zuerst; sonst nur nach Entfernung
      if (wantsHouse && (a.kind === 'house') !== (b.kind === 'house')) return a.kind === 'house' ? -1 : 1;
      // genau die eingetippte Hausnummer zuerst (12 vor 12A)
      if (typedNr && (a.hnr === typedNr) !== (b.hnr === typedNr)) return a.hnr === typedNr ? -1 : 1;
      return (a.dist ?? 0) - (b.dist ?? 0);
    })
    .slice(0, limit);
}
