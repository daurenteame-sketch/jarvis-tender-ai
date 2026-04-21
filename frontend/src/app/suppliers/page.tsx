'use client';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Search, ExternalLink, Truck, Package,
  AlertCircle, Loader2, ArrowRight, CheckCircle,
} from 'lucide-react';
import Link from 'next/link';
import { api } from '@/lib/api';
import { formatMoney } from '@/lib/utils';

// ── API ───────────────────────────────────────────────────────────────────────

async function searchMarketplaces(q: string) {
  const res = await api.get('/suppliers/search', { params: { q } });
  return res.data;
}

async function fetchRecentSuppliers() {
  const res = await api.get('/suppliers/recent', { params: { limit: 30 } });
  return res.data;
}

// ── Helpers ───────────────────────────────────────────────────────────────────

const FLAG: Record<string, string> = { CN: '🇨🇳', RU: '🇷🇺', KZ: '🇰🇿' };

const PLATFORM_STYLE: Record<string, string> = {
  'Wildberries': 'border-purple-500/40 text-purple-300 hover:bg-purple-500/10',
  'Kaspi.kz':    'border-yellow-500/40 text-yellow-300 hover:bg-yellow-500/10',
  'Satu.kz':     'border-green-500/40 text-green-300 hover:bg-green-500/10',
  'Ozon':        'border-blue-500/40 text-blue-300 hover:bg-blue-500/10',
  'Alibaba.com': 'border-orange-500/40 text-orange-300 hover:bg-orange-500/10',
  '1688.com':    'border-red-500/40 text-red-300 hover:bg-red-500/10',
  'AliExpress':  'border-orange-400/40 text-orange-200 hover:bg-orange-400/10',
};

const COUNTRY_LABEL: Record<string, string> = { KZ: 'Казахстан', RU: 'Россия', CN: 'Китай' };

function groupByCountry(links: any[]) {
  const groups: Record<string, any[]> = { KZ: [], RU: [], CN: [] };
  for (const link of links) {
    const c = link.country || 'CN';
    if (!groups[c]) groups[c] = [];
    groups[c].push(link);
  }
  return groups;
}

