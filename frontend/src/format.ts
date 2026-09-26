import type { Granularity, Source } from './types';

const nf = new Intl.NumberFormat('ru-RU', { maximumFractionDigits: 0 });
const MONTHS = ['янв', 'фев', 'мар', 'апр', 'май', 'июн', 'июл', 'авг', 'сен', 'окт', 'ноя', 'дек'];
const MONTHS_FULL = ['январь', 'февраль', 'март', 'апрель', 'май', 'июнь', 'июль', 'август', 'сентябрь', 'октябрь', 'ноябрь', 'декабрь'];

export const num = (v: number | null | undefined) => (v === null || v === undefined ? '—' : nf.format(v));

export function dateRu(iso: string): string {
  const [y, m, d] = iso.split('-').map(Number);
  return `${d} ${MONTHS[m - 1]} ${y}`;
}

export function periodLabel(t: string, g: Granularity, short = false): string {
  if (g === 'hour') return `${t.slice(11, 13)}:00`;
  if (g === 'month') {
    const [y, m] = t.split('-').map(Number);
    return short ? `${MONTHS[m - 1]} ${String(y).slice(2)}` : `${MONTHS_FULL[m - 1]} ${y}`;
  }
  const [, m, d] = t.split('-').map(Number);
  return g === 'week' ? `с ${d} ${MONTHS[m - 1]}` : `${d} ${MONTHS[m - 1]}`;
}

export const SOURCE_LABEL: Record<Source, string> = {
  model: 'модель',
  baseline: 'baseline (не ML)',
  mixed: 'модель + baseline',
  none: 'нет данных',
};

export const DAYTYPE_LABEL = { weekday: 'Будни', sat: 'Суббота', sun: 'Воскресенье', holiday: 'Праздники' } as const;

export const pad2 = (n: number) => String(n).padStart(2, '0');
