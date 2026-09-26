import type { ApiError } from '../api';

export function ErrorBox({ error, onRetry }: { error: ApiError; onRetry?: () => void }) {
  return (
    <div className="alert alert-error" role="alert">
      <span>{error.message}</span>
      {onRetry && (
        <button className="font-semibold text-accent" onClick={onRetry}>
          Повторить
        </button>
      )}
    </div>
  );
}

export function Loading({ text = 'Загрузка…' }: { text?: string }) {
  return (
    <div className="flex items-center gap-2.5 py-6 text-muted" aria-live="polite">
      <span className="size-[18px] animate-spin rounded-full border-2 border-line border-t-accent" />
      {text}
    </div>
  );
}
