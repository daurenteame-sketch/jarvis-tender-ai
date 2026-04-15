'use client';
import { useState, useRef, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useSearchParams } from 'next/navigation';
import {
  Search, ChevronLeft, ChevronRight, ExternalLink, FileText,
  SlidersHorizontal, X, ChevronDown, ChevronUp, Download,
  Flame, Clock, ArrowUpDown, Zap,
} from 'lucide-react';
import { fetchLots, exportLotsExcel, type LotListItem, type LotListResponse, api } from '@/lib/api';
import {
  formatMoney, formatDeadline, platformLabel, categoryLabel,
  confidenceLabel, confidenceColor, marginColor,
  platformTenderUrl, buildPageRange,
} from '@/lib/utils';
import { cn } from '@/lib/utils';
import Link from 'next/link';

// ── Skeleton row ───────────────────────────────────────────────────────────────
function SkeletonRow() {
  return (
    <tr className="border-b border-gray-800">
      {[300, 180, 120, 100, 100, 90, 80, 60].map((w, i) => (
        <td key={i} className="px-4 py-3">
          <div className={`skeleton h-4 rounded`} style={{ width: w }} />
          {i === 1 && <div className="skeleton h-3 rounded mt-1.5 w-24" />}
        </td>
      ))}
      <td className="px-4 py-3"><div className="skeleton h-4 w-12 rounded" /></td>
    </tr>
  );
}

// ── Filter pill ────────────────────────────────────────────────────────────────
function FilterPill({ label, onRemove }: { label: string; onRemove: () => void }) {
  return (
    <span className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium
                     bg-blue-500/15 text-blue-400 border border-blue-500/25">
      {label}
      <button onClick={onRemove} className="hover:text-blue-200 transition-colors ml-0.5">
        <X className="w-3 h-3" />
      </button>
    </span>
  );
}

// ── Profit badge ───────────────────────────────────────────────────────────────
function ProfitBadge({ label }: { label: string | null }) {
  if (!label) return null;
  const map: Record<string, string> = {
    high:   'badge-green',
    medium: 'badge-yellow',
    low:    'badge-red',
    loss:   'bg-red-900/40 text-red-400 border border-red-500/25 text-xs font-semibold rounded-md px-2 py-0.5',
  };
  const text: Record<string, string> = {
    high: 'ВЫГОДНО', medium: 'СРЕДНЕ', low: 'НИЗКАЯ', loss: 'УБЫТОК',
  };
  return <span className={`text-xs font-semibold rounded-md px-2 py-0.5 ${map[label] || 'badge-gray'}`}>{text[label] || label}</span>;
}

