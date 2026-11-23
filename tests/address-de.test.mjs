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
