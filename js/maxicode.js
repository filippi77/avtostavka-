// MaxiCode im Kamerabild finden und lesbar machen.
//
// zxing liest MaxiCode nur, wenn das Bild ausschließlich das gerade Symbol zeigt.
// Darum: 1) die "Zielscheibe" in der Mitte suchen (Ringe sehen in jeder Drehung gleich aus),
//        2) Größe aus dem Ringdurchmesser ableiten,
//        3) Symbol für verschiedene Drehwinkel gerade ausschneiden und zxing geben.

// Abstände Zielscheiben-Mitte → Symbolrand, in Einheiten des Ring-Außendurchmessers D (gemessen)
export const GEO = { left: 1.703, right: 1.814, top: 1.644, bottom: 1.605 };

/** RGBA → Graustufen */
export function toGray(img) {
  const { data, width, height } = img;
  const g = new Uint8Array(width * height);
  for (let i = 0, j = 0; j < g.length; i += 4, j++) g[j] = (data[i] * 77 + data[i + 1] * 150 + data[i + 2] * 29) >> 8;
  return g;
}

/** globaler Schwellwert (Otsu) */
function otsu(g) {
  const hist = new Uint32Array(256);
  for (let i = 0; i < g.length; i++) hist[g[i]]++;
  let sum = 0;
  for (let i = 0; i < 256; i++) sum += i * hist[i];
  let sumB = 0, wB = 0, best = 0, thr = 128;
  for (let t = 0; t < 256; t++) {
    wB += hist[t];
    if (!wB) continue;
    const wF = g.length - wB;
    if (!wF) break;
    sumB += t * hist[t];
    const mB = sumB / wB, mF = (sum - sumB) / wF;
    const v = wB * wF * (mB - mF) ** 2;
    if (v > best) { best = v; thr = t; }
  }
  return thr;
}

/** Läufe einer Linie (Folge dunkel/hell) */
function runsOf(get, n) {
  const runs = [];
  let cur = get(0), start = 0;
  for (let i = 1; i <= n; i++) {
    const d = i < n ? get(i) : !cur;
    if (d !== cur) { runs.push({ dark: cur, start, len: i - start }); cur = d; start = i; }
  }
  return runs;
}

/**
 * prüft 11 Läufe ab Index k: D H D H D [H-Mitte] D H D H D.
 * Breiten dürfen wegen Kantenglättung/Unschärfe schwanken, müssen aber symmetrisch zur Mitte sein.
 */
function ringMatch(runs, k) {
  if (k + 11 > runs.length || !runs[k].dark) return null;
  const r = runs.slice(k, k + 11);
  const outer = r.filter((_, i) => i !== 5);
  const u = outer.reduce((s, x) => s + x.len, 0) / 10;
  if (u < 2) return null;
  for (const x of outer) if (x.len < u * 0.35 || x.len > u * 2.1) return null;
  if (r[5].len < u * 0.6 || r[5].len > u * 3.2) return null;
  // Symmetrie: Lauf i ≈ Lauf 10-i
  for (let i = 0; i < 5; i++) {
    const a = r[i].len, b = r[10 - i].len;
    if (Math.abs(a - b) > Math.max(2, Math.max(a, b) * 0.5)) return null;
  }
  const c = r[5].start + r[5].len / 2;
  const D = r[10].start + r[10].len - r[0].start;
  return { c, D, u };
}

/**
 * Ring-Außendurchmesser genau durch die Mitte messen (waagrecht, senkrecht, zwei Diagonalen).
 * Die Suchzeile liegt oft etwas neben der Mitte – deren Sehne ist zu kurz.
 */
function measureD(dk, w, h, cx, cy, guess) {
  const out = [];
  for (const [ux, uy] of [[1, 0], [0, 1], [Math.SQRT1_2, Math.SQRT1_2], [Math.SQRT1_2, -Math.SQRT1_2]]) {
    const n = Math.round(guess * 1.6);
    const get = (i) => {
      const t = i - n;
      const x = Math.round(cx + ux * t), y = Math.round(cy + uy * t);
      return x >= 0 && y >= 0 && x < w && y < h && dk(x, y);
    };
    const runs = runsOf(get, 2 * n + 1);
    for (let k = 0; k + 11 <= runs.length; k++) {
      const m = ringMatch(runs, k);
      if (m && Math.abs(m.c - n) < guess * 0.2) { out.push(m.D); break; }
    }
  }
  if (!out.length) return guess;
  out.sort((a, b) => a - b);
  return out.length >= 3 ? (out[1] + out[out.length - 2]) / 2 : out.reduce((a, b) => a + b) / out.length;
}

