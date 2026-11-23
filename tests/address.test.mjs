import test from 'node:test';
import assert from 'node:assert/strict';
import { extractAddress, cleanForGeocode, geocodeQueries, extractPhone } from '../js/address.js';
import { optimizeOrder, haversine } from '../js/route.js';

test('метка «Куда:» с переносом строки', () => {
  const text = `СДЭК Заказ № 1234567890
Отправитель: ООО Ромашка
г. Москва, ул. Складская, д. 1
Получатель: Иванов Иван
Куда: 420111, г. Казань,
ул. Баумана, д. 15, кв. 7
Тел: 8 (917) 123-45-67
Вес: 1.2 кг`;
  const r = extractAddress(text);
  assert.equal(r.address, '420111, г. Казань, ул. Баумана, д. 15, кв. 7');
  assert.equal(r.phone, '+79171234567');
  assert.equal(r.confidence, 'high');
});

test('без меток — выбирается адресная строка, отправитель исключается', () => {
  const text = `OZON
От кого: Склад, Московская обл., г. Подольск, ул. Комсомольская, д. 1
Петров П.П.
+7 999 000-11-22
г. Екатеринбург, пр-т Ленина, д. 50, корп. 2, кв. 10
Штрихкод 46000123`;
  const r = extractAddress(text);
  assert.equal(r.address, 'г. Екатеринбург, пр-т Ленина, д. 50, корп. 2, кв. 10');
  assert.equal(r.phone, '+79990001122');
});

test('адрес из нескольких строк без меток', () => {
  const r = extractAddress(`Получатель Сидорова А.\nРеспублика Татарстан\nг. Набережные Челны\nул. Мира, д. 3`);
  assert.match(r.address, /Набережные Челны, ул\. Мира, д\. 3$/);
});

test('пустой текст', () => {
  assert.equal(extractAddress('').address, '');
  assert.equal(extractAddress('Спасибо за покупку!').address, '');
});

test('очистка для геокодера', () => {
  assert.equal(cleanForGeocode('420111, г. Казань, ул. Баумана, д. 15, кв. 7'), 'Казань, улица Баумана, 15');
  assert.equal(cleanForGeocode('г. Екатеринбург, пр-т Ленина, д. 50, корп. 2, кв. 10'), 'Екатеринбург, проспект Ленина, 50к2');
  assert.equal(cleanForGeocode('Россия, Московская обл., г. Химки, ул. Мира, д. 5 стр. 1, офис 3'), 'Московская область, Химки, улица Мира, 5с1');
});

test('варианты запросов с городом по умолчанию', () => {
  const q = geocodeQueries('ул. Баумана, д. 15', 'Казань');
  assert.equal(q[0], 'улица Баумана, 15, Казань');
  assert.ok(q.includes('улица Баумана, 15'));
  assert.equal(geocodeQueries('г. Казань, ул. Баумана 15', 'Казань')[0], 'Казань, улица Баумана 15');
});

test('телефон', () => {
  assert.equal(extractPhone('тел. +7(912)345-67-89'), '+79123456789');
  assert.equal(extractPhone('индекс 420111'), '');
});

test('оптимизация: точки на прямой обходятся по порядку', () => {
  const pts = [0, 5, 1, 4, 2, 3].map((x) => ({ lat: 55, lon: 37 + x * 0.01 }));
  const D = pts.map((a) => pts.map((b) => haversine(a, b)));
  const order = optimizeOrder(D);
  assert.deepEqual(order.map((i) => Math.round((pts[i].lon - 37) * 100)), [0, 1, 2, 3, 4, 5]);
});

test('оптимизация: не хуже ближайшего соседа на случайных точках', () => {
  let seed = 7;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  const pts = Array.from({ length: 30 }, () => ({ lat: 55 + rnd() * 0.2, lon: 37 + rnd() * 0.3 }));
  const D = pts.map((a) => pts.map((b) => haversine(a, b)));
  const order = optimizeOrder(D);
  assert.equal(order[0], 0);
  assert.equal(new Set(order).size, 30);
});

test('Express-Stopps werden immer zuerst angefahren', () => {
  let seed = 11;
  const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
  for (let run = 0; run < 20; run++) {
    const n = 25;
    const pts = Array.from({ length: n }, () => ({ lat: 52.4 + rnd() * 0.2, lon: 13.2 + rnd() * 0.3 }));
    const D = pts.map((a) => pts.map((b) => haversine(a, b) * (1 + rnd() * 0.2)));
    const prio = pts.map((_, i) => (i === 0 ? 0 : rnd() < 0.25 ? 0 : 1));
    const order = optimizeOrder(D, run % 2 === 1, prio);
    assert.equal(order[0], 0);
    assert.equal(new Set(order).size, n);
    const firstNormal = order.findIndex((i) => i !== 0 && prio[i] === 1);
    const lastExpress = order.reduce((acc, i, k) => (i !== 0 && prio[i] === 0 ? k : acc), -1);
    assert.ok(firstNormal < 0 || lastExpress < firstNormal, `Express nach normal in Lauf ${run}`);
  }
});

test('Express ganz weit weg wird trotzdem zuerst angefahren', () => {
  // Start bei 0, normale Stopps 1..4 auf dem Weg, Express (5) am anderen Ende
  const pts = [0, 1, 2, 3, 4, 10].map((x) => ({ lat: 52, lon: 13 + x * 0.01 }));
  const D = pts.map((a) => pts.map((b) => haversine(a, b)));
  const order = optimizeOrder(D, false, [0, 1, 1, 1, 1, 0]);
  assert.equal(order[1], 5);
  assert.deepEqual(order, [0, 5, 4, 3, 2, 1]);
});
