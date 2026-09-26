import type { Filters, Granularity, Horizon, RouteInfo, Stop } from '../types';
import { pad2 } from '../format';
import { card, control, label } from '../ui';

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
    <section className={`${card} mb-6 flex flex-wrap items-end gap-x-6 gap-y-4`} aria-label="Параметры прогноза">
      <div className="flex min-w-[150px] flex-col gap-2">
        <span className={label}>Горизонт</span>
        <div className="isolate inline-flex rounded-md shadow-sm" role="radiogroup">
          {HORIZONS.map((h) => (
            <button
              key={h.value}
              role="radio"
              aria-checked={filters.horizon === h.value}
              className={filters.horizon === h.value
                ? 'relative cursor-pointer bg-blue-600 px-4 py-2 text-sm font-semibold text-white ring-1 ring-inset ring-blue-600 first:rounded-l-md last:rounded-r-md not-first:-ml-px focus:z-10'
                : 'relative cursor-pointer bg-white px-4 py-2 text-sm font-semibold text-slate-900 ring-1 ring-inset ring-slate-300 first:rounded-l-md last:rounded-r-md not-first:-ml-px hover:bg-slate-50 focus:z-10'}
              onClick={() => onChange({ horizon: h.value, granularity: null })}
              title={h.hint}
            >
              {h.label}
            </button>
          ))}
        </div>
      </div>

      <label className="flex min-w-[150px] flex-col gap-2">
        <span className={label}>Дата начала</span>
        <input
          className={control}
          type="date"
          value={filters.date}
          min={available?.from}
          max={available?.to}
          onChange={(e) => e.target.value && onChange({ date: e.target.value })}
        />
      </label>

      <label className="flex min-w-[150px] flex-col gap-2">
        <span className={label}>Маршрут</span>
        <select
          className={control}
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

      <label className="flex min-w-[150px] flex-col gap-2">
        <span className={label}>Остановка</span>
        <select
          className={control}
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

      <div className="flex min-w-[150px] flex-col gap-2">
        <span className={label}>Часы</span>
        <div className="flex items-center gap-2 text-slate-400">
          <select className={control} value={filters.hourFrom} onChange={(e) => onChange({ hourFrom: Number(e.target.value) })} aria-label="С часа">
            {HOURS.map((h) => (
              <option key={h} value={h} disabled={h > filters.hourTo}>
                {pad2(h)}:00
              </option>
            ))}
          </select>
          <span>—</span>
          <select className={control} value={filters.hourTo} onChange={(e) => onChange({ hourTo: Number(e.target.value) })} aria-label="По час">
            {HOURS.map((h) => (
              <option key={h} value={h} disabled={h < filters.hourFrom}>
                {pad2(h)}:59
              </option>
            ))}
          </select>
        </div>
      </div>

      <label className="flex min-w-[150px] flex-col gap-2">
        <span className={label}>Шаг</span>
        <select
          className={control}
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
