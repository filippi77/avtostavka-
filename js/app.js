import { extractAddress } from './address.js';
import { geocode, reverse } from './geocode.js';
import { buildRoute } from './route.js';
import { recognize } from './ocr.js';

const $ = (s) => document.querySelector(s);
const KEY = 'avtostavka.v1';

const defaults = {
  stops: [],
  route: null,
  settings: { city: '', country: 'ru', start: 'gps', roundtrip: false, nav: 'yandex', autoAdd: false },
};

let state = load();
function load() {
  try {
    const s = JSON.parse(localStorage.getItem(KEY));
    if (s && Array.isArray(s.stops)) return { ...defaults, ...s, settings: { ...defaults.settings, ...s.settings } };
  } catch {}
  return structuredClone(defaults);
}
function save() {
  try { localStorage.setItem(KEY, JSON.stringify(state)); } catch {}
}
const uid = () => Math.random().toString(36).slice(2, 10);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

function toast(msg, ms = 2500) {
  const t = $('#toast');
  t.textContent = msg;
  t.classList.add('show');
  clearTimeout(toast.t);
  toast.t = setTimeout(() => t.classList.remove('show'), ms);
}

const fmtKm = (m) => (m >= 1000 ? (m / 1000).toFixed(1).replace('.', ',') + ' км' : Math.round(m) + ' м');
const fmtTime = (s) => {
  const m = Math.round(s / 60);
  return m >= 60 ? `${Math.floor(m / 60)} ч ${m % 60} мин` : `${m} мин`;
};

/* ---------------- Вкладки ---------------- */

let currentView = 'list';
function showView(v) {
  currentView = v;
  document.querySelectorAll('.view').forEach((el) => el.classList.toggle('active', el.id === 'view-' + v));
  document.querySelectorAll('.tab[data-view]').forEach((el) => el.classList.toggle('active', el.dataset.view === v));
  if (v === 'map') {
    initMap();
    setTimeout(() => { map.invalidateSize(); renderMap(); }, 0);
  }
}
document.querySelectorAll('.tab[data-view]').forEach((b) => b.addEventListener('click', () => showView(b.dataset.view)));

/* ---------------- Список ---------------- */

function invalidateRoute() {
  state.route = null;
}

let openId = null;
function render() {
  const list = $('#stops');
  const pending = state.stops.filter((s) => s.status !== 'delivered');
  const done = state.stops.length - pending.length;
  $('#summary').textContent = state.stops.length ? `${pending.length} осталось · ${done} доставлено` : '';
  $('#emptyList').hidden = state.stops.length > 0;
  $('#listFooter').hidden = state.stops.length === 0;

  const legs = state.route?.legsById || {};
  let n = 0;
  list.innerHTML = state.stops
    .map((s, i) => {
      const delivered = s.status === 'delivered';
      if (!delivered) n++;
      const leg = legs[s.id];
      return `
      <li class="stop ${openId === s.id ? 'open' : ''} ${delivered ? 'delivered' : ''} ${s.lat == null ? 'nocoords' : ''}" data-id="${s.id}">
        <div class="num">${delivered ? '✓' : n}</div>
        <div class="stop-main" data-act="toggle">
          <div class="addr">${esc(s.address)}</div>
          <div class="meta">
            ${s.lat == null ? '<span class="warn">нет координат — укажите на карте</span>' : ''}
            ${s.phone ? `<a href="tel:${esc(s.phone)}">${esc(s.phone)}</a>` : ''}
            ${s.note ? `<span>${esc(s.note)}</span>` : ''}
            ${leg && !delivered ? `<span>${fmtKm(leg.distance)} · ${fmtTime(leg.duration)}</span>` : ''}
          </div>
        </div>
        <div class="stop-actions">
          <button class="btn done" data-act="done">${delivered ? 'Вернуть' : '✓ Доставлено'}</button>
          ${s.lat != null ? '<button class="btn" data-act="nav">Навигатор</button>' : '<button class="btn" data-act="place">На карте</button>'}
          <button class="icon-btn" data-act="toggle" aria-label="Ещё"><svg viewBox="0 0 24 24"><circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/></svg></button>
        </div>
        <div class="stop-extra">
          <button class="icon-btn" data-act="up" aria-label="Выше" ${i === 0 ? 'disabled' : ''}><svg viewBox="0 0 24 24"><path d="m6 15 6-6 6 6"/></svg></button>
          <button class="icon-btn" data-act="down" aria-label="Ниже" ${i === state.stops.length - 1 ? 'disabled' : ''}><svg viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></svg></button>
          <button class="icon-btn" data-act="show" aria-label="Показать на карте" ${s.lat == null ? 'disabled' : ''}><svg viewBox="0 0 24 24"><path d="M12 21s-7-6.2-7-11a7 7 0 1 1 14 0c0 4.8-7 11-7 11Z"/><circle cx="12" cy="10" r="2.5"/></svg></button>
          <button class="icon-btn" data-act="edit" aria-label="Изменить"><svg viewBox="0 0 24 24"><path d="M4 20h4L19 9l-4-4L4 16v4Z"/></svg></button>
          <button class="icon-btn" data-act="del" aria-label="Удалить"><svg viewBox="0 0 24 24"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg></button>
        </div>
      </li>`;
    })
    .join('');
  if (map) renderMap();
}

