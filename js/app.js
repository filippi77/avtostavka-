import { extractAddress } from './address.js';
import { geocode, reverse } from './geocode.js';
import { suggest } from './autocomplete.js';
import { normKey, remember, updatePosition, lookup, searchBook, frequent, pruneBook, autosaveTour, saveNamedTour, restoreStops, today } from './memory.js';
import { buildRoute, haversine } from './route.js';
import { DwellTracker, pruneVisits, visitsCsv } from './visits.js';
import { NAV_APPS, navLink, appsFor, platformOf, defaultApp, isAppScheme } from './navigate.js';
import { recognize, warmUp } from './ocr.js';
import { t, setLang, getLang, applyI18n, fmtDist, fmtTime } from './i18n.js';

const $ = (s) => document.querySelector(s);
const KEY = 'avtostavka.v1';

const IS_IOS = /iPad|iPhone|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
const PLATFORM = platformOf(navigator.userAgent, navigator.maxTouchPoints, navigator.platform);
const NAV_CHOICES = [...appsFor(PLATFORM), 'ask'];
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
  book: {}, // Adressbuch: häufige Adressen
  tours: [], // gespeicherte Touren
  visits: [], // Aufenthalte an Adressen + Zustell-Ereignisse
  settings: {
    lang: 'de',
    ocr: 'deu+eng',
    city: '',
    country: 'de',
    start: 'gps',
    roundtrip: false,
    nav: defaultApp(PLATFORM),
    autoAdd: false,
    saverFirst: true,
    radius: 50,
    trackVisits: true,
    dwellSec: 30,
  },
};

let state = load();
function load() {
  let s = null;
  try { s = JSON.parse(localStorage.getItem(KEY)); } catch {}
  if (!s || !Array.isArray(s.stops)) return structuredClone(defaults);
  s = { ...defaults, ...s, settings: { ...defaults.settings, ...s.settings } };
  if (!NAV_CHOICES.includes(s.settings.nav)) s.settings.nav = defaults.settings.nav;
  if (!['de', 'ru'].includes(s.settings.lang)) s.settings.lang = 'de';
  for (const st of s.stops) if (st.express && !st.service) st.service = 'express';
  // Adressen aus älteren Versionen ins Adressbuch übernehmen
  s.visits = pruneVisits(s.visits || []);
  s.book = s.book || {};
  if (!Object.keys(s.book).length) for (const st of s.stops) remember(s.book, st);
  return s;
}
function save() {
  // Tour des Tages automatisch mitschreiben
  state.tours = autosaveTour(state.tours || [], state.stops);
  try { localStorage.setItem(KEY, JSON.stringify(state)); } catch {}
}
const uid = () => Math.random().toString(36).slice(2, 10);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const isOpen = (s) => s.status === 'pending';
// Service-Stufen (UPS): kleiner = früher anfahren
const SERVICES = ['plus', 'express', 'saver'];
const prioOf = (s) => ({ plus: 1, express: 2, saver: state.settings.saverFirst ? 3 : 9 }[s.service] || 9);
const isExpress = (s) => SERVICES.includes(s.service);
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
  road: '<svg viewBox="0 0 24 24"><path d="M5 21 9 3M19 21 15 3M12 4v2M12 10v3M12 17v3"/></svg>',
  star: '<svg viewBox="0 0 24 24"><path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1-4.4-4.3 6.1-.9z"/></svg>',
  bolt: '<svg viewBox="0 0 24 24"><path d="M13 2 4 14h7l-1 8 9-12h-7z"/></svg>',
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
  // ganze Tour auf einmal an Google Maps (bis 10 Stopps)
  const routable = pending.filter(hasPos).length;
  $('#btnAllGoogle').hidden = routable < 2;
  $('#allGoogleLabel').textContent = t('all_google', { n: Math.min(routable, 10) });
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
  const here = tracker?.presentAt();
  if (here && here.stopId === s.id) chips.push(`<span class="chip here">📍 ${esc(t('here_since', { t: fmtClock(here.since) }))}</span>`);
  if (!hasPos(s)) chips.push(`<span class="chip warn">${esc(t('no_coords'))}</span>`);
  else if (s.precision === 'street') chips.push(`<span class="chip warn">⚠ ${esc(t('street_only'))}</span>`);
  if (leg) chips.push(`<span class="chip">${fmtDist(leg.distance)} · ${fmtTime(leg.duration)}</span>`);
  if (s.note) chips.push(`<span class="chip">${esc(s.note)}</span>`);
  return chips.length ? `<div class="chips">${chips.join('')}</div>` : '';
}

// Kurzcode der Servicestufe wie auf dem Etikett (Kästchen oben rechts)
const SVC_CODE = { plus: '9:00', express: '12:00', saver: 'SAVER', '': 'STD' };
const fmtTracking = (t) => t.replace(/^(1Z)(\w{3})(\w{3})(\w{2})(\w{4})(\w{4})$/i, '$1 $2 $3 $4 $5 $6');

