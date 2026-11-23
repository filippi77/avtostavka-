// Оптимизация порядка объезда и построение маршрута (OSRM с локальным запасным вариантом).

const OSRM = 'https://router.project-osrm.org';

export function haversine(a, b) {
  const R = 6371000;
  const toRad = (x) => (x * Math.PI) / 180;
  const dLat = toRad(b.lat - a.lat);
  const dLon = toRad(b.lon - a.lon);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(toRad(a.lat)) * Math.cos(toRad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

function pathCost(order, D, roundtrip) {
  let c = 0;
  for (let i = 0; i < order.length - 1; i++) c += D[order[i]][order[i + 1]];
  if (roundtrip && order.length > 1) c += D[order[order.length - 1]][order[0]];
  return c;
}

/**
 * Порядок обхода точек. Индекс 0 — старт (фиксирован).
 * D — матрица стоимостей (может быть несимметричной).
 * Возвращает массив индексов, начинающийся с 0.
 */
export function optimizeOrder(D, roundtrip = false) {
  const n = D.length;
  if (n <= 2) return [...Array(n).keys()];

  // Ближайший сосед
  const used = new Array(n).fill(false);
  let order = [0];
  used[0] = true;
  for (let k = 1; k < n; k++) {
    const last = order[order.length - 1];
    let best = -1;
    for (let j = 0; j < n; j++) {
      if (!used[j] && (best < 0 || D[last][j] < D[last][best])) best = j;
    }
    used[best] = true;
    order.push(best);
  }

  // 2-opt + перемещение одной точки (or-opt), пока есть улучшение
  let cost = pathCost(order, D, roundtrip);
  let improved = true;
  let guard = 0;
  while (improved && guard++ < 200) {
    improved = false;
    for (let i = 1; i < n - 1; i++) {
      for (let j = i + 1; j < n; j++) {
        const cand = order.slice(0, i).concat(order.slice(i, j + 1).reverse(), order.slice(j + 1));
        const c = pathCost(cand, D, roundtrip);
        if (c + 1e-9 < cost) { order = cand; cost = c; improved = true; }
      }
    }
    for (let i = 1; i < n; i++) {
      for (let j = 1; j < n; j++) {
        if (i === j) continue;
        const cand = order.slice();
        const [x] = cand.splice(i, 1);
        cand.splice(j, 0, x);
        const c = pathCost(cand, D, roundtrip);
        if (c + 1e-9 < cost) { order = cand; cost = c; improved = true; }
      }
    }
  }
  return order;
}

const coordStr = (pts) => pts.map((p) => `${p.lon.toFixed(6)},${p.lat.toFixed(6)}`).join(';');

async function fetchJson(url, timeoutMs = 15000) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const r = await fetch(url, { signal: ctrl.signal });
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return await r.json();
  } finally {
    clearTimeout(t);
  }
}

/**
 * Строит маршрут: points[0] — старт.
 * Возвращает { order, geometry: [[lat,lon],...], distance, duration, source }.
 */
export async function buildRoute(points, { roundtrip = false } = {}) {
  let D = null;
  let source = 'osrm';
  try {
    if (points.length > 100) throw new Error('too many');
    const t = await fetchJson(`${OSRM}/table/v1/driving/${coordStr(points)}?annotations=duration`);
    if (t.code !== 'Ok') throw new Error(t.code);
    D = t.durations.map((row) => row.map((v) => (v == null ? 1e9 : v)));
  } catch {
    source = 'local';
    D = points.map((a) => points.map((b) => haversine(a, b)));
  }

  const order = optimizeOrder(D, roundtrip);
  const ordered = order.map((i) => points[i]);
  if (roundtrip) ordered.push(points[0]);

  if (source === 'osrm') {
    try {
      const r = await fetchJson(`${OSRM}/route/v1/driving/${coordStr(ordered)}?overview=full&geometries=geojson`);
      if (r.code !== 'Ok') throw new Error(r.code);
      const route = r.routes[0];
      return {
        order,
        geometry: route.geometry.coordinates.map(([lon, lat]) => [lat, lon]),
        distance: route.distance,
        duration: route.duration,
        legs: route.legs.map((l) => ({ distance: l.distance, duration: l.duration })),
        source,
      };
    } catch {
      source = 'local';
    }
  }

  // Запасной вариант: прямые отрезки, оценка по расстоянию ×1.3 и 30 км/ч
  const legs = [];
  for (let i = 0; i < ordered.length - 1; i++) {
    const d = haversine(ordered[i], ordered[i + 1]) * 1.3;
    legs.push({ distance: d, duration: d / (30 / 3.6) });
  }
  return {
    order,
    geometry: ordered.map((p) => [p.lat, p.lon]),
    distance: legs.reduce((s, l) => s + l.distance, 0),
    duration: legs.reduce((s, l) => s + l.duration, 0),
    legs,
    source,
  };
}