$('#stops').addEventListener('click', (e) => {
  const btn = e.target.closest('[data-act]');
  if (!btn) return;
  const id = btn.closest('.stop').dataset.id;
  const i = state.stops.findIndex((s) => s.id === id);
  const s = state.stops[i];
  switch (btn.dataset.act) {
    case 'toggle': openId = openId === id ? null : id; render(); return;
    case 'done':
      s.status = s.status === 'delivered' ? 'pending' : 'delivered';
      s.deliveredAt = s.status === 'delivered' ? Date.now() : null;
      // доставленные — в конец списка
      if (s.status === 'delivered') { state.stops.splice(i, 1); state.stops.push(s); }
      break;
    case 'nav': openNav([s]); return;
    case 'place': startPlacing(s.id); return;
    case 'show': showView('map'); setTimeout(() => { map.setView([s.lat, s.lon], 17); markers[s.id]?.openPopup(); }, 50); return;
    case 'up': if (i > 0) { [state.stops[i - 1], state.stops[i]] = [state.stops[i], state.stops[i - 1]]; invalidateRoute(); } break;
    case 'down': if (i < state.stops.length - 1) { [state.stops[i + 1], state.stops[i]] = [state.stops[i], state.stops[i + 1]]; invalidateRoute(); } break;
    case 'edit': openAdd({ edit: s }); return;
    case 'del':
      if (!confirm('Удалить адрес?\n' + s.address)) return;
      state.stops.splice(i, 1);
      invalidateRoute();
      break;
  }
  save();
  render();
});

$('#btnClearDelivered').addEventListener('click', () => {
  const n = state.stops.filter((s) => s.status === 'delivered').length;
  if (!n) return toast('Нет доставленных');
  if (!confirm(`Убрать ${n} доставленных из списка?`)) return;
  state.stops = state.stops.filter((s) => s.status !== 'delivered');
  invalidateRoute();
  save();
  render();
});

/* ---------------- Добавление / сканирование ---------------- */

const dlg = $('#dlgAdd');
let editing = null;
let candidates = [];
let lastPhoto = null;

function openAdd({ edit = null, scan = false } = {}) {
  editing = edit;
  candidates = [];
  $('#addTitle').textContent = edit ? 'Изменить адрес' : 'Новая посылка';
  $('#scanSrc').hidden = !!edit;
  $('#addrInput').value = edit?.address || '';
  $('#phoneInput').value = edit?.phone || '';
  $('#noteInput').value = edit?.note || '';
  $('#rawBox').hidden = true;
  $('#rawText').textContent = '';
  $('#scanPreview').hidden = true;
  $('#ocrProgress').hidden = true;
  $('#candidates').innerHTML = '';
  $('#geoStatus').textContent = '';
  $('#geoStatus').className = 'status';
  $('#btnAdd').disabled = !edit;
  $('#btnAdd').textContent = edit ? 'Сохранить' : 'Добавить';
  if (!dlg.open) dlg.showModal();
  if (scan) $('#fileCamera').click();
}

