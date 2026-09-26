import type { Summary } from '../types';
import { DAYTYPE_LABEL, dateRu, num, pad2 } from '../format';

export default function SummaryCards({ s }: { s: Summary }) {
  const types = (Object.keys(DAYTYPE_LABEL) as (keyof typeof DAYTYPE_LABEL)[]).filter((t) => s.by_daytype[t]);
  return (
    <div className="summary">
      <div className="stats">
        <div className="stat">
          <span>Всего посадок</span>
          <b>{num(s.total)}</b>
          <small>{s.days} дн.</small>
        </div>
        <div className="stat">
          <span>В среднем за день</span>
          <b>{num(s.per_day)}</b>
          <small>{num(s.per_hour)} в час</small>
        </div>
        <div className="stat">
          <span>Пиковый час</span>
          <b>{s.peak ? num(s.peak.value) : '—'}</b>
          <small>{s.peak ? `${dateRu(s.peak.date)}, ${pad2(s.peak.hour)}:00` : ''}</small>
        </div>
        <div className="stat">
          <span>Самый загруженный час суток</span>
          <b>{s.peak_hour_of_day ? `${pad2(s.peak_hour_of_day.hour)}:00` : '—'}</b>
          <small>{s.peak_hour_of_day ? `≈ ${num(s.peak_hour_of_day.avg)} посадок` : ''}</small>
        </div>
      </div>
      {types.length > 1 && (
        <table className="daytypes">
          <thead>
            <tr>
              <th>Тип дня</th>
              <th>Дней</th>
              <th>Посадок в день</th>
            </tr>
          </thead>
          <tbody>
            {types.map((t) => (
              <tr key={t}>
                <td>{DAYTYPE_LABEL[t]}</td>
                <td>{s.by_daytype[t]!.days}</td>
                <td>{num(s.by_daytype[t]!.per_day)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
