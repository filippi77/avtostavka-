// Kopiert die Web-App nach www/ (Quelle für die Android-App via Capacitor).
import { cpSync, rmSync, mkdirSync } from 'node:fs';

const OUT = 'www';
rmSync(OUT, { recursive: true, force: true });
mkdirSync(OUT);
for (const p of ['index.html', 'manifest.webmanifest', 'sw.js', 'css', 'js', 'icons']) {
  cpSync(p, `${OUT}/${p}`, { recursive: true });
}
console.log('Web-App nach www/ kopiert');
