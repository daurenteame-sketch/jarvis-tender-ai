'use client';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
  LayoutDashboard,
  FileSearch,
  BarChart3,
  Truck,
  History,
  Settings,
  Zap,
  LogOut,
  User,
  ChevronDown,
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { useAuth } from '@/contexts/AuthContext';
import { useState } from 'react';

const NAV_ITEMS = [
  { href: '/dashboard', label: 'Дашборд', icon: LayoutDashboard },
  { href: '/tenders', label: 'Тендеры', icon: FileSearch },
  { href: '/analytics', label: 'Аналитика', icon: BarChart3 },
  { href: '/suppliers', label: 'Поставщики', icon: Truck },
  { href: '/history', label: 'История', icon: History },
  { href: '/settings', label: 'Настройки', icon: Settings },
];

const PLAN_BADGE: Record<string, { label: string; color: string }> = {
  free:       { label: 'Free',       color: 'bg-gray-700 text-gray-300' },
  trial:      { label: 'Trial',      color: 'bg-yellow-700/60 text-yellow-300' },
  pro:        { label: 'Pro',        color: 'bg-blue-700/60 text-blue-300' },
  enterprise: { label: 'Enterprise', color: 'bg-purple-700/60 text-purple-300' },
  basic:      { label: 'Basic',      color: 'bg-gray-700 text-gray-300' },
};

export function Sidebar() {
  const pathname = usePathname();
  const { user, logout } = useAuth();
  const [showUserMenu, setShowUserMenu] = useState(false);

  const planKey = 'basic';
  const badge = PLAN_BADGE[planKey] ?? PLAN_BADGE.free;

  const initials = user?.email
    ? user.email.slice(0, 2).toUpperCase()
    : '??';

  return (
    <aside className="w-64 bg-gray-900 text-white flex flex-col min-h-screen border-r border-gray-800">
      {/* Logo */}
      <div className="p-6 border-b border-gray-800">
        <div className="flex items-center gap-2">
          <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center">
            <Zap className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="font-bold text-lg leading-tight">Tender AI KZ</h1>
            <p className="text-gray-400 text-xs">Тендерная аналитика</p>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 p-4 space-y-1">
        {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
          const isActive = pathname === href || (href !== '/dashboard' && pathname.startsWith(href));
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                'flex items-center gap-3 px-4 py-2.5 rounded-lg text-sm font-medium transition-colors',
                isActive
                  ? 'bg-blue-600 text-white'
                  : 'text-gray-400 hover:bg-gray-800 hover:text-white'
              )}
            >
              <Icon className="w-4 h-4" />
              {label}
            </Link>
          );
        })}
      </nav>

      {/* User section */}
      <div className="p-4 border-t border-gray-800">
        <button
          onClick={() => setShowUserMenu(!showUserMenu)}
          className="w-full flex items-center gap-3 px-3 py-2 rounded-lg hover:bg-gray-800 transition-colors"
        >
          {/* Avatar */}
          <div className="w-8 h-8 rounded-full bg-blue-700 flex items-center justify-center text-xs font-bold shrink-0">
            {initials}
          </div>

          <div className="flex-1 text-left min-w-0">
            <p className="text-sm font-medium text-white truncate">
              {user?.company_name || user?.email || '—'}
            </p>
            <p className="text-xs text-gray-400 truncate">{user?.email}</p>
          </div>

          <ChevronDown
            className={cn(
              'w-4 h-4 text-gray-500 transition-transform shrink-0',
              showUserMenu && 'rotate-180'
            )}
          />
        </button>

        {/* Dropdown */}
        {showUserMenu && (
          <div className="mt-2 bg-gray-800 border border-gray-700 rounded-lg overflow-hidden">
            {/* Plan badge */}
            <div className="px-4 py-2 border-b border-gray-700 flex items-center justify-between">
              <span className="text-xs text-gray-400">Тариф</span>
              <span className={cn('text-xs font-semibold px-2 py-0.5 rounded-full', badge.color)}>
                {badge.label}
              </span>
            </div>

            <Link
              href="/settings"
              onClick={() => setShowUserMenu(false)}
              className="flex items-center gap-2 px-4 py-2.5 text-sm text-gray-300 hover:bg-gray-700 hover:text-white transition-colors"
            >
              <User className="w-4 h-4" />
              Профиль и настройки
            </Link>

            <button
              onClick={() => { setShowUserMenu(false); logout(); }}
              className="w-full flex items-center gap-2 px-4 py-2.5 text-sm text-red-400 hover:bg-gray-700 hover:text-red-300 transition-colors"
            >
              <LogOut className="w-4 h-4" />
              Выйти
            </button>
          </div>
        )}

        <p className="text-gray-600 text-xs text-center mt-3">v1.0.0 · Tender AI KZ</p>
      </div>
    </aside>
  );
}
