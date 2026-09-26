import type { Filters, Granularity, Horizon, RouteInfo, Stop } from '../types';
import { pad2 } from '../format';

interface Props {
  filters: Filters;
  onChange: (patch: Partial<Filters>) => void;
  routes: RouteInfo[];
  stops: Stop[];
  available?: { from: string; to: string };
}

const HORIZONS: { value: Horizon; label: string; hint: string }[] = [
  { value: 'day', label: 'День', hint: 'по часам' },
  { value: 'month', label: 'Месяц', hint: 'по дням' },
  { value: 'year', label: 'Год', hint: 'по месяцам' },
];

const GRANULARITIES: { value: Granularity | ''; label: string }[] = [
  { value: '', label: 'Авто' },
  { value: 'hour', label: 'Час' },
  { value: 'day', label: 'День' },
  { value: 'week', label: 'Неделя' },
  { value: 'month', label: 'Месяц' },
];

const HOURS = Array.from({ length: 24 }, (_, h) => h);

export default function FiltersPanel({ filters, onChange, routes, stops, available }: Props) {
  const route = routes.find((r) => r.route === filters.route);
  const routeStops = filters.route === null ? [] : stops.filter((s) => s.routes.includes(filters.route!));

  return (
    <section className="card mb-5 flex flex-wrap items-end gap-x-5 gap-y-4" aria-label="Параметры прогноза">
      <div className="flex min-w-[150px] flex-col gap-1.5">
        <span className="field-label">Горизонт</span>
        <div className="inline-flex overflow-hidden rounded-lg border border-control" role="radiogroup">
          {HORIZONS.map((h) => (
            <button
              key={h.value}
              role="radio"
              aria-checked={filters.horizon === h.value}
              className={`px-4 py-2 not-first:border-l not-first:border-control ${filters.horizon === h.value ? 'bg-accent text-white' : 'bg-white text-ink'}`}
              onClick={() => onChange({ horizon: h.value, granularity: null })}
              title={h.hint}
            >
              {h.label}
            </button>
          ))}
        </div>
      </div>

      <label className="flex min-w-[150px] flex-col gap-1.5">
        <span className="field-label">Дата начала</span>
        <input
          className="control"
          type="date"
          value={filters.date}
          min={available?.from}
          max={available?.to}
          onChange={(e) => e.target.value && onChange({ date: e.target.value })}
        />
      </label>

      <label className="flex min-w-[150px] flex-col gap-1.5">
        <span className="field-label">Маршрут</span>
        <select
          className="control"
          value={filters.route ?? ''}
          onChange={(e) => onChange({ route: e.target.value ? Number(e.target.value) : null, stopId: null })}
        >
          <option value="">Все маршруты</option>
          {routes.map((r) => (
            <option key={r.route} value={r.route}>
              № {r.route}
              {r.name ? ` · ${r.name}` : ''}
            </option>
          ))}
        </select>
      </label>

      <label className="flex min-w-[150px] flex-col gap-1.5">
        <span className="field-label">Остановка</span>
        <select
          className="control"
          value={filters.stopId ?? ''}
          disabled={!route?.has_stops}
          onChange={(e) => onChange({ stopId: e.target.value ? Number(e.target.value) : null })}
          title={route && !route.has_stops ? 'Для этого маршрута нет координат остановок в справочнике' : undefined}
        >
          <option value="">{filters.route === null ? 'Выберите маршрут' : route?.has_stops ? 'Весь маршрут' : 'Нет данных об остановках'}</option>
          {routeStops.map((s) => (
            <option key={s.stop_id} value={s.stop_id}>
              {s.name}
            </option>
          ))}
        </select>
      </label>

      <div className="flex min-w-[150px] flex-col gap-1.5">
        <span className="field-label">Часы</span>
        <div className="flex items-center gap-1.5">
          <select className="control" value={filters.hourFrom} onChange={(e) => onChange({ hourFrom: Number(e.target.value) })} aria-label="С часа">
            {HOURS.map((h) => (
              <option key={h} value={h} disabled={h > filters.hourTo}>
                {pad2(h)}:00
              </option>
            ))}
          </select>
          <span>—</span>
          <select className="control" value={filters.hourTo} onChange={(e) => onChange({ hourTo: Number(e.target.value) })} aria-label="По час">
            {HOURS.map((h) => (
              <option key={h} value={h} disabled={h < filters.hourFrom}>
                {pad2(h)}:59
              </option>
            ))}
          </select>
        </div>
      </div>

      <label className="flex min-w-[150px] flex-col gap-1.5">
        <span className="field-label">Шаг</span>
        <select
          className="control"
          value={filters.granularity ?? ''}
          onChange={(e) => onChange({ granularity: (e.target.value || null) as Granularity | null })}
        >
          {GRANULARITIES.map((g) => (
            <option key={g.value} value={g.value}>
              {g.label}
            </option>
          ))}
        </select>
      </label>
    </section>
  );
}
