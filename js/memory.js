// Gedächtnis der App: Adressbuch (häufige Adressen) und gespeicherte Touren.

/** Schlüssel für Adressvergleich: Groß/klein, ß/ss, "Str."/"Straße", Satzzeichen egal. */
export function normKey(address) {
  return String(address || '')
    .toLowerCase()
    .replace(/ß/g, 'ss')
    .replace(/strasse|str\./g, 'str')
    .replace(/[^\p{L}\d]+/gu, ' ')
    .trim();
}

/* ---------------- Adressbuch ---------------- */

/** Adresse merken (bzw. Zähler erhöhen). Name/Telefon/Notiz/Position werden übernommen. */
export function remember(book, stop, { count = true } = {}) {
  if (!stop?.address) return;
  const k = normKey(stop.address);
  const e = book[k] || { count: 0 };
  book[k] = {
    address: stop.address,
    name: stop.name || e.name || '',
    phone: stop.phone || e.phone || '',
    note: stop.note || e.note || '',
    lat: stop.lat ?? e.lat ?? null,
    lon: stop.lon ?? e.lon ?? null,
    precision: stop.lat != null ? stop.precision || e.precision || '' : e.precision || '',
    count: e.count + (count ? 1 : 0),
    last: Date.now(),
  };
}

/** Von Hand korrigierte Position ins Adressbuch übernehmen. */
export function updatePosition(book, stop) {
  const e = book[normKey(stop.address)];
  if (!e) return;
  e.lat = stop.lat;
  e.lon = stop.lon;
  e.precision = stop.precision || e.precision;
}

export function lookup(book, address) {
  return book[normKey(address)] || null;
}

const byUse = (a, b) => b.count - a.count || b.last - a.last;

/** Gespeicherte Adressen, die alle eingetippten Wörter enthalten (häufigste zuerst). */
export function searchBook(book, q, limit = 4) {
  const toks = normKey(q).split(' ').filter(Boolean);
  if (!toks.length) return [];
  return Object.values(book)
    .filter((e) => {
      const k = normKey(e.address);
      return toks.every((t) => k.includes(t));
    })
    .sort(byUse)
    .slice(0, limit);
}

export function frequent(book, limit = 6) {
  return Object.values(book).sort(byUse).slice(0, limit);
}

/** Adressbuch begrenzen: selten und lange nicht genutzte Einträge fliegen zuerst raus. */
export function pruneBook(book, max = 3000) {
  const keys = Object.keys(book);
  if (keys.length <= max) return;
  keys.sort((a, b) => byUse(book[b], book[a])).slice(0, keys.length - max).forEach((k) => delete book[k]);
}

/* ---------------- Touren ---------------- */

/** Lokales Datum JJJJ-MM-TT */
export function today(d = new Date()) {
  const z = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${z(d.getMonth() + 1)}-${z(d.getDate())}`;
}

const FIELDS = ['address', 'name', 'phone', 'note', 'lat', 'lon', 'precision', 'status', 'service', 'tracking'];
export function snapshot(stops) {
  return stops.map((s) => Object.fromEntries(FIELDS.filter((f) => s[f] !== undefined && s[f] !== '').map((f) => [f, s[f]])));
}

const newId = () => Math.random().toString(36).slice(2, 10);

/** Tour des Tages automatisch mitschreiben (eine pro Tag, die letzten `keep` Tage). */
export function autosaveTour(tours, stops, { date = today(), keep = 30 } = {}) {
  if (!stops.length) return tours;
  let t = tours.find((x) => x.auto && x.date === date);
  if (!t) {
    t = { id: newId(), auto: true, date, name: '' };
    tours = [t, ...tours];
  }
  t.stops = snapshot(stops);
  t.savedAt = Date.now();
  const autos = tours.filter((x) => x.auto).sort((a, b) => b.date.localeCompare(a.date));
  const drop = new Set(autos.slice(keep));
  return tours.filter((x) => !drop.has(x));
}

/** Tour unter eigenem Namen speichern (gleicher Name → überschreiben). */
export function saveNamedTour(tours, stops, name, { date = today() } = {}) {
  const n = name.trim();
  const t = { id: newId(), auto: false, date, name: n, savedAt: Date.now(), stops: snapshot(stops) };
  return [t, ...tours.filter((x) => x.auto || x.name.toLowerCase() !== n.toLowerCase())];
}

/** Stopps einer gespeicherten Tour für heute vorbereiten: alles offen, Express/Sendungsnummer zurückgesetzt. */
export function restoreStops(tour) {
  return tour.stops.map((s) => ({
    ...s,
    id: newId(),
    status: 'pending',
    service: '',
    express: false,
    tracking: '',
    createdAt: Date.now(),
  }));
}
