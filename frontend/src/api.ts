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

export function forecastParams(f: Filters, source = 'model'): Params {
  return {
    source: source === 'model' ? null : source,
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

export interface UploadResult {
  blob: Blob;
  filename: string;
  headers: (name: string) => string | null;
}

/** Проверка файла до отправки: тип и размер по лимитам сервера (/api/meta → limits). null — можно отправлять. */
export function checkFile(file: File, limits?: { csv_bytes: number; xlsx_bytes: number }): string | null {
  const name = file.name.toLowerCase();
  const isXlsx = name.endsWith('.xlsx') || name.endsWith('.xls');
  if (!isXlsx && !name.endsWith('.csv') && !name.endsWith('.txt')) return 'Нужен файл CSV или XLSX.';
  if (file.size === 0) return 'Файл пустой.';
  const limit = isXlsx ? limits?.xlsx_bytes : limits?.csv_bytes;
  if (limit && file.size > limit) {
    const gb = (n: number) => (n >= 1024 ** 3 ? `${(n / 1024 ** 3).toFixed(2).replace('.', ',')} ГБ` : `${Math.round(n / 1024 ** 2)} МБ`);
    return `Файл ${gb(file.size)} больше допустимого для ${isXlsx ? 'XLSX' : 'CSV'}: ${gb(limit)}.` + (isXlsx ? ' Сохраните таблицу как CSV (UTF-8).' : '');
  }
  return null;
}

/**
 * Отправка файла сырым телом (без multipart — сервер стримит его сразу в обработку) с прогрессом отправки.
 * У fetch нет прогресса загрузки, поэтому XMLHttpRequest. Ответ — файл; ошибки API — ApiError с текстом сервера.
 */
export function uploadFile(
  path: string,
  file: File,
  params: Params,
  onProgress: (sent: number, total: number) => void,
  signal?: AbortSignal,
  expect: 'blob' | 'json' = 'blob',
): Promise<UploadResult & { json?: unknown }> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', buildUrl(path, { ...params, filename: file.name }));
    xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream');
    xhr.responseType = expect === 'json' ? 'json' : 'blob';
    xhr.upload.onprogress = (e) => onProgress(e.loaded, e.lengthComputable ? e.total : file.size);
    xhr.onerror = () => reject(new ApiError('Сервер недоступен или соединение прервано. Попробуйте ещё раз.', 0, 'network'));
    xhr.onabort = () => reject(new ApiError('Загрузка отменена.', 0, 'aborted'));
    xhr.onload = async () => {
      if (xhr.status >= 200 && xhr.status < 300 && expect === 'json') {
        resolve({ blob: new Blob(), filename: '', headers: (n) => xhr.getResponseHeader(n), json: xhr.response });
        return;
      }
      if (expect === 'json' && xhr.status >= 300) {
        const err = (xhr.response as { error?: { message?: string; code?: string } } | null)?.error;
        reject(new ApiError(err?.message ?? `Ошибка сервера (${xhr.status})`, xhr.status, err?.code ?? 'http'));
        return;
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        const cd = xhr.getResponseHeader('content-disposition') ?? '';
        const m = /filename\*=UTF-8''([^;]+)/i.exec(cd);
        resolve({ blob: xhr.response as Blob, filename: m ? decodeURIComponent(m[1]) : 'prediction.csv', headers: (n) => xhr.getResponseHeader(n) });
        return;
      }
      const body = await (xhr.response as Blob | null)?.text().then((t) => JSON.parse(t)).catch(() => null);
      const err = body?.error;
      reject(new ApiError(err?.message ?? `Ошибка сервера (${xhr.status})`, xhr.status, err?.code ?? 'http'));
    };
    signal?.addEventListener('abort', () => xhr.abort());
    xhr.send(file);
  });
}

export function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}