$('#btnScan').addEventListener('click', () => openAdd({ scan: true }));
$('#tabScan').addEventListener('click', () => openAdd({ scan: true }));
$('#btnManual').addEventListener('click', () => { openAdd(); $('#addrInput').focus(); });
$('#btnCamera').addEventListener('click', () => $('#fileCamera').click());
$('#btnGallery').addEventListener('click', () => $('#fileGallery').click());
$('#fileCamera').addEventListener('change', onPhoto);
$('#fileGallery').addEventListener('change', onPhoto);

async function onPhoto(e) {
  const file = e.target.files?.[0];
  e.target.value = '';
  if (!file) return;
  if (!dlg.open) openAdd();
  lastPhoto = file;
  const prev = $('#scanPreview');
  if (prev.src) URL.revokeObjectURL(prev.src);
  prev.src = URL.createObjectURL(file);
  prev.hidden = false;

  const pr = $('#ocrProgress');
  pr.hidden = false;
  $('#btnFind').disabled = true;
  try {
    if (!window.Tesseract) throw new Error('Модуль распознавания не загрузился — проверьте интернет');
    const { text } = await recognize(file, (label, p) => {
      $('#ocrLabel').textContent = label;
      $('#ocrBar').style.width = Math.round((p || 0) * 100) + '%';
    });
    $('#rawText').textContent = text.trim() || '(текст не найден)';
    $('#rawBox').hidden = false;
    const { address, phone, confidence } = extractAddress(text);
    if (!address) {
      $('#rawBox').open = true;
      setStatus('Адрес не найден на фото. Введите вручную или переснимите крупнее.', true);
      return;
    }
    $('#addrInput').value = address;
    if (phone && !$('#phoneInput').value) $('#phoneInput').value = phone;
    if (confidence === 'low') $('#rawBox').open = true;
    await findCandidates({ auto: state.settings.autoAdd && confidence !== 'low' });
  } catch (err) {
    console.error(err);
    setStatus('Ошибка распознавания: ' + (err.message || err), true);
  } finally {
    pr.hidden = true;
    $('#btnFind').disabled = false;
  }
}

function setStatus(msg, err = false) {
  const el = $('#geoStatus');
  el.textContent = msg;
  el.className = 'status' + (err ? ' err' : '');
}

function nearPoint() {
  const pts = state.stops.filter((s) => s.lat != null);
  if (pts.length) return { lat: pts.reduce((a, s) => a + s.lat, 0) / pts.length, lon: pts.reduce((a, s) => a + s.lon, 0) / pts.length };
  return myPos;
}

async function findCandidates({ auto = false } = {}) {
  const addr = $('#addrInput').value.trim();
  if (!addr) return setStatus('Введите адрес', true);
  setStatus('Поиск адреса на карте…');
  $('#candidates').innerHTML = '';
  $('#btnAdd').disabled = !editing;
  try {
    candidates = await geocode(addr, { country: state.settings.country.trim().toLowerCase(), city: state.settings.city, near: nearPoint() });
  } catch (err) {
    candidates = [];
    return setStatus(err.message || 'Ошибка геокодера', true);
  }
  if (!candidates.length) {
    return setStatus('Адрес не найден. Исправьте текст (город, улица, дом) или укажите точку на карте вручную.', true);
  }
  setStatus(candidates.length === 1 ? 'Найдено:' : `Найдено вариантов: ${candidates.length}. Выберите нужный:`);
  $('#candidates').innerHTML = candidates
    .map((c, i) => `<li><label><input type="radio" name="cand" value="${i}" ${i === 0 ? 'checked' : ''}><span>${esc(c.label)}</span></label></li>`)
    .join('');
  $('#btnAdd').disabled = false;
  if (auto && candidates.length === 1) commitAdd();
}

$('#btnFind').addEventListener('click', () => findCandidates());
$('#addrInput').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); findCandidates(); }
});

