import { extractAddress } from './address.js';
import { geocode, reverse } from './geocode.js';
import { buildRoute } from './route.js';
import { recognize, warmUp } from './ocr.js';
import { t, setLang, getLang, applyI18n, fmtDist, fmtTime } from './i18n.js';

const $ = (s) => document.querySelector(s);
const KEY = 'avtostavka.v1';

const IS_IOS = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
const IS_STANDALONE = navigator.standalone === true || matchMedia('(display-mode: standalone)').matches;

// Android-App (Capacitor): nativer Live-Scanner mit Google ML Kit
const IS_NATIVE = !!window.Capacitor?.isNativePlatform?.();
const NativeScanner = (() => {
  if (!IS_NATIVE) return null;
  try { return window.Capacitor.registerPlugin ? window.Capacitor.registerPlugin('LabelScanner') : window.Capacitor.Plugins?.LabelScanner; } catch { return null; }
})();

const defaults = {
  stops: [],
  route: null,
  hideInstallHint: false,
  settings: {
    lang: 'de',
    ocr: 'deu+eng',
    city: '',
    country: 'de',
    start: 'gps',
    roundtrip: false,
    nav: IS_IOS ? 'apple' : 'google',
    autoAdd: false,
  },
};

let state = load();
function load() {
  let s = null;
  try { s = JSON.parse(localStorage.getItem(KEY)); } catch {}
  if (!s || !Array.isArray(s.stops)) return structuredClone(defaults);
  s = { ...defaults, ...s, settings: { ...defaults.settings, ...s.settings } };
  if (!['apple', 'google', 'waze'].includes(s.settings.nav)) s.settings.nav = defaults.settings.nav;
  if (!['de', 'ru'].includes(s.settings.lang)) s.settings.lang = 'de';
  return s;
}
function save() {
  try { localStorage.setItem(KEY, JSON.stringify(state)); } catch {}
}
const uid = () => Math.random().toString(36).slice(2, 10);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const isOpen = (s) => s.status === 'pending';
const hasPos = (s) => s.lat != null;

