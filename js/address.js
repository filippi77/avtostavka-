// Извлечение адреса из распознанного текста этикетки и подготовка запросов к геокодеру.

// Граница слова для кириллицы (\b в JS работает только с латиницей).
const L = '(?<![\\p{L}\\d])';
const R = '(?![\\p{L}])';

const STREET_RE = new RegExp(
  L + '(ул|улица|пр-?т|просп|проспект|пер|переулок|ш|шоссе|б-р|бул|бульвар|наб|набережная|пл|площадь|проезд|пр-д|туп|тупик|мкр|мкрн|микрорайон|аллея|линия|тракт|кв-л|квартал|street|st|avenue|ave|road|rd)' + R + '\\.?',
  'iu'
);
const HOUSE_RE = new RegExp(L + '(д|дом|зд|здание|влд|владение)' + R + '\\.?\\s*\\d+', 'iu');
const NUM_RE = /(^|[\s,])\d{1,4}([а-яa-z]|\/\d+)?(\s*(к|корп|стр|с)\.?\s*\d+)?(?=[\s,.]|$)/iu;
const CITY_RE = new RegExp(L + '(г|город|пос|посёлок|поселок|пгт|с|село|д|деревня|ст-ца|станица)' + R + '\\.?\\s*[А-ЯЁ]', 'u');
const REGION_RE = new RegExp(L + '(обл|область|край|респ|республика|р-н|район|ао)' + R + '\\.?', 'iu');
const INDEX_RE = /(?<!\d)\d{6}(?!\d)/;
const PHONE_RE = /(?:\+7|(?<!\d)8)[\s\-(]*\d{3}[\s\-)]*\d{3}[\s-]*\d{2}[\s-]*\d{2}(?!\d)/;

// Метки, после которых идёт адрес получателя.
const ADDR_LABEL_RE = /^\s*(куда|адрес\s+(получателя|доставки|назначения)|адрес|delivery\s+address|ship\s+to|to)\s*[:\-]?\s*/iu;
// Метки, которые завершают блок адреса.
const STOP_RE = /^\s*(тел|телефон|моб|phone|tel|фио|кому|получатель|отправитель|от\s+кого|откуда|вес|weight|заказ|order|№|трек|track|штрих|дата|сумма|наложенный|оплата|комментарий|примечание)/iu;
const SENDER_RE = /^\s*(отправитель|от\s+кого|откуда|from|sender|адрес\s+отправителя)/iu;

