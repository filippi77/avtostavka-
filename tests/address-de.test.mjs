import test from 'node:test';
import assert from 'node:assert/strict';
import { extractAddress, cleanForGeocode, geocodeQueries, extractPhone } from '../js/address.js';

test('DHL-Etikett: Absender oben, Empfänger darunter', () => {
  const r = extractAddress(`DHL PAKET
Absender:
Online Shop GmbH
Lagerweg 3
04103 Leipzig
Empfänger:
Anna Schmidt
Hauptstraße 12a
10115 Berlin
Deutschland
Sendungsnummer 00340434161234567890`);
  assert.equal(r.address, 'Hauptstraße 12a, 10115 Berlin');
  assert.equal(r.name, 'Anna Schmidt');
  assert.equal(r.confidence, 'high');
});

test('Absender in einer Zeile ohne Label (Hermes/Amazon-Stil)', () => {
  const r = extractAddress(`Versand: Shop GmbH · Industriestr. 7 · 33602 Bielefeld
Herrn
Jonas Weber
Berliner Str. 45
60311 Frankfurt am Main
Tel.: 0151 23456789`);
  assert.equal(r.address, 'Berliner Str. 45, 60311 Frankfurt am Main');
  assert.equal(r.name, 'Jonas Weber');
  assert.equal(r.phone, '+4915123456789');
});

test('Adresse in einer Zeile mit Kommas', () => {
  const r = extractAddress('An: Lisa Wagner, Am Markt 3, D-80331 München');
  assert.equal(r.address, 'Am Markt 3, 80331 München');
  assert.equal(r.name, 'Lisa Wagner');
});

test('Packstation mit Postnummer', () => {
  const r = extractAddress(`Max Mustermann
Postnummer 12345678
Packstation 105
50667 Köln`);
  assert.equal(r.address, 'Packstation 105, 50667 Köln');
  assert.equal(r.name, 'Max Mustermann');
  assert.equal(r.note, 'Postnummer 12345678');
});

test('c/o und Straßen mit Präfix', () => {
  const r = extractAddress(`Empfänger
Familie Yilmaz
c/o Becker
Unter den Linden 5
10117 Berlin`);
  assert.equal(r.address, 'Unter den Linden 5, 10117 Berlin');
  assert.equal(r.note, 'c/o Becker');
  assert.equal(r.name, 'Familie Yilmaz');
});

test('Österreich (4-stellige PLZ)', () => {
  const r = extractAddress(`Sophie Gruber
Mariahilfer Straße 88
1070 Wien`);
  assert.equal(r.address, 'Mariahilfer Straße 88, 1070 Wien');
});

test('OCR-Fehler: O statt 0 in Zahlen', () => {
  const r = extractAddress(`Peter Klein\nGoethestraße 1O\n2O095 Hamburg`);
  assert.equal(r.address, 'Goethestraße 10, 20095 Hamburg');
});

test('Telefonnummern', () => {
  assert.equal(extractPhone('Tel: +49 (0)30 1234567'), '+49301234567');
  assert.equal(extractPhone('Mobil 0172/1234567'), '+491721234567');
  assert.equal(extractPhone('10115 Berlin'), '');
  assert.equal(extractPhone('Sendungsnummer 00340434161234567890'), '');
});

test('Bereinigung für den Geocoder', () => {
  assert.equal(cleanForGeocode('Hauptstr. 12 a, 2. OG, D-10115 Berlin, Deutschland'), 'Hauptstraße 12a, 10115 Berlin');
  assert.equal(cleanForGeocode('Berliner Str. 45, Whg. 7, 60311 Frankfurt am Main'), 'Berliner Straße 45, 60311 Frankfurt am Main');
  assert.equal(cleanForGeocode('Gartenweg 4, Hinterhaus, 04109 Leipzig'), 'Gartenweg 4, 04109 Leipzig');
});

test('Suchvarianten', () => {
  const q = geocodeQueries('Hauptstr. 12a, 10115 Berlin', 'Berlin');
  assert.equal(q[0], 'Hauptstraße 12a, 10115 Berlin');
  assert.ok(q.includes('Hauptstraße 12, 10115 Berlin'));
  assert.ok(q.includes('Hauptstraße 12a, Berlin'));
  assert.equal(geocodeQueries('Lindenweg 3', 'Potsdam')[0], 'Lindenweg 3, Potsdam');
});

