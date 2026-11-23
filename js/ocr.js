// Texterkennung auf dem Foto des Etiketts (Tesseract.js, läuft direkt auf dem Gerät).

let workerPromise = null;
let workerLangs = '';
let progressCb = () => {};

function getWorker(langs) {
  if (workerPromise && workerLangs !== langs) {
    workerPromise.then((w) => w.terminate()).catch(() => {});
    workerPromise = null;
  }
  if (!workerPromise) {
    workerLangs = langs;
    workerPromise = window.Tesseract.createWorker(langs, 1, {
      logger: (m) => {
        if (m.status === 'recognizing text') progressCb('run', m.progress);
        else if (/loading|initializ/.test(m.status)) progressCb('load', m.progress);
      },
    }).catch((e) => {
      workerPromise = null;
      throw e;
    });
  }
  return workerPromise;
}

/** Verkleinert das Foto, wandelt in Graustufen um und erhöht den Kontrast. */
export async function preprocess(file, maxSide = 2000) {
  const bmp = await createImageBitmap(file, { imageOrientation: 'from-image' }).catch(() => loadViaImg(file));
  const scale = Math.min(1, maxSide / Math.max(bmp.width, bmp.height));
  const w = Math.round(bmp.width * scale);
  const h = Math.round(bmp.height * scale);
  const c = document.createElement('canvas');
  c.width = w;
  c.height = h;
  const ctx = c.getContext('2d', { willReadFrequently: true });
  ctx.drawImage(bmp, 0, 0, w, h);
  const img = ctx.getImageData(0, 0, w, h);
  const d = img.data;
  // Helligkeitshistogramm für Auto-Kontrast
  const hist = new Uint32Array(256);
  for (let i = 0; i < d.length; i += 4) {
    const y = (d[i] * 299 + d[i + 1] * 587 + d[i + 2] * 114) / 1000;
    d[i] = y;
    hist[y | 0]++;
  }
  const total = w * h;
  let lo = 0, hi = 255, acc = 0;
  while (lo < 255 && (acc += hist[lo]) < total * 0.01) lo++;
  acc = 0;
  while (hi > 0 && (acc += hist[hi]) < total * 0.01) hi--;
  const range = Math.max(1, hi - lo);
  for (let i = 0; i < d.length; i += 4) {
    const v = Math.max(0, Math.min(255, ((d[i] - lo) * 255) / range));
    d[i] = d[i + 1] = d[i + 2] = v;
  }
  ctx.putImageData(img, 0, 0);
  return c;
}

function loadViaImg(file) {
  return new Promise((res, rej) => {
    const img = new Image();
    img.onload = () => res(img);
    img.onerror = rej;
    img.src = URL.createObjectURL(file);
  });
}

/** Vorab laden, damit der erste Scan schneller ist. */
export function warmUp(langs = 'deu+eng') {
  if (window.Tesseract) getWorker(langs).catch(() => {});
}

export async function recognize(file, onProgress = () => {}, langs = 'deu+eng') {
  progressCb = onProgress;
  onProgress('prep', 0);
  const canvas = await preprocess(file);
  const worker = await getWorker(langs);
  const { data } = await worker.recognize(canvas);
  return { text: data.text || '', canvas };
}