function toast(msg, ms = 2600) {
  const el = $('#toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(toast.t);
  toast.t = setTimeout(() => el.classList.remove('show'), ms);
}

/** "Hauptstraße 12, 10115 Berlin" → { street, city } */
function splitAddr(a) {
  const parts = String(a).split(/\s*,\s*/);
  const i = parts.findIndex((p, k) => k > 0 && /^\d{4,5}\s/.test(p));
  if (i > 0) return { street: parts.slice(0, i).join(', '), city: parts.slice(i).join(', ') };
  return { street: a, city: '' };
}

const ICON = {
  nav: '<svg viewBox="0 0 24 24"><path d="m3 11 19-9-9 19-2-8-8-2Z"/></svg>',
  check: '<svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"/></svg>',
  phone: '<svg viewBox="0 0 24 24"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.7 2Z"/></svg>',
  pin: '<svg viewBox="0 0 24 24"><path d="M12 21s-7-6.2-7-11a7 7 0 1 1 14 0c0 4.8-7 11-7 11Z"/><circle cx="12" cy="10" r="2.5"/></svg>',
  edit: '<svg viewBox="0 0 24 24"><path d="M4 20h4L19 9l-4-4L4 16v4Z"/></svg>',
  up: '<svg viewBox="0 0 24 24"><path d="m6 15 6-6 6 6"/></svg>',
  down: '<svg viewBox="0 0 24 24"><path d="m6 9 6 6 6-6"/></svg>',
  del: '<svg viewBox="0 0 24 24"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>',
  undo: '<svg viewBox="0 0 24 24"><path d="M9 14 4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/></svg>',
  chev: '<svg class="chev" viewBox="0 0 24 24"><path d="m9 6 6 6-6 6"/></svg>',
};

/* ---------------- Ansichten ---------------- */

let currentView = 'list';
function showView(v) {
  currentView = v;
  document.querySelectorAll('.view').forEach((el) => el.classList.toggle('active', el.id === 'view-' + v));
  document.querySelectorAll('.tab[data-view]').forEach((el) => el.classList.toggle('active', el.dataset.view === v));
  $('#title').dataset.i18n = v === 'map' ? 'tab_map' : 'tab_tour';
  $('#title').textContent = t($('#title').dataset.i18n);
  if (v === 'map') {
    initMap();
    if (map) setTimeout(() => { map.invalidateSize(); renderMap(); }, 0);
  }
}
document.querySelectorAll('.tab[data-view]').forEach((b) => b.addEventListener('click', () => showView(b.dataset.view)));

/* ---------------- Tour-Liste ---------------- */

let openId = null;

function invalidateRoute() { state.route = null; }

function render() {
  const pending = state.stops.filter(isOpen);
  const done = state.stops.filter((s) => !isOpen(s));
  const total = state.stops.length;

  $('#summary').textContent = total ? t('summary', { left: pending.length, done: done.length }) : t('summary_empty');
  $('#progressFill').style.width = total ? (done.length / total) * 100 + '%' : '0';
  $('#btnOptimizeTop').hidden = pending.filter(hasPos).length < 2;
  $('#emptyList').hidden = total > 0;
  $('#btnManual').hidden = total === 0;
  $('#installHint').hidden = !(IS_IOS && !IS_STANDALONE && !state.hideInstallHint);

  // Nächster Stopp
  const next = pending[0];
  $('#nextWrap').hidden = !next;
  if (next) $('#nextCard').innerHTML = nextCardHtml(next);

  // Weitere Stopps
  const rest = pending.slice(1);
  $('#restWrap').hidden = rest.length === 0;
  $('#restCount').textContent = rest.length;
  $('#stops').innerHTML = rest.map((s, k) => rowHtml(s, k + 2, { first: k === 0, last: k === rest.length - 1 })).join('');

  // Erledigt
  $('#doneWrap').hidden = done.length === 0;
  $('#doneCount').textContent = done.length;
  $('#doneList').innerHTML = done.map((s) => rowHtml(s, null)).join('');

  if (map) renderMap();
}

function chipsHtml(s) {
  const leg = state.route?.legsById?.[s.id];
  const chips = [];
  if (!hasPos(s)) chips.push(`<span class="chip warn">${esc(t('no_coords'))}</span>`);
  if (leg) chips.push(`<span class="chip">${fmtDist(leg.distance)} · ${fmtTime(leg.duration)}</span>`);
  if (s.note) chips.push(`<span class="chip">${esc(s.note)}</span>`);
  return chips.length ? `<div class="chips">${chips.join('')}</div>` : '';
}

function nextCardHtml(s) {
  const { street, city } = splitAddr(s.address);
  return `
    <div class="next-head" data-id="${s.id}">
      <div class="badge">1</div>
      <div>
        <div class="street">${esc(street)}</div>
        ${city ? `<div class="city">${esc(city)}</div>` : ''}
        ${s.name ? `<div class="who">${esc(s.name)}</div>` : ''}
        ${chipsHtml(s)}
      </div>
    </div>
    <div class="next-actions" data-id="${s.id}">
      ${hasPos(s)
        ? `<button class="btn primary" data-act="nav">${ICON.nav}<span>${t('navigate')}</span></button>`
        : `<button class="btn primary" data-act="place">${ICON.pin}<span>${t('set_on_map')}</span></button>`}
      <button class="btn success" data-act="done">${ICON.check}<span>${t('delivered')}</span></button>
      <button class="btn warn" data-act="fail">${t('not_home')}</button>
    </div>
    <div class="next-more" data-id="${s.id}">
      ${s.phone ? `<a class="btn plain" href="tel:${esc(s.phone)}">${ICON.phone}<span>${t('call')}</span></a>` : ''}
      <button class="btn plain" data-act="show" ${hasPos(s) ? '' : 'disabled'}>${ICON.pin}<span>${t('show_on_map')}</span></button>
      <button class="btn plain" data-act="edit">${ICON.edit}<span>${t('edit')}</span></button>
    </div>`;
}

function rowHtml(s, num, { first = false, last = false } = {}) {
  const { street, city } = splitAddr(s.address);
  const leg = state.route?.legsById?.[s.id];
  const sub = [s.name, city].filter(Boolean).map(esc).join(' · ');
  const cls = ['row', s.status, hasPos(s) ? '' : 'nocoords', openId === s.id ? 'open' : ''].join(' ');
  const badge = s.status === 'delivered' ? '✓' : s.status === 'failed' ? '!' : num;
  const actions = isOpen(s)
    ? `<div class="ra-main">
         ${hasPos(s) ? `<button class="btn primary" data-act="nav">${ICON.nav}<span>${t('nav_short')}</span></button>` : `<button class="btn primary" data-act="place">${ICON.pin}<span>${t('nav_short')}</span></button>`}
         <button class="btn success" data-act="done">${ICON.check}<span>${t('delivered')}</span></button>
         <button class="btn warn" data-act="fail">${t('not_home_short')}</button>
       </div>
       <div class="ra-tools">
         ${s.phone ? `<a class="btn icon-only" href="tel:${esc(s.phone)}" aria-label="${t('call')}">${ICON.phone}</a>` : ''}
         <button class="btn icon-only" data-act="show" aria-label="${t('show_on_map')}" ${hasPos(s) ? '' : 'disabled'}>${ICON.pin}</button>
         <button class="btn icon-only" data-act="up" aria-label="${t('up')}" ${first ? 'disabled' : ''}>${ICON.up}</button>
         <button class="btn icon-only" data-act="down" aria-label="${t('down')}" ${last ? 'disabled' : ''}>${ICON.down}</button>
         <button class="btn icon-only" data-act="edit" aria-label="${t('edit')}">${ICON.edit}</button>
         <button class="btn icon-only danger" data-act="del" aria-label="${t('delete')}">${ICON.del}</button>
       </div>`
    : `<div class="ra-tools">
         <button class="btn" data-act="restore" style="flex:4">${ICON.undo}<span>${t('restore')}</span></button>
         <button class="btn icon-only danger" data-act="del" aria-label="${t('delete')}">${ICON.del}</button>
       </div>`;
  return `
    <li class="${cls}" data-id="${s.id}">
      <button class="row-main" data-act="toggle">
        <span class="badge">${badge}</span>
        <span class="row-text">
          <span class="row-street" style="display:block">${esc(street)}</span>
          <span class="row-sub" style="display:block">${hasPos(s) ? sub || '&nbsp;' : `<span class="warn">${esc(t('no_coords'))}</span>`}</span>
        </span>
        ${leg && isOpen(s) ? `<span class="row-eta">${fmtDist(leg.distance)}<br>${fmtTime(leg.duration)}</span>` : ''}
        ${ICON.chev}
      </button>
      <div class="row-actions">${actions}</div>
    </li>`;
}

function setStatus(s, status) {
  const i = state.stops.indexOf(s);
  s.status = status;
  s.doneAt = status === 'pending' ? null : Date.now();
  state.stops.splice(i, 1);
  if (status === 'pending') {
    // vor die erledigten einreihen
    const firstDone = state.stops.findIndex((x) => !isOpen(x));
    state.stops.splice(firstDone < 0 ? state.stops.length : firstDone, 0, s);
  } else {
    state.stops.push(s);
  }
  if (state.route?.legsById) delete state.route.legsById[s.id];
  openId = null;
}

function handleAction(act, id) {
  const s = state.stops.find((x) => x.id === id);
  if (!s) return;
  const pending = state.stops.filter(isOpen);
  const pi = pending.indexOf(s);
  switch (act) {
    case 'toggle': openId = openId === id ? null : id; break;
    case 'done': setStatus(s, 'delivered'); break;
    case 'fail': setStatus(s, 'failed'); break;
    case 'restore': setStatus(s, 'pending'); invalidateRoute(); break;
    case 'nav': openNav([s]); return;
    case 'place': startPlacing(s.id); return;
    case 'edit': openAdd({ edit: s }); return;
    case 'show':
      showView('map');
      setTimeout(() => { if (map) { map.setView([s.lat, s.lon], 17); markers[s.id]?.openPopup(); } }, 60);
      return;
    case 'up':
    case 'down': {
      const other = pending[act === 'up' ? pi - 1 : pi + 1];
      if (!other) return;
      const a = state.stops.indexOf(s);
      const b = state.stops.indexOf(other);
      [state.stops[a], state.stops[b]] = [state.stops[b], state.stops[a]];
      invalidateRoute();
      break;
    }
    case 'del':
      if (!confirm(t('confirm_delete') + '\n' + s.address)) return;
      state.stops.splice(state.stops.indexOf(s), 1);
      invalidateRoute();
      break;
    default: return;
  }
  save();
  render();
}

$('#view-list').addEventListener('click', (e) => {
  const btn = e.target.closest('[data-act]');
  if (!btn || btn.disabled) return;
  const holder = btn.closest('[data-id]');
  if (holder) handleAction(btn.dataset.act, holder.dataset.id);
});

$('#btnClearDone').addEventListener('click', () => {
  const n = state.stops.filter((s) => !isOpen(s)).length;
  if (!n) return toast(t('nothing_done'));
  if (!confirm(t('confirm_clear_done', { n }))) return;
  state.stops = state.stops.filter(isOpen);
  save();
  render();
});
$('#btnHideHint').addEventListener('click', () => { state.hideInstallHint = true; save(); render(); });

/* ---------------- Hinzufügen / Scannen ---------------- */

const dlg = $('#dlgAdd');
let editing = null;
let candidates = [];

function resetForm() {
  candidates = [];
  $('#addrInput').value = editing?.address || '';
  $('#nameInput').value = editing?.name || '';
  $('#phoneInput').value = editing?.phone || '';
  $('#noteInput').value = editing?.note || '';
  $('#rawBox').hidden = true;
  $('#rawBox').open = false;
  $('#rawText').textContent = '';
  const prev = $('#scanPreview');
  if (prev.src) URL.revokeObjectURL(prev.src);
  prev.removeAttribute('src');
  prev.hidden = true;
  $('#photoEmpty').hidden = false;
  $('#photoRetake').hidden = true;
  $('#btnCamera').classList.remove('has-photo');
  $('#ocrProgress').hidden = true;
  $('#candidates').innerHTML = '';
  setGeoStatus('');
  setAddEnabled(!!editing);
}

function setAddEnabled(on) {
  $('#btnAdd').disabled = !on;
  $('#btnAddNext').disabled = !on;
}

function openAdd({ edit = null, scan = false } = {}) {
  editing = edit;
  $('#addTitle').textContent = t(edit ? 'edit_stop' : 'new_parcel');
  $('#scanSrc').hidden = !!edit;
  $('#btnAddNext').hidden = !!edit;
  $('#btnAdd').textContent = t(edit ? 'save' : 'add');
  resetForm();
  if (!dlg.open) dlg.showModal();
  if (!edit && !NativeScanner) warmUp(state.settings.ocr);
  if (scan) startCamera();
}

$('#tabScan').addEventListener('click', () => openAdd({ scan: true }));
$('#btnScanEmpty').addEventListener('click', () => openAdd({ scan: true }));
$('#btnManualEmpty').addEventListener('click', () => { openAdd(); $('#addrInput').focus(); });
$('#btnManual').addEventListener('click', () => { openAdd(); $('#addrInput').focus(); });
$('#btnCamera').addEventListener('click', () => startCamera());

/** Live-Scanner (Android-App) bzw. Foto aufnehmen (Browser). */
function startCamera() {
  if (NativeScanner) nativeScan();
  else $('#fileCamera').click();
}

async function nativeScan() {
  try {
    const r = await NativeScanner.scan({ lang: getLang() });
    if (!r || r.cancelled || !r.text) return;
    if (!dlg.open) openAdd();
    if (!editing) resetForm();
    $('#rawText').textContent = r.text.trim();
    $('#rawBox').hidden = false;
    await processText(r.text);
  } catch (err) {
    console.error(err);
    if (!dlg.open) openAdd();
    setGeoStatus(t('ocr_error') + (err.message || err), true);
  }
}
$('#btnGallery').addEventListener('click', () => $('#fileGallery').click());
$('#fileCamera').addEventListener('change', onPhoto);
$('#fileGallery').addEventListener('change', onPhoto);
// Tippen auf den abgedunkelten Hintergrund schließt das Sheet
for (const d of [dlg, $('#dlgSettings')]) {
  d.addEventListener('click', (e) => { if (e.target === d) d.close(); });
}

async function onPhoto(e) {
  const file = e.target.files?.[0];
  e.target.value = '';
  if (!file) return;
  if (!dlg.open) openAdd();
  if (!editing) resetForm();
  const prev = $('#scanPreview');
  prev.src = URL.createObjectURL(file);
  prev.hidden = false;
  $('#photoEmpty').hidden = true;
  $('#photoRetake').hidden = false;
  $('#btnCamera').classList.add('has-photo');

  const pr = $('#ocrProgress');
  pr.hidden = false;
  $('#btnFind').disabled = true;
  const labels = { prep: 'ocr_prep', load: 'ocr_load', run: 'ocr_run' };
  try {
    if (!window.Tesseract) throw new Error(t('ocr_unavailable'));
    const { text } = await recognize(file, (phase, p) => {
      $('#ocrLabel').textContent = t(labels[phase] || 'ocr_run');
      $('#ocrBar').style.width = Math.round((p || 0) * 100) + '%';
    }, state.settings.ocr);
    $('#rawText').textContent = text.trim() || t('no_text');
    $('#rawBox').hidden = false;
    pr.hidden = true;
    await processText(text);
  } catch (err) {
    console.error(err);
    setGeoStatus(t('ocr_error') + (err.message || err), true);
  } finally {
    pr.hidden = true;
    $('#btnFind').disabled = false;
  }
}

/** Adresse aus erkanntem Text übernehmen und auf der Karte suchen. */
async function processText(text) {
  const r = extractAddress(text);
  if (!r.address) {
    $('#rawBox').open = true;
    setGeoStatus(t('ocr_none'), true);
    return;
  }
  $('#addrInput').value = r.address;
  if (r.name) $('#nameInput').value = r.name;
  if (r.phone) $('#phoneInput').value = r.phone;
  if (r.note) $('#noteInput').value = r.note;
  if (r.confidence === 'low') $('#rawBox').open = true;
  await findCandidates({ auto: state.settings.autoAdd && r.confidence !== 'low' });
}

function setGeoStatus(msg, err = false) {
  const el = $('#geoStatus');
  el.textContent = msg;
  el.className = 'status' + (err ? ' err' : '');
}

function nearPoint() {
  const pts = state.stops.filter(hasPos);
  if (pts.length) return { lat: pts.reduce((a, s) => a + s.lat, 0) / pts.length, lon: pts.reduce((a, s) => a + s.lon, 0) / pts.length };
  return myPos;
}

async function findCandidates({ auto = false } = {}) {
  const addr = $('#addrInput').value.trim();
  if (!addr) return setGeoStatus(t('enter_address'), true);
  setGeoStatus(t('searching'));
  $('#candidates').innerHTML = '';
  setAddEnabled(!!editing);
  try {
    candidates = await geocode(addr, {
      country: state.settings.country.trim().toLowerCase(),
      city: state.settings.city,
      near: nearPoint(),
      lang: getLang(),
    });
  } catch (err) {
    candidates = [];
    return setGeoStatus(t('geocoder_error') + ' (' + (err.message || err) + ')', true);
  }
  if (!candidates.length) return setGeoStatus(t('not_found'), true);
  setGeoStatus(candidates.length === 1 ? t('found_one') : t('found_many', { n: candidates.length }));
  $('#candidates').innerHTML = candidates
    .map((c, i) => `<li><label><input type="radio" name="cand" value="${i}" ${i === 0 ? 'checked' : ''}><span>${esc(c.label)}</span></label></li>`)
    .join('');
  setAddEnabled(true);
  if (auto && candidates.length === 1) commitAdd({ stayOpen: true });
}

$('#btnFind').addEventListener('click', () => findCandidates());
$('#addrInput').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); findCandidates(); }
});

