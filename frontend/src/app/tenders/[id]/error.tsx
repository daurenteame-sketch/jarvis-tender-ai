'use client';

// Route-level error boundary for /tenders/[id]/.
// Prevents a client render exception from collapsing into a blank page —
// shows the actual stack so we can fix without guessing.

import { useEffect } from 'react';

export default function LotDetailError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error('[lot detail error boundary]', error);
  }, [error]);

  return (
    <div className="p-6 max-w-screen-xl mx-auto">
      <div className="card border border-red-700/40 bg-red-500/5">
        <h1 className="text-xl font-bold text-red-300 mb-2">
          Страница лота упала
        </h1>
        <p className="text-sm text-gray-300 mb-3">
          Что-то в клиентском рендере выбросило исключение. Покажи текст
          ниже разработчику — по нему сразу видно, где лот ломается.
        </p>
        <pre className="text-xs text-red-200 bg-black/40 rounded p-3 overflow-auto max-h-72 whitespace-pre-wrap">
{error.message}
{error.digest ? `\n\ndigest: ${error.digest}` : ''}
{error.stack ? `\n\n${error.stack}` : ''}
        </pre>
        <div className="flex gap-2 mt-4">
          <button onClick={() => reset()} className="btn-primary text-sm">
            Перезагрузить лот
          </button>
          <button
            onClick={() => {
              if (typeof window !== 'undefined') window.location.href = '/tenders';
            }}
            className="btn-secondary text-sm"
          >
            К списку тендеров
          </button>
        </div>
      </div>
    </div>
  );
}
