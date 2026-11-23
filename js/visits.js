// Aufenthalte an Lieferadressen erkennen (solange die App geöffnet ist).
//
// Ein Aufenthalt zählt, wenn man sich mindestens `minMs` lang im Umkreis `radius`
// um einen Stopp befindet. Lücken ohne GPS (App im Hintergrund) länger als `gapMs`
// beenden den Aufenthalt beim letzten bekannten Zeitpunkt.

import { haversine } from './route.js';

export class DwellTracker {
  constructor({ radius = 75, minMs = 30000, gapMs = 180000, maxAccuracy = 100 } = {}) {
    Object.assign(this, { radius, minMs, gapMs, maxAccuracy });
    this.cur = null; // { stopId, from, last, visit }
  }

  /** Stopp in der Nähe (nächster innerhalb des Radius, Genauigkeit eingerechnet) */
  nearest(pos, stops) {
    let best = null;
    for (const s of stops) {
      if (s.lat == null) continue;
      const d = haversine(pos, s);
      const limit = this.radius + Math.min(pos.acc || 0, 50) / 2;
      if (d <= limit && (!best || d < best.d)) best = { s, d };
    }
    return best;
  }

  /**
   * Neue GPS-Position verarbeiten.
   * pos: { lat, lon, acc, time }
   * Liefert Ereignisse: { started?: visit, updated?: visit, ended?: visit }
   *  started – Aufenthalt hat gerade minMs erreicht (jetzt speichern)
   *  updated – laufender Aufenthalt wurde verlängert
   *  ended   – Aufenthalt beendet
   */
  update(pos, stops) {
    const ev = {};
    if (pos.acc != null && pos.acc > this.maxAccuracy) return ev; // zu ungenau
    // lange Lücke → vorherigen Aufenthalt beim letzten bekannten Zeitpunkt beenden
    if (this.cur && pos.time - this.cur.last > this.gapMs) this.finish(ev);
    const near = this.nearest(pos, stops);
    if (this.cur && (!near || near.s.id !== this.cur.stopId)) this.finish(ev);
    if (!near) return ev;
    if (!this.cur) this.cur = { stopId: near.s.id, from: pos.time, last: pos.time, visit: null, d: near.d };
    this.cur.last = pos.time;
    this.cur.d = Math.min(this.cur.d, near.d);
    if (this.cur.last - this.cur.from >= this.minMs) {
      if (!this.cur.visit) {
        this.cur.visit = {
          id: Math.random().toString(36).slice(2, 10),
          stopId: near.s.id,
          address: near.s.address,
          name: near.s.name || '',
          from: this.cur.from,
          to: this.cur.last,
          lat: pos.lat,
          lon: pos.lon,
          dist: Math.round(this.cur.d),
        };
        ev.started = this.cur.visit;
      } else {
        this.cur.visit.to = this.cur.last;
        this.cur.visit.dist = Math.round(this.cur.d);
        ev.updated = this.cur.visit;
      }
    }
    return ev;
  }

  finish(ev) {
    if (this.cur?.visit) {
      this.cur.visit.to = this.cur.last;
      ev.ended = this.cur.visit;
    }
    this.cur = null;
  }

  /** Stopp, an dem man gerade (bestätigt) ist, sonst null */
  presentAt() {
    return this.cur?.visit ? { stopId: this.cur.stopId, since: this.cur.from } : null;
  }
}

/** Aufenthalte älter als `days` Tage verwerfen */
export function pruneVisits(visits, days = 30, now = Date.now()) {
  const limit = now - days * 86400000;
  return visits.filter((v) => v.to >= limit);
}

/** CSV für Auswertung/Nachweis (Semikolon, wie in deutschem Excel üblich) */
export function visitsCsv(visits, { locale = 'de-DE' } = {}) {
  const fmt = (t) => new Date(t).toLocaleString(locale, { dateStyle: 'short', timeStyle: 'medium' });
  const q = (s) => `"${String(s ?? '').replace(/"/g, '""')}"`;
  const rows = [['Typ', 'Von', 'Bis', 'Dauer (Min.)', 'Adresse', 'Empfänger', 'Lat', 'Lon', 'Abstand (m)'].map(q).join(';')];
  for (const v of [...visits].sort((a, b) => a.from - b.from)) {
    rows.push([v.type || 'aufenthalt', fmt(v.from), fmt(v.to), ((v.to - v.from) / 60000).toFixed(1).replace('.', ','), v.address, v.name, v.lat?.toFixed(6), v.lon?.toFixed(6), v.dist ?? ''].map(q).join(';'));
  }
  return '﻿' + rows.join('\r\n');
}