function nextCardHtml(s) {
  const { street, city } = splitAddr(s.address);
  const svc = s.service || '';
  return `
    <div class="label-strip">
      <span class="label-step"><b>1</b> ${esc(t('next_stop'))}</span>
      <span class="svc-box svc-${svc || 'std'}">${SVC_CODE[svc]}</span>
    </div>
    <div class="label-body" data-id="${s.id}">
      <div class="label-tag">SHIP TO</div>
      ${s.name ? `<div class="who">${esc(s.name)}</div>` : ''}
      <div class="street">${esc(street)}</div>
      ${city ? `<div class="city">${esc(city)}</div>` : ''}
      ${isExpress(s) ? `<div class="svc-line svc-${svc}">${esc(t('svc_chip_' + svc))}</div>` : ''}
      ${chipsHtml(s)}
    </div>
    ${s.tracking ? `<div class="label-track"><div class="barcode" aria-hidden="true"></div><div class="trk">TRACKING #: ${esc(fmtTracking(s.tracking))}</div></div>` : ''}
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
      <button class="btn plain ${isExpress(s) ? 'on' : ''}" data-act="express">${ICON.bolt}<span>Express</span></button>
      <button class="btn plain" data-act="edit">${ICON.edit}<span>${t('edit')}</span></button>
    </div>`;
}

function rowHtml(s, num, { first = false, last = false } = {}) {
  const { street, city } = splitAddr(s.address);
  const leg = state.route?.legsById?.[s.id];
  const sub = (isOpen(s) ? [s.name, city] : [doneInfo(s), s.name]).filter(Boolean).map(esc).join(' · ');
  const cls = ['row', s.status, hasPos(s) ? '' : 'nocoords', isExpress(s) && isOpen(s) ? 'svc-' + s.service : '', openId === s.id ? 'open' : ''].join(' ');
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
         <button class="btn icon-only ${isExpress(s) ? 'xp-on' : ''}" data-act="express" aria-label="Express">${ICON.bolt}</button>
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
          <span class="row-street" style="display:block">${isExpress(s) && isOpen(s) ? `<span class="svc-mini svc-${s.service}">${SVC_CODE[s.service]}</span>` : ''}${esc(street)}</span>
          <span class="row-sub" style="display:block">${hasPos(s) ? sub || '&nbsp;' : `<span class="warn">${esc(t('no_coords'))}</span>`}${s.tracking ? ` <span class="trk-mini">…${esc(s.tracking.slice(-4))}</span>` : ''}</span>
        </span>
        ${leg && isOpen(s) ? `<span class="row-eta">${fmtDist(leg.distance)}<br>${fmtTime(leg.duration)}</span>` : ''}
        ${ICON.chev}
      </button>
      <div class="row-actions">${actions}</div>
    </li>`;
}

/** Stopp nach Service-Stufe einreihen (Express Plus → Express → Saver → Standard), Erledigte ans Ende. */
function placeStop(s) {
  const i = state.stops.indexOf(s);
  if (i >= 0) state.stops.splice(i, 1);
  if (!isOpen(s)) { state.stops.push(s); return; }
  const pos = state.stops.findIndex((x) => !isOpen(x) || prioOf(x) > prioOf(s));
  state.stops.splice(pos < 0 ? state.stops.length : pos, 0, s);
}

