import { useRef, useState, type FormEvent } from 'react';
import { API, ApiError, checkFile, getJson, saveBlob, uploadFile } from '../api';
import type { Dataset, Filters, Meta, RouteInfo, Source } from '../types';
import { dateRu, num, pad2, SOURCE_LABEL } from '../format';
import { btn, btnActive, card, cardHead, cardTitle, control, label, muted } from '../ui';
import { ErrorBox } from './Status';
import { DownloadIcon, UploadIcon } from './icons';

interface Props {
  meta: Meta;
  routes: RouteInfo[];
  source: string;
  dataset: Dataset | null;
  /** Смена источника данных; date — куда перейти фильтрам (начало данных источника), patch — другие поля фильтров. */
  onSource: (source: string, date?: string, patch?: Partial<Filters>) => void;
  onDataset: (ds: Dataset | null) => void;
}

interface PredictResult {
  route: number;
  date: string;
  hour: number | null;
  prediction: number;
  source: Source;
}

const HOURS = Array.from({ length: 24 }, (_, h) => h);
// Шаблон — формат сырых валидаций хакатона: разделитель ;, UTF-8, первая строка — заголовок.
const TEMPLATE =
  'tran_no;device_no;tran_date_time;begin_date_time;input_date_time;crd_hashcode;validation_result;tran_type_id;place_id;good_type;pass_route;ngpt_route;bus_exit_no;garage_number\n' +
  '1;330100;2025-11-10 08:05:12;2025-11-10 08:05:12;2025-11-10 08:06:40;a1f3c9;1;52;10501;СКМ МГТ;;17 трамвай;5;31018\n' +
  '2;330100;2025-11-10 08:17:45;2025-11-10 08:17:45;2025-11-10 08:18:02;b7e210;1;52;10501;КОШЕЛЕК;;17 трамвай;5;31018\n' +
  '3;330214;2025-11-10 08:21:03;2025-11-10 08:21:03;2025-11-10 08:21:30;c90d44;0;52;10501;30 дней;;17 трамвай;5;31018\n' +
  '4;331502;2025-12-01 18:40:27;2025-12-01 18:40:27;2025-12-01 18:41:05;d25e8b;1;52;10203;СКМ МГТ;;1 трамвай;12;30456\n';
const mb = (bytes: number) => (bytes >= 1024 ** 3 ? `${(bytes / 1024 ** 3).toFixed(2)} ГБ` : `${(bytes / 1024 ** 2).toFixed(1)} МБ`);
const segment = (active: boolean) =>
  active
    ? 'relative cursor-pointer bg-blue-600 px-4 py-2 text-sm font-semibold text-white ring-1 ring-inset ring-blue-600 first:rounded-l-md last:rounded-r-md not-first:-ml-px focus:z-10 dark:bg-blue-500 dark:ring-blue-500'
    : 'relative cursor-pointer bg-white px-4 py-2 text-sm font-semibold text-slate-900 ring-1 ring-inset ring-slate-300 first:rounded-l-md last:rounded-r-md not-first:-ml-px hover:bg-slate-50 focus:z-10 disabled:cursor-not-allowed disabled:opacity-50 dark:bg-slate-800 dark:text-slate-100 dark:ring-slate-700 dark:hover:bg-slate-700';