function commitAdd({ withoutCoords = false } = {}) {
  const address = $('#addrInput').value.trim();
  if (!address) return setStatus('Введите адрес', true);
  const sel = document.querySelector('input[name="cand"]:checked');
  const c = !withoutCoords && sel ? candidates[+sel.value] : null;
  const data = {
    address,
    phone: $('#phoneInput').value.trim(),
    note: $('#noteInput').value.trim(),
  };
  let stop;
  if (editing) {
    stop = Object.assign(editing, data);
    if (c) { stop.lat = c.lat; stop.lon = c.lon; stop.geoLabel = c.label; }
  } else {
    if (state.stops.some((s) => s.address.toLowerCase() === address.toLowerCase()) && !confirm('Такой адрес уже есть в списке. Добавить ещё раз?')) return;
    stop = { id: uid(), ...data, lat: c?.lat ?? null, lon: c?.lon ?? null, geoLabel: c?.label || '', status: 'pending', createdAt: Date.now() };
    // новые — перед доставленными
    const firstDone = state.stops.findIndex((s) => s.status === 'delivered');
    if (firstDone < 0) state.stops.push(stop); else state.stops.splice(firstDone, 0, stop);
  }
  invalidateRoute();
  save();
  render();
  const wasEdit = !!editing;
  dlg.close();
  if (withoutCoords) startPlacing(stop.id);
  else if (!wasEdit) {
    toast('Добавлено: ' + address);
  }
}
$('#btnAdd').addEventListener('click', () => commitAdd());
$('#btnAddNoCoords').addEventListener('click', () => commitAdd({ withoutCoords: true }));

/* ---------------- Карта ---------------- */

let map = null;
let markers = {};
let routeLine = null;
let meMarker = null;
let myPos = null;
let placingId = null;
const FIT = { paddingTopLeft: [30, 30], paddingBottomRight: [30, 150] };

function initMap() {
  if (map) return;
  if (!window.L) { toast('Карта не загрузилась — проверьте интернет'); return; }
  map = L.map('map', { zoomControl: false }).setView([55.751, 37.618], 11);
  L.control.zoom({ position: 'topright' }).addTo(map);
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© OpenStreetMap',
  }).addTo(map);
  map.on('click', onMapClick);
  let fitted = false;
  const pts = state.stops.filter((s) => s.lat != null);
  if (pts.length) { map.fitBounds(pts.map((s) => [s.lat, s.lon]), FIT); fitted = true; }
  locate(!fitted);
}

function pinIcon(label, cls) {
  return L.divIcon({ className: '', html: `<div class="pin ${cls}"><span>${label}</span></div>`, iconSize: [30, 30], iconAnchor: [15, 30], popupAnchor: [0, -28] });
}

function renderMap() {
  if (!map) return;
  Object.values(markers).forEach((m) => m.remove());
  markers = {};
  let n = 0;
  let nextMarked = false;
  for (const s of state.stops) {
    const delivered = s.status === 'delivered';
    if (!delivered) n++;
    if (s.lat == null) continue;
    let cls = delivered ? 'delivered' : '';
    if (!delivered && !nextMarked) { cls = 'next'; nextMarked = true; }
    const m = L.marker([s.lat, s.lon], { icon: pinIcon(delivered ? '✓' : n, cls), draggable: true }).addTo(map);
    m.bindPopup(`
      <b>${delivered ? '✓' : n}. ${esc(s.address)}</b><br>
      ${s.phone ? `<a href="tel:${esc(s.phone)}">${esc(s.phone)}</a><br>` : ''}
      ${s.note ? esc(s.note) + '<br>' : ''}
      <button class="btn small primary" data-pop="nav" data-id="${s.id}">Навигатор</button>
      <button class="btn small" data-pop="done" data-id="${s.id}">${delivered ? 'Вернуть' : '✓ Доставлено'}</button>
      <div class="hint">Маркер можно перетащить, если точка неточная</div>`);
    m.on('dragend', () => {
      const p = m.getLatLng();
      s.lat = p.lat;
      s.lon = p.lng;
      invalidateRoute();
      save();
      render();
      toast('Точка перемещена');
    });
    markers[s.id] = m;
  }
  if (routeLine) { routeLine.remove(); routeLine = null; }
  if (state.route?.geometry?.length) {
    routeLine = L.polyline(state.route.geometry, { color: '#1f6feb', weight: 5, opacity: 0.75 }).addTo(map);
  }
  updateRouteInfo();
}

