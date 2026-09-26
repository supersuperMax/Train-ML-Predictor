// Нагрузочный тест API: смесь реальных запросов дашборда с постоянной интенсивностью по ступеням.
import http from 'k6/http';
import { check } from 'k6';

const BASE = __ENV.BASE || 'http://api:8000';
const RATE = Number(__ENV.RATE || 200);
const ROUTES = [1, 5, 7, 11, 12, 17, 25, 26, 28, 50];
const STOPS = [2594,2595,2596,2597,2598,2599]; // остановки маршрута 1
const pick = (a) => a[Math.floor(Math.random() * a.length)];
const day = () => `2025-${pick(['11', '12'])}-${String(1 + Math.floor(Math.random() * 28)).padStart(2, '0')}`;

export const options = {
  discardResponseBodies: true,
  scenarios: {
    load: { executor: 'constant-arrival-rate', rate: RATE, timeUnit: '1s', duration: __ENV.DURATION || '60s',
            preAllocatedVUs: 200, maxVUs: 1000 },
  },
  thresholds: { http_req_failed: ['rate<0.01'], http_req_duration: ['p(95)<300'] },
  summaryTrendStats: ['avg', 'med', 'p(95)', 'p(99)', 'max'],
};

export default function () {
  const x = Math.random();
  let url;
  if (x < 0.6) {
    const h = pick(['day', 'month', 'year']);
    url = `${BASE}/api/forecast?horizon=${h}&date=${day()}&route=${pick(ROUTES)}` + (Math.random() < 0.2 ? `&hour_from=7&hour_to=10` : '');
  } else if (x < 0.75) url = `${BASE}/api/summary?horizon=month&date=${day()}&route=${pick(ROUTES)}`;
  else if (x < 0.9) url = `${BASE}/api/map?date=${day()}&hour=${Math.floor(Math.random() * 24)}`;
  else url = `${BASE}/api/predict?route=${pick(ROUTES)}&date=${day()}&hour=${Math.floor(Math.random() * 24)}`;
  if (Math.random() < 0.05) url = `${BASE}/api/forecast?horizon=day&date=${day()}&route=1&stop_id=${pick(STOPS)}`;
  check(http.get(url), { '200': (r) => r.status === 200 });
}