// Типичные ошибки OCR.
function fixOcr(line) {
  return line
    .replace(/[|]/g, 'І')
    .replace(/[«»"“”]/g, '')
    .replace(/\s+/g, ' ')
    .replace(/\s+([,.])/g, '$1')
    .replace(/(?<=\d)[OО](?=\d)/g, '0')
    .trim();
}

export function scoreLine(line) {
  let s = 0;
  if (STREET_RE.test(line)) s += 3;
  if (HOUSE_RE.test(line)) s += 3;
  else if (NUM_RE.test(line) && STREET_RE.test(line)) s += 1;
  if (CITY_RE.test(line)) s += 2;
  if (REGION_RE.test(line)) s += 1;
  if (INDEX_RE.test(line)) s += 1;
  if (PHONE_RE.test(line)) s -= 3;
  if (line.replace(/[^\p{L}]/gu, '').length < 3) s -= 2;
  return s;
}

export function extractPhone(text) {
  const m = text.match(PHONE_RE);
  if (!m) return '';
  let d = m[0].replace(/\D/g, '');
  if (d.length === 11 && d[0] === '8') d = '7' + d.slice(1);
  return '+' + d;
}

/**
 * Возвращает { address, phone, confidence } из сырого текста OCR.
 */
export function extractAddress(text) {
  const lines = String(text || '')
    .split(/\r?\n/)
    .map(fixOcr)
    .filter(Boolean);
  const phone = extractPhone(lines.join('\n'));

  // Исключаем блок отправителя.
  const excluded = new Set();
  lines.forEach((l, i) => {
    if (!SENDER_RE.test(l)) return;
    // Блок отправителя продолжается, пока его адрес не стал «полным» (улица + дом).
    let acc = '';
    for (let j = i; j < Math.min(lines.length, i + 5); j++) {
      if (j > i && (ADDR_LABEL_RE.test(lines[j]) || /^\s*(кому|получатель)/iu.test(lines[j]))) break;
      excluded.add(j);
      acc += ' ' + lines[j];
      if (STREET_RE.test(acc) && (HOUSE_RE.test(acc) || NUM_RE.test(acc))) break;
    }
  });

  // 1) Явная метка «Куда:» / «Адрес получателя:».
  for (let i = 0; i < lines.length; i++) {
    if (excluded.has(i)) continue;
    const m = lines[i].match(ADDR_LABEL_RE);
    if (!m) continue;
    const parts = [];
    const rest = lines[i].slice(m[0].length).trim();
    if (rest) parts.push(rest);
    for (let j = i + 1; j < lines.length && parts.length < 4; j++) {
      if (STOP_RE.test(lines[j]) || excluded.has(j)) break;
      if (scoreLine(lines[j]) <= 0 && parts.length) break;
      parts.push(lines[j]);
    }
    const address = tidy(parts.join(', '));
    if (address && scoreLine(address) >= 3) return { address, phone, confidence: 'high' };
  }

  // 2) Эвристика: лучшая строка + соседние «адресные» строки.
  let best = -1;
  let bestScore = 0;
  lines.forEach((l, i) => {
    if (excluded.has(i)) return;
    const s = scoreLine(l);
    if (s > bestScore) { bestScore = s; best = i; }
  });
  if (best < 0) return { address: '', phone, confidence: 'none' };

  let from = best;
  let to = best;
  const ok = (j) => j >= 0 && j < lines.length && !excluded.has(j) && !STOP_RE.test(lines[j]) && scoreLine(lines[j]) > 0;
  while (from - 1 >= best - 2 && ok(from - 1)) from--;
  while (to + 1 <= best + 2 && ok(to + 1)) to++;
  const address = tidy(lines.slice(from, to + 1).map((l) => l.replace(ADDR_LABEL_RE, '')).join(', '));
  return { address, phone, confidence: bestScore >= 5 ? 'medium' : 'low' };
}

function tidy(s) {
  return s
    .replace(PHONE_RE, '')
    .replace(/\s*,\s*/g, ', ')
    .replace(/(,\s*)+/g, ', ')
    .replace(/^[\s,.:;-]+|[\s,.:;-]+$/g, '')
    .trim();
}

const EXPAND = [
  [/(?<![\p{L}])ул\.?(?![\p{L}])/giu, 'улица'],
  [/(?<![\p{L}])(пр-?т|просп)\.?(?![\p{L}])/giu, 'проспект'],
  [/(?<![\p{L}])пер\.?(?![\p{L}])/giu, 'переулок'],
  [/(?<![\p{L}])ш\.(?![\p{L}])/giu, 'шоссе'],
  [/(?<![\p{L}])(б-р|бул)\.?(?![\p{L}])/giu, 'бульвар'],
  [/(?<![\p{L}])наб\.?(?![\p{L}])/giu, 'набережная'],
  [/(?<![\p{L}])пл\.(?![\p{L}])/giu, 'площадь'],
  [/(?<![\p{L}])пр-д\.?(?![\p{L}])/giu, 'проезд'],
  [/(?<![\p{L}])туп\.?(?![\p{L}])/giu, 'тупик'],
  [/(?<![\p{L}])(мкр|мкрн)\.?(?![\p{L}])/giu, 'микрорайон'],
  [/(?<![\p{L}])обл\.?(?![\p{L}])/giu, 'область'],
  [/(?<![\p{L}])респ\.?(?![\p{L}])/giu, 'республика'],
  [/(?<![\p{L}])р-н\.?(?![\p{L}])/giu, 'район'],
];

/** Очищает адрес для геокодера: убирает индекс, квартиру, «д.», раскрывает сокращения. */
export function cleanForGeocode(addr) {
  let s = ' ' + String(addr || '') + ' ';
  s = s.replace(/(?<!\d)\d{6}(?!\d)/g, ' ');
  s = s.replace(/(?<![\p{L}])(россия|рф|russia)(?![\p{L}])/giu, ' ');
  // квартира, офис, подъезд, этаж, домофон — не нужны для геокодинга
  s = s.replace(/(?<![\p{L}])(кв|квартира|оф|офис|пом|помещение|подъезд|под|эт|этаж|домофон|комн|комната|apt|unit)(?![\p{L}])\.?\s*[\w\-/]*/giu, ' ');
  // корпус / строение → 5к2, 5с1
  s = s.replace(/(\d+[а-я]?)\s*,?\s*(?<![\p{L}])(корп|корпус|к)(?![\p{L}])\.?\s*(\d+)/giu, '$1к$3');
  s = s.replace(/(\d+[а-я]?(?:к\d+)?)\s*,?\s*(?<![\p{L}])(стр|строение)(?![\p{L}])\.?\s*(\d+)/giu, '$1с$3');
  s = s.replace(/(?<![\p{L}])(д|дом|зд|влд)(?![\p{L}])\.?\s*(?=\d)/giu, '');
  s = s.replace(/(?<![\p{L}])(г|город)(?![\p{L}])\.?\s*(?=[А-ЯЁA-Z])/gu, '');
  for (const [re, rep] of EXPAND) s = s.replace(re, rep);
  return s
    .replace(/\s+/g, ' ')
    .replace(/\s*,\s*/g, ', ')
    .replace(/(,\s*)+/g, ', ')
    .replace(/^[\s,.]+|[\s,.]+$/g, '')
    .trim();
}

/** Набор запросов к геокодеру от точного к более общему. */
export function geocodeQueries(addr, defaultCity = '') {
  const clean = cleanForGeocode(addr);
  const out = [];
  const add = (q) => { q = q.trim(); if (q && !out.includes(q)) out.push(q); };
  const city = defaultCity.trim();
  const hasCity = city && clean.toLowerCase().includes(city.toLowerCase());
  if (city && !hasCity) add(`${clean}, ${city}`);
  add(clean);
  // без области/района
  const parts = clean.split(', ').filter((p) => !/(область|край|район|республика|округ)/iu.test(p));
  add(parts.join(', '));
  if (city && !hasCity) add(`${parts.join(', ')}, ${city}`);
  // без типа улицы
  add(parts.join(', ').replace(/(?<![\p{L}])(улица|проспект|переулок)(?![\p{L}])\s*/giu, ''));
  return out;
}
