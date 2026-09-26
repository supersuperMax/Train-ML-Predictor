import { lazy, Suspense, useEffect, useState } from 'react';
import { forecastParams, useApi } from './api';
import type { Filters, ForecastResponse, Meta, RouteInfo, StopsResponse, Summary } from './types';
import { dateRu, num, SOURCE_LABEL } from './format';
import FiltersPanel from './components/FiltersPanel';
import ForecastChart from './components/ForecastChart';
import SummaryCards from './components/SummaryCards';
import ExportLinks from './components/ExportLinks';
import { ErrorBox, Loading } from './components/Status';

// Карта (MapLibre) — самый тяжёлый модуль, грузим её отдельным чанком.
const MapPanel = lazy(() => import('./components/MapPanel'));

const HORIZON_TITLE = { day: 'Краткосрочный прогноз: день по часам', month: 'Среднесрочный прогноз: месяц по дням', year: 'Долгосрочный прогноз: год по месяцам' };

export default function App() {
  const [retry, setRetry] = useState(0);
  const meta = useApi<Meta>('/meta', {}, retry);
  const routes = useApi<RouteInfo[]>(meta.data?.ready ? '/routes' : null, {}, meta.data?.version);
  const allStops = useApi<StopsResponse>(meta.data?.ready ? '/stops' : null, {}, meta.data?.version);

  const [filters, setFilters] = useState<Filters | null>(null);
  useEffect(() => {
    if (meta.data?.available && !filters) {
      setFilters({ horizon: 'day', date: meta.data.available.from, route: null, stopId: null, hourFrom: 0, hourTo: 23, granularity: null });
    }
  }, [meta.data, filters]);

  // Пока worker не опубликовал прогноз — периодически спрашиваем снова.
  useEffect(() => {
    if (meta.data && !meta.data.ready) {
      const id = window.setTimeout(() => setRetry((r) => r + 1), 10_000);
      return () => window.clearTimeout(id);
    }
  }, [meta.data]);

  const params = filters ? forecastParams(filters) : {};
  const forecast = useApi<ForecastResponse>(filters ? '/forecast' : null, params);
  const summary = useApi<Summary>(filters ? '/summary' : null, params);

  const update = (patch: Partial<Filters>) => setFilters((f) => (f ? { ...f, ...patch } : f));
  const routeInfo = routes.data?.find((r) => r.route === filters?.route);

  return (
    <main>
      <header>
        <div>
          <h1>Прогноз пассажиропотока</h1>
          <p className="muted">Трамвайные маршруты Москвы · посадки (успешные валидации) по часам</p>
        </div>
        {meta.data?.ready && (
          <div className="meta muted small">
            <div>Прогноз: {dateRu(meta.data.available!.from)} — {dateRu(meta.data.available!.to)}</div>
            <div>Модель: {meta.data.model}</div>
            <div title={meta.data.version}>Обновлён: {new Date(meta.data.created_at!).toLocaleString('ru-RU')}</div>
          </div>
        )}
      </header>

      {meta.error && <ErrorBox error={meta.error} onRetry={() => setRetry((r) => r + 1)} />}
      {meta.loading && !meta.data && <Loading text="Подключение к сервису…" />}
      {meta.data && !meta.data.ready && (
        <div className="alert info">
          Прогноз ещё строится: пайплайн не опубликовал данные. Страница обновится автоматически.
          {meta.data.last_run?.error && <div className="small">Последний прогон завершился ошибкой: {meta.data.last_run.error}</div>}
        </div>
      )}
      {meta.data?.last_run?.status === 'error' && meta.data.ready && (
        <div className="alert warn small">
          Последний прогон пайплайна завершился ошибкой, показан предыдущий прогноз: {meta.data.last_run.error}
        </div>
      )}

      {filters && meta.data?.ready && (
        <>
          <FiltersPanel filters={filters} onChange={update} routes={routes.data ?? []} stops={allStops.data?.stops ?? []} available={meta.data.available} />

          <div className="grid">
            <section className="card chart-card">
              <div className="card-head">
                <h2>{HORIZON_TITLE[filters.horizon]}</h2>
                <span className="muted">
                  {filters.route === null ? 'все маршруты' : `маршрут № ${filters.route}`}
                  {forecast.data?.query.stop_name ? ` · ${forecast.data.query.stop_name}` : ''}
                </span>
              </div>
              {forecast.error && <ErrorBox error={forecast.error} />}
              {forecast.loading && !forecast.data && <Loading />}
              {forecast.data && (
                <>
                  <div className={forecast.loading ? 'stale' : ''}>
                    <ForecastChart data={forecast.data} />
                  </div>
                  <p className="muted small">
                    {dateRu(forecast.data.query.from)} — {dateRu(forecast.data.query.to)} · итого {num(forecast.data.total)} посадок
                    {forecast.data.query.truncated && ' · период обрезан до доступного прогноза'}
                    {forecast.data.points.some((p) => p.source !== 'model') && (
                      <> · <span className="badge">серые столбцы — {SOURCE_LABEL.baseline}, за пределами горизонта модели</span></>
                    )}
                  </p>
                </>
              )}
              {summary.error && !forecast.error && <ErrorBox error={summary.error} />}
              {summary.data && <SummaryCards s={summary.data} />}
              <ExportLinks filters={filters} />
            </section>

            <Suspense fallback={<section className="card"><Loading text="Загрузка карты…" /></section>}>
              <MapPanel
                date={filters.date}
                route={filters.route}
                routeHasStops={!!routeInfo?.has_stops}
                selectedStop={filters.stopId}
                available={meta.data.available}
                onDateChange={(date) => update({ date })}
                onSelectStop={(stopId, stopRoutes) =>
                  update({ stopId, route: filters.route !== null && stopRoutes.includes(filters.route) ? filters.route : stopRoutes[0] })
                }
              />
            </Suspense>
          </div>

          <section className="card factors">
            <h2>Учитываемые факторы</h2>
            <ul>
              {Object.entries(meta.data.factors ?? {}).map(([k, v]) => (
                <li key={k}>{v}</li>
              ))}
              <li className="muted">Погода: {meta.data.weather}</li>
            </ul>
          </section>
        </>
      )}
    </main>
  );
}
