// Adresserkennung aus OCR-Text von Versandetiketten.
// Primär: deutsche Adressen (Straße Nr. / PLZ Ort). Fallback: russische Adressen.
// Hinweis: bewusst ohne Lookbehind-RegExp (würde Safari < 16.4 / ältere iPhones brechen).

/* ===================== Gemeinsames ===================== */

const B = '(?:^|[^\\p{L}\\d])'; // linke Wortgrenze (Unicode-fähig)
const E = '(?![\\p{L}])'; // rechte Wortgrenze

// Telefon: DE (+49 / 0049 / 0…) und RU (+7 / 8…)
const PHONE_DE = /(?:^|[^\d+])((?:\+|00)49[\s\-/()]*\d[\d\s\-/()]{5,15}\d|0\d{2,5}[\s\-/]*\d[\d\s\-]{3,11}\d)(?!\d)/;
const PHONE_RU = /(?:^|[^\d])((?:\+7|8)[\s\-(]*\d{3}[\s\-)]*\d{3}[\s-]*\d{2}[\s-]*\d{2})(?!\d)/;

export function extractPhone(text) {
  const lines = String(text || '').split('\n');
  // Zeilen mit Tel.-Label bevorzugen
  const labelled = lines.filter((l) => /(tel|telefon|phone|mobil|handy|тел)/i.test(l));
  for (const src of [labelled.join('\n'), text]) {
    const ru = src.match(PHONE_RU);
    const de = src.match(PHONE_DE);
    if (de && (!ru || de.index <= ru.index)) {
      let d = de[1].replace(/\(0\)/, '').replace(/[^\d+]/g, '');
      if (d.startsWith('0049')) d = '+49' + d.slice(4);
      else if (d.startsWith('0')) d = '+49' + d.slice(1);
      if (d.replace(/\D/g, '').length >= 9) return d;
    }
    if (ru) {
      let d = ru[1].replace(/\D/g, '');
      if (d.length === 11 && d[0] === '8') d = '7' + d.slice(1);
      if (d.length === 11) return '+' + d;
    }
  }
  return '';
}

function fixOcr(line) {
  return line
    .replace(/[«»"“”„]/g, '')
    .replace(/\s+/g, ' ')
    .replace(/\s+([,.])/g, '$1')
    .replace(/(\d)[OО](?=[\d\s,]|$)/g, (_, d) => d + '0')
    .replace(/(\d)[OО](?=[\d\s,]|$)/g, (_, d) => d + '0')
    .replace(/(\d)[lI|](?=\d)/g, (_, d) => d + '1')
    .trim();
}

/* ===================== Deutsch ===================== */

const DE_RECIPIENT = /^\s*(?:(?:empfänger(?:in)?|lieferadresse|lieferanschrift|zustelladresse|versandadresse|ship\s*to|deliver\s*to|recipient|куда|кому|получатель|адрес\s+(?:получателя|доставки))(?:\s*[:.\-]\s*|\s+|$)|(?:an|to)\s*:\s*)/iu;
const DE_SENDER = /^\s*(?:(?:absender(?:in)?|abs\.|abs|sender|versender|return(?:\s+address)?|rücksende(?:adresse|anschrift)?|retour(?:e|enadresse)?|отправитель|от\s+кого|откуда)(?:\s*[:.\-]\s*|\s+|$)|(?:von|from|versand)\s*:\s*)/iu;
const DE_STOP = /^\s*(tel|telefon|phone|mobil|handy|e-?mail|gewicht|weight|sendungs?(nummer|-?nr)|paket-?nr|tracking|referenz|ref\.|bestell|auftrag|kunden-?nr|datum|date|inhalt|warenwert|hinweis|zustellhinweis|lieferhinweis|nachnahme|vers(and)?art|service|produkt|тел|вес|заказ|трек)/iu;

const DE_SUFFIX = '(?:straße|strasse|str\\.|str|weg|allee|platz|pl\\.|gasse|ring|damm|ufer|chaussee|steig|stieg|pfad|markt|graben|wall|kamp|promenade|zeile|hof|berg|feld|garten|winkel|brücke|tor|park|siedlung|anger|aue|bogen|grund|höhe|kai|stadt|heide)';
const DE_PREFIX = '(?:am|an\\s+der|an\\s+den|an\\s+dem|auf\\s+der|auf\\s+dem|auf\\s+den|im|in\\s+der|in\\s+den|unter\\s+den|zum|zur|hinter\\s+der|hinter\\s+dem|vor\\s+dem|vor\\s+der|alte[rs]?|neue[rs]?|großer?|kleiner?|obere[rs]?|untere[rs]?|hohe[rs]?|lange[rs]?|platz\\s+der|straße\\s+de[rs])';
const HNR = '\\d{1,4}\\s?[a-zA-Z]?(?:\\s?[-/]\\s?\\d{1,4}\\s?[a-zA-Z]?)?';

const DE_STREET = new RegExp(`^(?:[\\p{L}][\\p{L}.\\-' ]*?${DE_SUFFIX}|${DE_PREFIX}\\s[\\p{L}][\\p{L}.\\-' ]*?)\\.?\\s*,?\\s*(${HNR})$`, 'iu');
const DE_STREET_GENERIC = new RegExp(`^[\\p{L}][\\p{L}.\\-' ]{2,40}\\s(${HNR})$`, 'iu');
const DE_PACKSTATION = /^(packstation|postfiliale|paketshop|paketbox|postfach|filiale|dhl\s*packstation)\s*(nr\.?|no\.?)?\s*\d{2,5}$/iu;
const DE_POSTNUMMER = /^(postnummer|kundennummer|postnr\.?)\s*:?\s*\d{6,10}$/iu;
// PLZ + Ort (DE 5-stellig, AT/CH 4-stellig, optional "D-", "DE-")
const DE_PLZ = /^(?:(?:D|DE|A|AT|CH)\s?-\s?)?(\d{5}|\d{4})\s+(\p{Lu}[\p{L}.'\-]*(?:[ \-/]+\(?[\p{L}.'\-]+\)?){0,4})$/u;
const COUNTRY_TAIL = /[,\s]*(deutschland|germany|bundesrepublik deutschland|brd|de)\s*$/iu;

