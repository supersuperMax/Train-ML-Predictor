import type { ApiError } from '../api';

export function ErrorBox({ error, onRetry }: { error: ApiError; onRetry?: () => void }) {
  return (
    <div className="alert error" role="alert">
      <span>{error.message}</span>
      {onRetry && (
        <button className="link" onClick={onRetry}>
          Повторить
        </button>
      )}
    </div>
  );
}

export function Loading({ text = 'Загрузка…' }: { text?: string }) {
  return (
    <div className="loading" aria-live="polite">
      <span className="spinner" />
      {text}
    </div>
  );
}