function commitAdd({ withoutCoords = false, next = false, stayOpen = false } = {}) {
  const address = $('#addrInput').value.trim().replace(/\s*\n\s*/g, ', ');
  if (!address) return setGeoStatus(t('enter_address'), true);
  const sel = document.querySelector('input[name="cand"]:checked');
  const c = !withoutCoords && sel ? candidates[+sel.value] : null;
  const data = {
    address,
    name: $('#nameInput').value.trim(),
    phone: $('#phoneInput').value.trim(),
    note: $('#noteInput').value.trim(),
  };
  let stop;
  const wasEdit = !!editing;
  if (editing) {
    stop = Object.assign(editing, data);
    if (c) { stop.lat = c.lat; stop.lon = c.lon; stop.geoLabel = c.label; }
  } else {
    if (state.stops.some((s) => s.address.toLowerCase() === address.toLowerCase()) && !confirm(t('duplicate'))) return;
    stop = { id: uid(), ...data, lat: c?.lat ?? null, lon: c?.lon ?? null, geoLabel: c?.label || '', status: 'pending', createdAt: Date.now() };
    const firstDone = state.stops.findIndex((s) => !isOpen(s));
    state.stops.splice(firstDone < 0 ? state.stops.length : firstDone, 0, stop);
  }
  invalidateRoute();
  save();
  render();
  if (!wasEdit) toast(t('added', { a: splitAddr(address).street }));

  if (next || stayOpen) {
    editing = null;
    resetForm();
    if (next) startCamera(); // noch innerhalb der Nutzer-Geste (wichtig für iOS)
    return;
  }
  dlg.close();
  if (withoutCoords) startPlacing(stop.id);
}
$('#btnAdd').addEventListener('click', () => commitAdd());
$('#btnAddNext').addEventListener('click', () => commitAdd({ next: true }));
$('#btnAddNoCoords').addEventListener('click', () => commitAdd({ withoutCoords: true }));

