import { lazy, Suspense, useEffect, useState } from 'react';
import { forecastParams, useApi } from './api';
import type { Dataset, Filters, ForecastResponse, Meta, RouteInfo, StopsResponse, Summary } from './types';
import { dateRu, num, SOURCE_LABEL } from './format';
import FiltersPanel from './components/FiltersPanel';
import ForecastChart from './components/ForecastChart';
import SummaryCards from './components/SummaryCards';
import ExportLinks from './components/ExportLinks';
import PredictPanel from './components/PredictPanel';
import { ErrorBox, Loading } from './components/Status';
import { alertInfo, alertWarn, btn, card, cardHead, cardTitle, muted } from './ui';
import { useTheme } from './theme';
import { MoonIcon, SunIcon } from './components/icons';
import TramStrip from './components/TramStrip';

// Карта (MapLibre) — самый тяжёлый модуль, грузим её отдельным чанком.
const MapPanel = lazy(() => import('./components/MapPanel'));

const HORIZON_TITLE = { day: 'Краткосрочный прогноз: день по часам', month: 'Среднесрочный прогноз: месяц по дням', year: 'Долгосрочный прогноз: год по месяцам' };

export default function App() {
  const { dark, toggle } = useTheme();
  const [retry, setRetry] = useState(0);
  const meta = useApi<Meta>('/meta', {}, retry);
  const routes = useApi<RouteInfo[]>(meta.data?.ready ? '/routes' : null, {}, meta.data?.version);
  const allStops = useApi<StopsResponse>(meta.data?.ready ? '/stops' : null, {}, meta.data?.version);

  const [filters, setFilters] = useState<Filters | null>(null);
  // Источник данных для графиков и карты: model | baseline | file:<id> (залитый файл ключей).
  const [source, setSource] = useState('model');
  const [dataset, setDataset] = useState<Dataset | null>(null);
  useEffect(() => {
    if (meta.data?.available && !filters) {
      // по умолчанию — первый день прогноза модели (ноябрь 2025), а не начало всего диапазона
      const start = meta.data.sources?.model?.[0] ?? meta.data.available.from;
      setFilters({ horizon: 'day', date: start, route: null, stopId: null, hourFrom: 0, hourTo: 23, granularity: null });
      // при входе на сайт графики и карта показывают baseline; модель и файл — переключателем
      setSource(meta.data.has_baseline ? 'baseline' : 'model');
    }
  }, [meta.data, filters]);

  // Пока worker не опубликовал прогноз — периодически спрашиваем снова.
  useEffect(() => {
    if (meta.data && !meta.data.ready) {
      const id = window.setTimeout(() => setRetry((r) => r + 1), 10_000);
      return () => window.clearTimeout(id);
    }
  }, [meta.data]);

  const params = filters ? forecastParams(filters, source) : {};
  const forecast = useApi<ForecastResponse>(filters ? '/forecast' : null, params);
  const summary = useApi<Summary>(filters ? '/summary' : null, params);

  const update = (patch: Partial<Filters>) => setFilters((f) => (f ? { ...f, ...patch } : f));
  const changeSource = (next: string, date?: string, patch?: Partial<Filters>) => {
    setSource(next);
    if (date || patch) update({ ...patch, ...(date ? { date } : {}) });
  };
  // Набор валидаций расширяет шкалу на период своего факта (например, сентябрь–октябрь до начала прогноза).
  const factRange = source.startsWith('file:') && dataset?.kind === 'validations' ? dataset.range : null;
  const available =
    meta.data?.available && factRange
      ? {
          from: factRange[0] < meta.data.available.from ? factRange[0] : meta.data.available.from,
          to: factRange[1] > meta.data.available.to ? factRange[1] : meta.data.available.to,
        }
      : meta.data?.available;
  const sourceTitle = source === 'baseline' ? 'baseline' : source.startsWith('file:') ? `файл ${dataset?.name ?? ''}` : 'модель';
  const routeInfo = routes.data?.find((r) => r.route === filters?.route);

  return (
    <>
      <TramStrip />
      <main className="mx-auto max-w-7xl px-4 py-8 sm:px-6 lg:px-8">
      <header className="mb-8 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-slate-900 dark:text-white">Прогноз пассажиропотока</h1>
          <p className="mt-1 text-sm text-slate-500 dark:text-slate-400">Трамвайные маршруты Москвы · посадки (успешные валидации) по часам</p>
        </div>
        <div className="flex items-end gap-4">
        {meta.data?.ready && (
          <div className="text-right text-xs leading-5 text-slate-500 dark:text-slate-400">
            <div>Прогноз: {dateRu(meta.data.available!.from)} — {dateRu(meta.data.available!.to)}</div>
            <div title={meta.data.version}>Обновлён: {new Date(meta.data.created_at!).toLocaleString('ru-RU')}</div>
          </div>
        )}
          <button className={`${btn} size-9 justify-center p-0`} onClick={toggle} aria-label={dark ? 'Светлая тема' : 'Тёмная тема'} title={dark ? 'Светлая тема' : 'Тёмная тема'}>
            {dark ? <SunIcon /> : <MoonIcon />}
          </button>
        </div>
      </header>

      {meta.error && <ErrorBox error={meta.error} onRetry={() => setRetry((r) => r + 1)} />}
      {meta.loading && !meta.data && <Loading text="Подключение к сервису…" />}
      {meta.data && !meta.data.ready && (
        <div className={alertInfo}>
          Прогноз ещё строится: пайплайн не опубликовал данные. Страница обновится автоматически.
          {meta.data.last_run?.error && <div className="text-xs">Последний прогон завершился ошибкой: {meta.data.last_run.error}</div>}
        </div>
      )}
      {meta.data?.last_run?.status === 'error' && meta.data.ready && (
        <div className={alertWarn}>
          Последний прогон пайплайна завершился ошибкой, показан предыдущий прогноз: {meta.data.last_run.error}
        </div>
      )}

      {filters && meta.data?.ready && (
        <>
          <div className="mb-6">
            <PredictPanel meta={meta.data} routes={routes.data ?? []} source={source} dataset={dataset} onSource={changeSource} onDataset={setDataset} />
          </div>

          <FiltersPanel filters={filters} onChange={update} routes={routes.data ?? []} stops={allStops.data?.stops ?? []} available={available} />

          <div className="flex flex-col gap-6">
            <section className={card}>
              <div className={cardHead}>
                <h2 className={cardTitle}>{HORIZON_TITLE[filters.horizon]}</h2>
                <span className={muted}>
                  {sourceTitle} · {filters.route === null ? 'все маршруты' : `маршрут № ${filters.route}`}
                  {forecast.data?.query.stop_name ? ` · ${forecast.data.query.stop_name}` : ''}
                </span>
              </div>
              {forecast.error && <ErrorBox error={forecast.error} />}
              {forecast.loading && !forecast.data && <Loading />}
              {forecast.data && (
                <>
                  <div className={forecast.loading ? 'opacity-55 transition-opacity' : 'transition-opacity'}>
                    <ForecastChart data={forecast.data} dark={dark} solid={source === 'baseline'} />
                  </div>
                  <p className="mt-3 text-xs text-slate-500 dark:text-slate-400">
                    {dateRu(forecast.data.query.from)} — {dateRu(forecast.data.query.to)} · итого {num(forecast.data.total)} посадок
                    {forecast.data.fact_total !== undefined && ` · факт ${num(forecast.data.fact_total)} посадок`}
                    {forecast.data.compare?.error_pct != null &&
                      ` · отклонение прогноза от факта за ${dateRu(forecast.data.compare.from)}${forecast.data.compare.to !== forecast.data.compare.from ? ` — ${dateRu(forecast.data.compare.to)}` : ''}: ${forecast.data.compare.error_pct > 0 ? '+' : ''}${forecast.data.compare.error_pct.toFixed(1).replace('.', ',').replace('-', '−')} %`}
                    {forecast.data.fact_total !== undefined && !forecast.data.compare && dataset?.note && ` · ${dataset.note}`}
                    {forecast.data.query.truncated && ' · период обрезан до доступного прогноза'}
                    {source !== 'baseline' && forecast.data.points.some((p) => p.source === 'baseline' || p.source === 'mixed') && (
                      <> · <span className="inline-flex items-center rounded-md bg-slate-100 px-2 py-0.5 font-medium text-slate-600 dark:bg-slate-800 dark:text-slate-300">серые столбцы — {SOURCE_LABEL.baseline}, за пределами горизонта модели</span></>
                    )}
                  </p>
                </>
              )}
              {summary.error && !forecast.error && <ErrorBox error={summary.error} />}
              {summary.data && <SummaryCards s={summary.data} />}
              <ExportLinks filters={filters} source={source} />
            </section>

            <Suspense fallback={<section className={card}><Loading text="Загрузка карты…" /></section>}>
              <MapPanel
                date={filters.date}
                route={filters.route}
                routeHasStops={!!routeInfo?.has_stops}
                selectedStop={filters.stopId}
                dark={dark}
                source={source}
                available={available}
                onDateChange={(date) => update({ date })}
                onSelectStop={(stopId, stopRoutes) =>
                  update({ stopId, route: filters.route !== null && stopRoutes.includes(filters.route) ? filters.route : stopRoutes[0] })
                }
              />
            </Suspense>
          </div>
        </>
      )}
      </main>
    </>
  );
}