// ── Pagination ─────────────────────────────────────────────────────────────────
function Pagination({
  page, pages, total, perPage, onChange,
}: {
  page: number; pages: number; total: number; perPage: number; onChange: (p: number) => void;
}) {
  const [jumpValue, setJumpValue] = useState('');
  const inputRef = useRef<HTMLInputElement>(null);
  const handleJump = () => {
    const n = parseInt(jumpValue, 10);
    if (!isNaN(n) && n >= 1 && n <= pages) { onChange(n); setJumpValue(''); inputRef.current?.blur(); }
  };
  const rangeStart = (page - 1) * perPage + 1;
  const rangeEnd = Math.min(page * perPage, total);
  const pageRange = buildPageRange(page, pages);

  return (
    <div className="px-4 py-3 border-t border-gray-800 flex flex-wrap items-center justify-between gap-3">
      <span className="text-sm text-gray-500 shrink-0">
        {rangeStart}–{rangeEnd} из {total.toLocaleString('ru')}
      </span>
      <div className="flex items-center gap-1 flex-wrap">
        <button
          onClick={() => onChange(page - 1)} disabled={page <= 1}
          className="w-8 h-8 flex items-center justify-center rounded border border-gray-700 text-gray-400
                     hover:bg-gray-800 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
        >
          <ChevronLeft className="w-4 h-4" />
        </button>
        {pageRange.map((item, i) =>
          item === '…' ? (
            <span key={`e${i}`} className="w-8 h-8 flex items-center justify-center text-gray-600 text-sm select-none">…</span>
          ) : (
            <button
              key={item}
              onClick={() => onChange(item as number)}
              className={cn(
                'w-8 h-8 flex items-center justify-center rounded border text-sm font-medium transition-colors',
                item === page
                  ? 'bg-blue-600 border-blue-600 text-white'
                  : 'border-gray-700 text-gray-400 hover:bg-gray-800'
              )}
            >
              {item}
            </button>
          )
        )}
        <button
          onClick={() => onChange(page + 1)} disabled={page >= pages}
          className="w-8 h-8 flex items-center justify-center rounded border border-gray-700 text-gray-400
                     hover:bg-gray-800 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
        >
          <ChevronRight className="w-4 h-4" />
        </button>
      </div>
      {pages > 5 && (
        <div className="flex items-center gap-1.5 shrink-0">
          <span className="text-sm text-gray-500">Перейти:</span>
          <input
            ref={inputRef} type="number" min={1} max={pages}
            value={jumpValue} onChange={e => setJumpValue(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleJump()}
            placeholder={String(page)}
            className="w-14 px-2 py-1 text-sm bg-gray-800 border border-gray-700 rounded text-center text-gray-200
                       focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
          <button
            onClick={handleJump}
            className="px-2 py-1 text-sm border border-gray-700 rounded text-gray-400 hover:bg-gray-800 transition-colors"
          >→</button>
        </div>
      )}
    </div>
  );
}

// ── Main component ─────────────────────────────────────────────────────────────
export default function TendersClient() {
  const searchParams = useSearchParams();
  const [showAdvanced, setShowAdvanced] = useState(false);

  const [filters, setFilters] = useState({
    platform: searchParams.get('platform') || '',
    category: searchParams.get('category') || '',
    is_profitable:
      searchParams.get('is_profitable') === 'true' ? true :
      searchParams.get('is_profitable') === 'false' ? false : undefined as boolean | undefined,
    confidence_level: searchParams.get('confidence_level') || '',
    search: '',
    min_budget: '',
    max_budget: '',
    min_accuracy: undefined as number | undefined,
    only_analyzed: undefined as boolean | undefined,
    new_today: undefined as boolean | undefined,
    sort_by: searchParams.get('sort_by') as any || undefined,
    page: 1,
    per_page: 20,
  });

  // Load user saved settings on mount
  useEffect(() => {
    api.get('/users/me/settings').then(res => {
      const s = res.data;
      if (s?.min_budget || s?.max_budget) {
        setFilters(prev => ({
          ...prev,
          min_budget: s.min_budget ? String(s.min_budget) : prev.min_budget,
          max_budget: s.max_budget ? String(s.max_budget) : prev.max_budget,
        }));
      }
    }).catch(() => {/* no settings saved yet */});
  }, []);

  const { data, isLoading } = useQuery<LotListResponse>({
    queryKey: ['lots', filters],
    queryFn: () => fetchLots({
      ...filters,
      min_budget: filters.min_budget ? Number(filters.min_budget) : undefined,
      max_budget: filters.max_budget ? Number(filters.max_budget) : undefined,
    }),
    placeholderData: prev => prev,
  });

  // Quality filter toggle: show only analyzed lots with accuracy ≥ 40%
  const [qualityFilter, setQualityFilter] = useState(false);
  useEffect(() => {
    if (qualityFilter) {
      setFilters(prev => ({ ...prev, min_accuracy: 40, only_analyzed: true, page: 1 }));
    } else {
      setFilters(prev => ({ ...prev, min_accuracy: undefined, only_analyzed: undefined, page: 1 }));
    }
  }, [qualityFilter]);

  const setPage = (p: number) =>
    setFilters(prev => ({ ...prev, page: Math.max(1, Math.min(data?.pages ?? 1, p)) }));

  const updateFilter = (key: string, value: unknown) =>
    setFilters(prev => ({ ...prev, [key]: value, page: 1 }));

  const clearAllFilters = () => {
    setQualityFilter(false);
    setFilters(prev => ({
      ...prev,
      platform: '', category: '', is_profitable: undefined,
      confidence_level: '', search: '', min_budget: '', max_budget: '',
      min_accuracy: undefined, only_analyzed: undefined,
      new_today: undefined, sort_by: undefined, page: 1,
    }));
  };

  const [exporting, setExporting] = useState(false);
  const handleExport = async () => {
    setExporting(true);
    try {
      const blob = await exportLotsExcel({
        platform: filters.platform || undefined,
        category: filters.category || undefined,
        is_profitable: filters.is_profitable,
        confidence_level: filters.confidence_level || undefined,
        min_budget: filters.min_budget ? Number(filters.min_budget) : undefined,
        max_budget: filters.max_budget ? Number(filters.max_budget) : undefined,
        search: filters.search || undefined,
        min_accuracy: filters.min_accuracy,
        only_analyzed: filters.only_analyzed,
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `tenders_${new Date().toISOString().slice(0, 10)}.xlsx`;
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      alert('Ошибка экспорта');
    } finally {
      setExporting(false);
    }
  };

  // Active filter pills
  const activePills: { label: string; clear: () => void }[] = [];
  if (filters.platform) activePills.push({ label: platformLabel(filters.platform), clear: () => updateFilter('platform', '') });
  if (filters.category) activePills.push({ label: categoryLabel(filters.category), clear: () => updateFilter('category', '') });
  if (filters.is_profitable !== undefined) activePills.push({ label: filters.is_profitable ? 'Прибыльные' : 'Неприбыльные', clear: () => updateFilter('is_profitable', undefined) });
  if (filters.confidence_level) activePills.push({ label: `Уверенность: ${confidenceLabel(filters.confidence_level)}`, clear: () => updateFilter('confidence_level', '') });
  if (filters.min_budget) activePills.push({ label: `Бюджет от ${Number(filters.min_budget).toLocaleString('ru')} ₸`, clear: () => updateFilter('min_budget', '') });
  if (filters.max_budget) activePills.push({ label: `Бюджет до ${Number(filters.max_budget).toLocaleString('ru')} ₸`, clear: () => updateFilter('max_budget', '') });

  return (
    <div className="p-6">
      {/* Header */}
      <div className="flex items-start justify-between mb-5">
        <div>
          <h1 className="text-2xl font-bold text-white">Тендеры</h1>
          <p className="text-gray-500 text-sm mt-1">
            {data?.total != null ? `Найдено: ${data.total.toLocaleString('ru')} лотов` : 'Загрузка...'}
          </p>
        </div>
        <button
          onClick={handleExport}
          disabled={exporting}
          className="flex items-center gap-2 px-4 py-2 rounded-lg border border-green-600/40 bg-green-500/10 text-green-400 text-sm font-medium hover:bg-green-500/20 hover:border-green-500/60 transition-all disabled:opacity-50 disabled:cursor-wait"
        >
          <Download className="w-4 h-4" />
          {exporting ? 'Экспорт...' : 'Excel'}
        </button>
      </div>

      {/* Quick filters + sort bar */}
      <div className="flex items-center gap-2 bg-gray-900 rounded-xl border border-gray-800 px-4 py-2.5 mb-3 flex-wrap">
        {/* Quality mode */}
        <button
          onClick={() => setQualityFilter(v => !v)}
          className={cn(
            'flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-semibold transition-all',
            qualityFilter
              ? 'bg-green-500/20 border-green-500/40 text-green-400'
              : 'border-gray-700 text-gray-500 hover:border-gray-600 hover:text-gray-400'
          )}
        >
          {qualityFilter ? '✓ Точность ≥40%' : 'Все лоты'}
        </button>

        {/* New today */}
        <button
          onClick={() => updateFilter('new_today', filters.new_today ? undefined : true)}
          className={cn(
            'flex items-center gap-1.5 px-3 py-1.5 rounded-lg border text-xs font-semibold transition-all',
            filters.new_today
              ? 'bg-blue-500/20 border-blue-500/40 text-blue-400'
              : 'border-gray-700 text-gray-500 hover:border-gray-600 hover:text-gray-400'
          )}
        >
          <Zap className="w-3 h-3" />
          Сегодня
        </button>

        {/* Divider */}
        <div className="w-px h-4 bg-gray-700 mx-1" />

        {/* Sort */}
        <div className="flex items-center gap-1">
          <ArrowUpDown className="w-3 h-3 text-gray-500" />
          <span className="text-xs text-gray-500">Сорт:</span>
          {[
            { key: undefined, label: 'Новые' },
            { key: 'deadline', label: 'Дедлайн' },
            { key: 'margin', label: 'Маржа' },
            { key: 'budget', label: 'Бюджет' },
            { key: 'profit', label: 'Прибыль' },
          ].map(({ key, label }) => (
            <button key={label}
              onClick={() => updateFilter('sort_by', key)}
              className={cn(
                'px-2 py-1 rounded text-xs transition-all',
                filters.sort_by === key
                  ? 'bg-blue-600 text-white font-semibold'
                  : 'text-gray-500 hover:text-gray-300'
              )}
            >{label}</button>
          ))}
        </div>

        <div className="ml-auto text-xs text-gray-600">
          {data?.total != null ? `${data.total.toLocaleString('ru')} лотов` : ''}
        </div>
      </div>

      {/* Filters card */}
      <div className="bg-gray-900 rounded-xl border border-gray-800 p-4 mb-5">
        {/* Primary row */}
        <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-5 gap-3">
          <div className="xl:col-span-2 relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 w-4 h-4 pointer-events-none" />
            <input
              type="text"
              placeholder="Поиск по названию или заказчику..."
              value={filters.search}
              onChange={e => updateFilter('search', e.target.value)}
              className="input w-full pl-10"
            />
          </div>
          <select value={filters.platform} onChange={e => updateFilter('platform', e.target.value)} className="select">
            <option value="">Все площадки</option>
            <option value="goszakup">GosZakup</option>
            <option value="zakupsk">Zakup SK</option>
          </select>
          <select value={filters.category} onChange={e => updateFilter('category', e.target.value)} className="select">
            <option value="">Все категории</option>
            <option value="product">Товары</option>
            <option value="software_service">IT / Разработка</option>
            <option value="other">Прочее</option>
          </select>
          <button
            onClick={() => setShowAdvanced(v => !v)}
            className={cn(
              'flex items-center justify-center gap-2 px-4 py-2 rounded-lg border text-sm font-medium transition-colors',
              showAdvanced
                ? 'bg-blue-600/20 border-blue-500/40 text-blue-400'
                : 'border-gray-700 text-gray-400 hover:bg-gray-800'
            )}
          >
            <SlidersHorizontal className="w-4 h-4" />
            Фильтры
            {showAdvanced ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </button>
        </div>

        {/* Advanced filters */}
        {showAdvanced && (
          <div className="mt-3 pt-3 border-t border-gray-800 grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
            <select
              value={filters.is_profitable === undefined ? '' : String(filters.is_profitable)}
              onChange={e => updateFilter('is_profitable', e.target.value === '' ? undefined : e.target.value === 'true')}
              className="select"
            >
              <option value="">Все тендеры</option>
              <option value="true">Только прибыльные</option>
              <option value="false">Неприбыльные</option>
            </select>
            <select value={filters.confidence_level} onChange={e => updateFilter('confidence_level', e.target.value)} className="select">
              <option value="">Любая уверенность</option>
              <option value="high">Высокая</option>
              <option value="medium">Средняя</option>
              <option value="low">Низкая</option>
            </select>
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 text-sm pointer-events-none">от</span>
              <input
                type="number"
                placeholder="Мин. бюджет"
                value={filters.min_budget}
                onChange={e => updateFilter('min_budget', e.target.value)}
                className="input w-full pl-9"
              />
            </div>
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-500 text-sm pointer-events-none">до</span>
              <input
                type="number"
                placeholder="Макс. бюджет"
                value={filters.max_budget}
                onChange={e => updateFilter('max_budget', e.target.value)}
                className="input w-full pl-9"
              />
            </div>
          </div>
        )}

        {/* Active filter pills */}
        {activePills.length > 0 && (
          <div className="mt-3 flex flex-wrap gap-2 items-center">
            {activePills.map((pill, i) => (
              <FilterPill key={i} label={pill.label} onRemove={pill.clear} />
            ))}
            <button
              onClick={clearAllFilters}
              className="text-xs text-gray-500 hover:text-gray-300 transition-colors underline underline-offset-2"
            >
              Сбросить все
            </button>
          </div>
        )}
      </div>

      {/* Table */}
      <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="border-b border-gray-800">
              <tr>
                {['№ / площадка', 'Наименование', 'Заказчик', 'Срок', 'Бюджет', 'Прибыль', 'Маржа', 'Уверенность', ''].map((h, i) => (
                  <th key={i} className="table-header whitespace-nowrap">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/60">
              {isLoading ? (
                Array.from({ length: 8 }).map((_, i) => <SkeletonRow key={i} />)
              ) : !data?.items?.length ? (
                <tr>
                  <td colSpan={9} className="px-6 py-16 text-center">
                    <div className="flex flex-col items-center gap-3">
                      <div className="w-12 h-12 rounded-full bg-gray-800 flex items-center justify-center">
                        <Search className="w-5 h-5 text-gray-600" />
                      </div>
                      <p className="text-gray-500 text-sm">Тендеры не найдены</p>
                      {activePills.length > 0 && (
                        <button onClick={clearAllFilters} className="text-blue-400 text-xs hover:text-blue-300 transition-colors">
                          Сбросить фильтры
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ) : (
                data.items.map((lot: LotListItem) => {
                  const externalUrl = platformTenderUrl(lot.platform, lot.tender_external_id);
                  const isUrgent = lot.deadline_at && new Date(lot.deadline_at) < new Date(Date.now() + 3 * 86_400_000);
                  return (
                    <tr key={lot.id} className={cn(
                      "hover:bg-gray-800/40 transition-colors group",
                      lot.accuracy_pct != null && lot.accuracy_pct < 40 && "opacity-60"
                    )}>
                      {/* № / площадка */}
                      <td className="table-cell">
                        <span className={`badge text-xs ${lot.platform === 'goszakup' ? 'badge-blue' : 'badge-yellow'}`}>
                          {platformLabel(lot.platform)}
                        </span>
                        <div className="text-xs text-gray-500 font-mono mt-1 leading-4">{lot.tender_external_id || '—'}</div>
                        <div className="text-xs text-gray-600 mt-0.5">Лот {lot.lot_external_id || '—'}</div>
                      </td>

                      {/* Наименование */}
                      <td className="table-cell max-w-[280px]">
                        <Link
                          href={`/tenders/${lot.id}`}
                          className="font-medium text-gray-200 hover:text-blue-400 line-clamp-2 transition-colors"
                        >
                          {lot.title}
                        </Link>
                        {lot.product_name && lot.product_name !== lot.title && (
                          <div className="text-xs text-blue-400 bg-blue-500/10 border border-blue-500/20 rounded px-1.5 py-0.5 mt-1 line-clamp-1 font-medium">
                            📦 {lot.product_name}
                          </div>
                        )}
                        {lot.characteristics && (
                          <div className="text-xs text-gray-600 mt-0.5 line-clamp-1">{lot.characteristics}</div>
                        )}
                        {lot.category && (
                          <span className="badge-gray text-xs mt-1 inline-block">{categoryLabel(lot.category)}</span>
                        )}
                      </td>

                      {/* Заказчик */}
                      <td className="table-cell max-w-[160px]">
                        <span className="text-gray-400 line-clamp-2 text-xs leading-5">{lot.customer_name || '—'}</span>
                      </td>

                      {/* Срок */}
                      <td className="table-cell whitespace-nowrap">
                        <span className={isUrgent ? 'text-red-400 font-semibold' : 'text-gray-400'}>
                          {formatDeadline(lot.deadline_at)}
                        </span>
                        {lot.days_until_deadline != null && (
                          <div className={cn(
                            'text-xs mt-0.5 font-semibold',
                            lot.days_until_deadline <= 2 ? 'text-red-400 animate-pulse' :
                            lot.days_until_deadline <= 5 ? 'text-orange-400' :
                            lot.days_until_deadline <= 10 ? 'text-yellow-400' : 'text-gray-600'
                          )}>
                            {lot.days_until_deadline <= 0 ? 'истёк' :
                             lot.days_until_deadline <= 2 ? `🔥 ${lot.days_until_deadline}д осталось` :
                             `${lot.days_until_deadline}д`}
                          </div>
                        )}
                      </td>

                      {/* Бюджет */}
                      <td className="table-cell whitespace-nowrap font-medium text-gray-200">
                        {formatMoney(lot.budget)}
                      </td>

                      {/* Прибыль */}
                      <td className="table-cell whitespace-nowrap">
                        {lot.expected_profit != null ? (
                          <span className={lot.expected_profit >= 0 ? 'text-green-400 font-medium' : 'text-red-400 font-medium'}>
                            {formatMoney(lot.expected_profit)}
                          </span>
                        ) : (
                          <span className="text-gray-700">—</span>
                        )}
                      </td>

                      {/* Маржа */}
                      <td className="table-cell whitespace-nowrap">
                        {lot.profit_margin_percent != null ? (
                          <div className="flex flex-col gap-1">
                            <span className={`font-bold text-base ${marginColor(lot.profit_margin_percent)}`}>
                              {lot.profit_margin_percent.toFixed(1)}%
                            </span>
                            <ProfitBadge label={lot.profit_label} />
                          </div>
                        ) : (
                          <span className="text-gray-700">—</span>
                        )}
                      </td>

                      {/* Уверенность / Точность */}
                      <td className="table-cell">
                        {lot.accuracy_pct != null ? (
                          <div className="flex flex-col gap-1">
                            {/* Accuracy bar */}
                            <div className="flex items-center gap-1.5">
                              <div className="w-16 h-1.5 rounded-full bg-gray-800 overflow-hidden">
                                <div
                                  className={`h-full rounded-full transition-all ${
                                    lot.accuracy_pct >= 70 ? 'bg-green-500' :
                                    lot.accuracy_pct >= 45 ? 'bg-yellow-500' : 'bg-red-500'
                                  }`}
                                  style={{ width: `${Math.min(100, lot.accuracy_pct)}%` }}
                                />
                              </div>
                              <span className={`text-xs font-bold ${
                                lot.accuracy_pct >= 70 ? 'text-green-400' :
                                lot.accuracy_pct >= 45 ? 'text-yellow-400' : 'text-red-400'
                              }`}>
                                {lot.accuracy_pct.toFixed(0)}%
                              </span>
                            </div>
                            {lot.confidence_level && (
                              <span className={`badge text-xs ${confidenceColor(lot.confidence_level)}`}>
                                {confidenceLabel(lot.confidence_level)}
                              </span>
                            )}
                            {lot.is_suspicious && (
                              <span className="text-xs text-orange-400 font-semibold">⚠ подозрительно</span>
                            )}
                            {lot.opportunity_score != null && lot.opportunity_score >= 50 && (
                              <div className={cn(
                                'text-xs font-bold flex items-center gap-1',
                                lot.opportunity_score >= 70 ? 'text-green-400' : 'text-yellow-400'
                              )}>
                                <Flame className="w-3 h-3" />
                                {lot.opportunity_score}
                              </div>
                            )}
                          </div>
                        ) : (
                          <span className="text-gray-600 text-xs">не анализирован</span>
                        )}
                      </td>

                      {/* Actions */}
                      <td className="table-cell">
                        <div className="flex items-center gap-2 opacity-60 group-hover:opacity-100 transition-opacity">
                          <Link
                            href={`/tenders/${lot.id}`}
                            className="flex items-center gap-1 text-blue-400 hover:text-blue-300 text-xs font-medium whitespace-nowrap"
                          >
                            <FileText className="w-3.5 h-3.5" />
                            Детали
                          </Link>
                          {externalUrl && (
                            <a
                              href={externalUrl} target="_blank" rel="noopener noreferrer"
                              className="flex items-center gap-1 text-gray-500 hover:text-gray-300 text-xs font-medium whitespace-nowrap"
                            >
                              <ExternalLink className="w-3.5 h-3.5" />
                            </a>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
        {data && data.pages > 1 && (
          <Pagination
            page={filters.page} pages={data.pages} total={data.total}
            perPage={filters.per_page} onChange={setPage}
          />
        )}
      </div>
    </div>
  );
}
