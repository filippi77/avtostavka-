import test from 'node:test';
import assert from 'node:assert/strict';
import { extractAddressList } from '../js/addrlist.js';

// Texterkennung eines abfotografierten Listen-Bildschirms (mit Spiegelungen) – erfundene Adressen
const SCREEN = `ay LISTE (60) KARTE ÜBERSICHT ERSTELLEN.
| py PUSTERWE ; ; HAT
MUSTERSTADT 12345 3
.
4 A9 477.59m Q
| WERKSTRASSE 8 8000 | 0430)
| a MUSTERSTADT 12345
| °
| ®
[J
| | A9 13km Q
| Erika Muster 8000 | 0+2 jg)
| FE, LINDENSTRASSE 2B
| MUSTERSTADT 12345 :
H
| AP 795.8m Q
ALTE POSTSTRASSE 27 8000 | +20
% MUSTERSTADT 12345
®
:
|
“> 5 2.79 «km Q |
AM ALTEN MARKT 7 8000 | off* 1 |
| MuSTeRSTAT 12355 mi =`;

test('Liste vom Bildschirm: Adressen, Name, Müll ignoriert, verlesener Ort korrigiert', () => {
  const r = extractAddressList(SCREEN);
  assert.deepEqual(r.map((x) => x.address), [
    'Werkstrasse 8, 12345 Musterstadt',
    'Lindenstrasse 2b, 12345 Musterstadt',
    'Alte Poststrasse 27, 12345 Musterstadt',
    'Am Alten Markt 7, 12345 Musterstadt',
  ]);
  assert.equal(r[1].name, 'Erika Muster');
  assert.equal(r[0].name, '');
});

test('Liste mit "PLZ Ort" (Ausdruck)', () => {
  const r = extractAddressList('Max Muster\nHauptstraße 12a\n10115 Berlin\n\nErika Beispiel\nAm Markt 3\n10117 Berlin');
  assert.deepEqual(r.map((x) => x.address), ['Hauptstraße 12a, 10115 Berlin', 'Am Markt 3, 10117 Berlin']);
  assert.deepEqual(r.map((x) => x.name), ['Max Muster', 'Erika Beispiel']);
});