const RU_HINT = /[а-яё]/i;

function matchPlz(line) {
  const l = line.replace(COUNTRY_TAIL, '').trim();
  const m = l.match(DE_PLZ);
  if (!m) return null;
  return { code: m[1], city: m[2].trim(), five: m[1].length === 5 };
}

function streetScore(line) {
  const l = line.replace(DE_RECIPIENT, '').trim();
  if (DE_PACKSTATION.test(l)) return 5;
  if (DE_POSTNUMMER.test(l)) return 0;
  if (DE_STREET.test(l)) return 4;
  if (DE_STREET_GENERIC.test(l) && !/\d{5}/.test(l)) return 1;
  return 0;
}

function isNameLine(line) {
  const l = line.replace(DE_RECIPIENT, '').trim();
  if (!l || l.length < 3 || l.length > 60) return false;
  if (/\d/.test(l)) return false;
  if (DE_STOP.test(l) || DE_SENDER.test(line)) return false;
  if (/^(c\/o|z\.\s?hd\.?|zu\s+händen)/i.test(l)) return false;
  if (l.split(/\s+/).length > 6) return false;
  return /\p{L}{2,}/u.test(l);
}

// "Max Muster, Hauptstr. 5, 10115 Berlin" bzw. "Firma · Weg 1 · 12345 Ort" in Zeilen aufteilen
function splitLines(lines) {
  const out = [];
  for (const l of lines) {
    const hasPlz = /(?:^|[\s,·|•])(?:D-?)?\d{4,5}\s+\p{Lu}/u.test(l);
    if (hasPlz && /[,·|•]|\s[–-]\s/.test(l)) {
      const parts = l.split(/\s*(?:[,·|•]|\s[–-]\s)\s*/).filter(Boolean);
      // Label (z.B. "Absender:") am ersten Teil lassen
      parts.forEach((p) => out.push(p));
    } else {
      out.push(l);
    }
  }
  return out;
}

function senderExcluded(lines) {
  const ex = new Set();
  lines.forEach((l, i) => {
    if (!DE_SENDER.test(l)) return;
    for (let j = i; j < Math.min(lines.length, i + 6); j++) {
      if (j > i && DE_RECIPIENT.test(lines[j])) break;
      ex.add(j);
      if (matchPlz(lines[j].replace(DE_SENDER, ''))) break;
    }
  });
  return ex;
}

