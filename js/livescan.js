// Live-Scan über die Handykamera: liest MaxiCode / 1Z-Strichcodes direkt aus dem Videobild
// (zxing-wasm, läuft im Browser – auch auf dem iPhone).

import { readMaxiCode, GEO } from './maxicode.js';

const ZX_VERSION = '3.1.7';
const ZX_BASE = `https://cdn.jsdelivr.net/npm/zxing-wasm@${ZX_VERSION}/dist`;
let zxReady = null;

/** Bibliothek erst bei Bedarf laden (~1 MB, danach aus dem Cache) */
export function loadZXing() {
  if (zxReady) return zxReady;
  zxReady = new Promise((resolve, reject) => {
    if (window.ZXingWASM) return resolve(window.ZXingWASM);
    const s = document.createElement('script');
    s.src = `${ZX_BASE}/iife/reader/index.js`;
    s.onload = () => {
      const Z = window.ZXingWASM;
      Z.prepareZXingModule({
        overrides: { locateFile: (path, prefix) => (path.endsWith('.wasm') ? `${ZX_BASE}/reader/${path}` : prefix + path) },
        fireImmediately: true,
      });
      resolve(Z);
    };
    s.onerror = () => { zxReady = null; reject(new Error('ZXing')); };
    document.head.appendChild(s);
  });
  return zxReady;
}

export class LiveScanner {
  /**
   * video: <video>-Element; onCode({ text, format }) wird für jeden gefundenen Code aufgerufen.
   */
  constructor(video, onCode) {
    this.video = video;
    this.onCode = onCode;
    this.canvas = document.createElement('canvas');
    this.ctx = this.canvas.getContext('2d', { willReadFrequently: true });
    this.running = false;
    this.stream = null;
    this.busy = false;
  }

  async start() {
    const Z = await loadZXing();
    this.Z = Z;
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1080 } },
    });
    this.video.srcObject = this.stream;
    this.video.setAttribute('playsinline', ''); // iPhone: nicht im Vollbild-Player öffnen
    this.video.muted = true;
    await this.video.play();
    this.running = true;
    this.loop();
  }

  stop() {
    this.running = false;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.video.srcObject = null;
  }

  /** Taschenlampe (geht auf Android, auf dem iPhone im Browser leider nicht) */
  async torch(on) {
    const track = this.stream?.getVideoTracks()[0];
    if (!track?.getCapabilities?.().torch) return false;
    await track.applyConstraints({ advanced: [{ torch: on }] });
    return true;
  }

  /**
   * aktuelles Kamerabild als JPEG (für die Texterkennung im Hintergrund).
   * Ein gerade gelesener MaxiCode wird weiß abgedeckt – seine Punkte würden sonst als
   * Buchstabensalat an den Adresszeilen hängen.
   */
  snapshot() {
    const v = this.video;
    if (!v.videoWidth) return Promise.resolve(null);
    const c = document.createElement('canvas');
    c.width = v.videoWidth;
    c.height = v.videoHeight;
    const ctx = c.getContext('2d');
    ctx.drawImage(v, 0, 0);
    const m = this.lastSymbol;
    if (m) {
      const k = 1.12;
      ctx.save();
      ctx.translate(m.x, m.y);
      ctx.rotate((m.deg * Math.PI) / 180);
      ctx.fillStyle = '#fff';
      ctx.fillRect(-GEO.left * m.D * k, -GEO.top * m.D * k, (GEO.left + GEO.right) * m.D * k, (GEO.top + GEO.bottom) * m.D * k);
      ctx.restore();
    }
    return new Promise((r) => c.toBlob(r, 'image/jpeg', 0.92));
  }

  async loop() {
    while (this.running) {
      const t0 = performance.now();
      try { await this.scanFrame(); } catch {}
      // ca. 6–8 Bilder pro Sekunde reichen und schonen den Akku
      const wait = Math.max(40, 140 - (performance.now() - t0));
      await new Promise((r) => setTimeout(r, wait));
    }
  }

  async scanFrame() {
    const v = this.video;
    if (!v.videoWidth || this.busy) return;
    this.busy = true;
    try {
      // auf max. 1280 px verkleinern – schneller, MaxiCode bleibt gut lesbar
      const scale = Math.min(1, 1280 / Math.max(v.videoWidth, v.videoHeight));
      const w = Math.round(v.videoWidth * scale);
      const h = Math.round(v.videoHeight * scale);
      if (this.canvas.width !== w) { this.canvas.width = w; this.canvas.height = h; }
      this.ctx.drawImage(v, 0, 0, w, h);
      const img = this.ctx.getImageData(0, 0, w, h);
      // 1) MaxiCode: Zielscheibe suchen, Symbol gerade ausschneiden, dann lesen
      const maxi = await readMaxiCode(img, (sym) => this.Z.readBarcodes(sym, { formats: ['MaxiCode'], isPure: true, textMode: 'Plain' }), { budgetMs: 220 });
      if (!this.running) return;
      if (maxi?.text) {
        // Lage des Codes im Videobild merken (für die Texterkennung wird er weiß abgedeckt)
        const b = maxi.bullseye;
        this.lastSymbol = { x: b.x / scale, y: b.y / scale, D: b.D / scale, deg: maxi.deg };
        return this.onCode({ text: maxi.text, format: 'MaxiCode' });
      }
      if (maxi) { this.onSeen?.(); return; } // MaxiCode im Bild, aber noch nicht gelesen → nächstes Bild
      // 2) kein MaxiCode im Bild → 1Z-Strichcode
      this.lastSymbol = null;
      const res = await this.Z.readBarcodes(img, { formats: ['Code128'], tryHarder: false, maxNumberOfSymbols: 2, textMode: 'Plain' });
      const one = res.find((r) => /1Z[0-9A-Z]{16}/i.test(r.text));
      if (one && this.running) this.onCode({ text: one.text, format: one.format });
    } finally {
      this.busy = false;
    }
  }
}

/** kurzer Signalton (Web Audio; funktioniert nach einer Nutzer-Geste auch auf dem iPhone) */
let actx = null;
export function unlockAudio() {
  try {
    actx = actx || new (window.AudioContext || window.webkitAudioContext)();
    if (actx.state === 'suspended') actx.resume();
  } catch {}
}
export function beep(kind = 'ok') {
  try {
    if (!actx) return;
    const tones = { ok: [[1320, 0.09]], dup: [[660, 0.07], [660, 0.07]], text: [[990, 0.08], [1320, 0.08]] }[kind] || [[1000, 0.1]];
    let t = actx.currentTime;
    for (const [f, d] of tones) {
      const o = actx.createOscillator();
      const g = actx.createGain();
      o.frequency.value = f;
      g.gain.setValueAtTime(0.25, t);
      g.gain.exponentialRampToValueAtTime(0.001, t + d);
      o.connect(g).connect(actx.destination);
      o.start(t);
      o.stop(t + d);
      t += d + 0.04;
    }
  } catch {}
}