/* ---------------- Karte ---------------- */

let map = null;
let markers = {};
let routeLine = null;
let meMarker = null;
let myPos = null;
let placingId = null;
const FIT = { paddingTopLeft: [40, 40], paddingBottomRight: [40, 170] };

function initMap() {
  if (map) return;
  if (!window.L) { toast(t('map_failed')); return; }
  map = L.map('map', { zoomControl: false }).setView([51.1657, 10.4515], 6);
  L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
    maxZoom: 20,
    subdomains: 'abcd',
    attribution: '© OpenStreetMap · © CARTO',
  }).addTo(map);
  map.on('click', onMapClick);
  const pts = state.stops.filter(hasPos);
  if (pts.length) map.fitBounds(pts.map((s) => [s.lat, s.lon]), FIT);
  locate(!pts.length);
}

function pinIcon(label, cls) {
  const big = cls === 'next';
  const small = cls === 'delivered' || cls === 'failed';
  const size = big ? 40 : small ? 24 : 32;
  return L.divIcon({
    className: '',
    html: `<div class="pin ${cls}"><span>${label}</span></div>`,
    iconSize: [size, size],
    iconAnchor: [size / 2, size + 2],
    popupAnchor: [0, -size],
  });
}

function renderMap() {
  if (!map) return;
  Object.values(markers).forEach((m) => m.remove());
  markers = {};
  const pending = state.stops.filter(isOpen);
  state.stops.forEach((s) => {
    if (!hasPos(s)) return;
    const n = pending.indexOf(s) + 1;
    const cls = s.status === 'pending' ? (n === 1 ? 'next' : '') : s.status;
    const label = s.status === 'delivered' ? '✓' : s.status === 'failed' ? '!' : n;
    const m = L.marker([s.lat, s.lon], {
      icon: pinIcon(label, cls),
      draggable: true,
      zIndexOffset: cls === 'next' ? 1000 : isOpen(s) ? 500 : 0,
    }).addTo(map);
    const { street, city } = splitAddr(s.address);
    m.bindPopup(`
      <b>${isOpen(s) ? n + '. ' : ''}${esc(street)}</b><br>
      ${city ? esc(city) + '<br>' : ''}
      ${s.name ? esc(s.name) + '<br>' : ''}
      ${s.phone ? `<a href="tel:${esc(s.phone)}">${esc(s.phone)}</a>` : ''}
      <div class="pop-actions">
        ${isOpen(s)
          ? `<button class="btn primary" data-pop="nav" data-id="${s.id}">${t('navigate')}</button>
             <button class="btn success" data-pop="done" data-id="${s.id}">✓</button>`
          : `<button class="btn" data-pop="restore" data-id="${s.id}">${t('restore')}</button>`}
      </div>
      <div class="pop-hint">${t('drag_hint')}</div>`);
    m.on('dragend', () => {
      const p = m.getLatLng();
      s.lat = p.lat;
      s.lon = p.lng;
      invalidateRoute();
      save();
      render();
      toast(t('point_moved'));
    });
    markers[s.id] = m;
  });
  if (routeLine) { routeLine.remove(); routeLine = null; }
  if (state.route?.geometry?.length) {
    routeLine = L.polyline(state.route.geometry, { color: '#007aff', weight: 6, opacity: 0.8, lineJoin: 'round' }).addTo(map);
  }
  updateRouteInfo();
}