function extractGerman(rawLines) {
  const lines = splitLines(rawLines);
  const ex = senderExcluded(lines);
  const cands = [];
  lines.forEach((l, i) => {
    if (ex.has(i)) return;
    const plz = matchPlz(l.replace(DE_RECIPIENT, ''));
    if (!plz) return;
    let si = -1;
    let sScore = 0;
    for (let j = i - 1; j >= Math.max(0, i - 3); j--) {
      if (ex.has(j) || DE_STOP.test(lines[j])) break;
      const s = streetScore(lines[j]);
      if (s > 0) { si = j; sScore = s; break; }
    }
    let score = sScore + (plz.five ? 2 : 1);
    for (let j = i; j >= Math.max(0, i - 5); j--) {
      if (DE_RECIPIENT.test(lines[j])) { score += 3; break; }
    }
    cands.push({ i, si, sScore, plz, score });
  });
  if (!cands.length) return null;
  // Höchster Score; bei Gleichstand die spätere Adresse (Empfänger steht meist unter dem Absender)
  cands.sort((a, b) => b.score - a.score || b.i - a.i);
  const c = cands[0];

  const street = c.si >= 0 ? normalizeStreet(lines[c.si].replace(DE_RECIPIENT, '').trim()) : '';
  const address = [street, `${c.plz.code} ${c.plz.city}`].filter(Boolean).join(', ');

  // Name: Zeile(n) direkt über der Straße (c/o-Zeilen überspringen → als Notiz)
  let name = '';
  let note = '';
  const top = c.si >= 0 ? c.si : c.i;
  for (let j = top - 1; j >= Math.max(0, top - 3); j--) {
    if (ex.has(j)) break;
    const l = lines[j].replace(DE_RECIPIENT, '').trim();
    if (/^(c\/o|z\.\s?hd)/i.test(l)) { note = l; continue; }
    if (DE_POSTNUMMER.test(l)) { note = l; continue; }
    if (isNameLine(lines[j])) { name = l; }
    break;
  }
  const confidence = c.sScore >= 4 && c.plz.five ? 'high' : c.sScore > 0 ? 'medium' : 'low';
  return { address, name, note, confidence };
}

function normalizeStreet(s) {
  return s
    .replace(/\s*,\s*(?=\d)/, ' ')
    .replace(/(\d)\s+([a-zA-Z])$/, '$1$2')
    .replace(/\s+/g, ' ')
    .trim();
}

/* ===================== Russisch (Fallback) ===================== */

const RU_STREET = new RegExp(B + '(ул|улица|пр-?т|просп|проспект|пер|переулок|ш|шоссе|б-р|бул|бульвар|наб|набережная|пл|площадь|проезд|пр-д|туп|тупик|мкр|мкрн|микрорайон|аллея|линия|тракт|кв-л|квартал)' + E, 'iu');
const RU_HOUSE = new RegExp(B + '(д|дом|зд|здание|влд|владение)' + E + '\\.?\\s*\\d+', 'iu');
const RU_CITY = new RegExp(B + '(г|город|пос|посёлок|поселок|пгт|с|село|д|деревня|ст-ца|станица)' + E + '\\.?\\s*[А-ЯЁ]', 'u');
const RU_REGION = new RegExp(B + '(обл|область|край|респ|республика|р-н|район|ао)' + E, 'iu');
const RU_INDEX = /(?:^|\D)\d{6}(?!\d)/;
const RU_STOP = /^\s*(тел|телефон|моб|фио|кому|получатель|отправитель|от\s+кого|откуда|вес|заказ|№|трек|штрих|дата|сумма|оплата|комментарий)/iu;
const RU_LABEL = /^\s*(куда|адрес\s+(получателя|доставки|назначения)|адрес)\s*[:\-]?\s*/iu;
const RU_SENDER = /^\s*(отправитель|от\s+кого|откуда|адрес\s+отправителя)/iu;

function ruScore(line) {
  let s = 0;
  if (RU_STREET.test(line)) s += 3;
  if (RU_HOUSE.test(line)) s += 3;
  if (RU_CITY.test(line)) s += 2;
  if (RU_REGION.test(line)) s += 1;
  if (RU_INDEX.test(line)) s += 1;
  if (PHONE_RU.test(line)) s -= 3;
  if (line.replace(/[^\p{L}]/gu, '').length < 3) s -= 2;
  return s;
}

