import type { ReactNode } from 'react';
import type { Summary } from '../types';
import { DAYTYPE_LABEL, dateRu, num, pad2 } from '../format';

function Stat({ label, value, note }: { label: string; value: ReactNode; note: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 rounded-xl bg-page px-3.5 py-3">
      <span className="text-xs text-muted">{label}</span>
      <b className="text-[22px]">{value}</b>
      <small className="text-xs text-muted">{note}</small>
    </div>
  );
}

export default function SummaryCards({ s }: { s: Summary }) {
  const types = (Object.keys(DAYTYPE_LABEL) as (keyof typeof DAYTYPE_LABEL)[]).filter((t) => s.by_daytype[t]);
  return (
    <div className="mt-4">
      <div className="grid grid-cols-[repeat(auto-fit,minmax(150px,1fr))] gap-3">
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
      </div>
      {types.length > 1 && (
        <table className="mt-3.5 w-full text-sm [&_td]:border-b [&_td]:border-line [&_td]:px-2 [&_td]:py-1.5 [&_th]:border-b [&_th]:border-line [&_th]:px-2 [&_th]:py-1.5">
          <thead className="text-xs font-semibold text-muted">
            <tr>
              <th className="text-left">Тип дня</th>
              <th className="text-right">Дней</th>
              <th className="text-right">Посадок в день</th>
            </tr>
          </thead>
          <tbody>
            {types.map((t) => (
              <tr key={t}>
                <td>{DAYTYPE_LABEL[t]}</td>
                <td className="text-right">{s.by_daytype[t]!.days}</td>
                <td className="text-right">{num(s.by_daytype[t]!.per_day)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