function setStatus(s, status) {
  s.status = status;
  s.doneAt = status === 'pending' ? null : Date.now();
  if (status !== 'pending') logStatusEvent(s, status);
  placeStop(s);
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
    case 'express':
      s.service = isExpress(s) ? '' : 'express';
      s.express = isExpress(s);
      placeStop(s);
      invalidateRoute();
      toast(isExpress(s) ? t('express_on') : t('express_off'));
      break;
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
let scanTracking = '';

function getService() {
  return $('#serviceSeg .active')?.dataset.v || '';
}
function setService(v) {
  document.querySelectorAll('#serviceSeg button').forEach((b) => b.classList.toggle('active', b.dataset.v === v));
}
$('#serviceSeg').addEventListener('click', (e) => {
  const b = e.target.closest('button[data-v]');
  if (b) setService(b.dataset.v);
});
let candidates = [];

function resetForm() {
  candidates = [];
  $('#addrInput').value = editing?.address || '';
  pickedStreet = null;
  pickedAddress = '';
  hideSuggest();
  $('#nameInput').value = editing?.name || '';
  $('#phoneInput').value = editing?.phone || '';
  $('#noteInput').value = editing?.note || '';
  setService(editing?.service || '');
  scanTracking = editing?.tracking || '';
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

function openAdd({ edit = null, scan = false, manual = false } = {}) {
  editing = edit;
  $('#addTitle').textContent = t(edit ? 'edit_stop' : 'new_parcel');
  $('#scanSrc').hidden = !!edit || manual;
  $('#btnAddNext').hidden = !!edit;
  $('#btnAdd').textContent = t(edit ? 'save' : 'add');
  resetForm();
  if (!dlg.open) dlg.showModal();
  if (!edit && !NativeScanner) warmUp(state.settings.ocr);
  if (!myPos) locate(); // für die Umkreissuche
  if (scan) startCamera();
}

$('#tabScan').addEventListener('click', () => openAdd({ scan: true }));
$('#btnScanEmpty').addEventListener('click', () => openAdd({ scan: true }));
$('#btnManualEmpty').addEventListener('click', () => { openAdd({ manual: true }); $('#addrInput').focus(); });
$('#btnManual').addEventListener('click', () => { openAdd({ manual: true }); $('#addrInput').focus(); });
// Adressfeld beim Tippen nach oben holen, damit die Vorschläge über der Tastatur sichtbar sind
$('#addrInput').addEventListener('focus', () => setTimeout(() => $('#addrInput').closest('.form-group').scrollIntoView({ block: 'start', behavior: 'smooth' }), 250));
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
for (const d of [dlg, $('#dlgSettings'), $('#dlgTours'), $('#dlgNav')]) {
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
  setService(r.service || '');
  scanTracking = r.tracking || '';
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

/** Mittelpunkt für die Umkreissuche: aktueller GPS-Standort, sonst letzter bekannter, sonst Mitte der Stopps. */
function searchCenter() {
  return myPos || state.lastPos || nearPoint();
}

/* ---- Vorschläge beim Tippen (Umkreis) ---- */
let sugTimer = null;
let sugAbort = null;
let sugItems = [];
let pickedStreet = null;
let pickedAddress = '';

function hideSuggest() {
  sugItems = [];
  $('#suggest').hidden = true;
  $('#suggest').innerHTML = '';
}

/** Gespeicherte Adresse → Vorschlag */
function bookItem(e) {
  const { street, city } = splitAddr(e.address);
  return {
    kind: 'saved', entry: e, main: street, address: e.address, lat: e.lat, lon: e.lon, precision: e.precision,
    sub: [city, e.name, `${e.count}×`].filter(Boolean).join(' · '),
    dist: e.lat != null && searchCenter() ? haversine(searchCenter(), e) : null,
  };
}

function renderSuggest(items, emptyText = '') {
  sugItems = items;
  const ul = $('#suggest');
  if (!items.length && !emptyText) return hideSuggest();
  ul.innerHTML = items.length
    ? items.map((x, i) => `
      <li><button type="button" class="sug ${x.kind === 'saved' ? 'saved' : ''}" data-i="${i}">
        <span class="sug-ic">${x.kind === 'saved' ? ICON.star : x.kind === 'street' ? ICON.road : ICON.pin}</span>
        <span class="sug-text"><b>${esc(x.main)}</b><small>${esc(x.sub)}</small></span>
        ${x.dist != null ? `<span class="sug-dist">${fmtDist(x.dist)}</span>` : ''}
      </button></li>`).join('')
    : `<li class="sug-empty">${esc(emptyText)}</li>`;
  ul.hidden = false;
}

/** Leeres Feld: häufigste gespeicherte Adressen zeigen */
function showFrequent() {
  if ($('#addrInput').value.trim()) return;
  const items = frequent(state.book).map(bookItem);
  if (items.length) renderSuggest(items);
}

async function runSuggest() {
  const q = $('#addrInput').value.trim();
  if (!q) return showFrequent();
  if (q.length < 2 || q === pickedAddress) return hideSuggest();
  // gespeicherte Adressen sofort (offline, ohne Wartezeit)
  const local = searchBook(state.book, q).map(bookItem);
  if (local.length) renderSuggest(local);
  if (q.length < 3) return;
  sugAbort?.abort();
  sugAbort = new AbortController();
  let query = q;
  // Nach Auswahl einer Straße: Ort mitschicken, damit die Hausnummer eindeutig wird
  if (pickedStreet && q.toLowerCase().startsWith(pickedStreet.street.toLowerCase()) && !q.includes(',')) {
    query = `${q}, ${[pickedStreet.postcode, pickedStreet.city].filter(Boolean).join(' ')}`;
  }
  const radiusKm = +state.settings.radius || 50;
  // Ohne bekannten Standort kurz auf GPS warten, damit der Umkreis greift
  if (!searchCenter()) await Promise.race([locate(), new Promise((r) => setTimeout(r, 3000))]);
  let remote = [];
  try {
    remote = await suggest(query, { center: searchCenter(), radiusKm, lang: getLang(), signal: sugAbort.signal });
  } catch (err) {
    if (err.name === 'AbortError') return;
  }
  if ($('#addrInput').value.trim() !== q) return; // inzwischen weitergetippt
  const known = new Set(local.map((x) => normKey(x.address)));
  const items = [...local, ...remote.filter((x) => !known.has(normKey(x.address)))].slice(0, 8);
  renderSuggest(items, t('no_suggest', { r: radiusKm }));
}

function pickSuggestion(i) {
  const x = sugItems[i];
  if (!x) return;
  const input = $('#addrInput');
  hideSuggest();
  if (x.kind === 'street') {
    // Straße gewählt → Hausnummer eintippen
    pickedStreet = x;
    pickedAddress = '';
    input.value = x.main + ' ';
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
    setGeoStatus(t('enter_number'));
    return;
  }
  // Haus / gespeicherte Adresse gewählt → Koordinaten sind bekannt, direkt hinzufügbar
  pickedStreet = null;
  pickedAddress = x.address;
  input.value = x.address;
  input.blur();
  if (x.kind === 'saved') {
    const e = x.entry;
    if (!$('#nameInput').value && e.name) $('#nameInput').value = e.name;
    if (!$('#phoneInput').value && e.phone) $('#phoneInput').value = e.phone;
    if (!$('#noteInput').value && e.note) $('#noteInput').value = e.note;
    if (e.lat == null) { setGeoStatus(''); return findCandidates(); }
  }
  const precision = x.kind === 'saved' ? x.precision : x.kind === 'house' ? 'house' : 'street';
  candidates = [{ lat: x.lat, lon: x.lon, label: x.address, precision, postcode: x.postcode, city: x.city }];
  $('#candidates').innerHTML = `<li><label><input type="radio" name="cand" value="0" checked><span>${esc(x.address)}${x.dist != null ? ` · ${fmtDist(x.dist)}` : ''}</span></label></li>`;
  setGeoStatus(t('found_one'));
  setAddEnabled(true);
}

$('#addrInput').addEventListener('input', () => {
  const v = $('#addrInput').value.trim();
  // Text nach einer Auswahl geändert → alte Koordinaten verwerfen
  if (pickedAddress && v !== pickedAddress) {
    pickedAddress = '';
    candidates = [];
    $('#candidates').innerHTML = '';
    setGeoStatus('');
    setAddEnabled(!!editing);
  }
  clearTimeout(sugTimer);
  sugTimer = setTimeout(runSuggest, 220);
});
$('#addrInput').addEventListener('blur', () => setTimeout(hideSuggest, 200));
$('#addrInput').addEventListener('focus', () => setTimeout(showFrequent, 300));
$('#suggest').addEventListener('pointerdown', (e) => e.preventDefault()); // Fokus behalten
$('#suggest').addEventListener('click', (e) => {
  const b = e.target.closest('.sug');
  if (b) pickSuggestion(+b.dataset.i);
});

async function findCandidates({ auto = false } = {}) {
  const addr = $('#addrInput').value.trim();
  if (!addr) return setGeoStatus(t('enter_address'), true);
  // schon bekannte Adresse → gespeicherte Position, keine Suche nötig
  const known = lookup(state.book, addr);
  if (known?.lat != null) {
    candidates = [{ lat: known.lat, lon: known.lon, label: '★ ' + known.address, precision: known.precision }];
    $('#candidates').innerHTML = `<li><label><input type="radio" name="cand" value="0" checked><span>${esc(candidates[0].label)}</span></label></li>`;
    setGeoStatus(t('from_memory'));
    setAddEnabled(true);
    if (auto) commitAdd({ stayOpen: true });
    return;
  }
  setGeoStatus(t('searching'));
  $('#candidates').innerHTML = '';
  setAddEnabled(!!editing);
  try {
    candidates = await geocode(addr, {
      country: state.settings.country.trim().toLowerCase(),
      city: state.settings.city,
      near: searchCenter(),
      radiusKm: +state.settings.radius || 50,
      lang: getLang(),
    });
  } catch (err) {
    candidates = [];
    return setGeoStatus(t('geocoder_error') + ' (' + (err.message || err) + ')', true);
  }
  if (!candidates.length) return setGeoStatus(t('not_found'), true);
  setGeoStatus(candidates.length === 1 ? t('found_one') : t('found_many', { n: candidates.length }));
  $('#candidates').innerHTML = candidates
    .map((c, i) => `<li><label><input type="radio" name="cand" value="${i}" ${i === 0 ? 'checked' : ''}><span>${esc(c.label)}${c.precision === 'street' ? `<br><small class="warn">⚠ ${esc(t('street_only_short'))}</small>` : ''}</span></label></li>`)
    .join('');
  setAddEnabled(true);
  if (auto && candidates.length === 1) commitAdd({ stayOpen: true });
}

$('#btnFind').addEventListener('click', () => findCandidates());
$('#addrInput').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    if (sugItems.length && !$('#suggest').hidden) pickSuggestion(0);
    else { hideSuggest(); findCandidates(); }
  }
});