function tidy(s) {
  return s
    .replace(PHONE_RU, '')
    .replace(/\s*,\s*/g, ', ')
    .replace(/(,\s*)+/g, ', ')
    .replace(/^[\s,.:;-]+|[\s,.:;-]+$/g, '')
    .trim();
}

function extractRussian(lines) {
  const ex = new Set();
  lines.forEach((l, i) => {
    if (!RU_SENDER.test(l)) return;
    let acc = '';
    for (let j = i; j < Math.min(lines.length, i + 5); j++) {
      if (j > i && (RU_LABEL.test(lines[j]) || /^\s*(кому|получатель)/iu.test(lines[j]))) break;
      ex.add(j);
      acc += ' ' + lines[j];
      if (RU_STREET.test(acc) && (RU_HOUSE.test(acc) || /\d/.test(acc))) break;
    }
  });
  for (let i = 0; i < lines.length; i++) {
    if (ex.has(i)) continue;
    const m = lines[i].match(RU_LABEL);
    if (!m) continue;
    const parts = [];
    const rest = lines[i].slice(m[0].length).trim();
    if (rest) parts.push(rest);
    for (let j = i + 1; j < lines.length && parts.length < 4; j++) {
      if (RU_STOP.test(lines[j]) || ex.has(j)) break;
      if (ruScore(lines[j]) <= 0 && parts.length) break;
      parts.push(lines[j]);
    }
    const address = tidy(parts.join(', '));
    if (address && ruScore(address) >= 3) return { address, confidence: 'high' };
  }
  let best = -1;
  let bestScore = 0;
  lines.forEach((l, i) => {
    if (ex.has(i)) return;
    const s = ruScore(l);
    if (s > bestScore) { bestScore = s; best = i; }
  });
  if (best < 0) return { address: '', confidence: 'none' };
  let from = best;
  let to = best;
  const ok = (j) => j >= 0 && j < lines.length && !ex.has(j) && !RU_STOP.test(lines[j]) && ruScore(lines[j]) > 0;
  while (from - 1 >= best - 2 && ok(from - 1)) from--;
  while (to + 1 <= best + 2 && ok(to + 1)) to++;
  const address = tidy(lines.slice(from, to + 1).map((l) => l.replace(RU_LABEL, '')).join(', '));
  return { address, confidence: bestScore >= 5 ? 'medium' : 'low' };
}

/* ===================== API ===================== */

/** Liefert { address, name, phone, note, confidence } aus dem OCR-Text. */
export function extractAddress(text) {
  const lines = String(text || '').split(/\r?\n/).map(fixOcr).filter(Boolean);
  const phone = extractPhone(lines.join('\n'));
  const de = extractGerman(lines);
  if (de && (de.confidence !== 'low' || !RU_HINT.test(text))) return { ...de, phone };
  const ru = extractRussian(lines);
  if (ru.address) return { name: '', note: '', ...ru, phone };
  if (de) return { ...de, phone };
  return { address: '', name: '', note: '', phone, confidence: 'none' };
}

const RU_EXPAND = [
  ['ул\\.?', 'улица'], ['(?:пр-?т|просп)\\.?', 'проспект'], ['пер\\.?', 'переулок'], ['ш\\.', 'шоссе'],
  ['(?:б-р|бул)\\.?', 'бульвар'], ['наб\\.?', 'набережная'], ['пл\\.', 'площадь'], ['пр-д\\.?', 'проезд'],
  ['туп\\.?', 'тупик'], ['(?:мкр|мкрн)\\.?', 'микрорайон'], ['обл\\.?', 'область'], ['респ\\.?', 'республика'], ['р-н\\.?', 'район'],
];
// Ersetzung mit Wortgrenze ohne Lookbehind: Gruppe 1 = Zeichen davor
const wordRe = (body, flags = 'giu') => new RegExp('(^|[^\\p{L}])' + body + '(?![\\p{L}])', flags);

