// Übergabe an Navigations-Apps (Deep Links / URL-Schemata).

/**
 * Unterstützte Apps.
 * text: Ziel kann als Adresse übergeben werden (sonst nur Koordinaten)
 * multi: maximale Anzahl Stopps in einem Link (Zwischenziele)
 * platforms: wo die App angeboten wird
 */
export const NAV_APPS = {
  apple: { name: 'Apple Karten', text: true, multi: 1, platforms: ['ios', 'other'] },
  google: { name: 'Google Maps', text: true, multi: 10, platforms: ['ios', 'android', 'other'] },
  waze: { name: 'Waze', text: true, multi: 1, platforms: ['ios', 'android', 'other'] },
  tomtom: { name: 'TomTom GO Navigation', text: false, multi: 1, platforms: ['ios', 'android'] },
  // TomTom AmiGO hat auf dem iPhone keinen bekannten Link für Ziele → Adresse kopieren und einfügen
  amigo: { name: 'TomTom AmiGO', text: true, multi: 1, platforms: ['ios', 'android'], copyOnly: ['ios'] },
  here: { name: 'HERE WeGo', text: false, multi: 1, platforms: ['ios', 'android', 'other'] },
  sygic: { name: 'Sygic', text: false, multi: 1, platforms: ['ios', 'android'] },
  yandex: { name: 'Yandex Navi', text: false, multi: 1, platforms: ['ios', 'android'] },
  geo: { name: 'Android', text: true, multi: 1, platforms: ['android'] },
};

export function platformOf(ua = '', maxTouch = 0, platform = '') {
  if (/iPad|iPhone|iPod/.test(ua) || (platform === 'MacIntel' && maxTouch > 1)) return 'ios';
  if (/Android/i.test(ua)) return 'android';
  return 'other';
}

export function appsFor(platform) {
  return Object.keys(NAV_APPS).filter((k) => NAV_APPS[k].platforms.includes(platform));
}

export function defaultApp(platform) {
  return platform === 'ios' ? 'apple' : 'google';
}

const enc = encodeURIComponent;

/**
 * Link für die App `app`.
 * points: Stopps { lat, lon, address }; exact(s): true, wenn die Koordinaten genau sind (Haus / von Hand).
 * Liefert { url, count } – count = wie viele Stopps tatsächlich übergeben wurden.
 */
export function navLink(app, points, { exact = () => true, address = (s) => s.address, platform = 'ios' } = {}) {
  const cfg = NAV_APPS[app] || NAV_APPS.google;
  if (cfg.copyOnly?.includes(platform)) return { url: null, count: 1, coordsOnly: false, copyOnly: true, text: address(points[0]) };
  const list = points.slice(0, cfg.multi);
  const first = list[0];
  const ll = (s) => `${s.lat},${s.lon}`;
  // Ziel als Text nur, wenn die App das kann und die Koordinaten ungenau sind
  const asText = (s) => cfg.text && !exact(s);
  const dest = (s) => (asText(s) ? address(s) : ll(s));
  let url;
  switch (app) {
    case 'apple': {
      const p = new URLSearchParams({ daddr: dest(first), dirflg: 'd' });
      if (asText(first)) p.set('sll', ll(first)); // Suchhinweis: in dieser Gegend
      url = 'https://maps.apple.com/?' + p;
      break;
    }
    case 'waze':
      url = asText(first)
        ? `https://waze.com/ul?q=${enc(address(first))}&navigate=yes`
        : `https://waze.com/ul?ll=${ll(first)}&navigate=yes`;
      break;
    case 'tomtom':
      url = `tomtomgo://x-callback-url/navigate?destination=${ll(first)}`;
      break;
    case 'here':
      url = `https://share.here.com/r/mylocation/${ll(first)},${enc(address(first))}?m=d`;
      break;
    case 'sygic':
      url = `com.sygic.aura://coordinate|${first.lon}|${first.lat}|drive`;
      break;
    case 'yandex':
      url = `yandexnavi://build_route_on_map?lat_to=${first.lat}&lon_to=${first.lon}`;
      break;
    case 'amigo': // Android: System-Link geo:, AmiGO erscheint in der Auswahl, falls installiert
    case 'geo':
      // Android zeigt die Auswahl aller installierten Navi-Apps
      url = asText(first) ? `geo:0,0?q=${enc(address(first))}` : `geo:${ll(first)}?q=${ll(first)}(${enc(address(first))})`;
      break;
    default: {
      const last = list[list.length - 1];
      const p = new URLSearchParams({ api: '1', destination: dest(last), travelmode: 'driving' });
      const way = list.slice(0, -1);
      if (way.length) p.set('waypoints', way.map(dest).join('|'));
      url = 'https://www.google.com/maps/dir/?' + p;
    }
  }
  return { url, count: list.length, coordsOnly: !cfg.text };
}

/** true für App-Schemata (tomtomgo:, geo: …), die nicht per window.open geöffnet werden dürfen. */
export function isAppScheme(url) {
  return !/^https?:/i.test(url);
}