/**
 * Zielscheiben im Graubild suchen. Liefert [{ x, y, D }] (Mitte, Ring-Außendurchmesser in Pixeln).
 * step: jede wievielte Zeile geprüft wird.
 */
export function findBullseyes(g, w, h, step = 2) {
  const thr = otsu(g);
  const dk = (x, y) => g[y * w + x] < thr;
  const found = [];
  for (let y = 0; y < h; y += step) {
    const runs = runsOf((x) => dk(x, y), w);
    for (let k = 0; k + 11 <= runs.length; k++) {
      const m = ringMatch(runs, k);
      if (!m) continue;
      const x = Math.round(m.c);
      // senkrecht gegenprüfen
      const vr = runsOf((yy) => dk(x, yy), h);
      let v = null;
      for (let j = 0; j + 11 <= vr.length; j++) {
        const mm = ringMatch(vr, j);
        if (mm && Math.abs(mm.c - y) < mm.D * 0.25) { v = mm; break; }
      }
      if (!v) continue;
      if (Math.abs(v.D - m.D) > Math.max(m.D, v.D) * 0.35) continue; // zu schräg
      const cx = m.c, cy = v.c;
      // nahe beieinander liegende Funde derselben Zielscheibe als Varianten behalten (max. 3)
      const near = found.filter((f) => Math.hypot(f.x - cx, f.y - cy) < f.D / 2);
      if (near.length >= 3) continue;
      const D = measureD(dk, w, h, cx, cy, (m.D + v.D) / 2);
      if (near.some((f) => Math.abs(f.x - cx) < 1 && Math.abs(f.y - cy) < 1 && Math.abs(f.D - D) < 1)) continue;
      found.push({ x: cx, y: cy, D });
    }
  }
  return found;
}

/**
 * Symbol um die Zielscheibe für Drehwinkel `deg` gerade ausschneiden.
 * Es wird großzügig ausgeschnitten; die echten Symbolränder werden danach an der Dichte der
 * dunklen Punkte erkannt (das Symbol ist von Text durch eine helle Ruhezone getrennt).
 * Alles außerhalb wird weiß – so braucht zxing keinen exakten Maßstab.
 * Liefert { data, width, height } (RGBA).
 */