function cleanRussian(s) {
  s = ' ' + s + ' ';
  s = s.replace(/(^|\D)\d{6}(?!\d)/g, '$1 ');
  s = s.replace(wordRe('(?:россия|рф|russia)'), '$1 ');
  s = s.replace(wordRe('(?:кв|квартира|оф|офис|пом|помещение|подъезд|под|эт|этаж|домофон|комн|комната)\\.?\\s*[\\w\\-/]*'), '$1 ');
  s = s.replace(/(\d+[а-я]?)\s*,?\s*(^|[^\p{L}])(?:корп|корпус|к)(?![\p{L}])\.?\s*(\d+)/giu, '$1к$3');
  s = s.replace(/(\d+[а-я]?(?:к\d+)?)\s*,?\s*(^|[^\p{L}])(?:стр|строение)(?![\p{L}])\.?\s*(\d+)/giu, '$1с$3');
  s = s.replace(wordRe('(?:д|дом|зд|влд)\\.?\\s*(?=\\d)'), '$1');
  s = s.replace(/(^|[^\p{L}])(?:г|город)\.?\s*(?=[А-ЯЁA-Z])/gu, '$1');
  for (const [from, to] of RU_EXPAND) s = s.replace(wordRe(from), '$1' + to);
  return s;
}

function cleanGerman(s) {
  s = ' ' + s + ' ';
  s = s.replace(/(^|[\s,])(?:D|DE)\s?-\s?(?=\d{5})/g, '$1');
  s = s.replace(wordRe('(?:deutschland|germany)'), '$1 ');
  // Wohnungs-/Etagenangaben sind für die Suche störend
  s = s.replace(/(^|[\s,])\d{1,2}\.\s*(?:og|etage|stock|obergeschoss)(?![\p{L}])/giu, '$1 ');
  s = s.replace(wordRe('(?:whg|wohnung|app|apt|etage|og|eg|dg|ug|hinterhaus|hh|vorderhaus|vh|seitenflügel|sf|gartenhaus|zimmer|zi|top|stiege|tür|aufgang)\\.?(?:\\s*(?:nr\\.?)?\\s*[\\d/.-]+[a-z]?)?'), '$1 ');
  // Abkürzungen
  s = s.replace(/(\p{Ll})str\.?(?=\s*\d|\s*,|\s*$)/gu, '$1straße');
  s = s.replace(wordRe('str\\.(?=\\s)'), '$1Straße');
  s = s.replace(/(\d)\s+([a-z])(?![\p{L}])/giu, '$1$2');
  // c/o-Teile entfernen
  s = s.split(',').filter((p) => !/^\s*(c\/o|z\.\s?hd)/i.test(p)).join(',');
  return s;
}

/** Bereinigt eine Adresse für den Geocoder. */
export function cleanForGeocode(addr) {
  let s = String(addr || '');
  s = RU_HINT.test(s) ? cleanRussian(s) : cleanGerman(s);
  return s
    .replace(/\s+/g, ' ')
    .replace(/\s*,\s*/g, ', ')
    .replace(/(,\s*)+/g, ', ')
    .replace(/^[\s,.]+|[\s,.]+$/g, '')
    .trim();
}

/** Suchanfragen von genau zu allgemein. */
export function geocodeQueries(addr, defaultCity = '') {
  const clean = cleanForGeocode(addr);
  const out = [];
  const add = (q) => { q = q.replace(/(,\s*)+$/, '').trim(); if (q && !out.includes(q)) out.push(q); };
  const city = defaultCity.trim();
  const hasPlz = /(^|\D)\d{4,5}(\s|$)/.test(clean) && !RU_HINT.test(clean);
  const hasCity = !city || clean.toLowerCase().includes(city.toLowerCase());
  if (!hasPlz && !hasCity) add(`${clean}, ${city}`);
  add(clean);
  // Hausnummer-Zusatz weglassen (12a → 12, 12-14 → 12)
  add(clean.replace(/(\d+)\s?[a-z]?(?:\s?[-/]\s?\d+[a-z]?)?(?=,|$)/i, '$1'));
  // nur Straße + Ort (ohne PLZ, falls PLZ falsch erkannt)
  if (hasPlz) add(clean.replace(/(^|,\s*)\d{4,5}\s+/, '$1'));
  const parts = clean.split(', ').filter((p) => !/(область|край|район|республика|округ)/iu.test(p));
  add(parts.join(', '));
  if (!hasCity) add(`${parts.join(', ')}, ${city}`);
  add(parts.join(', ').replace(wordRe('(?:улица|проспект|переулок)\\s*'), '$1'));
  return out;
}
