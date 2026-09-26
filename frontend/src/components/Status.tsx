import type { ApiError } from '../api';
import { alertError } from '../ui';

export function ErrorBox({ error, onRetry }: { error: ApiError; onRetry?: () => void }) {
  return (
    <div className={alertError} role="alert">
      <span>{error.message}</span>
      {onRetry && (
        <button className="cursor-pointer font-semibold text-red-800 hover:text-red-600 dark:text-red-200 dark:hover:text-red-100" onClick={onRetry}>
          Повторить
        </button>
      )}
    </div>
  );
}

export function Loading({ text = 'Загрузка…' }: { text?: string }) {
  return (
    <div className="flex items-center gap-3 py-6 text-sm text-slate-500 dark:text-slate-400" aria-live="polite">
      <span className="size-5 animate-spin rounded-full border-2 border-slate-200 border-t-blue-600 dark:border-slate-700 dark:border-t-blue-500" />
      {text}
    </div>
  );
}
