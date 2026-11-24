// Auswertung gescannter Barcodes (Hardware-Scanner, z. B. Zebra über DataWedge).
//
// UPS-Etiketten tragen zwei Codes:
//  - 1D-Strichcode mit der Sendungsnummer 1Z… (18 Zeichen)
//  - MaxiCode (2D, Achteck mit Zielscheibe) nach ANSI MH10.8.3 / ISO 15434:
//      [)> RS 01 GS 96 <PLZ> GS <Land> GS <Service> GS <Tracking> GS <SCAC> GS <Versender>
//      GS <Julian-Tag> GS <Sendungs-ID> GS <n/x> GS <Gewicht> GS <Adressprüfung>
//      GS <Straße> GS <Ort> GS <Bundesland> RS EOT
//    Ob Straße/Ort enthalten sind, hängt vom Etikett ab (manche sind leer oder komprimiert).
//    Deshalb wird alles defensiv gelesen und im Zweifel nur Sendungsnummer/PLZ/Service genutzt.

const GS = '\x1d';
const RS = '\x1e';
const EOT = '\x04';

// UPS-Servicecodes (3-stellig im MaxiCode) → Stufe in der App
const SERVICE = {
  '054': 'plus', // Worldwide Express Plus
  '014': 'plus', // Next Day Air Early
  '007': 'express', // Worldwide Express
  '001': 'express', // Next Day Air
  '065': 'saver', // UPS Saver
  '013': 'saver', // Next Day Air Saver
  '011': '', // UPS Standard
  '008': '', // Expedited
  '003': '', // Ground
};

const TRACKING_RE = /1Z[0-9A-Z]{16}/i;

/** Gruppentrenner können je nach Scanner-Einstellung als echte Steuerzeichen oder als Platzhalter ankommen */
function normalize(raw) {
  return String(raw || '')
    .replace(/<GS>|\{GS\}|\^\]|␝|␝/gi, GS)
    .replace(/<RS>|\{RS\}|␞|␞/gi, RS)
    .replace(/<EOT>|\{EOT\}|␄|␄/gi, EOT);
}

const clean = (s) => String(s || '').replace(/[\x00-\x1f]/g, '').trim();

/**
 * data: gelesener Inhalt, type: Codetyp vom Scanner (z. B. "LABEL-TYPE-MAXICODE")
 * Liefert { kind: 'maxicode' | 'tracking' | 'other', tracking, postcode, country, service, street, city, raw }
 */
export function parseScan(data, type = '') {
  const raw = normalize(data);
  const out = { kind: 'other', tracking: '', postcode: '', country: '', service: null, street: '', city: '', raw: String(data || '') };
  const tr = raw.replace(/\s/g, '').match(TRACKING_RE);
  if (tr) out.tracking = tr[0].toUpperCase();

  const isMaxi = /maxicode/i.test(type) || raw.includes('[)>');
  if (isMaxi && raw.includes(GS)) {
    // Nutzdaten nach "[)>RS01GS96" (oder ohne Kopf, wenn der Scanner ihn abschneidet)
    let body = raw;
    const head = body.indexOf('[)>');
    if (head >= 0) body = body.slice(head + 3);
    body = body.replace(new RegExp(`^${RS}?01${GS}(96)?`), '');
    const f = body.split(RS)[0].split(GS).map(clean);
    // f[0]=PLZ, f[1]=Land, f[2]=Service, f[3]=Tracking, f[4]=SCAC, f[5]=Versender, f[6]=Julian, f[7]=Sendungs-ID,
    // f[8]=n/x, f[9]=Gewicht, f[10]=Adressprüfung, f[11]=Straße, f[12]=Ort, f[13]=Bundesland
    out.kind = 'maxicode';
    if (/^\d{3}$/.test(f[1] || '')) out.country = f[1];
    // PLZ: Deutschland 5-stellig; Österreich (040) und Schweiz (756) 4-stellig (UPS füllt mit Nullen auf)
    const plz = (f[0] || '').match(out.country === '040' || out.country === '756' ? /^\d{4}/ : /^\d{5}/);
    if (plz) out.postcode = plz[0];
    if (/^\d{3}$/.test(f[2] || '')) out.service = SERVICE[f[2]] ?? null;
    if (!out.tracking && /^1Z/i.test(f[3] || '')) out.tracking = f[3].toUpperCase();
    // Straße/Ort nur übernehmen, wenn sie wie Klartext aussehen (keine komprimierten Daten)
    const plain = (s) => s && s.length >= 2 && s.length <= 60 && /^[\p{L}\d .,'\-/]+$/u.test(s) && /\p{L}{2}/u.test(s);
    if (plain(f[11]) && plain(f[12])) {
      out.street = f[11];
      out.city = f[12];
    }
    return out;
  }
  if (out.tracking) out.kind = 'tracking';
  return out;
}

/** Adresse aus MaxiCode-Daten (oder '' wenn keine vollständige Adresse enthalten ist) */
export function scanAddress(s) {
  if (!s.street || !s.city) return '';
  return [s.street, [s.postcode, s.city].filter(Boolean).join(' ')].join(', ');
}
