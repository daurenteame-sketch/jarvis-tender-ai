'use client';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  CalendarDays, TrendingUp, Building2, Package,
  ChevronLeft, ChevronRight, AlertCircle,
} from 'lucide-react';
import { api } from '@/lib/api';
import { formatMoney } from '@/lib/utils';
import { cn } from '@/lib/utils';

// ── API ───────────────────────────────────────────────────────────────────────

async function fetchProcurementPlan(year: number) {
  const res = await api.get('/procurement/plan', { params: { year } });
  return res.data;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const CATEGORY_COLORS: Record<string, string> = {
  product:          'bg-blue-500/20 text-blue-300 border-blue-500/30',
  software_service: 'bg-purple-500/20 text-purple-300 border-purple-500/30',
  other:            'bg-gray-500/20 text-gray-300 border-gray-500/30',
  unknown:          'bg-gray-700/40 text-gray-400 border-gray-600/30',
};

const CATEGORY_BAR: Record<string, string> = {
  product:          'bg-blue-500',
  software_service: 'bg-purple-500',
  other:            'bg-gray-500',
  unknown:          'bg-gray-600',
};

function StatCard({ icon: Icon, label, value, sub, color = 'text-blue-400' }: {
  icon: React.ElementType; label: string; value: string; sub?: string; color?: string;
}) {
  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-5 flex items-start gap-4">
      <div className="w-10 h-10 rounded-xl bg-gray-800 flex items-center justify-center shrink-0">
        <Icon className={cn('w-5 h-5', color)} />
      </div>
      <div>
        <p className="text-sm text-gray-500">{label}</p>
        <p className="text-xl font-bold text-white mt-0.5">{value}</p>
        {sub && <p className="text-xs text-gray-500 mt-0.5">{sub}</p>}
      </div>
    </div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function ProcurementPlanPage() {
  const currentYear = new Date().getFullYear();
  const [year, setYear] = useState(currentYear);

  const { data, isLoading, isError } = useQuery({
    queryKey: ['procurement-plan', year],
    queryFn:  () => fetchProcurementPlan(year),
  });

  const maxBudget = data?.months
    ? Math.max(...data.months.map((m: any) => m.total_budget), 1)
    : 1;

  return (
    <div className="p-6 max-w-6xl mx-auto space-y-6">

      {/* Header */}
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <div className="w-10 h-10 bg-blue-500/10 rounded-xl flex items-center justify-center border border-blue-500/20">
            <CalendarDays className="w-5 h-5 text-blue-400" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-white">План закупок</h1>
            <p className="text-sm text-gray-500">Предстоящие тендеры по месяцам и категориям</p>
          </div>
        </div>

        {/* Year selector */}
        <div className="flex items-center gap-2">
          <button
            onClick={() => setYear(y => y - 1)}
            className="p-2 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-white transition-colors"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <div className="w-20 text-center font-bold text-white text-lg">{year}</div>
          <button
            onClick={() => setYear(y => y + 1)}
            disabled={year >= currentYear + 1}
            className="p-2 rounded-lg bg-gray-800 hover:bg-gray-700 text-gray-400 hover:text-white transition-colors disabled:opacity-40"
          >
            <ChevronRight className="w-4 h-4" />
          </button>

          {/* Available years pills */}
          {data?.available_years && data.available_years.length > 1 && (
            <div className="flex gap-1 ml-2">
              {data.available_years.slice(0, 4).map((y: number) => (
                <button
                  key={y}
                  onClick={() => setYear(y)}
                  className={cn(
                    'px-2.5 py-1 rounded-lg text-xs font-medium transition-colors',
                    year === y
                      ? 'bg-blue-600 text-white'
                      : 'bg-gray-800 text-gray-400 hover:bg-gray-700'
                  )}
                >
                  {y}
                </button>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="bg-gray-900 rounded-xl border border-gray-800 p-5">
              <div className="skeleton h-4 w-24 rounded mb-3" />
              <div className="skeleton h-7 w-32 rounded" />
            </div>
          ))}
        </div>
      )}

      {/* Error */}
      {isError && (
        <div className="flex items-center gap-3 p-4 rounded-xl bg-red-500/10 border border-red-500/20 text-red-400">
          <AlertCircle className="w-5 h-5 shrink-0" />
          <p className="text-sm">Ошибка загрузки данных. Попробуйте позже.</p>
        </div>
      )}

      {data && (
        <>
          {/* Summary stats */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            <StatCard
              icon={CalendarDays}
              label="Всего лотов"
              value={data.summary.total_lots.toLocaleString('ru')}
              sub={`за ${year} год`}
              color="text-blue-400"
            />
            <StatCard
              icon={TrendingUp}
              label="Общий бюджет"
              value={formatMoney(data.summary.total_budget)}
              sub="прогноз"
              color="text-green-400"
            />
            <StatCard
              icon={CalendarDays}
              label="Активных месяцев"
              value={`${data.summary.months_with_data} / 12`}
              color="text-yellow-400"
            />
            <StatCard
              icon={Building2}
              label="Топ заказчиков"
              value={`${data.top_customers.length}`}
              sub="в ближайшие 90 дней"
              color="text-purple-400"
            />
          </div>

          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">

            {/* Monthly chart */}
            <div className="lg:col-span-2 bg-gray-900 rounded-xl border border-gray-800 p-5 space-y-4">
              <h2 className="font-semibold text-white">Тендеры по месяцам</h2>

              {data.months.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-16 gap-3">
                  <CalendarDays className="w-10 h-10 text-gray-700" />
                  <p className="text-gray-500 text-sm">Нет данных за {year} год</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {data.months.map((m: any) => (
                    <div key={m.month} className={cn('space-y-1', m.is_past && 'opacity-50')}>
                      <div className="flex items-center justify-between text-sm">
                        <span className={cn('font-medium', m.is_past ? 'text-gray-500' : 'text-gray-300')}>
                          {m.month_label}
                          {m.is_past && <span className="text-xs text-gray-600 ml-1">(прошёл)</span>}
                        </span>
                        <div className="flex items-center gap-3">
                          <span className="text-gray-500 text-xs">{m.total_lots} лот.</span>
                          <span className="font-semibold text-white">{formatMoney(m.total_budget)}</span>
                        </div>
                      </div>

                      {/* Stacked bar */}
                      <div className="h-6 rounded-lg bg-gray-800 overflow-hidden flex">
                        {m.categories.map((cat: any) => {
                          const pct = (cat.total_budget / maxBudget) * 100;
                          return (
                            <div
                              key={cat.category}
                              className={cn('h-full transition-all', CATEGORY_BAR[cat.category] || 'bg-gray-500')}
                              style={{ width: `${pct}%` }}
                              title={`${cat.category_label}: ${formatMoney(cat.total_budget)}`}
                            />
                          );
                        })}
                      </div>

                      {/* Category pills */}
                      <div className="flex flex-wrap gap-1">
                        {m.categories.map((cat: any) => (
                          <span
                            key={cat.category}
                            className={cn('inline-flex items-center gap-1 text-xs px-2 py-0.5 rounded-full border', CATEGORY_COLORS[cat.category])}
                          >
                            {cat.category_label} · {cat.lot_count}
                          </span>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>

            {/* Right column */}
            <div className="space-y-4">

              {/* Category breakdown */}
              <div className="bg-gray-900 rounded-xl border border-gray-800 p-5 space-y-3">
                <h2 className="font-semibold text-white flex items-center gap-2">
                  <Package className="w-4 h-4 text-gray-500" />
                  Категории
                </h2>
                {data.categories.length === 0 ? (
                  <p className="text-gray-500 text-sm">Нет данных</p>
                ) : (
                  <div className="space-y-2">
                    {data.categories.map((cat: any) => {
                      const total = data.summary.total_budget || 1;
                      const pct = Math.round((cat.total_budget / total) * 100);
                      return (
                        <div key={cat.category} className="space-y-1">
                          <div className="flex items-center justify-between text-sm">
                            <span className="text-gray-300">{cat.category_label}</span>
                            <span className="text-gray-500 text-xs">{pct}%</span>
                          </div>
                          <div className="h-1.5 rounded-full bg-gray-800">
                            <div
                              className={cn('h-full rounded-full', CATEGORY_BAR[cat.category] || 'bg-gray-500')}
                              style={{ width: `${pct}%` }}
                            />
                          </div>
                          <p className="text-xs text-gray-500">{formatMoney(cat.total_budget)} · {cat.lot_count} лот.</p>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>

              {/* Top upcoming customers */}
              <div className="bg-gray-900 rounded-xl border border-gray-800 p-5 space-y-3">
                <h2 className="font-semibold text-white flex items-center gap-2">
                  <Building2 className="w-4 h-4 text-gray-500" />
                  Топ заказчиков (90 дн.)
                </h2>
                {data.top_customers.length === 0 ? (
                  <p className="text-gray-500 text-sm">Нет данных</p>
                ) : (
                  <div className="space-y-2.5">
                    {data.top_customers.slice(0, 6).map((c: any, i: number) => (
                      <div key={i} className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="text-sm text-gray-200 truncate">{c.customer_name}</p>
                          {c.customer_region && (
                            <p className="text-xs text-gray-500 truncate">{c.customer_region}</p>
                          )}
                        </div>
                        <div className="text-right shrink-0">
                          <p className="text-sm font-semibold text-white">{formatMoney(c.total_budget)}</p>
                          <p className="text-xs text-gray-500">{c.lot_count} лот.</p>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