function commitAdd({ withoutCoords = false, next = false, stayOpen = false } = {}) {
  let address = $('#addrInput').value.trim().replace(/\s*\n\s*/g, ', ');
  if (!address) return setGeoStatus(t('enter_address'), true);
  const sel = document.querySelector('input[name="cand"]:checked');
  const c = !withoutCoords && sel ? candidates[+sel.value] : null;
  // PLZ + Ort ergänzen, wenn nur "Straße Nr." eingegeben wurde (wichtig für die Navigation)
  if (c?.postcode && c?.city && !/(^|\D)\d{4,5}\s+\p{L}/u.test(address)) address = `${address}, ${c.postcode} ${c.city}`;
  const data = {
    address,
    name: $('#nameInput').value.trim(),
    phone: $('#phoneInput').value.trim(),
    note: $('#noteInput').value.trim(),
    service: getService(),
    express: getService() !== '',
    tracking: scanTracking,
  };
  let stop;
  const wasEdit = !!editing;
  if (editing) {
    const oldPrio = prioOf(editing);
    stop = Object.assign(editing, data);
    if (c) { stop.lat = c.lat; stop.lon = c.lon; stop.geoLabel = c.label; stop.precision = c.precision || ''; }
    if (oldPrio !== prioOf(stop)) placeStop(stop);
  } else {
    if (state.stops.some((s) => s.address.toLowerCase() === address.toLowerCase()) && !confirm(t('duplicate'))) return;
    stop = { id: uid(), ...data, lat: c?.lat ?? null, lon: c?.lon ?? null, geoLabel: c?.label || '', precision: c?.precision || '', status: 'pending', createdAt: Date.now() };
    placeStop(stop);
  }
  remember(state.book, stop, { count: !wasEdit });
  pruneBook(state.book);
  invalidateRoute();
  save();
  render();
  if (!wasEdit) toast((isExpress(stop) ? t('svc_chip_' + stop.service) + ' · ' : '') + t('added', { a: splitAddr(address).street }));

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
  addBaseLayer(0);
  map.on('click', onMapClick);
  const pts = state.stops.filter(hasPos);
  if (pts.length) map.fitBounds(pts.map((s) => [s.lat, s.lon]), FIT);
  locate(!pts.length);
}

