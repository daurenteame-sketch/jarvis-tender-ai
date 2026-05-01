'use client';

// Next.js App Router error boundary for /dashboard.
// Catches client-side render exceptions so the user sees the actual
// stack trace instead of a blank screen / "Application error" toast.

import { useEffect } from 'react';

export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Surface to console for DevTools debugging
    // eslint-disable-next-line no-console
    console.error('[dashboard error boundary]', error);
  }, [error]);

  return (
    <div className="p-6 max-w-screen-xl mx-auto">
      <div className="card border border-red-700/40 bg-red-500/5">
        <h1 className="text-xl font-bold text-red-300 mb-2">
          Дашборд упал — что-то в коде
        </h1>
        <p className="text-sm text-gray-300 mb-3">
          Это страница ошибки, не пустой экран. Покажи текст ниже разработчику —
          по нему сразу видно где упало.
        </p>
        <pre className="text-xs text-red-200 bg-black/40 rounded p-3 overflow-auto max-h-72 whitespace-pre-wrap">
{error.message}
{error.digest ? `\n\ndigest: ${error.digest}` : ''}
{error.stack ? `\n\n${error.stack}` : ''}
        </pre>
        <div className="flex gap-2 mt-4">
          <button onClick={() => reset()} className="btn-primary text-sm">
            Перезагрузить дашборд
          </button>
          <button
            onClick={() => {
              if (typeof window !== 'undefined') window.location.href = '/tenders';
            }}
            className="btn-secondary text-sm"
          >
            Уйти в тендеры
          </button>
        </div>
      </div>
    </div>
  );
}
