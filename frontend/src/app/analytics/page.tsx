'use client';
import { useQuery } from '@tanstack/react-query';
import {
  fetchTrends, fetchTopCategories, fetchScanHistory,
  fetchMarginDistribution, fetchPlatformBreakdown,
  fetchCategoryProfitability, fetchConfidenceBreakdown,
} from '@/lib/api';
import {
  XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, BarChart, Bar, LineChart, Line, Cell,
} from 'recharts';
import { formatDate, formatMoney, platformLabel, categoryLabel } from '@/lib/utils';

const MARGIN_COLORS = ['#10b981', '#3b82f6', '#8b5cf6', '#f59e0b', '#ef4444'];

const darkTooltip = {
  contentStyle: { background: '#111827', border: '1px solid #374151', borderRadius: 8, fontSize: 12 },
  labelStyle: { color: '#9ca3af' },
  itemStyle: { color: '#e5e7eb' },
};

export default function AnalyticsPage() {
  const { data: trends }         = useQuery({ queryKey: ['trends', 30],               queryFn: () => fetchTrends(30) });
  const { data: categories }     = useQuery({ queryKey: ['top-categories'],            queryFn: fetchTopCategories });
  const { data: scanHistory }    = useQuery({ queryKey: ['scan-history'],              queryFn: () => fetchScanHistory(20) });
  const { data: marginDist }     = useQuery({ queryKey: ['margin-distribution'],       queryFn: fetchMarginDistribution });
  const { data: platforms }      = useQuery({ queryKey: ['platform-breakdown'],        queryFn: fetchPlatformBreakdown });
  const { data: catProfit }      = useQuery({ queryKey: ['category-profitability'],    queryFn: fetchCategoryProfitability });
  const { data: confBreakdown }  = useQuery({ queryKey: ['confidence-breakdown'],      queryFn: fetchConfidenceBreakdown });

  const statusMap: Record<string, { label: string; cls: string }> = {
    completed: { label: 'Выполнено', cls: 'badge-green' },
    failed:    { label: 'Ошибка',    cls: 'badge-red' },
    running:   { label: 'Идёт...',   cls: 'badge-yellow' },
  };

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white">Аналитика</h1>
        <p className="text-gray-500 text-sm mt-1">Статистика по тендерам и сканированиям</p>
      </div>

      {/* Platform cards */}
      {platforms && platforms.length > 0 && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {platforms.map((p: any) => (
            <div key={p.platform} className="bg-gray-900 rounded-xl border border-gray-800 p-5">
              <div className="flex items-center justify-between mb-4">
                <h3 className="font-semibold text-white">{platformLabel(p.platform)}</h3>
                <span className={`badge text-xs ${p.platform === 'goszakup' ? 'badge-blue' : 'badge-yellow'}`}>
                  {p.platform}
                </span>
              </div>
              <div className="grid grid-cols-3 gap-3 text-center">
                <div>
                  <p className="text-2xl font-bold text-white">{p.total_lots?.toLocaleString('ru') ?? '—'}</p>
                  <p className="text-gray-500 text-xs mt-1">Всего лотов</p>
                </div>
                <div>
                  <p className="text-2xl font-bold text-green-400">{p.profitable_lots?.toLocaleString('ru') ?? '—'}</p>
                  <p className="text-gray-500 text-xs mt-1">Прибыльных</p>
                </div>
                <div>
                  <p className="text-2xl font-bold text-blue-400">{p.avg_margin ?? '—'}%</p>
                  <p className="text-gray-500 text-xs mt-1">Ср. маржа</p>
                </div>
              </div>
              <p className="text-xs text-gray-600 mt-3">Бюджет: {formatMoney(p.total_budget)}</p>
            </div>
          ))}
        </div>
      )}

      {/* Margin distribution */}
      {marginDist && marginDist.some((b: any) => b.count > 0) && (
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
          <h2 className="font-semibold text-white mb-4">Распределение маржи</h2>
          <ResponsiveContainer width="100%" height={200}>
            <BarChart data={marginDist} margin={{ top: 4, right: 4, bottom: 0, left: -10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis dataKey="range" tick={{ fontSize: 11, fill: '#6b7280' }} />
              <YAxis tick={{ fontSize: 11, fill: '#6b7280' }} />
              <Tooltip {...darkTooltip} formatter={(v: any) => [v, 'Тендеров']} />
              <Bar dataKey="count" radius={[4, 4, 0, 0]}>
                {marginDist.map((_: any, i: number) => (
                  <Cell key={i} fill={MARGIN_COLORS[i % MARGIN_COLORS.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Margin trend */}
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
        <h2 className="font-semibold text-white mb-4">Средняя маржа за 30 дней</h2>
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={trends || []} margin={{ top: 4, right: 4, bottom: 0, left: -10 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
            <XAxis dataKey="date" tick={{ fontSize: 11, fill: '#6b7280' }} tickFormatter={d => d.slice(5)} />
            <YAxis tick={{ fontSize: 11, fill: '#6b7280' }} unit="%" />
            <Tooltip {...darkTooltip} formatter={(v: any) => [`${v}%`, 'Средняя маржа']} />
            <Line type="monotone" dataKey="avg_margin" stroke="#10b981" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      {/* Category breakdown */}
      {categories && (
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
          <h2 className="font-semibold text-white mb-4">Прибыльность по категориям</h2>
          <ResponsiveContainer width="100%" height={240}>
            <BarChart data={categories} margin={{ top: 4, right: 4, bottom: 0, left: -10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1f2937" />
              <XAxis dataKey="category" tick={{ fontSize: 11, fill: '#6b7280' }} />
              <YAxis tick={{ fontSize: 11, fill: '#6b7280' }} unit="%" />
              <Tooltip {...darkTooltip} formatter={(v: any, name: string) => [
                name === 'avg_margin' ? `${v}%` : v,
                name === 'avg_margin' ? 'Средняя маржа' : 'Количество',
              ]} />
              <Bar dataKey="avg_margin" fill="#3b82f6" radius={[4, 4, 0, 0]} name="avg_margin" />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Category profitability table */}
      {catProfit && catProfit.length > 0 && (
        <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-800 flex items-center justify-between">
            <h2 className="font-semibold text-white">Прибыльность по категориям</h2>
            <span className="text-xs text-gray-500">% прибыльных / ср. маржа</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-gray-800">
                <tr>
                  {['Категория', 'Всего лотов', 'Прибыльных', '% прибыльных', 'Ср. маржа', 'Бюджет'].map(h => (
                    <th key={h} className="table-header whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/60">
                {catProfit.map((row: any) => (
                  <tr key={row.category} className="hover:bg-gray-800/40 transition-colors">
                    <td className="table-cell font-medium text-gray-200">{categoryLabel(row.category)}</td>
                    <td className="table-cell text-gray-400">{row.total_lots.toLocaleString('ru')}</td>
                    <td className="table-cell text-green-400 font-medium">{row.profitable_lots.toLocaleString('ru')}</td>
                    <td className="table-cell">
                      <div className="flex items-center gap-2">
                        <div className="w-16 h-1.5 rounded-full bg-gray-800 overflow-hidden">
                          <div className="h-full rounded-full bg-green-500" style={{ width: `${Math.min(100, row.profitable_pct)}%` }} />
                        </div>
                        <span className="text-xs font-bold text-green-400">{row.profitable_pct}%</span>
                      </div>
                    </td>
                    <td className="table-cell">
                      <span className={row.avg_margin >= 20 ? 'text-green-400 font-bold' : row.avg_margin >= 10 ? 'text-yellow-400 font-medium' : 'text-red-400'}>
                        {row.avg_margin}%
                      </span>
                    </td>
                    <td className="table-cell text-gray-500 text-xs">{formatMoney(row.total_budget)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Confidence breakdown */}
      {confBreakdown && confBreakdown.length > 0 && (
        <div className="bg-gray-900 rounded-xl border border-gray-800 p-5">
          <h2 className="font-semibold text-white mb-4">Распределение уверенности AI</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {confBreakdown.map((row: any) => {
              const color = row.confidence_level === 'high' ? 'border-green-500/30 bg-green-500/5'
                : row.confidence_level === 'medium' ? 'border-yellow-500/30 bg-yellow-500/5'
                : 'border-red-500/30 bg-red-500/5';
              const textColor = row.confidence_level === 'high' ? 'text-green-400'
                : row.confidence_level === 'medium' ? 'text-yellow-400' : 'text-red-400';
              const label = row.confidence_level === 'high' ? 'Высокая' : row.confidence_level === 'medium' ? 'Средняя' : 'Низкая';
              return (
                <div key={row.confidence_level} className={`rounded-xl border p-4 ${color}`}>
                  <p className={`text-lg font-bold ${textColor}`}>{label}</p>
                  <p className="text-2xl font-black text-white mt-1">{row.total.toLocaleString('ru')}</p>
                  <p className="text-xs text-gray-500 mt-0.5">{row.pct}% от всех анализированных</p>
                  <div className="mt-3 pt-3 border-t border-gray-700/50">
                    <p className="text-xs text-gray-500">Ср. маржа: <span className={`font-bold ${row.avg_margin > 0 ? 'text-green-400' : 'text-red-400'}`}>{row.avg_margin}%</span></p>
                    <p className="text-xs text-gray-500 mt-0.5">Бюджет: {row.total_budget_mln} млн ₸</p>
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Scan history */}
      <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
        <div className="px-5 py-4 border-b border-gray-800">
          <h2 className="font-semibold text-white">Последние сканирования</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-gray-800">
              <tr>
                {['Время', 'Площадка', 'Найдено', 'Новых', 'Прибыльных', 'Статус'].map(h => (
                  <th key={h} className="table-header whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/60">
              {(scanHistory || []).map((run: any) => {
                const s = statusMap[run.status] || { label: run.status, cls: 'badge-gray' };
                return (
                  <tr key={run.id} className="hover:bg-gray-800/40 transition-colors">
                    <td className="table-cell whitespace-nowrap text-gray-400">{formatDate(run.started_at)}</td>
                    <td className="table-cell">
                      <span className={`badge text-xs ${run.platform === 'goszakup' ? 'badge-blue' : run.platform === 'zakupsk' ? 'badge-yellow' : 'badge-gray'}`}>
                        {run.platform || 'Все'}
                      </span>
                    </td>
                    <td className="table-cell text-gray-300 font-medium">{run.tenders_found}</td>
                    <td className="table-cell text-gray-300">{run.tenders_new}</td>
                    <td className="table-cell">
                      <span className="text-green-400 font-semibold">{run.profitable_found}</span>
                    </td>
                    <td className="table-cell">
                      <span className={`badge text-xs ${s.cls}`}>{s.label}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
