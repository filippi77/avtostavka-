// App-Shell-Cache für schwaches Netz unterwegs.
const VERSION = 'v32';
const SHELL = [
  './', 'index.html', 'css/app.css', 'manifest.webmanifest', 'icons/icon.svg', 'icons/icon-180.png', 'icons/icon-192.png',
  'js/app.js', 'js/i18n.js', 'js/address.js', 'js/geocode.js', 'js/autocomplete.js', 'js/memory.js', 'js/navigate.js', 'js/visits.js', 'js/barcode.js', 'js/livescan.js', 'js/maxicode.js', 'js/route.js', 'js/ocr.js',
];
const CDN = 'https://cdn.jsdelivr.net/';

self.addEventListener('install', (e) => {
  // cache: 'reload' – am HTTP-Cache des Browsers vorbei, sonst landen alte Dateien im neuen Paket
  e.waitUntil(caches.open('shell-' + VERSION).then((c) => c.addAll(SHELL.map((u) => new Request(u, { cache: 'reload' })))).then(() => self.skipWaiting()));
});
self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k.startsWith('shell-') && k !== 'shell-' + VERSION).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});
self.addEventListener('fetch', (e) => {
  const url = e.request.url;
  if (e.request.method !== 'GET') return;
  // Bibliotheken und OCR-Modelle vom CDN: Cache zuerst (Versionen sind fixiert)
  if (url.startsWith(CDN)) {
    e.respondWith(
      caches.open('cdn').then(async (c) => {
        const hit = await c.match(e.request);
        if (hit) return hit;
        const res = await fetch(e.request);
        if (res.ok) c.put(e.request, res.clone());
        return res;
      })
    );
    return;
  }
  // App-Dateien: Netz zuerst (immer beim Server nachfragen – GitHub Pages erlaubt sonst 10 min alte Kopien,
  // dann passen neue Seite und alte Skripte nicht zusammen), ohne Netz aus dem Cache
  if (new URL(url).origin === location.origin) {
    const req = e.request.mode === 'navigate' ? url : e.request;
    e.respondWith(
      fetch(req, { cache: 'no-cache' })
        .then((res) => {
          if (res.ok) caches.open('shell-' + VERSION).then((c) => c.put(e.request, res.clone()));
          return res;
        })
        .catch(() => caches.match(e.request).then((r) => r || caches.match('index.html')))
    );
  }
});
