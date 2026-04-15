'use client';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useParams } from 'next/navigation';
import {
  ArrowLeft, Download, CheckCircle, XCircle, TrendingUp,
  Package, Truck, AlertTriangle, FileText, ExternalLink,
  ShoppingCart, Search, Tag, BookOpen, RefreshCw
} from 'lucide-react';
import Link from 'next/link';
import { fetchLotDetail, recordLotAction, getLotBidUrl, reanalyzeLot, reanalyzeLotFull } from '@/lib/api';
import {
  formatMoney, formatDeadline, platformLabel,
  confidenceLabel, riskColor, marginColor
} from '@/lib/utils';
import { useToast } from '@/components/ui/Toast';

// ── Types ──────────────────────────────────────────────────────────────────────

interface ResolvedProduct {
  product_name:    string;
  brand:           string | null;   // manufacturer / brand name
  model:           string | null;   // strict — only if explicitly in ТЗ
  characteristics: string | null;   // compact spec string e.g. "2х0,08–4мм², 32A"
  standard:        string | null;
  parameters:      Record<string, string>;
  search_query:    string;
  source:          'ai_model' | 'regex' | 'ai_name' | 'title';
  suggested_model: string | null;   // AI inference from spec characteristics
  confidence:      number | null;   // 0–100
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const FLAG: Record<string, string> = { CN: '🇨🇳', RU: '🇷🇺', KZ: '🇰🇿', DE: '🇩🇪', US: '🇺🇸' };
const CNAME: Record<string, string> = { CN: 'Китай', RU: 'Россия', KZ: 'Казахстан', DE: 'Германия', US: 'США' };

const flag  = (c: string | null) => FLAG[c || '']  || '🌐';
const cname = (c: string | null) => CNAME[c || ''] || c || '—';

const isSearchUrl = (url: string) =>
  /SearchText|keywords|search\?|\/search\//i.test(url);

const SOURCE_LABEL: Record<string, string> = {
  ai_model: 'AI (точная модель)',
  regex:    'Из спецификации',
  ai_name:  'AI (наименование)',
  title:    'Из заголовка',
};

// ── Product Identification Card ───────────────────────────────────────────────

function ConfidenceBar({ value }: { value: number }) {
  const color = value >= 70 ? 'bg-green-500' : value >= 40 ? 'bg-amber-400' : 'bg-gray-500';
  const label = value >= 70 ? 'text-green-400' : value >= 40 ? 'text-amber-400' : 'text-gray-500';
  return (
    <div className="flex items-center gap-2">
      <div className="w-16 h-1.5 bg-gray-700 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${color}`} style={{ width: `${value}%` }} />
      </div>
      <span className={`text-xs ${label}`}>{value}%</span>
    </div>
  );
}

function ProductCard({ resolved, analysis, characteristics: charsProp }: {
  resolved:        ResolvedProduct | null;
  analysis:        any;
  characteristics: string | null;
}) {
  const displayName      = analysis?.normalized_name || resolved?.product_name || null;
  const hasName          = !!displayName && displayName !== 'product';
  const productType      = analysis?.product_type ?? null;
  const brand            = resolved?.brand ?? analysis?.brand ?? null;
  const strictModel      = resolved?.model ?? analysis?.brand_model ?? null;
  const aiModel          = resolved?.suggested_model ?? null;
  const confidence       = resolved?.confidence ?? null;
  const exactMatch       = analysis?.exact_product_match ?? null;
  const keySpecs: { label: string; value: string }[] = analysis?.key_specs ?? [];
  const procurementHint  = analysis?.procurement_hint ?? null;
  const isStandardBased  = analysis?.is_standard_based ?? false;
  const possibleSuppliers: string[] = analysis?.possible_suppliers ?? [];
  const summaryText      = analysis?.ai_summary_ru || null;
  const analogs          = analysis?.analogs_allowed;

  // Best display model
  const bestModel = strictModel || aiModel || exactMatch;

  return (
    <div className="card">
      <h2 className="font-semibold mb-4 flex items-center gap-2">
        <Package className="w-4 h-4 text-purple-600" />
        Идентификация товара
      </h2>

      {/* ── Точный товар ───────────────────────────────────────────────── */}
      <div className={`rounded-lg border px-4 py-3 mb-3 ${
        hasName ? 'bg-gray-800/60 border-gray-700' : 'bg-amber-500/10 border-amber-500/30'
      }`}>
        <div className="flex items-start justify-between gap-2 mb-1">
          <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wide">Точный товар</p>
          {productType && (
            <span className="text-[10px] font-medium text-purple-600 bg-purple-50 border border-purple-100 px-2 py-0.5 rounded-full shrink-0">
              {productType}
            </span>
          )}
        </div>
        {hasName ? (
          <p className="font-bold text-white text-base leading-snug break-words">
            {displayName}
          </p>
        ) : (
          <div className="flex items-center gap-1.5">
            <AlertTriangle className="w-3.5 h-3.5 text-amber-400 shrink-0" />
            <p className="text-amber-400 text-sm font-medium">Нажмите «Полный анализ» для идентификации</p>
          </div>
        )}
        {brand && (
          <div className="flex items-center gap-1.5 mt-1.5">
            <Tag className="w-3 h-3 text-indigo-400 shrink-0" />
            <span className="text-xs text-gray-500">Марка:</span>
            <span className="text-xs font-semibold text-indigo-700">{brand}</span>
          </div>
        )}
      </div>

      {/* ── Параметры (key_specs) ──────────────────────────────────────── */}
      {keySpecs.length > 0 && (
        <div className="rounded-lg border border-gray-700 bg-gray-800/40 mb-3 overflow-hidden">
          <div className="px-3 py-1.5 bg-gray-800 border-b border-gray-700">
            <span className="text-[11px] font-semibold text-gray-500 uppercase tracking-wide">Параметры</span>
          </div>
          <div className="divide-y divide-gray-700/60">
            {keySpecs.map((spec, i) => (
              <div key={i} className="flex items-center justify-between px-3 py-2">
                <span className="text-xs text-gray-500 shrink-0">{spec.label}</span>
                <span className="text-xs font-semibold text-gray-300 text-right ml-2">{spec.value}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* ── Точная модель / что искать ─────────────────────────────────── */}
      <div className="rounded-lg border border-blue-500/25 bg-blue-500/10 px-3 py-3 mb-3">
        <div className="flex items-center gap-1.5 mb-2">
          <Search className="w-3.5 h-3.5 text-blue-500 shrink-0" />
          <span className="text-[11px] font-semibold text-blue-400 uppercase tracking-wide">
            {isStandardBased ? 'Это стандарт (не бренд)' : 'Точная модель'}
          </span>
        </div>

        {strictModel ? (
          <div className="flex items-center gap-2">
            <span className="text-sm font-bold text-blue-300 break-words">{strictModel}</span>
            <span className="text-[10px] text-green-400 bg-green-500/10 border border-green-500/25 px-1.5 py-0.5 rounded font-medium uppercase shrink-0">из ТЗ</span>
          </div>
        ) : aiModel ? (
          <div>
            <p className="text-sm font-bold text-blue-300 break-words mb-1">{aiModel}</p>
            {confidence != null && confidence > 0 && (
              <div className="flex items-center gap-2">
                <span className="text-xs text-blue-500">Уверенность AI:</span>
                <div className="w-14 h-1 bg-blue-200 rounded-full overflow-hidden">
                  <div className={`h-full rounded-full ${confidence >= 70 ? 'bg-green-500' : confidence >= 40 ? 'bg-amber-400' : 'bg-gray-400'}`}
                    style={{ width: `${confidence}%` }} />
                </div>
                <span className={`text-xs font-medium ${confidence >= 70 ? 'text-green-600' : confidence >= 40 ? 'text-amber-600' : 'text-gray-500'}`}>
                  {confidence}%
                </span>
              </div>
            )}
          </div>
        ) : exactMatch ? (
          <p className="text-sm font-bold text-blue-300 break-words">{exactMatch}</p>
        ) : (
          <p className="text-xs text-blue-400 italic">Нужен полный анализ</p>
        )}

        {procurementHint && (
          <div className="mt-2 pt-2 border-t border-blue-100">
            <p className="text-[10px] text-blue-500 mb-0.5">Искать у поставщиков:</p>
            <p className="text-xs font-mono text-blue-800 font-medium">{procurementHint}</p>
          </div>
        )}
      </div>

      {/* ── Реальные варианты поставщиков/брендов ─────────────────────── */}
      {possibleSuppliers.length > 0 && (
        <div className="mb-3">
          <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wide mb-2">
            Реальные варианты
          </p>
          <div className="flex flex-wrap gap-1.5">
            {possibleSuppliers.map((s, i) => (
              <span key={i} className="text-xs bg-gray-800 text-gray-300 border border-gray-700 px-2 py-1 rounded-full font-medium">
                {s}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* ── Количество / аналоги / ГОСТ ───────────────────────────────── */}
      <div className="space-y-1.5 text-xs mb-3">
        {(analysis?.quantity || analysis?.quantity_extracted) && (
          <div className="flex justify-between">
            <span className="text-gray-500">Количество</span>
            <span className="font-medium text-gray-200">
              {analysis.quantity || analysis.quantity_extracted}{' '}
              {analysis.unit || analysis.unit_extracted || 'шт.'}
            </span>
          </div>
        )}
        {resolved?.standard && (
          <div className="flex justify-between">
            <span className="text-gray-500">Стандарт</span>
            <span className="font-medium text-blue-700">{resolved.standard}</span>
          </div>
        )}
        {analogs != null && (
          <div className="flex justify-between">
            <span className="text-gray-500">Аналоги</span>
            <span className="font-medium">{analogs ? '✅ Разрешены' : '❌ Запрещены'}</span>
          </div>
        )}
      </div>

      {/* ── Резюме AI ─────────────────────────────────────────────────── */}
      {summaryText && (
        <div className="pt-2 border-t border-gray-800">
          <p className="text-[11px] font-semibold text-gray-400 uppercase tracking-wide mb-1">Резюме</p>
          <p className="text-gray-600 text-xs leading-relaxed">{summaryText}</p>
        </div>
      )}
    </div>
  );
}

// ── Suppliers Card ────────────────────────────────────────────────────────────

function SuppliersCard({ suppliers, searchQuery }: { suppliers: any[]; searchQuery: string }) {
  const sorted = [...suppliers].sort(
    (a, b) => (a.unit_price_kzt ?? Infinity) - (b.unit_price_kzt ?? Infinity)
  );
  const priceMin = sorted.length > 0 ? sorted[0].unit_price_kzt : null;
  const priceMax = sorted.length > 1 ? sorted[sorted.length - 1].unit_price_kzt : null;

  return (
    <div className="card mt-5">
      <div className="flex items-start justify-between mb-4 gap-2">
        <h2 className="font-semibold flex items-center gap-2">
          <ShoppingCart className="w-4 h-4 text-indigo-600" />
          Поставщики
          {sorted.length > 0 && (
            <span className="text-xs text-gray-400 font-normal">
              {sorted.length} варианта
            </span>
          )}
        </h2>
        {searchQuery && (
          <p className="text-xs text-gray-400 text-right max-w-[50%] leading-snug">
            Поиск: <span className="text-gray-600 font-medium">{searchQuery}</span>
          </p>
        )}
      </div>

      {sorted.length === 0 ? (
        <div className="text-sm text-gray-500 py-6 text-center border border-dashed border-gray-700 rounded-lg">
          Нет данных поставщиков.<br />
          <span className="text-xs">Запустите «Пересчитать маржу» на главной странице.</span>
        </div>
      ) : (
        <div className="space-y-3">
          {sorted.map((s: any, i: number) => {
            const isBest  = priceMin != null && s.unit_price_kzt === priceMin && sorted.length > 1;
            const isWorst = priceMax != null && s.unit_price_kzt === priceMax && sorted.length > 1;
            const isSearch = s.source_url && isSearchUrl(s.source_url);

            return (
              <div
                key={i}
                className={`rounded-xl border px-4 py-3 ${
                  isBest  ? 'border-green-500/30 bg-green-500/10' :
                  isWorst ? 'border-red-500/25   bg-red-500/10'   :
                            'border-gray-700     bg-gray-800/40 hover:bg-gray-800/60'
                } transition-colors`}
              >
                <div className="flex items-start justify-between gap-3">
                  {/* Left */}
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 flex-wrap mb-1">
                      <span className="font-semibold text-gray-200 text-sm">
                        {s.supplier_name || '—'}
                      </span>
                      {isBest && (
                        <span className="text-xs bg-green-500/15 text-green-400 border border-green-500/25 px-1.5 py-0.5 rounded font-medium">
                          Лучшая цена
                        </span>
                      )}
                      {isWorst && (
                        <span className="text-xs bg-red-500/15 text-red-400 border border-red-500/25 px-1.5 py-0.5 rounded font-medium">
                          Дороже всех
                        </span>
                      )}
                    </div>

                    <div className="flex items-center gap-3 text-xs text-gray-500 flex-wrap">
                      <span>{flag(s.country)} {cname(s.country)}</span>
                      {s.lead_time_days != null && (
                        <span className="flex items-center gap-0.5">
                          <Truck className="w-3 h-3" />
                          {s.lead_time_days} дн.
                        </span>
                      )}
                      <span className="flex items-center gap-1.5">
                        <span>Совпадение:</span>
                        <span className={`font-medium ${
                          (s.match_score || 0) >= 0.8 ? 'text-green-400' :
                          (s.match_score || 0) >= 0.6 ? 'text-blue-400' : 'text-gray-500'
                        }`}>
                          {((s.match_score || 0) * 100).toFixed(0)}%
                        </span>
                        <span className="w-12 bg-gray-700 rounded-full h-1 inline-block align-middle">
                          <span
                            className={`block h-1 rounded-full ${
                              (s.match_score || 0) >= 0.8 ? 'bg-green-500' :
                              (s.match_score || 0) >= 0.6 ? 'bg-blue-500' : 'bg-gray-400'
                            }`}
                            style={{ width: `${(s.match_score || 0) * 100}%` }}
                          />
                        </span>
                      </span>
                    </div>
                  </div>

                  {/* Right */}
                  <div className="text-right shrink-0">
                    <p className={`font-bold text-base ${
                      isBest ? 'text-green-400' : isWorst ? 'text-red-400' : 'text-gray-200'
                    }`}>
                      {formatMoney(s.unit_price_kzt)}
                    </p>
                    <p className="text-xs text-gray-400 mb-2">за ед.</p>
                    {s.source_url ? (
                      <a
                        href={s.source_url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className={`inline-flex items-center gap-1 text-xs px-2 py-1 rounded border transition-colors ${
                          isSearch
                            ? 'border-gray-700 text-gray-400 hover:border-gray-500'
                            : 'border-blue-500/30 text-blue-400 hover:border-blue-400'
                        }`}
                      >
                        {isSearch
                          ? <><Search className="w-3 h-3" /> Поиск товара</>
                          : <><ExternalLink className="w-3 h-3" /> Открыть товар</>
                        }
                      </a>
                    ) : (
                      <span className="text-gray-300 text-xs">нет ссылки</span>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {sorted.length > 0 && (
        <p className="text-xs text-gray-600 mt-3 pt-3 border-t border-gray-800">
          * Расчётные оценки на основе рыночных данных. Ссылки ведут на поиск по наименованию товара.
        </p>
      )}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function TenderDetailPage() {
  const { id } = useParams<{ id: string }>();
  const { toast } = useToast();
  const [reanalyzing, setReanalyzing]     = useState(false);
  const [fullAnalyzing, setFullAnalyzing] = useState(false);

  const { data: lot, isLoading, error, refetch } = useQuery({
    queryKey: ['lot', id],
    queryFn:  () => fetchLotDetail(id),
  });

  const handleAction = async (action: string) => {
    try {
      await recordLotAction(id, action);
      toast(`Действие "${action}" записано`, 'success');
    } catch {
      toast('Не удалось записать действие', 'error');
    }
  };

  const handleReanalyze = async () => {
    setReanalyzing(true);
    try {
      await reanalyzeLot(id);
      await refetch();
      toast('AI-анализ завершён', 'success');
    } catch (e: any) {
      const msg = e?.response?.data?.detail || e?.message || String(e);
      toast(`Ошибка AI-анализа: ${msg}`, 'error');
      console.error('[reanalyze] error:', e);
    } finally {
      setReanalyzing(false);
    }
  };

  const handleFullReanalyze = async () => {
    setFullAnalyzing(true);
    try {
      await reanalyzeLotFull(id);
      await refetch();
      toast('Полный анализ завершён', 'success');
    } catch (e: any) {
      const msg = e?.response?.data?.detail || e?.message || String(e);
      toast(`Ошибка полного анализа: ${msg}`, 'error');
      console.error('[reanalyze-full] error:', e);
    } finally {
      setFullAnalyzing(false);
    }
  };

  if (isLoading) {
    return (
      <div className="p-8 flex items-center gap-3 text-gray-500">
        <div className="w-5 h-5 border-2 border-blue-500 border-t-transparent rounded-full animate-spin" />
        Загрузка...
      </div>
    );
  }

  if (error) {
    const status = (error as any)?.response?.status;
    const detail = (error as any)?.response?.data?.detail;
    const is402 = status === 402;
    return (
      <div className="p-8 max-w-lg">
        <Link href="/tenders" className="flex items-center gap-1.5 text-gray-500 hover:text-gray-300 text-sm mb-6">
          <ArrowLeft className="w-4 h-4" /> Назад к списку
        </Link>
        {is402 ? (
          <div className="bg-gray-900 rounded-xl border border-blue-500/30 p-8 text-center">
            <div className="w-14 h-14 rounded-full bg-blue-500/10 border border-blue-500/20 flex items-center justify-center mx-auto mb-4">
              <TrendingUp className="w-6 h-6 text-blue-400" />
            </div>
            <h2 className="text-xl font-bold text-white mb-2">Нужен Pro-доступ</h2>
            <p className="text-gray-400 text-sm mb-1">
              {typeof detail === 'object' ? detail?.message : 'Детали тендера доступны только на платном тарифе.'}
            </p>
            {typeof detail === 'object' && detail?.views_today != null && (
              <p className="text-gray-600 text-xs mb-4">
                Просмотрено сегодня: {detail.views_today} / {detail.limit}
              </p>
            )}
            <div className="flex gap-3 justify-center mt-6">
              <a
                href="https://t.me/jarvis_tender_kz" target="_blank" rel="noreferrer"
                className="btn-primary px-5 py-2 text-sm"
              >
                Перейти на Pro
              </a>
              <Link href="/settings" className="btn-secondary px-5 py-2 text-sm">
                Настройки
              </Link>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-2 text-red-400">
            <AlertTriangle className="w-5 h-5" />
            Лот не найден или произошла ошибка
          </div>
        )}
      </div>
    );
  }

  if (!lot) {
    return (
      <div className="p-8">
        <div className="flex items-center gap-2 text-red-400 mb-4">
          <AlertTriangle className="w-5 h-5" />
          Лот не найден
        </div>
        <Link href="/tenders" className="text-blue-400 hover:text-blue-300 text-sm">
          ← Назад к списку
        </Link>
      </div>
    );
  }

  const p            = lot.profitability;
  const analysis     = lot.analysis || null;
  const resolved     = (lot.resolved_product as ResolvedProduct) || null;
  const customerName = lot.customer_name ?? lot.tender?.customer_name;
  const suppliers    = lot.suppliers || [];
  const searchQuery  = resolved?.search_query || analysis?.product_name || '';

  // Debug: log the full lot to verify field presence
  console.log('[LotDetail] lot:', lot);
  console.log('[LotDetail] characteristics (top-level):', (lot as any).characteristics);
  console.log('[LotDetail] characteristics (resolved):', resolved?.characteristics);
  console.log('[LotDetail] characteristics (analysis):', analysis?.characteristics);

  return (
    <div className="p-6 max-w-5xl">

      {/* Back + Actions */}
      <div className="flex items-center justify-between mb-5 gap-2 flex-wrap">
        <Link href="/tenders" className="flex items-center gap-2 text-gray-500 hover:text-gray-200 text-sm shrink-0">
          <ArrowLeft className="w-4 h-4" /> Назад к списку
        </Link>
        <div className="flex gap-2 flex-wrap">
          <a
            href={getLotBidUrl(id, 'Ваша компания', '')}
            target="_blank"
            rel="noopener noreferrer"
            className="btn-primary flex items-center gap-2 text-sm"
          >
            <Download className="w-4 h-4" />
            Скачать заявку
          </a>
          <button
            onClick={() => handleAction('bid_submitted')}
            className="btn-secondary flex items-center gap-2 text-sm text-green-700"
          >
            <CheckCircle className="w-4 h-4" />
            Участвую
          </button>
          <button
            onClick={() => handleAction('ignored')}
            className="btn-secondary flex items-center gap-2 text-sm text-red-600"
          >
            <XCircle className="w-4 h-4" />
            Игнорировать
          </button>
          <button
            onClick={handleReanalyze}
            disabled={reanalyzing || fullAnalyzing}
            className="btn-secondary flex items-center gap-2 text-sm text-purple-700 disabled:opacity-50"
            title="Повторить AI-анализ товара"
          >
            <RefreshCw className={`w-4 h-4 ${reanalyzing ? 'animate-spin' : ''}`} />
            {reanalyzing ? 'Анализирую...' : 'AI-анализ'}
          </button>
          <button
            onClick={handleFullReanalyze}
            disabled={reanalyzing || fullAnalyzing}
            className="btn-secondary flex items-center gap-2 text-sm text-orange-700 disabled:opacity-50"
            title="Полный анализ: AI + пересчёт цены и маржи"
          >
            <RefreshCw className={`w-4 h-4 ${fullAnalyzing ? 'animate-spin' : ''}`} />
            {fullAnalyzing ? 'Считаю...' : 'Полный анализ'}
          </button>
        </div>
      </div>

      {/* Title card */}
      <div className="card mb-5">
        <div className="flex items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2 mb-2 flex-wrap">
              <span className={`badge ${lot.platform === 'goszakup' ? 'badge-blue' : 'badge-yellow'}`}>
                {platformLabel(lot.platform)}
              </span>
              {lot.category && (
                <span className="badge-gray">
                  {lot.category === 'software_service' ? 'IT / Разработка' : 'Товар'}
                </span>
              )}
              {lot.lot_external_id && (
                <span className="text-xs text-gray-400 font-mono">Лот {lot.lot_external_id}</span>
              )}
            </div>
            <h1 className="text-xl font-bold mb-1 leading-snug text-white">{lot.title}</h1>
            <p className="text-sm text-gray-400">{customerName}</p>
            {lot.tender?.customer_region && (
              <p className="text-xs text-gray-400 mt-0.5">{lot.tender.customer_region}</p>
            )}
          </div>
          <div className="text-right shrink-0">
            <p className="text-2xl font-bold text-white">{formatMoney(lot.budget)}</p>
            <p className="text-sm text-gray-500">Бюджет лота</p>
            {lot.quantity && (
              <p className="text-sm text-gray-500 mt-0.5">{lot.quantity} {lot.unit || 'шт.'}</p>
            )}
            <p className="text-sm text-gray-500 mt-1">До: {formatDeadline(lot.deadline_at)}</p>
          </div>
        </div>
      </div>

      {/* ── Buy recommendation banner ───────────────────────────────────── */}
      {(() => {
        const rec = (lot as any).buy_recommendation;
        const idc = (lot as any).identification_confidence as number | null;
        if (!rec) return null;
        const bg =
          rec.level === 'high'                      ? 'bg-green-500/10 border-green-500/30' :
          rec.level === 'medium'                    ? 'bg-amber-500/10 border-amber-500/30' :
          rec.level === 'low' || rec.level === 'loss' ? 'bg-red-500/10   border-red-500/30'   :
                                                      'bg-gray-800     border-gray-700';
        const textColor =
          rec.level === 'high'                      ? 'text-green-400' :
          rec.level === 'medium'                    ? 'text-amber-400' :
          rec.level === 'low' || rec.level === 'loss' ? 'text-red-400'   : 'text-gray-400';
        const barColor =
          idc == null ? 'bg-gray-300' :
          idc >= 70   ? 'bg-green-500' :
          idc >= 40   ? 'bg-amber-400' : 'bg-red-400';
        return (
          <div className={`rounded-xl border px-5 py-4 mb-5 flex items-center justify-between gap-4 flex-wrap ${bg}`}>
            <div>
              <p className={`font-bold text-base ${textColor}`}>{rec.label}</p>
              <p className="text-sm text-gray-500 mt-0.5">{rec.detail}</p>
            </div>
            {idc != null && (
              <div className="flex items-center gap-3 shrink-0">
                <div className="text-right">
                  <p className="text-xs text-gray-500 mb-1">Качество идентификации</p>
                  <div className="flex items-center gap-2">
                    <div className="w-28 h-2 bg-gray-700 rounded-full overflow-hidden">
                      <div className={`h-full rounded-full ${barColor}`} style={{ width: `${idc}%` }} />
                    </div>
                    <span className={`text-sm font-bold ${
                      idc >= 70 ? 'text-green-600' : idc >= 40 ? 'text-amber-600' : 'text-red-500'
                    }`}>{idc}%</span>
                  </div>
                </div>
              </div>
            )}
          </div>
        );
      })()}

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-5">

        {/* Product Identification */}
        <ProductCard
          resolved={resolved}
          analysis={analysis}
          characteristics={(lot as any).characteristics ?? null}
        />

        {/* Financial Analysis + Bid Strategy */}
        {p ? (
          <div className="card">
            <h2 className="font-semibold mb-4 flex items-center gap-2">
              <TrendingUp className="w-4 h-4 text-green-600" />
              Финансовый анализ
            </h2>

            {/* Confidence warning banner */}
            {p.confidence_score != null && p.confidence_score < 0.70 && (
              <div className={`rounded-lg border px-3 py-2.5 mb-4 flex items-start gap-2 ${
                p.confidence_score >= 0.45
                  ? 'bg-yellow-500/10 border-yellow-500/30'
                  : 'bg-red-500/10 border-red-500/30'
              }`}>
                <AlertTriangle className={`w-4 h-4 shrink-0 mt-0.5 ${
                  p.confidence_score >= 0.45 ? 'text-yellow-400' : 'text-red-400'
                }`} />
                <div>
                  <p className={`text-sm font-semibold ${
                    p.confidence_score >= 0.45 ? 'text-yellow-300' : 'text-red-300'
                  }`}>
                    {p.confidence_score >= 0.45
                      ? 'Средняя точность определения'
                      : 'Товар не определен с высокой точностью'}
                  </p>
                  <p className={`text-xs mt-0.5 ${
                    p.confidence_score >= 0.45 ? 'text-yellow-500' : 'text-red-500'
                  }`}>
                    {p.confidence_score < 0.45
                      ? 'Данные могут быть неточными. Рекомендуем провести полный анализ.'
                      : 'Цена определена по категории товара. Для точного расчёта — полный анализ.'}
                  </p>
                </div>
              </div>
            )}

            {/* High confidence badge */}
            {p.confidence_score != null && p.confidence_score >= 0.70 && (
              <div className="rounded-lg border bg-green-500/10 border-green-500/30 px-3 py-2 mb-4 flex items-center gap-2">
                <CheckCircle className="w-4 h-4 text-green-400 shrink-0" />
                <p className="text-sm font-semibold text-green-300">
                  Высокая точность ({(p.confidence_score * 100).toFixed(0)}%) — данные достоверны
                </p>
              </div>
            )}

            <div className="space-y-2 text-sm">
              {([
                ['Себестоимость товара', p.product_cost ?? 0],
                ['Логистика',           p.logistics_cost ?? 0],
                ['Таможенные пошлины',  p.customs_cost ?? 0],
                ['НДС (16%)',           p.vat_amount ?? 0],
                ['Операционные расходы', p.operational_costs ?? 0],
              ] as [string, number][]).map(([label, val]) => (
                <div key={label} className="flex justify-between text-gray-400">
                  <span>{label}</span>
                  <span>{formatMoney(val)}</span>
                </div>
              ))}
              <div className="pt-2 border-t border-gray-800 space-y-1">
                <div className="flex justify-between font-semibold text-gray-200">
                  <span>Итого затрат</span>
                  <span>{formatMoney(p.total_cost ?? 0)}</span>
                </div>
                <div className={`flex justify-between font-bold text-base ${
                  (p.expected_profit ?? 0) >= 0 ? 'text-green-400' : 'text-red-400'
                }`}>
                  <span>Ожидаемая прибыль</span>
                  <span>{formatMoney(p.expected_profit ?? 0)}</span>
                </div>
                <div className={`flex justify-between font-bold text-lg ${marginColor(p.profit_margin_percent ?? 0)}`}>
                  <span>Маржа</span>
                  <span>{(p.profit_margin_percent ?? 0).toFixed(1)}%</span>
                </div>
              </div>
            </div>

            {/* Bid strategy inline */}
            <div className="mt-4 pt-4 border-t border-gray-800">
              <p className="text-xs text-gray-500 mb-2 flex items-center gap-1">
                <FileText className="w-3.5 h-3.5" /> Стратегия участия
              </p>
              {/* Show bid strategy only when confidence is adequate */}
              {(p.confidence_score ?? 0) >= 0.45 ? (
                <div className="grid grid-cols-3 gap-2 text-center text-sm">
                  <div className="bg-green-500/10 border border-green-500/20 rounded-lg p-2">
                    <p className="text-xs text-green-400">Безопасная</p>
                    <p className="font-bold text-green-300 text-sm">{formatMoney(p.safe_bid ?? 0)}</p>
                  </div>
                  <div className="bg-blue-500/10 border border-blue-500/20 rounded-lg p-2">
                    <p className="text-xs text-blue-400">Рекомендуется</p>
                    <p className="font-bold text-blue-300 text-sm">{formatMoney(p.recommended_bid ?? 0)}</p>
                  </div>
                  <div className="bg-orange-500/10 border border-orange-500/20 rounded-lg p-2">
                    <p className="text-xs text-orange-400">Агрессивная</p>
                    <p className="font-bold text-orange-300 text-sm">{formatMoney(p.aggressive_bid ?? 0)}</p>
                  </div>
                </div>
              ) : (
                <div className="text-center py-3 text-gray-600 text-xs border border-gray-800 rounded-lg">
                  Стратегия доступна при точности ≥ 45%
                </div>
              )}
              <div className="flex justify-between mt-3 text-xs text-gray-500">
                <span>
                  Точность:{' '}
                  <strong className={
                    (p.confidence_score ?? 0) >= 0.70 ? 'text-green-400' :
                    (p.confidence_score ?? 0) >= 0.45 ? 'text-yellow-400' : 'text-red-400'
                  }>
                    {confidenceLabel(p.confidence_level)}
                    {p.confidence_score != null && ` (${(p.confidence_score * 100).toFixed(0)}%)`}
                  </strong>
                </span>
                <span className={`font-semibold ${riskColor(p.risk_level ?? 'medium')}`}>
                  Риск:{' '}
                  {({ low: 'Низкий', medium: 'Средний', high: 'Высокий' } as Record<string, string>)[p.risk_level ?? ''] || '—'}
                </span>
              </div>
            </div>
          </div>
        ) : (
          <div className="card border-yellow-500/30 bg-yellow-500/10">
            <div className="flex items-start gap-2 text-yellow-400">
              <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
              <div>
                <p className="font-medium text-sm">Анализ прибыльности не выполнен</p>
                <p className="text-xs mt-1 text-yellow-500">
                  Нажмите «Полный анализ» для расчёта маржи.
                </p>
              </div>
            </div>
          </div>
        )}

        {/* Logistics */}
        {lot.logistics && (
          <div className="card">
            <h2 className="font-semibold mb-4 flex items-center gap-2">
              <Truck className="w-4 h-4 text-orange-600" />
              Логистика
            </h2>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-gray-500">Маршрут</span>
                <span className="text-right text-gray-300 ml-4">{lot.logistics.route}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Доставка</span>
                <span className="text-gray-300">{formatMoney(lot.logistics.shipping_cost)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">Таможня</span>
                <span className="text-gray-300">{formatMoney(lot.logistics.customs_duty)}</span>
              </div>
              <div className="flex justify-between">
                <span className="text-gray-500">НДС</span>
                <span className="text-gray-300">{formatMoney(lot.logistics.vat_amount)}</span>
              </div>
              <div className="flex justify-between font-semibold border-t border-gray-800 pt-2 text-gray-200">
                <span>Итого логистика</span>
                <span>{formatMoney(lot.logistics.total_logistics)}</span>
              </div>
              <div className="flex justify-between text-gray-500">
                <span>Срок поставки</span>
                <span>{lot.logistics.lead_time_days} дней</span>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Suppliers */}
      <SuppliersCard suppliers={suppliers} searchQuery={searchQuery} />
    </div>
  );
}