document.addEventListener('click', (e) => {
  const b = e.target.closest('[data-pop]');
  if (!b) return;
  const s = state.stops.find((x) => x.id === b.dataset.id);
  if (!s) return;
  if (b.dataset.pop === 'nav') openNav([s]);
  if (b.dataset.pop === 'done') {
    s.status = s.status === 'delivered' ? 'pending' : 'delivered';
    const i = state.stops.indexOf(s);
    if (s.status === 'delivered') { state.stops.splice(i, 1); state.stops.push(s); }
    save();
    map.closePopup();
    render();
  }
});

function updateRouteInfo() {
  const el = $('#routeInfo');
  const r = state.route;
  const pending = state.stops.filter((s) => s.status !== 'delivered' && s.lat != null).length;
  if (!r) {
    el.innerHTML = pending ? `Точек к доставке: <b>${pending}</b>. Маршрут не построен.` : 'Нет точек для маршрута';
    return;
  }
  el.innerHTML = `Маршрут: <b>${fmtKm(r.distance)}</b> · <b>${fmtTime(r.duration)}</b> · ${pending} точек${r.source === 'local' ? ' <span class="warn">(приблизительно, сервер маршрутов недоступен)</span>' : ''}`;
}

function locate(center = false) {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null);
    navigator.geolocation.getCurrentPosition(
      (p) => {
        myPos = { lat: p.coords.latitude, lon: p.coords.longitude };
        if (map) {
          if (!meMarker) meMarker = L.marker([myPos.lat, myPos.lon], { icon: L.divIcon({ className: '', html: '<div class="me-dot"></div>', iconSize: [18, 18] }), interactive: false, zIndexOffset: -100 }).addTo(map);
          else meMarker.setLatLng([myPos.lat, myPos.lon]);
          if (center) map.setView([myPos.lat, myPos.lon], 14);
        }
        resolve(myPos);
      },
      () => resolve(null),
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 }
    );
  });
}
$('#btnLocate').addEventListener('click', async () => {
  const p = await locate(true);
  if (!p) toast('Не удалось определить местоположение');
});

/* ---- ручная установка точки ---- */
function startPlacing(id) {
  const s = state.stops.find((x) => x.id === id);
  if (!s) return;
  placingId = id;
  showView('map');
  $('#placeHintAddr').textContent = s.address;
  $('#placeHint').hidden = false;
}
function stopPlacing() {
  placingId = null;
  $('#placeHint').hidden = true;
}
$('#btnPlaceCancel').addEventListener('click', stopPlacing);
async function onMapClick(e) {
  if (!placingId) return;
  const s = state.stops.find((x) => x.id === placingId);
  stopPlacing();
  if (!s) return;
  s.lat = e.latlng.lat;
  s.lon = e.latlng.lng;
  invalidateRoute();
  save();
  render();
  toast('Точка установлена');
  try { s.geoLabel = await reverse(s.lat, s.lon); save(); } catch {}
}

/* ---------------- Маршрут ---------------- */

