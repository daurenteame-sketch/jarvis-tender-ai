'use client';
import { usePathname } from 'next/navigation';
import { useAuth } from '@/contexts/AuthContext';
import { Sidebar } from '@/components/dashboard/Sidebar';
import { Loader2, ServerCrash, RefreshCw } from 'lucide-react';

const AUTH_PATHS = ['/auth/login', '/auth/register'];
const PUBLIC_PATHS = ['/', '/auth/login', '/auth/register'];

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const { isLoading, backendError } = useAuth();

  const isAuthPage = AUTH_PATHS.includes(pathname);
  const isPublicPage = PUBLIC_PATHS.includes(pathname);

  // Public pages (landing, auth): render immediately — no auth check needed
  if (isPublicPage) {
    return <>{children}</>;
  }

  // Backend unreachable — show a clear error instead of blank screen
  if (backendError) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center px-4">
        <div className="text-center max-w-sm">
          <ServerCrash className="w-12 h-12 text-red-500 mx-auto mb-4" />
          <h2 className="text-white text-lg font-bold mb-2">Сервер недоступен</h2>
          <p className="text-gray-400 text-sm mb-6">
            Не удается подключиться к backend.
            Убедитесь что контейнеры запущены:
          </p>
          <code className="block bg-gray-900 text-green-400 text-xs rounded-lg px-4 py-3 mb-6 text-left">
            docker compose -f docker-compose.yml \<br />
            &nbsp;&nbsp;-f docker-compose.dev.yml up -d
          </code>
          <button
            onClick={() => window.location.reload()}
            className="flex items-center gap-2 mx-auto bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium px-4 py-2 rounded-lg transition-colors"
          >
            <RefreshCw className="w-4 h-4" />
            Повторить
          </button>
        </div>
      </div>
    );
  }

  // While validating token on first mount, show a spinner
  if (isLoading) {
    return (
      <div className="min-h-screen bg-gray-950 flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="w-8 h-8 text-blue-500 animate-spin" />
          <p className="text-gray-400 text-sm">Загрузка...</p>
        </div>
      </div>
    );
  }

  // Dashboard pages: sidebar + main content
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="flex-1 overflow-y-auto">
        {children}
      </main>
    </div>
  );
}