document.addEventListener('click', (e) => {
  const b = e.target.closest('[data-pop]');
  if (!b) return;
  const s = state.stops.find((x) => x.id === b.dataset.id);
  if (!s) return;
  const act = b.dataset.pop;
  if (act === 'nav') return openNav([s]);
  map.closePopup();
  if (act === 'done') setStatus(s, 'delivered');
  if (act === 'restore') { setStatus(s, 'pending'); invalidateRoute(); }
  save();
  render();
});

function updateRouteInfo() {
  const el = $('#routeInfo');
  const r = state.route;
  const n = state.stops.filter((s) => isOpen(s) && hasPos(s)).length;
  if (!n) { el.textContent = t('route_nopoints'); return; }
  if (!r) { el.textContent = t('route_none', { n }); return; }
  el.innerHTML = t('route_info', { dist: fmtDist(r.distance), time: fmtTime(r.duration), n })
    + (r.source === 'local' ? `<span class="warn">${esc(t('route_approx'))}</span>` : '');
}

function locate(center = false) {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null);
    navigator.geolocation.getCurrentPosition(
      (p) => {
        myPos = { lat: p.coords.latitude, lon: p.coords.longitude };
        if (map) {
          if (!meMarker) {
            meMarker = L.marker([myPos.lat, myPos.lon], {
              icon: L.divIcon({ className: '', html: '<div class="me-dot"></div>', iconSize: [18, 18] }),
              interactive: false,
              zIndexOffset: -100,
            }).addTo(map);
          } else meMarker.setLatLng([myPos.lat, myPos.lon]);
          if (center) map.setView([myPos.lat, myPos.lon], 15);
        }
        resolve(myPos);
      },
      () => resolve(null),
      { enableHighAccuracy: true, timeout: 10000, maximumAge: 30000 }
    );
  });
}
$('#btnLocate').addEventListener('click', async () => {
  if (!(await locate(true))) toast(t('locate_failed'));
});

