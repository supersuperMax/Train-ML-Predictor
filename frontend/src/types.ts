export type Horizon = 'day' | 'month' | 'year';
export type Granularity = 'hour' | 'day' | 'week' | 'month';
export type Source = 'model' | 'baseline' | 'mixed' | 'none' | 'fact';

export interface Meta {
  ready: boolean;
  version?: string;
  created_at?: string;
  available?: { from: string; to: string };
  sources?: Record<string, [string, string]>;
  model?: string;
  model_mode?: string;
  history_range?: [string, string];
  routes?: number[];
  routes_with_stops?: number[];
  factors?: Record<string, string>;
  weather?: string;
  stop_forecast_method?: string;
  last_run?: { started_at: string; finished_at: string; status: string; error?: string; version?: string } | null;
  has_baseline?: boolean;
  limits?: { csv_bytes: number; xlsx_bytes: number };
}

/** Набор данных из залитого файла: сырые валидации (факт + прогноз модели по их ключам) или ключи route/date/hour. */
export interface Dataset {
  id: string;
  name: string;
  kind?: 'validations' | 'keys';
  rows: number;
  ok: number;
  errors: number;
  /** только для сырых валидаций */
  boardings?: number;
  skipped?: number;
  keys?: number;
  warning?: string;
  /** пересечение периода факта с периодом прогноза; null — не пересекаются */
  overlap?: [string, string] | null;
  note?: string;
  trimmed_days?: string[];
  range: [string, string] | null;
  routes: number[];
  source: string;
  result_url: string;
  created_at: string;
}


export interface RouteInfo {
  route: number;
  name: string | null;
  has_stops: boolean;
}

export interface Stop {
  stop_id: number;
  name: string;
  lat: number;
  lon: number;
  routes: number[];
}

export interface RouteLine {
  route: number;
  direction: number;
  coordinates: [number, number][];
}

export interface StopsResponse {
  stops: Stop[];
  lines: RouteLine[];
}

export interface ForecastQuery {
  horizon: Horizon | null;
  granularity: Granularity;
  from: string;
  to: string;
  hour_from: number;
  hour_to: number;
  route: number | null;
  stop_id: number | null;
  stop_name: string | null;
  truncated: boolean;
  available: { from: string; to: string };
  version: string;
}

export interface Point {
  t: string;
  /** null — прогноза на эту дату нет (например, период факта из файла до начала прогноза) */
  value: number | null;
  source: Source;
  date?: string;
  hour?: number;
  days?: number;
  /** факт посадок из залитого файла валидаций; null — в файле нет данных */
  fact?: number | null;
}

export interface ForecastResponse {
  query: ForecastQuery;
  unit: string;
  total: number;
  points: Point[];
  fact_total?: number;
  /** прогноз против факта только в часах, где есть и то и другое */
  compare?: { from: string; to: string; forecast: number; fact: number; error_pct: number | null } | null;
}

export interface DaytypeStat {
  days: number;
  total: number;
  per_day: number;
}

export interface Summary {
  query: ForecastQuery;
  total: number;
  days: number;
  per_day: number;
  per_hour: number;
  peak: { date: string; hour: number; value: number } | null;
  peak_day: { date: string; value: number } | null;
  peak_hour_of_day: { hour: number; avg: number } | null;
  by_daytype: Partial<Record<'weekday' | 'sat' | 'sun' | 'holiday', DaytypeStat>>;
  source: Source;
}

export interface MapState {
  date: string;
  hour: number | null;
  route: number | null;
  /** load — загруженность 0…1: доля от максимума посадок на остановке своего маршрута за эти сутки */
  stops: { stop_id: number; value: number; load: number }[];
  max: number;
  /** day_max — максимум посадок на остановке маршрута за сутки (граница красного цвета) */
  routes: { route: number; value: number; day_max: number }[];
  source: Source;
}

export interface Filters {
  horizon: Horizon;
  date: string;
  route: number | null;
  stopId: number | null;
  hourFrom: number;
  hourTo: number;
  granularity: Granularity | null;
}