async function optimize() {
  const pending = state.stops.filter((s) => s.status !== 'delivered' && s.lat != null);
  if (!pending.length) return toast('Нет адресов с координатами');
  const btns = [$('#btnRoute'), $('#btnOptimize')];
  btns.forEach((b) => { b.disabled = true; });
  const oldText = $('#btnRoute').textContent;
  $('#btnRoute').textContent = 'Строю…';
  try {
    let start = null;
    if (state.settings.start === 'gps') {
      start = await locate();
      if (!start) toast('GPS недоступен — старт с первой точки');
    }
    const points = start ? [{ ...start, id: '__start' }, ...pending] : pending;
    const r = await buildRoute(points, { roundtrip: state.settings.roundtrip });
    const orderedStops = r.order.map((i) => points[i]).filter((p) => p.id !== '__start');
    const legsById = {};
    // legs[k] — участок от k-й к (k+1)-й точке в порядке обхода
    r.order.forEach((pi, k) => {
      if (k === 0 && start) return;
      const p = points[pi];
      const leg = r.legs[k - 1];
      if (leg) legsById[p.id] = leg;
    });
    const noCoords = state.stops.filter((s) => s.status !== 'delivered' && s.lat == null);
    const delivered = state.stops.filter((s) => s.status === 'delivered');
    state.stops = [...orderedStops, ...noCoords, ...delivered];
    state.route = { geometry: r.geometry, distance: r.distance, duration: r.duration, source: r.source, legsById, builtAt: Date.now() };
    save();
    render();
    if (map) {
      const b = L.latLngBounds(r.geometry);
      if (b.isValid()) map.fitBounds(b, FIT);
    }
    toast(`Маршрут построен: ${fmtKm(r.distance)}, ${fmtTime(r.duration)}`);
  } catch (err) {
    console.error(err);
    toast('Не удалось построить маршрут');
  } finally {
    btns.forEach((b) => { b.disabled = false; });
    $('#btnRoute').textContent = oldText;
  }
}
$('#btnRoute').addEventListener('click', optimize);
$('#btnOptimize').addEventListener('click', async () => { await optimize(); });

/* ---------------- Навигатор ---------------- */

function navUrl(points) {
  const nav = state.settings.nav;
  const last = points[points.length - 1];
  if (nav === 'google') {
    const p = new URLSearchParams({ api: '1', destination: `${last.lat},${last.lon}`, travelmode: 'driving' });
    const way = points.slice(0, -1).slice(0, 9);
    if (way.length) p.set('waypoints', way.map((s) => `${s.lat},${s.lon}`).join('|'));
    return 'https://www.google.com/maps/dir/?' + p;
  }
  if (nav === '2gis') {
    return `https://2gis.ru/routeSearch/rsType/car/to/${last.lon},${last.lat}`;
  }
  // Яндекс: пустая первая точка = «от моего местоположения»
  return 'https://yandex.ru/maps/?rtt=auto&rtext=' + ['', ...points.map((s) => `${s.lat},${s.lon}`)].join('~');
}

function openNav(points) {
  if (!points.length) return toast('Нет точек');
  window.open(navUrl(points), '_blank');
}
$('#btnOpenNav').addEventListener('click', () => {
  const pending = state.stops.filter((s) => s.status !== 'delivered' && s.lat != null);
  if (!pending.length) return toast('Нет точек');
  // В навигатор передаём ближайшие точки по порядку (у сервисов есть лимит на число точек)
  const limit = state.settings.nav === 'google' ? 10 : state.settings.nav === '2gis' ? 1 : 20;
  openNav(pending.slice(0, limit));
});

/* ---------------- Настройки ---------------- */

const dlgS = $('#dlgSettings');
$('#btnSettings').addEventListener('click', () => {
  const s = state.settings;
  $('#setCity').value = s.city;
  $('#setCountry').value = s.country;
  $('#setStart').value = s.start;
  $('#setRoundtrip').checked = s.roundtrip;
  $('#setNav').value = s.nav;
  $('#setAutoAdd').checked = s.autoAdd;
  dlgS.showModal();
});
$('#btnSaveSettings').addEventListener('click', () => {
  Object.assign(state.settings, {
    city: $('#setCity').value.trim(),
    country: $('#setCountry').value.trim().toLowerCase(),
    start: $('#setStart').value,
    roundtrip: $('#setRoundtrip').checked,
    nav: $('#setNav').value,
    autoAdd: $('#setAutoAdd').checked,
  });
  save();
  toast('Настройки сохранены');
});
$('#btnClearAll').addEventListener('click', () => {
  if (!confirm('Удалить все адреса из списка?')) return;
  state.stops = [];
  state.route = null;
  save();
  render();
  dlgS.close();
});

/* ---------------- Старт ---------------- */

render();
if ('serviceWorker' in navigator && location.protocol !== 'file:') {
  navigator.serviceWorker.register('sw.js').catch(() => {});
}
// Для автотестов
window.__app = { state: () => state, render, optimize };