/* ---- Punkt manuell setzen ---- */
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
  toast(t('point_set'));
  try { s.geoLabel = await reverse(s.lat, s.lon, getLang()); save(); } catch {}
}

/* ---------------- Route ---------------- */

async function optimize() {
  const pending = state.stops.filter((s) => isOpen(s) && hasPos(s));
  if (!pending.length) return toast(t('route_nopoints'));
  const btns = [$('#btnRoute'), $('#btnOptimizeTop')];
  btns.forEach((b) => { b.disabled = true; });
  const label = $('#btnRoute span');
  const labelKey = label.dataset.i18n;
  label.textContent = t('route_building');
  try {
    let start = null;
    if (state.settings.start === 'gps') {
      start = await locate();
      if (!start) toast(t('gps_unavailable'));
    }
    const points = start ? [{ ...start, id: '__start' }, ...pending] : pending;
    const r = await buildRoute(points, { roundtrip: state.settings.roundtrip });
    const ordered = r.order.map((i) => points[i]).filter((p) => p.id !== '__start');
    const legsById = {};
    r.order.forEach((pi, k) => {
      const leg = r.legs[k - 1];
      if (leg && points[pi].id !== '__start') legsById[points[pi].id] = leg;
    });
    const noPos = state.stops.filter((s) => isOpen(s) && !hasPos(s));
    const done = state.stops.filter((s) => !isOpen(s));
    state.stops = [...ordered, ...noPos, ...done];
    state.route = { geometry: r.geometry, distance: r.distance, duration: r.duration, source: r.source, legsById, builtAt: Date.now() };
    save();
    render();
    if (map) {
      const b = L.latLngBounds(r.geometry);
      if (b.isValid()) map.fitBounds(b, FIT);
    }
    toast(t('route_built', { dist: fmtDist(r.distance), time: fmtTime(r.duration) }));
  } catch (err) {
    console.error(err);
    toast(t('route_failed'));
  } finally {
    btns.forEach((b) => { b.disabled = false; });
    label.textContent = t(labelKey);
  }
}
$('#btnRoute').addEventListener('click', optimize);
$('#btnOptimizeTop').addEventListener('click', optimize);

