'use client';
import { useQuery } from '@tanstack/react-query';
import { fetchScanHistory } from '@/lib/api';
import { formatDate } from '@/lib/utils';
import { Clock } from 'lucide-react';

export default function HistoryPage() {
  const { data: history, isLoading } = useQuery({
    queryKey: ['scan-history-full'],
    queryFn: () => fetchScanHistory(50),
  });

  const statusMap: Record<string, { label: string; cls: string }> = {
    completed: { label: 'Выполнено', cls: 'badge-green' },
    failed:    { label: 'Ошибка',    cls: 'badge-red' },
    running:   { label: 'Идёт...',   cls: 'badge-yellow' },
  };

  return (
    <div className="p-6">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-white">История сканирований</h1>
        <p className="text-gray-500 text-sm mt-1">Логи запусков парсинга тендерных площадок</p>
      </div>

      <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-gray-800">
              <tr>
                {['Время запуска', 'Площадка', 'Найдено', 'Новых', 'Прибыльных', 'Статус'].map(h => (
                  <th key={h} className="table-header whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/60">
              {isLoading ? (
                Array.from({ length: 8 }).map((_, i) => (
                  <tr key={i} className="border-b border-gray-800">
                    {[160, 100, 60, 60, 80, 80].map((w, j) => (
                      <td key={j} className="px-4 py-3">
                        <div className="skeleton h-4 rounded" style={{ width: w }} />
                      </td>
                    ))}
                  </tr>
                ))
              ) : !(history || []).length ? (
                <tr>
                  <td colSpan={6} className="px-6 py-16 text-center">
                    <div className="flex flex-col items-center gap-3">
                      <Clock className="w-8 h-8 text-gray-700" />
                      <p className="text-gray-500 text-sm">История пуста</p>
                    </div>
                  </td>
                </tr>
              ) : (
                (history || []).map((run: any) => {
                  const s = statusMap[run.status] || { label: run.status, cls: 'badge-gray' };
                  return (
                    <tr key={run.id} className="hover:bg-gray-800/40 transition-colors">
                      <td className="table-cell whitespace-nowrap text-gray-400">{formatDate(run.started_at)}</td>
                      <td className="table-cell">
                        <span className={`badge text-xs ${run.platform === 'goszakup' ? 'badge-blue' : run.platform === 'zakupsk' ? 'badge-yellow' : 'badge-gray'}`}>
                          {run.platform || 'Все'}
                        </span>
                      </td>
                      <td className="table-cell text-gray-300 font-medium">{run.tenders_found ?? '—'}</td>
                      <td className="table-cell text-gray-300">{run.tenders_new ?? '—'}</td>
                      <td className="table-cell">
                        <span className="text-green-400 font-semibold">{run.profitable_found ?? '—'}</span>
                      </td>
                      <td className="table-cell">
                        <span className={`badge text-xs ${s.cls}`}>{s.label}</span>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
