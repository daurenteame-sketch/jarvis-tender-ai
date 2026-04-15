'use client';
import { createContext, useContext, useState, useCallback, ReactNode } from 'react';
import { CheckCircle, AlertCircle, Info, X } from 'lucide-react';
import { cn } from '@/lib/utils';

// ── Types ─────────────────────────────────────────────────────────────────────
type ToastType = 'success' | 'error' | 'info';

interface Toast {
  id: string;
  message: string;
  type: ToastType;
}

interface ToastContextType {
  toast: (message: string, type?: ToastType) => void;
}

// ── Context ───────────────────────────────────────────────────────────────────
const ToastContext = createContext<ToastContextType | null>(null);

// ── Provider ──────────────────────────────────────────────────────────────────
export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const toast = useCallback((message: string, type: ToastType = 'info') => {
    const id = Math.random().toString(36).slice(2);
    setToasts(prev => [...prev, { id, message, type }]);
    setTimeout(() => {
      setToasts(prev => prev.filter(t => t.id !== id));
    }, 4000);
  }, []);

  const remove = (id: string) => setToasts(prev => prev.filter(t => t.id !== id));

  return (
    <ToastContext.Provider value={{ toast }}>
      {children}
      {/* Portal */}
      <div className="fixed bottom-5 right-5 z-50 flex flex-col gap-2 max-w-sm w-full pointer-events-none">
        {toasts.map(t => (
          <div
            key={t.id}
            className={cn(
              'flex items-start gap-3 px-4 py-3 rounded-xl border shadow-xl pointer-events-auto',
              'animate-in slide-in-from-bottom-2 fade-in duration-200',
              t.type === 'success' && 'bg-gray-900 border-green-700/60 text-green-300',
              t.type === 'error'   && 'bg-gray-900 border-red-700/60 text-red-300',
              t.type === 'info'    && 'bg-gray-900 border-blue-700/60 text-blue-300',
            )}
          >
            {t.type === 'success' && <CheckCircle className="w-4 h-4 shrink-0 mt-0.5 text-green-400" />}
            {t.type === 'error'   && <AlertCircle  className="w-4 h-4 shrink-0 mt-0.5 text-red-400" />}
            {t.type === 'info'    && <Info          className="w-4 h-4 shrink-0 mt-0.5 text-blue-400" />}
            <span className="text-sm flex-1 text-gray-200">{t.message}</span>
            <button onClick={() => remove(t.id)} className="text-gray-500 hover:text-gray-300 transition-colors shrink-0">
              <X className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

// ── Hook ──────────────────────────────────────────────────────────────────────
export function useToast(): ToastContextType {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within <ToastProvider>');
  return ctx;
}
