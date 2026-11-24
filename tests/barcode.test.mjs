import test from 'node:test';
import assert from 'node:assert/strict';
import { parseScan, scanAddress } from '../js/barcode.js';

const GS = '\x1d', RS = '\x1e', EOT = '\x04';

test('1Z-Strichcode', () => {
  const r = parseScan('1Z999AA10123456784', 'LABEL-TYPE-CODE128');
  assert.equal(r.kind, 'tracking');
  assert.equal(r.tracking, '1Z999AA10123456784');
});

test('MaxiCode mit Adresse (Klartext)', () => {
  const data = `[)>${RS}01${GS}9610115${GS}276${GS}065${GS}1Z999AA10123456784${GS}UPSN${GS}999AA1${GS}328${GS}${GS}1/1${GS}2.0${GS}Y${GS}HAUPTSTRASSE 12A${GS}BERLIN${GS}${RS}${EOT}`;
  const r = parseScan(data, 'LABEL-TYPE-MAXICODE');
  assert.equal(r.kind, 'maxicode');
  assert.equal(r.postcode, '10115');
  assert.equal(r.country, '276');
  assert.equal(r.service, 'saver');
  assert.equal(r.tracking, '1Z999AA10123456784');
  assert.equal(r.street, 'HAUPTSTRASSE 12A');
  assert.equal(r.city, 'BERLIN');
  assert.equal(scanAddress(r), 'HAUPTSTRASSE 12A, 10115 BERLIN');
});

test('MaxiCode ohne lesbare Adresse (komprimiert) → nur PLZ, Service, Sendungsnummer', () => {
  const data = `[)>${RS}01${GS}9631135${GS}276${GS}054${GS}1Z999AA10123450011${GS}UPSN${GS}999AA1${GS}328${GS}${GS}1/1${GS}1${GS}N${GS}\u0007ÿ#~${GS}${RS}${EOT}`;
  const r = parseScan(data, 'LABEL-TYPE-MAXICODE');
  assert.equal(r.postcode, '31135');
  assert.equal(r.service, 'plus');
  assert.equal(r.tracking, '1Z999AA10123450011');
  assert.equal(scanAddress(r), '');
});

test('Platzhalter statt Steuerzeichen (Scanner-Einstellung)', () => {
  const r = parseScan('[)><RS>01<GS>9641065<GS>276<GS>011<GS>1Z999AA10123450022<GS>UPSN<GS>X<GS>1<GS><GS>1/1<GS>1<GS>Y<GS>DAIMLERRING 2<GS>MOENCHENGLADBACH<GS><RS><EOT>', 'MAXICODE');
  assert.equal(r.service, '');
  assert.equal(scanAddress(r), 'DAIMLERRING 2, 41065 MOENCHENGLADBACH');
});

test('Unbekannter Code', () => {
  assert.equal(parseScan('4006381333931', 'EAN13').kind, 'other');
});