/* ---------------- Navigation ---------------- */

const NAV_NAMES = { apple: 'Apple Karten', google: 'Google Maps', waze: 'Waze' };

function navUrl(points) {
  const nav = state.settings.nav;
  const first = points[0];
  if (nav === 'apple') return `https://maps.apple.com/?daddr=${first.lat},${first.lon}&dirflg=d`;
  if (nav === 'waze') return `https://waze.com/ul?ll=${first.lat},${first.lon}&navigate=yes`;
  const last = points[points.length - 1];
  const p = new URLSearchParams({ api: '1', destination: `${last.lat},${last.lon}`, travelmode: 'driving' });
  const way = points.slice(0, -1).slice(0, 9);
  if (way.length) p.set('waypoints', way.map((s) => `${s.lat},${s.lon}`).join('|'));
  return 'https://www.google.com/maps/dir/?' + p;
}

function openNav(points) {
  if (!points.length) return toast(t('no_stops'));
  // In der Android-App öffnet Capacitor externe Links in der passenden App (Google Maps, Waze …)
  if (IS_NATIVE) window.location.href = navUrl(points);
  else window.open(navUrl(points), '_blank');
}

$('#btnOpenNav').addEventListener('click', () => {
  const pending = state.stops.filter((s) => isOpen(s) && hasPos(s));
  if (!pending.length) return toast(t('no_stops'));
  if (state.settings.nav === 'google') return openNav(pending.slice(0, 10));
  if (pending.length > 1) toast(t('single_dest', { app: NAV_NAMES[state.settings.nav] }), 3500);
  openNav([pending[0]]);
});

