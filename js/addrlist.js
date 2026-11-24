// Mehrere Adressen aus dem Foto einer Liste lesen (Bildschirm eines Scanners, Ausdruck, Screenshot).
// Typisch für Zustell-Listen: Straße + Hausnummer, darunter "ORT PLZ" (oder "PLZ ORT"), dazwischen
// Mengen, Entfernungen und Symbole. Alles andere wird ignoriert.

import { smartCase } from './address.js';

// kurze Wörter, die am Anfang eines Straßennamens stehen dürfen (alles andere Kurze ist Bildschirm-Müll)
const KEEP = new Set(['am', 'an', 'im', 'in', 'zum', 'zur', 'auf', 'der', 'die', 'das', 'den', 'dem', 'vor', 'st', 'st.', 'alt', 'neu', 'bei', 'hof', 'weg', 'ost', 'süd', 'nord']);
// Spalten rechts daneben: "8000 | 0+3", Entfernungen "477.59m", "1.3km"
const TAIL = /\s+(?:\d{3,5}\s*[|Il!/]\s*.*|\d+(?:[.,]\d+)?\s*k?m\b.*|[|!:;.,'"`°®*=~_\\/()[\]{}<>-]+.*)$/u;

function clean(line) {
  let s = String(line || '')
    .replace(/[«»"“”„]/g, '')
    .replace(/\s+/g, ' ')
    .trim();
  // Müll am Anfang: Rahmenstriche, Symbole, kurze Fremdwörter ("| FE, LINDENSTR…", "a MUSTERSTADT…")
  for (;;) {
    const m = s.match(/^(\S+)\s+(?=\S)/u);
    if (!m) break;
    const tok = m[1];
    const letters = tok.replace(/[^\p{L}]/gu, '');
    const junk = /[^\p{L}\d.\-']/u.test(tok) || (letters.length <= 2 && !/\d/.test(tok) && !KEEP.has(tok.toLowerCase()));
    if (!junk) break;
    s = s.slice(m[0].length);
  }
  s = s.replace(/^[^\p{L}\d]+/u, '');
  // Spalten/Müll am Ende abschneiden (mehrmals, falls mehreres dranhängt)
  for (let i = 0; i < 3; i++) s = s.replace(TAIL, '');
  return s.replace(/[^\p{L}\d.)]+$/u, '').trim();
}

const CITY_PLZ = /^(\p{L}[\p{L}.\- ]{1,40}?)\s+(\d{5})(?:\s+\S{1,3})*$/u; // MUSTERSTADT 12345 (+ kurzer Müll)
const PLZ_CITY = /^(\d{5})\s+(\p{L}[\p{L}.\- ]{1,40})$/u; // 12345 MUSTERSTADT
const STREET = /^(\p{L}[\p{L}.\-' ]{2,45}?)\s?(\d{1,4}\s?[a-zA-Z]?(?:\s?[-/]\s?\d{1,4}\s?[a-zA-Z]?)?)$/u;
const UI_WORDS = /^(liste|karte|übersicht|uebersicht|erstellen|stopp|stops|tour|menü|menu)\b/i;

function lev(a, b) {
  const d = Array.from({ length: a.length + 1 }, (_, i) => [i]);
  for (let j = 1; j <= b.length; j++) d[0][j] = j;
  for (let i = 1; i <= a.length; i++) for (let j = 1; j <= b.length; j++) {
    d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
  }
  return d[a.length][b.length];
}

/**
 * Liefert [{ address, name, street, plz, city }] in der Reihenfolge der Liste.
 * Einträge, die am Bildrand abgeschnitten sind (keine Hausnummer oder kein Ort), werden übersprungen.
 */
export function extractAddressList(text) {
  const lines = String(text || '').split(/\r?\n/).map(clean);
  const out = [];
  for (let i = 0; i < lines.length; i++) {
    const l = lines[i];
    let m = l.match(CITY_PLZ);
    let city, plz;
    if (m) { city = m[1]; plz = m[2]; } else if ((m = l.match(PLZ_CITY))) { plz = m[1]; city = m[2]; } else continue;
    if (!/\p{L}{3}/u.test(city)) continue;
    // Straße: eine der zwei Zeilen darüber
    let si = -1;
    for (let j = i - 1; j >= Math.max(0, i - 2); j--) {
      if (STREET.test(lines[j]) && !CITY_PLZ.test(lines[j]) && !PLZ_CITY.test(lines[j])) { si = j; break; }
    }
    if (si < 0) continue;
    const sm = lines[si].match(STREET);
    const street = `${sm[1].trim()} ${sm[2].replace(/\s+/g, '')}`;
    // Name: Zeile direkt über der Straße, wenn sie wie ein Name aussieht (keine Ziffern, kein Ort/PLZ)
    let name = '';
    const n = si > 0 ? lines[si - 1] : '';
    if (n && !/\d/.test(n) && /\p{L}{2,}\s+\p{L}{2,}/u.test(n) && !UI_WORDS.test(n) && !out.some((o) => o._ci === si - 1)) name = n;
    out.push({ street: smartCase(street), plz, city: smartCase(city.trim()), name: smartCase(name), _ci: i });
  }
  // verlesene Orte/PLZ an die häufigsten der Liste angleichen ("MuSTeRSTAT 12355" → Musterstadt 12345)
  const count = {};
  for (const o of out) count[o.city.toLowerCase() + '|' + o.plz] = (count[o.city.toLowerCase() + '|' + o.plz] || 0) + 1;
  const common = Object.entries(count).filter(([, c]) => c >= 2).map(([k]) => k.split('|'));
  for (const o of out) {
    if (count[o.city.toLowerCase() + '|' + o.plz] >= 2) continue;
    const c = o.city.toLowerCase().replace(/[^\p{L}]/gu, '');
    const best = common.find(([cc, pp]) => lev(c, cc.replace(/[^\p{L}]/gu, '')) <= 3 && lev(o.plz, pp) <= 1);
    if (best) { o.city = smartCase(out.find((x) => x.city.toLowerCase() === best[0]).city); o.plz = best[1]; }
  }
  return out.map(({ street, plz, city, name }) => ({ street, plz, city, name, address: `${street}, ${plz} ${city}` }));
}