// Kartenkacheln ohne API-Schlüssel. Fällt ein Server aus, wird automatisch der nächste genommen.
const TILE_SOURCES = [
  { url: 'https://tile.openstreetmap.de/{z}/{x}/{y}.png', maxZoom: 19, attribution: '© OpenStreetMap-Mitwirkende' },
  { url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png', maxZoom: 19, attribution: '© OpenStreetMap contributors' },
];
let baseLayer = null;

function addBaseLayer(i) {
  const src = TILE_SOURCES[i];
  if (!src || !map) return;
  if (baseLayer) baseLayer.remove();
  let errors = 0;
  let loaded = 0;
  baseLayer = L.tileLayer(src.url, { maxZoom: src.maxZoom, attribution: src.attribution })
    .on('tileload', () => { loaded++; })
    .on('tileerror', () => {
      // mehrere Fehler ohne erfolgreich geladene Kachel → nächsten Server versuchen
      if (++errors >= 4 && loaded === 0 && i + 1 < TILE_SOURCES.length) addBaseLayer(i + 1);
    })
    .addTo(map);
}

function pinIcon(label, cls) {
  const big = cls.includes('next');
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
    const cls = s.status === 'pending' ? [n === 1 ? 'next' : '', isExpress(s) ? 'svc-' + s.service : ''].join(' ').trim() : s.status;
    const label = s.status === 'delivered' ? '✓' : s.status === 'failed' ? '!' : n;
    const m = L.marker([s.lat, s.lon], {
      icon: pinIcon(label, cls),
      draggable: true,
      zIndexOffset: cls.includes('next') ? 1000 : isExpress(s) && isOpen(s) ? 900 - prioOf(s) * 10 : isOpen(s) ? 500 : 0,
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
      s.precision = 'manual';
      updatePosition(state.book, s);
      invalidateRoute();
      save();
      render();
      toast(t('point_moved'));
    });
    markers[s.id] = m;
  });
  if (routeLine) { routeLine.remove(); routeLine = null; }
  if (state.route?.geometry?.length) {
    routeLine = L.layerGroup([
      L.polyline(state.route.geometry, { color: '#351c15', weight: 9, opacity: 0.85, lineJoin: 'round' }),
      L.polyline(state.route.geometry, { color: '#ffb500', weight: 5, opacity: 1, lineJoin: 'round' }),
    ]).addTo(map);
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

/* ---------------- Aufenthalte (solange die App offen ist) ---------------- */

let tracker = null;
let watchId = null;
let lastFix = null; // { lat, lon, acc, time }
let lastVisitSave = 0;
const fmtClock = (ms) => new Date(ms).toLocaleTimeString(getLang(), { hour: '2-digit', minute: '2-digit' });
const fmtDur = (ms) => (ms < 60000 ? `${Math.max(1, Math.round(ms / 1000))} ${t('sec')}` : `${Math.round(ms / 60000)} ${t('min')}`);

function updateMe() {
  if (!map || !myPos) return;
  if (!meMarker) {
    meMarker = L.marker([myPos.lat, myPos.lon], {
      icon: L.divIcon({ className: '', html: '<div class="me-dot"></div>', iconSize: [18, 18] }),
      interactive: false,
      zIndexOffset: -100,
    }).addTo(map);
  } else meMarker.setLatLng([myPos.lat, myPos.lon]);
}

function startTracking() {
  stopTracking();
  if (!state.settings.trackVisits || !navigator.geolocation) return;
  tracker = new DwellTracker({ minMs: (+state.settings.dwellSec || 30) * 1000 });
  watchId = navigator.geolocation.watchPosition(onFix, () => {}, { enableHighAccuracy: true, maximumAge: 5000, timeout: 30000 });
}
function stopTracking() {
  if (watchId != null) navigator.geolocation.clearWatch(watchId);
  watchId = null;
  tracker = null;
}

function onFix(p) {
  const fix = { lat: p.coords.latitude, lon: p.coords.longitude, acc: p.coords.accuracy, time: Date.now() };
  lastFix = fix;
  myPos = { lat: fix.lat, lon: fix.lon };
  state.lastPos = myPos;
  updateMe();
  handleFix(fix);
}

// Im Stand liefert das Handy kaum neue Positionen → alle 5 s die letzte (frische) Position weiterzählen
setInterval(() => {
  if (tracker && lastFix && document.visibilityState === 'visible' && Date.now() - lastFix.time < 600000) {
    handleFix({ ...lastFix, time: Date.now() });
  }
}, 5000);

function handleFix(fix) {
  if (!tracker) return;
  const ev = tracker.update(fix, state.stops);
  if (ev.ended) saveVisit(ev.ended);
  if (ev.started) {
    state.visits.push(ev.started);
    saveVisit(ev.started);
    toast('📍 ' + t('visit_started', { a: splitAddr(ev.started.address).street }));
  } else if (ev.updated && Date.now() - lastVisitSave > 15000) {
    saveVisit(ev.updated);
  }
  if (ev.started || ev.ended) render();
}
function saveVisit() {
  lastVisitSave = Date.now();
  state.visits = pruneVisits(state.visits);
  save();
}

/** Zustellung / nicht angetroffen mit Zeit und Position festhalten */
function logStatusEvent(s, status) {
  const fresh = lastFix && Date.now() - lastFix.time < 600000 ? lastFix : null;
  const dist = fresh && hasPos(s) ? Math.round(haversine(fresh, s)) : null;
  s.donePos = fresh ? { lat: fresh.lat, lon: fresh.lon, acc: Math.round(fresh.acc || 0) } : null;
  state.visits.push({
    id: uid(), type: status === 'delivered' ? 'zugestellt' : 'nicht angetroffen', stopId: s.id,
    address: s.address, name: s.name || '', from: Date.now(), to: Date.now(),
    lat: fresh?.lat ?? null, lon: fresh?.lon ?? null, dist,
  });
}

/** "✓ 10:44 · vor Ort 2 Min." für erledigte Stopps */
function doneInfo(s) {
  if (!s.doneAt) return '';
  const v = [...state.visits].reverse().find((x) => x.stopId === s.id && !x.type);
  return `${s.status === 'delivered' ? '✓' : '!'} ${fmtClock(s.doneAt)}${v ? ' · ' + t('on_site', { d: fmtDur(v.to - v.from) }) : ''}`;
}

document.addEventListener('visibilitychange', () => {
  // im Hintergrund weiß die App nicht, wo man ist → erst nach neuer echter Position weiterzählen
  if (document.visibilityState === 'hidden') lastFix = null;
  else if (state.settings.trackVisits && watchId == null) startTracking();
});

function locate(center = false) {
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null);
    navigator.geolocation.getCurrentPosition(
      (p) => {
        myPos = { lat: p.coords.latitude, lon: p.coords.longitude };
        state.lastPos = myPos;
        save();
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
  s.precision = 'manual';
  if (lookup(state.book, s.address)) updatePosition(state.book, s);
  else remember(state.book, s);
  invalidateRoute();
  save();
  render();
  toast(t('point_set'));
  try { s.geoLabel = await reverse(s.lat, s.lon, getLang()); save(); } catch {}
}

/* ---------------- Route ---------------- */

async function optimize() {
  // Express zuerst (wichtig, falls ohne GPS beim ersten Stopp gestartet wird)
  const pending = state.stops.filter((s) => isOpen(s) && hasPos(s)).sort((a, b) => prioOf(a) - prioOf(b));
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
    const priority = points.map((p) => (p.id === '__start' ? 0 : prioOf(p)));
    const r = await buildRoute(points, { roundtrip: state.settings.roundtrip, priority });
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

/**
 * Genauigkeit des Ziels:
 * genaues Haus oder von Hand gesetzter Punkt → Koordinaten;
 * sonst (nur Straße gefunden, alte Einträge) → Adresse als Text, die Navi-App sucht das Haus selbst
 * (bei Apps, die nur Koordinaten verstehen, gibt es einen Hinweis).
 */
function useCoords(s) {
  return s.precision === 'house' || s.precision === 'manual';
}
function navAddress(s) {
  let a = s.address;
  if (!/(^|\D)\d{4,5}\s+\p{L}/u.test(a) && state.settings.city && !a.toLowerCase().includes(state.settings.city.toLowerCase())) a += ', ' + state.settings.city;
  return a;
}
const navName = (app) => (app === 'geo' ? t('nav_geo') : app === 'ask' ? t('nav_ask') : NAV_APPS[app]?.name || app);

function openNavWith(app, points) {
  const { url, count, coordsOnly } = navLink(app, points, { exact: useCoords, address: navAddress });
  if (points.length > count) toast(count > 1 ? t('nav_first_n', { app: navName(app), n: count }) : t('single_dest', { app: navName(app) }), 4000);
  else if (coordsOnly && !useCoords(points[0])) toast(t('nav_coords_hint'), 4500);
  window.__lastNav = url; // für automatisierte Tests
  // App-Schemata (yandexnavi:, geo: …) und die Android-App: direkt aufrufen; Webseiten im neuen Tab
  if (IS_NATIVE || isAppScheme(url)) window.location.href = url;
  else window.open(url, '_blank');
}

let navPending = [];
function openNav(points) {
  if (!points.length) return toast(t('no_stops'));
  if (state.settings.nav !== 'ask') return openNavWith(state.settings.nav, points);
  // "Jedes Mal fragen": Auswahl anzeigen
  navPending = points;
  $('#navGrid').innerHTML = appsFor(PLATFORM)
    .map((a) => `<button type="button" class="btn nav-app" data-app="${a}">${esc(navName(a))}</button>`)
    .join('');
  $('#navRemember').checked = false;
  $('#dlgNav').showModal();
}
$('#navGrid').addEventListener('click', (e) => {
  const b = e.target.closest('[data-app]');
  if (!b) return;
  if ($('#navRemember').checked) { state.settings.nav = b.dataset.app; save(); }
  $('#dlgNav').close();
  openNavWith(b.dataset.app, navPending);
});

$('#btnAllGoogle').addEventListener('click', () => {
  openNavWith('google', state.stops.filter((s) => isOpen(s) && hasPos(s)));
});

$('#btnOpenNav').addEventListener('click', () => {
  openNav(state.stops.filter((s) => isOpen(s) && hasPos(s)));
});

/* ---------------- Einstellungen: Navi-Auswahl je nach Gerät ---------------- */
function fillNavSelect() {
  $('#setNav').innerHTML = NAV_CHOICES.map((a) => `<option value="${a}">${esc(navName(a))}</option>`).join('');
}

/* ---------------- Touren & Gedächtnis ---------------- */

const dlgT = $('#dlgTours');

function tourTitle(tr) {
  if (!tr.auto) return tr.name;
  const d = new Date(tr.date + 'T12:00:00');
  const diff = Math.round((new Date(today() + 'T12:00:00') - d) / 86400000);
  if (diff === 0) return t('today');
  if (diff === 1) return t('yesterday');
  return d.toLocaleDateString(getLang(), { weekday: 'long', day: '2-digit', month: '2-digit' });
}

function dayKey(ms) {
  return today(new Date(ms));
}
function renderHistory() {
  const sel = $('#histDay');
  const days = [...new Set(state.visits.map((v) => dayKey(v.from)))].sort().reverse();
  if (!days.includes(today())) days.unshift(today());
  const cur = days.includes(sel.value) ? sel.value : days[0];
  sel.innerHTML = days.map((d) => `<option value="${d}">${esc(d === today() ? t('today') : new Date(d + 'T12:00:00').toLocaleDateString(getLang(), { weekday: 'short', day: '2-digit', month: '2-digit' }))}</option>`).join('');
  sel.value = cur;
  const list = state.visits.filter((v) => dayKey(v.from) === cur).sort((a, b) => b.from - a.from);
  $('#histList').innerHTML = list.length
    ? list.map((v) => {
      const { street } = splitAddr(v.address);
      const what = v.type === 'zugestellt' ? `<span class="h-ok">✓ ${t('delivered')}</span>`
        : v.type ? `<span class="h-fail">! ${t('not_home')}</span>`
        : `📍 ${t('on_site', { d: fmtDur(v.to - v.from) })}`;
      return `<li class="hist"><span class="h-time">${fmtClock(v.from)}${!v.type ? '–' + fmtClock(v.to) : ''}</span>
        <span class="h-text"><b>${esc(street)}</b><small>${what}${v.dist != null ? ` · ${v.dist} m` : ''}</small></span></li>`;
    }).join('')
    : `<li class="sug-empty">${esc(state.settings.trackVisits ? t('hist_empty') : t('hist_off'))}</li>`;
}

function renderTours() {
  renderHistory();
  const list = [...(state.tours || [])].sort((a, b) => b.date.localeCompare(a.date) || (b.savedAt || 0) - (a.savedAt || 0));
  $('#tourList').innerHTML = list.length
    ? list.map((tr) => {
      const done = tr.stops.filter((s) => s.status === 'delivered').length;
      const date = new Date(tr.date + 'T12:00:00').toLocaleDateString(getLang(), { day: '2-digit', month: '2-digit', year: 'numeric' });
      return `
      <li class="tour" data-id="${tr.id}">
        <div class="tour-text">
          <b>${tr.auto ? '' : '★ '}${esc(tourTitle(tr))}</b>
          <small>${esc(tr.auto ? t('tour_auto') + ' · ' + date : date)} · ${t('tour_count', { n: tr.stops.length, d: done })}</small>
        </div>
        <div class="tour-actions">
          <button type="button" class="btn small primary" data-tour="load">${t('tour_load')}</button>
          <button type="button" class="btn small" data-tour="add" aria-label="${t('tour_add')}">+</button>
          <button type="button" class="btn small danger" data-tour="del" aria-label="${t('delete')}">${ICON.del}</button>
        </div>
      </li>`;
    }).join('')
    : `<li class="sug-empty">${esc(t('tours_empty'))}</li>`;
  $('#bookInfo').textContent = t('book_info', { n: Object.keys(state.book || {}).length });
}

$('#btnTours').addEventListener('click', () => {
  $('#tourName').value = '';
  $('#tourName').placeholder = t('tour_name_ph', { d: new Date().toLocaleDateString(getLang(), { weekday: 'long' }) });
  renderTours();
  dlgT.showModal();
});

$('#btnSaveTour').addEventListener('click', () => {
  if (!state.stops.length) return toast(t('no_stops'));
  const name = $('#tourName').value.trim() || $('#tourName').placeholder;
  state.tours = saveNamedTour(state.tours, state.stops, name);
  save();
  renderTours();
  $('#tourName').value = '';
  toast(t('tour_saved', { n: name }));
});

$('#tourList').addEventListener('click', (e) => {
  const b = e.target.closest('[data-tour]');
  if (!b) return;
  const tr = state.tours.find((x) => x.id === b.closest('.tour').dataset.id);
  if (!tr) return;
  const act = b.dataset.tour;
  if (act === 'del') {
    if (!confirm(t('tour_confirm_del', { n: tourTitle(tr) }))) return;
    state.tours = state.tours.filter((x) => x !== tr);
    save();
    return renderTours();
  }
  const restored = restoreStops(tr);
  if (act === 'load') {
    if (state.stops.some(isOpen) && !confirm(t('tour_confirm_replace'))) return;
    state.stops = restored;
  } else {
    const have = new Set(state.stops.map((s) => normKey(s.address)));
    const add = restored.filter((s) => !have.has(normKey(s.address)));
    const firstDone = state.stops.findIndex((x) => !isOpen(x));
    state.stops.splice(firstDone < 0 ? state.stops.length : firstDone, 0, ...add);
  }
  state.route = null;
  save();
  render();
  dlgT.close();
  showView('list');
  toast(t('tour_loaded', { n: restored.length }));
});

$('#histDay').addEventListener('change', renderHistory);
$('#btnHistCsv').addEventListener('click', async () => {
  const day = $('#histDay').value;
  const list = state.visits.filter((v) => dayKey(v.from) === day);
  if (!list.length) return toast(t('hist_empty'));
  const name = `delivery-verlauf-${day}.csv`;
  const file = new File([visitsCsv(list, { locale: getLang() === 'ru' ? 'ru-RU' : 'de-DE' })], name, { type: 'text/csv' });
  try {
    if (navigator.canShare?.({ files: [file] })) { await navigator.share({ files: [file], title: name }); return; }
  } catch (err) { if (err.name === 'AbortError') return; }
  const a = document.createElement('a');
  a.href = URL.createObjectURL(file);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
});

$('#btnClearBook').addEventListener('click', () => {
  if (!confirm(t('book_confirm_clear'))) return;
  state.book = {};
  save();
  renderTours();
});

// Sicherung als Datei (Adressbuch, Touren, Einstellungen, aktuelle Tour)
$('#btnExport').addEventListener('click', async () => {
  const data = JSON.stringify({ app: 'delivery', version: 1, exportedAt: new Date().toISOString(), book: state.book, tours: state.tours, settings: state.settings, stops: state.stops, visits: state.visits });
  const name = `delivery-sicherung-${today()}.json`;
  const file = new File([data], name, { type: 'application/json' });
  try {
    if (navigator.canShare?.({ files: [file] })) { await navigator.share({ files: [file], title: name }); return; }
  } catch (err) { if (err.name === 'AbortError') return; }
  const a = document.createElement('a');
  a.href = URL.createObjectURL(file);
  a.download = name;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
});
$('#btnImport').addEventListener('click', () => $('#importFile').click());
$('#importFile').addEventListener('change', async (e) => {
  const f = e.target.files?.[0];
  e.target.value = '';
  if (!f) return;
  try {
    const d = JSON.parse(await f.text());
    if (d.app !== 'delivery' || typeof d.book !== 'object') throw new Error('format');
    // zusammenführen: Adressbuch (höherer Zähler gewinnt), Touren (nach ID)
    for (const [k, v] of Object.entries(d.book || {})) if (!state.book[k] || state.book[k].count < v.count) state.book[k] = v;
    const ids = new Set(state.tours.map((x) => x.id));
    state.tours = [...state.tours, ...(d.tours || []).filter((x) => !ids.has(x.id))];
    const vids = new Set(state.visits.map((x) => x.id));
    state.visits = pruneVisits([...state.visits, ...(d.visits || []).filter((x) => !vids.has(x.id))]);
    save();
    renderTours();
    toast(t('backup_loaded', { n: Object.keys(d.book || {}).length, t: (d.tours || []).length }));
  } catch {
    toast(t('backup_bad'));
  }
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
  fillNavSelect();
  $('#setNav').value = s.nav;
  $('#setAutoAdd').checked = s.autoAdd;
  $('#setSaverFirst').checked = s.saverFirst;
  $('#setRadius').value = String(s.radius || 50);
  $('#setTrack').checked = !!s.trackVisits;
  $('#setDwell').value = String(s.dwellSec || 30);
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
    saverFirst: $('#setSaverFirst').checked,
    radius: +$('#setRadius').value || 50,
    trackVisits: $('#setTrack').checked,
    dwellSec: +$('#setDwell').value || 30,
  });
  save();
  startTracking();
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
startTracking();
if (!IS_NATIVE && 'serviceWorker' in navigator && location.protocol !== 'file:') {
  navigator.serviceWorker.register('sw.js').catch(() => {});
}
// für automatisierte Tests
window.__app = { state: () => state, render, optimize };
