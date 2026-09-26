export type Horizon = 'day' | 'month' | 'year';
export type Granularity = 'hour' | 'day' | 'week' | 'month';
export type Source = 'model' | 'baseline' | 'mixed' | 'none';

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
  value: number;
  source: Source;
  date?: string;
  hour?: number;
  days?: number;
}

export interface ForecastResponse {
  query: ForecastQuery;
  unit: string;
  total: number;
  points: Point[];
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
  stops: { stop_id: number; value: number }[];
  max: number;
  routes: { route: number; value: number }[];
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
