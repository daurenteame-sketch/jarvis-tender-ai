'use client';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  History, Search, Building2, TrendingUp, Package,
  ChevronLeft, ChevronRight, AlertCircle, ExternalLink,
  Filter, X,
} from 'lucide-react';
import { api } from '@/lib/api';
import { formatMoney, formatDate } from '@/lib/utils';
import { cn } from '@/lib/utils';

// ── API ───────────────────────────────────────────────────────────────────────

async function fetchHistory(params: Record<string, any>) {
  const clean = Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== undefined && v !== '' && v !== null)
  );
  const res = await api.get('/procurement/history', { params: clean });
  return res.data;
}

async function fetchHistoryStats() {
  const res = await api.get('/procurement/history/stats');
  return res.data;
}

// ── Types ─────────────────────────────────────────────────────────────────────

interface HistoryItem {
  id: string;
  tender_id: string;
  platform: string;
  platform_key: string;
  tender_external_id: string;
  lot_external_id: string;
  title: string;
  category: string;
  category_label: string;
  budget: number | null;
  currency: string;
  customer_name: string | null;
  customer_region: string | null;
  procurement_method: string;
  deadline_at: string | null;
  published_at: string | null;
  status: string;
  is_profitable: boolean | null;
  profit_margin_percent: number | null;
  winner_name: string | null;
  winner_bin: string | null;
  contract_sum: number | null;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const PLATFORM_BADGE: Record<string, string> = {
  goszakup: 'badge-blue',
  zakupsk:  'badge-yellow',
};

const STATUS_MAP: Record<string, { label: string; cls: string }> = {
  closed:    { label: 'Завершён',  cls: 'badge-green' },
  finished:  { label: 'Завершён',  cls: 'badge-green' },
  completed: { label: 'Выполнен', cls: 'badge-green' },
  cancelled: { label: 'Отменён',  cls: 'badge-red' },
  published: { label: 'Истёк',    cls: 'badge-gray' },
};

function StatCard({ icon: Icon, label, value, sub, color = 'text-blue-400' }: {
  icon: React.ElementType; label: string; value: string; sub?: string; color?: string;
}) {
  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-4 flex items-start gap-3">
      <div className="w-9 h-9 rounded-xl bg-gray-800 flex items-center justify-center shrink-0">
        <Icon className={cn('w-4 h-4', color)} />
      </div>
      <div>
        <p className="text-xs text-gray-500">{label}</p>
        <p className="text-lg font-bold text-white leading-tight">{value}</p>
        {sub && <p className="text-xs text-gray-500 mt-0.5">{sub}</p>}
      </div>
    </div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────

export default function PurchaseHistoryPage() {
  const [search, setSearch]     = useState('');
  const [platform, setPlatform] = useState('');
  const [category, setCategory] = useState('');
  const [yearFilter, setYear]   = useState<number | ''>('');
  const [page, setPage]         = useState(1);

  const { data, isLoading, isError } = useQuery({
    queryKey: ['purchase-history', search, platform, category, yearFilter, page],
    queryFn:  () => fetchHistory({ search, platform, category, year: yearFilter || undefined, page, per_page: 25 }),
    placeholderData: (prev) => prev,
  });

  const { data: stats } = useQuery({
    queryKey: ['history-stats'],
    queryFn:  fetchHistoryStats,
  });

  const clearFilters = () => {
    setSearch(''); setPlatform(''); setCategory(''); setYear(''); setPage(1);
  };
  const hasFilters = search || platform || category || yearFilter;

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">

      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 bg-purple-500/10 rounded-xl flex items-center justify-center border border-purple-500/20">
          <History className="w-5 h-5 text-purple-400" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-white">История закупок</h1>
          <p className="text-sm text-gray-500">Завершённые тендеры за последние 3 года</p>
        </div>
      </div>

      {/* Stats */}
      {stats && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <StatCard
            icon={History}
            label="Завершённых лотов"
            value={stats.total_lots.toLocaleString('ru')}
            sub="за 3 года"
            color="text-purple-400"
          />
          <StatCard
            icon={TrendingUp}
            label="Общий объём"
            value={formatMoney(stats.total_budget)}
            color="text-green-400"
          />
          <StatCard
            icon={Building2}
            label="Уникальных заказчиков"
            value={stats.unique_customers.toLocaleString('ru')}
            color="text-blue-400"
          />
          <StatCard
            icon={Package}
            label="Топ категория"
            value={stats.top_categories?.[0]?.category_label || '—'}
            sub={stats.top_categories?.[0] ? formatMoney(stats.top_categories[0].total_budget) : ''}
            color="text-yellow-400"
          />
        </div>
      )}

      {/* Top customers (from stats) */}
      {stats?.top_customers?.length > 0 && (
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
          <h2 className="font-semibold text-white mb-3 flex items-center gap-2">
            <Building2 className="w-4 h-4 text-gray-500" />
            Крупнейшие заказчики за 3 года
          </h2>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800">
                  <th className="text-left px-3 py-2 text-gray-500 font-medium">#</th>
                  <th className="text-left px-3 py-2 text-gray-500 font-medium">Заказчик</th>
                  <th className="text-left px-3 py-2 text-gray-500 font-medium">Регион</th>
                  <th className="text-right px-3 py-2 text-gray-500 font-medium">Лотов</th>
                  <th className="text-right px-3 py-2 text-gray-500 font-medium">Объём</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/50">
                {stats.top_customers.slice(0, 8).map((c: any, i: number) => (
                  <tr key={i} className="hover:bg-gray-800/30 transition-colors">
                    <td className="px-3 py-2 text-gray-600 font-mono text-xs">{i + 1}</td>
                    <td className="px-3 py-2 text-gray-200">{c.customer_name}</td>
                    <td className="px-3 py-2 text-gray-500 text-xs">{c.customer_region || '—'}</td>
                    <td className="px-3 py-2 text-right text-gray-300">{c.lot_count}</td>
                    <td className="px-3 py-2 text-right font-semibold text-white">{formatMoney(c.total_budget)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        {/* Search */}
        <div className="relative flex-1 min-w-[200px] max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500 pointer-events-none" />
          <input
            value={search}
            onChange={e => { setSearch(e.target.value); setPage(1); }}
            placeholder="Поиск по названию, заказчику..."
            className="input w-full pl-9"
          />
        </div>

        {/* Platform */}
        <select
          value={platform}
          onChange={e => { setPlatform(e.target.value); setPage(1); }}
          className="input"
        >
          <option value="">Все площадки</option>
          <option value="goszakup">GosZakup</option>
          <option value="zakupsk">Zakup SK</option>
        </select>

        {/* Category */}
        <select
          value={category}
          onChange={e => { setCategory(e.target.value); setPage(1); }}
          className="input"
        >
          <option value="">Все категории</option>
          <option value="product">Товары / Оборудование</option>
          <option value="software_service">IT / ПО</option>
          <option value="other">Прочие услуги</option>
        </select>

        {/* Year */}
        <select
          value={yearFilter}
          onChange={e => { setYear(e.target.value ? Number(e.target.value) : ''); setPage(1); }}
          className="input"
        >
          <option value="">Все годы</option>
          {data?.year_counts?.map((yc: any) => (
            <option key={yc.year} value={yc.year}>{yc.year} ({yc.count})</option>
          ))}
        </select>

        {hasFilters && (
          <button
            onClick={clearFilters}
            className="flex items-center gap-1.5 text-sm text-gray-400 hover:text-white transition-colors px-3 py-2 rounded-lg hover:bg-gray-800"
          >
            <X className="w-4 h-4" />
            Сбросить
          </button>
        )}
      </div>

      {/* Table */}
      <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-gray-800">
              <tr>
                {['Дата', 'Площадка', 'Лот', 'Заказчик', 'Категория', 'Бюджет', 'Победитель', 'Статус'].map(h => (
                  <th key={h} className="table-header whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/60">
              {isLoading ? (
                [...Array(8)].map((_, i) => (
                  <tr key={i}>
                    {[80, 80, 200, 150, 100, 100, 120, 80].map((w, j) => (
                      <td key={j} className="px-4 py-3">
                        <div className="skeleton h-4 rounded" style={{ width: w }} />
                      </td>
                    ))}
                  </tr>
                ))
              ) : isError ? (
                <tr>
                  <td colSpan={8} className="px-6 py-12 text-center">
                    <div className="flex flex-col items-center gap-2">
                      <AlertCircle className="w-8 h-8 text-red-500/50" />
                      <p className="text-gray-500 text-sm">Ошибка загрузки данных</p>
                    </div>
                  </td>
                </tr>
              ) : !data?.items?.length ? (
                <tr>
                  <td colSpan={8} className="px-6 py-16 text-center">
                    <div className="flex flex-col items-center gap-3">
                      <History className="w-8 h-8 text-gray-700" />
                      <p className="text-gray-500 text-sm">
                        {hasFilters ? 'По вашим фильтрам ничего не найдено' : 'История закупок пуста'}
                      </p>
                      {hasFilters && (
                        <button onClick={clearFilters} className="text-blue-400 hover:text-blue-300 text-sm">
                          Сбросить фильтры
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ) : (
                data.items.map((item: HistoryItem) => {
                  const status = STATUS_MAP[item.status] || { label: item.status, cls: 'badge-gray' };
                  return (
                    <tr key={item.id} className="hover:bg-gray-800/40 transition-colors">
                      {/* Date */}
                      <td className="table-cell whitespace-nowrap text-gray-400 text-xs">
                        {item.deadline_at ? formatDate(item.deadline_at) : '—'}
                      </td>

                      {/* Platform */}
                      <td className="table-cell">
                        <span className={cn('badge text-xs', PLATFORM_BADGE[item.platform_key] || 'badge-gray')}>
                          {item.platform}
                        </span>
                      </td>

                      {/* Title */}
                      <td className="table-cell max-w-[240px]">
                        <p className="text-gray-200 truncate" title={item.title}>{item.title}</p>
                        <p className="text-gray-600 text-xs font-mono mt-0.5">{item.lot_external_id}</p>
                      </td>

                      {/* Customer */}
                      <td className="table-cell max-w-[180px]">
                        <p className="text-gray-300 truncate text-xs" title={item.customer_name || '—'}>
                          {item.customer_name || '—'}
                        </p>
                        {item.customer_region && (
                          <p className="text-gray-600 text-xs truncate">{item.customer_region}</p>
                        )}
                      </td>

                      {/* Category */}
                      <td className="table-cell">
                        <span className="text-xs text-gray-400">{item.category_label}</span>
                      </td>

                      {/* Budget */}
                      <td className="table-cell whitespace-nowrap">
                        {item.budget ? (
                          <span className="font-semibold text-white">{formatMoney(item.budget)}</span>
                        ) : '—'}
                      </td>

                      {/* Winner */}
                      <td className="table-cell max-w-[160px]">
                        {item.winner_name ? (
                          <div>
                            <p className="text-green-400 text-xs truncate font-medium">{item.winner_name}</p>
                            {item.contract_sum && (
                              <p className="text-gray-500 text-xs">{formatMoney(item.contract_sum)}</p>
                            )}
                          </div>
                        ) : (
                          <span className="text-gray-600 text-xs">—</span>
                        )}
                      </td>

                      {/* Status */}
                      <td className="table-cell">
                        <span className={cn('badge text-xs', status.cls)}>{status.label}</span>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        {data && data.total > 0 && (
          <div className="flex items-center justify-between px-5 py-3 border-t border-gray-800">
            <p className="text-sm text-gray-500">
              Показано {Math.min((page - 1) * 25 + 1, data.total)}–{Math.min(page * 25, data.total)} из {data.total.toLocaleString('ru')}
            </p>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page === 1}
                className="p-1.5 rounded-lg hover:bg-gray-800 text-gray-400 hover:text-white disabled:opacity-40 transition-colors"
              >
                <ChevronLeft className="w-4 h-4" />
              </button>
              <span className="text-sm text-gray-400">
                {page} / {data.pages}
              </span>
              <button
                onClick={() => setPage(p => Math.min(data.pages, p + 1))}
                disabled={page >= data.pages}
                className="p-1.5 rounded-lg hover:bg-gray-800 text-gray-400 hover:text-white disabled:opacity-40 transition-colors"
              >
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
