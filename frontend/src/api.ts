import { useEffect, useState } from 'react';
import type { Filters } from './types';

export const API = import.meta.env.VITE_API ?? '/api';

export class ApiError extends Error {
  constructor(message: string, public status: number, public code: string) {
    super(message);
  }
}

type Params = Record<string, string | number | null | undefined>;

export function buildUrl(path: string, params: Params = {}): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== null && v !== undefined && v !== '') qs.set(k, String(v));
  }
  const q = qs.toString();
  return `${API}${path}${q ? `?${q}` : ''}`;
}

export async function getJson<T>(path: string, params: Params = {}, signal?: AbortSignal): Promise<T> {
  let res: Response;
  try {
    res = await fetch(buildUrl(path, params), { signal });
  } catch (e) {
    if ((e as Error).name === 'AbortError') throw e;
    throw new ApiError('Сервер недоступен. Проверьте подключение и попробуйте ещё раз.', 0, 'network');
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const err = body?.error;
    throw new ApiError(err?.message ?? `Ошибка сервера (${res.status})`, res.status, err?.code ?? 'http');
  }
  return body as T;
}

export function forecastParams(f: Filters): Params {
  return {
    horizon: f.horizon,
    date: f.date,
    route: f.route,
    stop_id: f.stopId,
    hour_from: f.hourFrom === 0 ? null : f.hourFrom,
    hour_to: f.hourTo === 23 ? null : f.hourTo,
    granularity: f.granularity,
  };
}

export interface Loadable<T> {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
}

/** Загрузка с отменой устаревших запросов. path = null — не загружать. */
export function useApi<T>(path: string | null, params: Params = {}, reloadKey?: unknown): Loadable<T> {
  const [state, setState] = useState<Loadable<T>>({ data: null, error: null, loading: path !== null });
  const key = path === null ? null : buildUrl(path, params);

  useEffect(() => {
    if (path === null) {
      setState({ data: null, error: null, loading: false });
      return;
    }
    const ctrl = new AbortController();
    setState((s) => ({ ...s, loading: true, error: null }));
    getJson<T>(path, params, ctrl.signal)
      .then((data) => setState({ data, error: null, loading: false }))
      .catch((e: Error) => {
        if (e.name === 'AbortError') return;
        const err = e instanceof ApiError ? e : new ApiError(e.message, 0, 'unknown');
        setState({ data: null, error: err, loading: false });
      });
    return () => ctrl.abort();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, reloadKey]);

  return state;
}