test('Express-Erkennung', async () => {
  const { detectExpress } = await import('../js/address.js');
  for (const t of ['DHL EXPRESS', 'GLS Express 10:00', 'DPD Express vor 12 Uhr', 'Zustellung bis 10:00 Uhr', 'PRIORITY', 'UPS Express Saver', 'Экспресс-доставка']) {
    assert.equal(detectExpress(t), true, t);
  }
  for (const t of ['DHL Paket', 'Hermes', 'Expressweg 5\n10115 Berlin'.replace('Expressweg', 'Exportweg'), 'Gewicht 2 kg', 'Prioritätsstraße'.replace('Prioritäts', 'Pracht')]) {
    assert.equal(detectExpress(t), false, t);
  }
  const r = extractAddress('DHL EXPRESS\nEmpfänger:\nAnna Schmidt\nHauptstraße 12a\n10115 Berlin');
  assert.equal(r.express, true);
  assert.equal(r.address, 'Hauptstraße 12a, 10115 Berlin');
  assert.equal(extractAddress('Anna Schmidt\nHauptstraße 12a\n10115 Berlin').express, false);
});

test('UPS-Etikett (Großbuchstaben, SHIP/TO, Absender ohne Label)', async () => {
  const { extractTracking } = await import('../js/address.js');
  const label = `MUSTER VERSAND GMBH
+49 30 9876543
INDUSTRIESTR. 7
33602 BIELEFELD
GERMANY
1 KG
1 OF 1
SHIP
TO: ANNA SCHMIDT
ACME GMBH
+49 151 23456789
HAUPTSTRASSE 12A
10115 BERLIN
GERMANY
DEU 101 2-01
UPS EXPRESS SAVER
TRACKING #: 1Z 999 AA1 01 2345 6784
BILLING: P/P`;
  const r = extractAddress(label);
  assert.equal(r.address, 'Hauptstrasse 12a, 10115 Berlin');
  assert.equal(r.name, 'Anna Schmidt · Acme GmbH');
  assert.equal(r.phone, '+4915123456789');
  assert.equal(r.service, 'saver');
  assert.equal(r.tracking, '1Z999AA10123456784');
  assert.equal(extractTracking('kein code'), '');
});

test('UPS-Servicestufen', async () => {
  const { detectService } = await import('../js/address.js');
  assert.equal(detectService('UPS EXPRESS PLUS'), 'plus');
  assert.equal(detectService('UPS EXPRESS 12:00'), 'express');
  assert.equal(detectService('UPS WORLDWIDE EXPRESS'), 'express');
  assert.equal(detectService('UPS EXPRESS SAVER'), 'saver');
  assert.equal(detectService('UPS SAVER'), 'saver');
  assert.equal(detectService('UPS STANDARD'), '');
  assert.equal(detectService('UPS EXPEDITED'), '');
  assert.equal(detectService('Zustellung bis 9:00 Uhr'), 'plus');
});

test('SHIP TO in einer Zeile, Absender oben', () => {
  const r = extractAddress(`SHIPPER INC\nWERKSTRASSE 1\n70173 STUTTGART\nSHIP TO: MAX MÜLLER-LÜDENSCHEID\nAM MARKT 3\n80331 MÜNCHEN\nUPS STANDARD`);
  assert.equal(r.address, 'Am Markt 3, 80331 München');
  assert.equal(r.name, 'Max Müller-Lüdenscheid');
  assert.equal(r.service, '');
});

test('OCR-Müll hinter der Hausnummer (Punkte eines MaxiCodes)', () => {
  const r = extractAddress(`SHIP TO:\nLISA WAGNER\nROSENTHALER STRASSE 40 TAB SRE hos\n10178 BERLIN\nGERMANY`);
  assert.equal(r.address, 'Rosenthaler Strasse 40, 10178 Berlin');
  assert.equal(r.name, 'Lisa Wagner');
});