export function extract(g, w, h, be, deg, px = 62, thr = 128) {
  const s = be.D / px;
  const a = (deg * Math.PI) / 180, ca = Math.cos(a), sa = Math.sin(a);
  const k = 1.25; // Reserve für ungenaue Größe
  const L = GEO.left * px * k, R = GEO.right * px * k, T = GEO.top * px * k, B = GEO.bottom * px * k;
  const ow = Math.round(L + R), oh = Math.round(T + B);
  const gray = new Uint8Array(ow * oh).fill(255);
  for (let y = 0; y < oh; y++) {
    const dy = (y - T) * s;
    for (let x = 0; x < ow; x++) {
      const dx = (x - L) * s;
      const sx = be.x + dx * ca - dy * sa, sy = be.y + dx * sa + dy * ca;
      const xi = sx | 0, yi = sy | 0;
      if (xi < 0 || yi < 0 || xi >= w - 1 || yi >= h - 1) continue;
      const fx = sx - xi, fy = sy - yi, i = yi * w + xi;
      gray[y * ow + x] = (g[i] * (1 - fx) + g[i + 1] * fx) * (1 - fy) + (g[i + w] * (1 - fx) + g[i + w + 1] * fx) * fy;
    }
  }
  // Ränder suchen: von der Mitte nach außen, bis eine Lücke von ~1 Modul ohne dunkle Punkte kommt
  const gap = Math.max(4, Math.round(px * 0.13));
  const cx = Math.round(L), cy = Math.round(T);
  const band = (fixedIsX, idx, from, to) => {
    for (let t = from; t < to; t++) {
      const v = fixedIsX ? gray[t * ow + idx] : gray[idx * ow + t];
      if (v < thr) return true;
    }
    return false;
  };
  const ry0 = Math.round(T - GEO.top * px * 1.1), ry1 = Math.round(T + GEO.bottom * px * 1.1);
  const rx0 = Math.round(L - GEO.left * px * 1.1), rx1 = Math.round(L + GEO.right * px * 1.1);
  const edge = (start, step, limit, fixedIsX, from, to) => {
    let last = start, empty = 0;
    for (let i = start; i !== limit; i += step) {
      if (band(fixedIsX, i, Math.max(0, from), Math.min(fixedIsX ? oh : ow, to))) { last = i; empty = 0; }
      else if (++empty >= gap) break;
    }
    return last;
  };
  const x0 = edge(cx, -1, -1, true, ry0, ry1), x1 = edge(cx, 1, ow, true, ry0, ry1);
  const y0 = edge(cy, -1, -1, false, x0, x1 + 1), y1 = edge(cy, 1, oh, false, x0, x1 + 1);
  const m = 6;
  const W = x1 - x0 + 1 + 2 * m, H = y1 - y0 + 1 + 2 * m;
  const out = new Uint8ClampedArray(W * H * 4).fill(255);
  for (let y = y0; y <= y1; y++) {
    for (let x = x0; x <= x1; x++) {
      const v = gray[y * ow + x], o = ((y - y0 + m) * W + (x - x0 + m)) * 4;
      out[o] = out[o + 1] = out[o + 2] = v;
    }
  }
  return { data: out, width: W, height: H };
}

let lastDeg = 0;
let search = null; // { x, y, D, i } – Fortschritt der Winkelsuche für dieselbe Zielscheibe über mehrere Bilder

/** Reihenfolge der Winkel: letzter Erfolg, dann 0/90/180/270 (Pakete liegen meist gerade), dann alle */
function angleOrder() {
  const seen = new Set();
  const out = [];
  const add = (d) => { d = ((Math.round(d) % 360) + 360) % 360; if (!seen.has(d)) { seen.add(d); out.push(d); } };
  for (const e of [0, 1, -1, 2, -2, 3, -3]) add(lastDeg + e);
  for (const e of [0, 1, -1, 2, -2, 3, -3, 4, -4, 5, -5]) for (const q of [0, 90, 180, 270]) add(q + e);
  for (let d = 0; d < 180; d++) { add(lastDeg + d); add(lastDeg - d); }
  return out;
}

export async function readMaxiCode(img, read, { budgetMs = 250 } = {}) {
  const t0 = Date.now();
  const g = toGray(img);
  const thr = otsu(g);
  const all = findBullseyes(g, img.width, img.height);
  if (!all.length) return null;
  // größte Zielscheibe (nächstes Etikett) samt nahe beieinander liegender Varianten
  const main = all.reduce((a, b) => (b.D > a.D ? b : a));
  const variants = all.filter((f) => Math.hypot(f.x - main.x, f.y - main.y) < main.D / 2).slice(0, 2);
  // dieselbe Zielscheibe wie im letzten Bild → Suche dort fortsetzen
  const same = search && Math.hypot(search.x - main.x, search.y - main.y) < main.D * 0.6 && Math.abs(search.D - main.D) < main.D * 0.15;
  if (!same) search = { x: main.x, y: main.y, D: main.D, i: 0, order: angleOrder() };
  while (search.i < search.order.length) {
    const deg = search.order[search.i++];
    for (const be of variants) {
      const res = await read(extract(g, img.width, img.height, be, deg, 62, thr));
      if (res?.length) {
        lastDeg = deg;
        search = null;
        return { text: res[0].text, bullseye: be, deg };
      }
    }
    if (Date.now() - t0 > budgetMs) return { text: null, bullseye: main };
  }
  search.i = 0; // einmal komplett durch – im nächsten Bild neu beginnen
  return { text: null, bullseye: main };
}
