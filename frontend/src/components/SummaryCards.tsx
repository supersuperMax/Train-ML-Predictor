import type { ReactNode } from 'react';
import type { Summary } from '../types';
import { DAYTYPE_LABEL, dateRu, num, pad2 } from '../format';

function Stat({ label, value, note }: { label: string; value: ReactNode; note: ReactNode }) {
  return (
    <div className="rounded-lg bg-slate-50 px-4 py-3">
      <dt className="text-xs font-medium text-slate-500">{label}</dt>
      <dd className="mt-1 text-2xl font-semibold tracking-tight text-slate-900">{value}</dd>
      <dd className="text-xs text-slate-500">{note}</dd>
    </div>
  );
}

export default function SummaryCards({ s }: { s: Summary }) {
  const types = (Object.keys(DAYTYPE_LABEL) as (keyof typeof DAYTYPE_LABEL)[]).filter((t) => s.by_daytype[t]);
  return (
    <div className="mt-6">
      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Всего посадок" value={num(s.total)} note={`${s.days} дн.`} />
        <Stat label="В среднем за день" value={num(s.per_day)} note={`${num(s.per_hour)} в час`} />
        <Stat
          label="Пиковый час"
          value={s.peak ? num(s.peak.value) : '—'}
          note={s.peak ? `${dateRu(s.peak.date)}, ${pad2(s.peak.hour)}:00` : ''}
        />
        <Stat
          label="Самый загруженный час суток"
          value={s.peak_hour_of_day ? `${pad2(s.peak_hour_of_day.hour)}:00` : '—'}
          note={s.peak_hour_of_day ? `≈ ${num(s.peak_hour_of_day.avg)} посадок` : ''}
        />
      </dl>
      {types.length > 1 && (
        <table className="mt-4 min-w-full divide-y divide-slate-200 text-sm">
          <thead>
            <tr className="text-xs font-semibold text-slate-500">
              <th className="py-2 pr-3 text-left">Тип дня</th>
              <th className="px-3 py-2 text-right">Дней</th>
              <th className="py-2 pl-3 text-right">Посадок в день</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 text-slate-700">
            {types.map((t) => (
              <tr key={t}>
                <td className="py-2 pr-3 font-medium text-slate-900">{DAYTYPE_LABEL[t]}</td>
                <td className="px-3 py-2 text-right">{s.by_daytype[t]!.days}</td>
                <td className="py-2 pl-3 text-right">{num(s.by_daytype[t]!.per_day)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