function LinkCard({ link }: { link: any }) {
  const style = PLATFORM_STYLE[link.platform] || 'border-gray-700 text-gray-300 hover:bg-gray-800';
  const isProduct = link.type === 'product';
  return (
    <a
      href={link.url}
      target="_blank"
      rel="noopener noreferrer"
      className={`flex items-center justify-between gap-3 px-4 py-3 rounded-xl border transition-colors ${style}`}
    >
      <div className="min-w-0 flex items-center gap-3">
        <span className="text-lg shrink-0">{FLAG[link.country] || '🌐'}</span>
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 flex-wrap">
            <span className="font-semibold text-sm">{link.platform}</span>
            {isProduct && (
              <span className="text-xs bg-green-500/15 text-green-400 border border-green-500/25 px-1.5 py-0.5 rounded-full font-medium flex items-center gap-0.5">
                <CheckCircle className="w-2.5 h-2.5" /> с фото
              </span>
            )}
          </div>
          {link.name && (
            <p className="text-xs text-gray-400 truncate mt-0.5">{link.name}</p>
          )}
        </div>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        {link.price_rub > 0 && (
          <span className="text-xs text-gray-400 font-mono">{link.price_rub.toLocaleString('ru')} ₽</span>
        )}
        <ExternalLink className="w-3.5 h-3.5 opacity-50" />
      </div>
    </a>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function SuppliersPage() {
  const [query, setQuery]           = useState('');
  const [activeQuery, setActiveQuery] = useState('');

  const { data: searchResult, isLoading: searching, isError: searchError } = useQuery({
    queryKey: ['supplier-search', activeQuery],
    queryFn:  () => searchMarketplaces(activeQuery),
    enabled:  !!activeQuery,
    staleTime: 60_000,
  });

  const { data: recent } = useQuery({
    queryKey: ['recent-suppliers'],
    queryFn:  fetchRecentSuppliers,
  });

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (query.trim().length >= 2) setActiveQuery(query.trim());
  };

  const links: any[]  = searchResult?.links || [];
  const groups        = groupByCountry(links);

  const QUICK_EXAMPLES = [
    'Ноутбук i7 16GB', 'Принтер лазерный A4', 'Стол офисный',
    'Насос центробежный', 'Кабель ВВГ 3x2.5', 'Кресло руководителя',
  ];

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">

      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 bg-blue-500/10 rounded-xl flex items-center justify-center border border-blue-500/20">
          <Truck className="w-5 h-5 text-blue-400" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-white">Поиск поставщиков</h1>
          <p className="text-sm text-gray-500">Найдите товар на маркетплейсах KZ · RU · CN</p>
        </div>
      </div>

      {/* Search form */}
      <div className="bg-gray-900 rounded-2xl border border-gray-800 p-6">
        <form onSubmit={handleSearch} className="flex gap-3">
          <div className="relative flex-1">
            <Search className="absolute left-4 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-500 pointer-events-none" />
            <input
              value={query}
              onChange={e => setQuery(e.target.value)}
              placeholder="Введите название товара из ТЗ..."
              className="input w-full pl-11 pr-4 py-3 text-base"
              autoFocus
            />
          </div>
          <button
            type="submit"
            disabled={query.trim().length < 2 || searching}
            className="px-6 py-3 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 disabled:cursor-not-allowed text-white font-semibold rounded-xl transition-colors flex items-center gap-2"
          >
            {searching ? <Loader2 className="w-4 h-4 animate-spin" /> : <Search className="w-4 h-4" />}
            Найти
          </button>
        </form>

        {!activeQuery && (
          <div className="mt-4">
            <p className="text-xs text-gray-600 mb-2">Быстрый поиск:</p>
            <div className="flex flex-wrap gap-2">
              {QUICK_EXAMPLES.map(ex => (
                <button
                  key={ex}
                  onClick={() => { setQuery(ex); setActiveQuery(ex); }}
                  className="text-xs px-3 py-1.5 rounded-lg border border-gray-700 text-gray-400 hover:border-gray-500 hover:text-white transition-colors"
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>

      {/* Results */}
      {activeQuery && (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <p className="text-gray-400 text-sm">
              Результаты для <span className="text-white font-semibold">«{activeQuery}»</span>
            </p>
            {searching && <Loader2 className="w-4 h-4 text-gray-500 animate-spin" />}
            {!searching && links.length > 0 && (
              <span className="text-xs text-gray-600 ml-1">— {links.length} ссылок</span>
            )}
          </div>

          {searchError && (
            <div className="flex items-center gap-2 p-4 bg-red-500/10 border border-red-500/20 rounded-xl text-red-400 text-sm">
              <AlertCircle className="w-4 h-4 shrink-0" />
              Ошибка поиска. Попробуйте ещё раз.
            </div>
          )}

          {!searching && links.length > 0 && (
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
              {(['KZ', 'RU', 'CN'] as const).map(country => {
                const cl = groups[country] || [];
                if (!cl.length) return null;
                return (
                  <div key={country} className="bg-gray-900 rounded-xl border border-gray-800 p-4">
                    <div className="flex items-center gap-2 mb-3">
                      <span className="text-xl">{FLAG[country]}</span>
                      <span className="font-semibold text-white">{COUNTRY_LABEL[country]}</span>
                      <span className="text-xs text-gray-600 ml-auto">{cl.length} площадок</span>
                    </div>
                    <div className="space-y-2">
                      {cl.map((link: any, i: number) => (
                        <LinkCard key={i} link={link} />
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Country info cards */}
      {!activeQuery && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {[
            { flag: '🇰🇿', title: 'Казахстан', desc: 'Kaspi.kz, Satu.kz — без таможни, быстрая доставка', cls: 'border-yellow-500/20 bg-yellow-500/5' },
            { flag: '🇷🇺', title: 'Россия',     desc: 'Wildberries, Ozon — широкий ассортимент',          cls: 'border-purple-500/20 bg-purple-500/5' },
            { flag: '🇨🇳', title: 'Китай',      desc: 'Alibaba, 1688, AliExpress — оптовые цены',         cls: 'border-red-500/20 bg-red-500/5' },
          ].map(item => (
            <div key={item.title} className={`rounded-xl border p-4 ${item.cls}`}>
              <div className="text-2xl mb-2">{item.flag}</div>
              <p className="font-semibold text-white">{item.title}</p>
              <p className="text-xs text-gray-400 mt-1">{item.desc}</p>
            </div>
          ))}
        </div>
      )}

      {/* Recent supplier matches */}
      {recent?.items?.length > 0 && (
        <div className="bg-gray-900 rounded-xl border border-gray-800 overflow-hidden">
          <div className="px-5 py-4 border-b border-gray-800 flex items-center justify-between">
            <h2 className="font-semibold text-white flex items-center gap-2">
              <Package className="w-4 h-4 text-gray-500" />
              Недавно найденные поставщики
            </h2>
            <span className="text-xs text-gray-500">из проанализированных тендеров</span>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="border-b border-gray-800">
                <tr>
                  {['Товар', 'Поставщик', 'Страна', 'Цена/ед.', 'Срок', 'Совпадение', ''].map(h => (
                    <th key={h} className="table-header whitespace-nowrap">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-800/60">
                {recent.items.slice(0, 15).map((item: any, i: number) => (
                  <tr key={i} className="hover:bg-gray-800/40 transition-colors">
                    <td className="table-cell max-w-[200px]">
                      <p className="text-gray-200 truncate text-xs font-medium" title={item.product_name}>
                        {item.product_name || '—'}
                      </p>
                    </td>
                    <td className="table-cell">
                      <span className="text-gray-300 text-xs">{item.supplier_name}</span>
                    </td>
                    <td className="table-cell">
                      <span className="text-sm">{FLAG[item.country] || '🌐'}</span>
                    </td>
                    <td className="table-cell whitespace-nowrap">
                      {item.unit_price_kzt
                        ? <span className="text-white font-semibold text-xs">{formatMoney(item.unit_price_kzt)}</span>
                        : '—'}
                    </td>
                    <td className="table-cell text-gray-500 text-xs">
                      {item.lead_time_days ? `${item.lead_time_days} дн.` : '—'}
                    </td>
                    <td className="table-cell">
                      {item.match_score != null && (
                        <span className={`text-xs font-bold ${
                          item.match_score >= 0.8 ? 'text-green-400' :
                          item.match_score >= 0.6 ? 'text-blue-400' : 'text-gray-500'
                        }`}>
                          {(item.match_score * 100).toFixed(0)}%
                        </span>
                      )}
                    </td>
                    <td className="table-cell">
                      {item.lot_id && (
                        <Link
                          href={`/tenders/${item.lot_id}`}
                          className="text-xs text-gray-500 hover:text-blue-400 transition-colors flex items-center gap-0.5"
                        >
                          Открыть <ArrowRight className="w-3 h-3" />
                        </Link>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