export default function PredictPanel({ meta, routes, source, dataset, onSource, onDataset }: Props) {
  const modelFrom = meta.sources?.model?.[0] ?? meta.available?.from ?? '';
  const [route, setRoute] = useState<number | null>(null);
  const [date, setDate] = useState(modelFrom);
  const [hour, setHour] = useState<number | null>(8);
  const [one, setOne] = useState<PredictResult | null>(null);
  const [oneError, setOneError] = useState<ApiError | null>(null);
  const [oneBusy, setOneBusy] = useState(false);

  const [file, setFile] = useState<File | null>(null);
  const [fileError, setFileError] = useState<string | null>(null);
  const [uploadError, setUploadError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<{ sent: number; total: number } | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const selectedRoute = route ?? routes[0]?.route ?? null;
  // Набор валидаций: шкала от начала факта до конца прогноза, по неделям — видно, где факт, где прогноз.
  const openDataset = (ds: Dataset) => {
    if (!ds.range) return;
    if (ds.kind === 'validations') {
      onSource(ds.source, ds.range[0] < modelFrom ? ds.range[0] : modelFrom, { horizon: 'year', granularity: 'week' });
    } else {
      onSource(ds.source, ds.range[0]);
    }
  };
  const kind = source.startsWith('file:') ? 'file' : source;

  const pickFile = (f: File | null) => {
    setFile(f);
    setUploadError(null);
    setFileError(f ? checkFile(f, meta.limits) : null); // размер и тип — до отправки
  };

  const runOne = async (e: FormEvent) => {
    e.preventDefault();
    if (selectedRoute === null) return;
    setOneBusy(true);
    setOneError(null);
    try {
      setOne(await getJson<PredictResult>('/predict', { route: selectedRoute, date, hour, source: kind === 'baseline' ? 'baseline' : null }));
    } catch (err) {
      setOne(null);
      setOneError(err as ApiError);
    } finally {
      setOneBusy(false);
    }
  };

  const upload = async (e: FormEvent) => {
    e.preventDefault();
    if (!file || fileError) return;
    setBusy(true);
    setUploadError(null);
    setProgress({ sent: 0, total: file.size });
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const res = await uploadFile('/datasets', file, {}, (sent, total) => setProgress({ sent, total }), ctrl.signal, 'json');
      const ds = res.json as Dataset;
      onDataset(ds);
      openDataset(ds);
    } catch (err) {
      if ((err as ApiError).code !== 'aborted') setUploadError(err as ApiError);
    } finally {
      setBusy(false);
      setProgress(null);
      abortRef.current = null;
    }
  };

  const percent = progress && progress.total ? Math.round((progress.sent / progress.total) * 100) : 0;

  return (
    <section className={card}>
      <div className={cardHead}>
        <h2 className={cardTitle}>Данные и прогон на модели</h2>
      </div>

      <div className="mb-6 flex flex-wrap items-center gap-4">
        <span className={label}>Показывать на графиках и карте:</span>
        <div className="isolate inline-flex rounded-md shadow-sm" role="radiogroup">
          <button type="button" role="radio" aria-checked={kind === 'model'} className={segment(kind === 'model')} onClick={() => onSource('model', modelFrom)}>
            Модель
          </button>
          <button
            type="button"
            role="radio"
            aria-checked={kind === 'baseline'}
            disabled={!meta.has_baseline}
            className={segment(kind === 'baseline')}
            onClick={() => onSource('baseline', kind === 'file' ? modelFrom : undefined)}
          >
            Baseline
          </button>
          <button
            type="button"
            role="radio"
            aria-checked={kind === 'file'}
            disabled={!dataset?.range}
            className={segment(kind === 'file')}
            onClick={() => dataset && openDataset(dataset)}
            title={dataset ? dataset.name : 'Сначала загрузите файл'}
          >
            Файл
          </button>
        </div>
        <span className={muted}>
          {kind === 'baseline' && 'профильный прогноз по истории (не ML) на весь период — для сравнения с моделью'}
          {kind === 'file' && dataset && (dataset.kind === 'validations'
            ? `факт из файла ${dataset.name} и полный прогноз модели на одной шкале`
            : `прогноз модели по ключам файла ${dataset.name}`)}
        </span>
      </div>

      <div className="grid gap-8 lg:grid-cols-2">
        <form onSubmit={upload} className="flex flex-col gap-4">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-white">Файл валидаций → факт и прогноз на графиках и карте</h3>
          <p className={muted}>
            Сырые валидации (как в «Шаблоне»): CSV — до {meta.limits ? mb(meta.limits.csv_bytes) : '2,5 ГБ'}, XLSX — до {meta.limits ? mb(meta.limits.xlsx_bytes) : '50 МБ'}.
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <input
              type="file"
              accept=".csv,.txt,.xlsx,.xls,text/csv"
              onChange={(e) => pickFile(e.target.files?.[0] ?? null)}
              className="block text-sm text-slate-700 file:mr-3 file:cursor-pointer file:rounded-md file:border-0 file:bg-slate-100 file:px-3 file:py-2 file:text-sm file:font-semibold file:text-slate-900 hover:file:bg-slate-200 dark:text-slate-300 dark:file:bg-slate-800 dark:file:text-slate-100 dark:hover:file:bg-slate-700"
            />
            <button type="submit" className={btnActive} disabled={!file || !!fileError || busy}>
              <UploadIcon className="size-4" />
              {busy ? 'Обработка…' : 'Загрузить'}
            </button>
            {busy && (
              <button type="button" className={btn} onClick={() => abortRef.current?.abort()}>
                Отмена
              </button>
            )}
            <button type="button" className={btn} onClick={() => saveBlob(new Blob(['\uFEFF' + TEMPLATE], { type: 'text/csv' }), 'validations_template.csv')}>
              <DownloadIcon className="size-4" />
              Шаблон
            </button>
          </div>
          {file && !busy && !fileError && <p className="text-xs text-slate-500 dark:text-slate-400">Выбран {file.name}, {mb(file.size)}</p>}
          {fileError && <div className="rounded-md bg-red-50 p-3 text-sm text-red-700 dark:bg-red-950/50 dark:text-red-300">{fileError}</div>}
          {progress && (
            <div className="flex flex-col gap-1.5" aria-live="polite">
              <div className="h-2 overflow-hidden rounded-full bg-slate-200 dark:bg-slate-800">
                <div className="h-full rounded-full bg-blue-600 transition-[width] duration-200 dark:bg-blue-500" style={{ width: `${percent}%` }} />
              </div>
              <span className="text-xs text-slate-500 dark:text-slate-400">
                {progress.sent < progress.total ? `Отправка: ${mb(progress.sent)} из ${mb(progress.total)} (${percent}%)` : 'Файл отправлен, идёт обработка на сервере…'}
              </span>
            </div>
          )}
          {uploadError && <ErrorBox error={uploadError} />}
          {dataset && (
            <div className="rounded-lg bg-slate-50 px-4 py-3 text-sm text-slate-700 dark:bg-slate-800/60 dark:text-slate-300">
              <div className="font-semibold text-slate-900 dark:text-white">{dataset.name}</div>
              <div>
                {dataset.kind === 'validations'
                  ? `Валидаций: ${num(dataset.rows)}, посадок: ${num(dataset.boardings ?? 0)}, пропущено (отказы, нет маршрута или даты): ${num(dataset.skipped ?? 0)}`
                  : `Строк: ${num(dataset.rows)}, с ошибкой: ${num(dataset.errors)}`}
                {dataset.range && ` · ${dataset.kind === 'validations' ? 'факт за' : 'период'} ${dateRu(dataset.range[0])} — ${dateRu(dataset.range[1])}`}
                {dataset.routes.length > 0 && ` · маршруты ${dataset.routes.join(', ')}`}
              </div>
              {!!dataset.trimmed_days?.length && (
                <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">
                  Отброшены неполные крайние дни: {dataset.trimmed_days.map((d) => dateRu(d)).join(', ')}
                </div>
              )}
              {dataset.note && <div className="mt-1 text-xs text-slate-500 dark:text-slate-400">{dataset.note}</div>}
              {dataset.warning && <div className="mt-2 text-amber-700 dark:text-amber-400">{dataset.warning}</div>}
              <div className="mt-2 flex flex-wrap gap-3">
                <a className={btn} href={API + dataset.result_url.replace(/^\/api/, '')} download>
                  <DownloadIcon className="size-4" />
                  Скачать результат
                </a>
                <button
                  type="button"
                  className={btn}
                  onClick={() => {
                    onDataset(null);
                    if (kind === 'file') onSource('model', modelFrom);
                  }}
                >
                  Сбросить
                </button>
              </div>
            </div>
          )}
        </form>

        <form onSubmit={runOne} className="flex flex-col gap-4">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-white">Одно значение</h3>
          <div className="flex flex-wrap items-end gap-4">
            <label className="flex flex-col gap-2">
              <span className={label}>Маршрут</span>
              <select className={control} value={selectedRoute ?? ''} onChange={(e) => setRoute(Number(e.target.value))}>
                {routes.map((r) => (
                  <option key={r.route} value={r.route}>
                    № {r.route}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-2">
              <span className={label}>Дата</span>
              <input className={control} type="date" required value={date} min={meta.available?.from} max={meta.available?.to} onChange={(e) => setDate(e.target.value)} />
            </label>
            <label className="flex flex-col gap-2">
              <span className={label}>Час</span>
              <select className={control} value={hour ?? ''} onChange={(e) => setHour(e.target.value === '' ? null : Number(e.target.value))}>
                <option value="">весь день</option>
                {HOURS.map((h) => (
                  <option key={h} value={h}>
                    {pad2(h)}:00
                  </option>
                ))}
              </select>
            </label>
            <button type="submit" className={btnActive} disabled={oneBusy || !date}>
              {oneBusy ? 'Расчёт…' : 'Рассчитать'}
            </button>
          </div>
          {oneError && <ErrorBox error={oneError} />}
          {one && (
            <div className="rounded-lg bg-slate-50 px-4 py-3 dark:bg-slate-800/60">
              <div className="text-xs text-slate-500 dark:text-slate-400">
                Маршрут № {one.route}, {dateRu(one.date)}, {one.hour === null ? 'весь день' : `${pad2(one.hour)}:00`}
              </div>
              <div className="mt-1 text-2xl font-semibold tracking-tight text-slate-900 dark:text-white">{num(one.prediction)} посадок</div>
              <div className="text-xs text-slate-500 dark:text-slate-400">источник: {SOURCE_LABEL[one.source]}</div>
            </div>
          )}
        </form>
      </div>
    </section>
  );
}