/* ---------------- Einstellungen ---------------- */

const dlgS = $('#dlgSettings');
$('#btnSettings').addEventListener('click', () => {
  const s = state.settings;
  $('#setLang').value = s.lang;
  $('#setOcr').value = s.ocr;
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
    lang: $('#setLang').value,
    ocr: $('#setOcr').value,
    city: $('#setCity').value.trim(),
    country: $('#setCountry').value.trim().toLowerCase(),
    start: $('#setStart').value,
    roundtrip: $('#setRoundtrip').checked,
    nav: $('#setNav').value,
    autoAdd: $('#setAutoAdd').checked,
  });
  save();
  setLang(state.settings.lang);
  showView(currentView);
  render();
  toast(t('saved'));
});
$('#btnClearAll').addEventListener('click', () => {
  if (!confirm(t('confirm_clear_all'))) return;
  state.stops = [];
  state.route = null;
  save();
  render();
  dlgS.close();
});

/* ---------------- Start ---------------- */

if (NativeScanner) {
  $('#photoEmpty b').dataset.i18n = 'scan_live';
  $('#photoEmpty small').dataset.i18n = 'scan_live_hint';
}
setLang(state.settings.lang);
render();
if (!IS_NATIVE && 'serviceWorker' in navigator && location.protocol !== 'file:') {
  navigator.serviceWorker.register('sw.js').catch(() => {});
}
// für automatisierte Tests
window.__app = { state: () => state, render, optimize };
