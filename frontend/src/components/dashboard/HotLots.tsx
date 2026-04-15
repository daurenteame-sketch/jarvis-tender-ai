'use client';
import { useQuery } from '@tanstack/react-query';
import { fetchTopLots, type TopLotItem } from '@/lib/api';
import { formatMoney, marginColor, confidenceColor } from '@/lib/utils';
import { Flame, Clock, TrendingUp, ArrowRight, Star } from 'lucide-react';
import Link from 'next/link';
import { cn } from '@/lib/utils';

function UrgencyBadge({ days }: { days: number | null }) {
  if (days === null) return null;
  if (days <= 0) return <span className="text-xs px-1.5 py-0.5 rounded bg-red-900/40 text-red-400 border border-red-700/40">Истёк</span>;
  if (days <= 2) return <span className="text-xs px-1.5 py-0.5 rounded bg-red-500/20 text-red-400 border border-red-500/30 animate-pulse">{days}д</span>;
  if (days <= 5) return <span className="text-xs px-1.5 py-0.5 rounded bg-orange-500/20 text-orange-400 border border-orange-500/30">{days}д</span>;
  if (days <= 10) return <span className="text-xs px-1.5 py-0.5 rounded bg-yellow-500/15 text-yellow-400 border border-yellow-500/20">{days}д</span>;
  return <span className="text-xs px-1.5 py-0.5 rounded bg-gray-800 text-gray-500">{days}д</span>;
}

function ScoreBadge({ score }: { score: number }) {
  const color = score >= 70 ? 'text-green-400 bg-green-500/10 border-green-500/20'
    : score >= 50 ? 'text-yellow-400 bg-yellow-500/10 border-yellow-500/20'
    : 'text-gray-400 bg-gray-800 border-gray-700';
  return (
    <div className={cn('flex items-center gap-1 px-2 py-1 rounded-lg border text-xs font-bold', color)}>
      <Star className="w-3 h-3" />
      {score}
    </div>
  );
}

function LotRow({ lot, rank }: { lot: TopLotItem; rank: number }) {
  const confColor = lot.confidence_level === 'high' ? 'text-green-400'
    : lot.confidence_level === 'medium' ? 'text-yellow-400' : 'text-gray-500';

  return (
    <Link href={`/tenders/${lot.id}`}
      className="flex items-center gap-3 p-3 rounded-xl bg-gray-800/50 hover:bg-gray-800 border border-gray-700/50 hover:border-gray-600 transition-all group">

      {/* Rank */}
      <div className={cn(
        'w-7 h-7 rounded-lg flex items-center justify-center text-xs font-black shrink-0',
        rank === 1 ? 'bg-yellow-500/20 text-yellow-400' :
        rank === 2 ? 'bg-gray-400/20 text-gray-300' :
        rank === 3 ? 'bg-orange-600/20 text-orange-400' :
        'bg-gray-800 text-gray-600'
      )}>
        {rank}
      </div>

      {/* Title & customer */}
      <div className="flex-1 min-w-0">
        <p className="text-sm text-gray-200 font-medium line-clamp-1 group-hover:text-white transition-colors">
          {lot.title}
        </p>
        <div className="flex items-center gap-2 mt-0.5">
          <span className="text-xs text-gray-600 truncate max-w-[180px]">{lot.customer_name || '—'}</span>
          {lot.confidence_level && (
            <span className={cn('text-xs font-medium', confColor)}>
              {lot.confidence_level === 'high' ? '↑ высокая' : lot.confidence_level === 'medium' ? '≈ средняя' : '↓ низкая'}
            </span>
          )}
        </div>
      </div>

      {/* Score + deadline */}
      <div className="flex items-center gap-2 shrink-0">
        <UrgencyBadge days={lot.days_until_deadline} />
        <ScoreBadge score={lot.opportunity_score} />
      </div>

      {/* Budget + margin */}
      <div className="text-right shrink-0 w-28">
        <p className="text-sm font-semibold text-white">{formatMoney(lot.budget)}</p>
        {lot.profit_margin_percent != null && (
          <p className={cn('text-xs font-bold', marginColor(lot.profit_margin_percent))}>
            +{lot.profit_margin_percent.toFixed(0)}% маржа
          </p>
        )}
      </div>

      <ArrowRight className="w-4 h-4 text-gray-600 group-hover:text-gray-400 transition-colors shrink-0" />
    </Link>
  );
}

export function HotLots() {
  const { data, isLoading } = useQuery({
    queryKey: ['hot-lots'],
    queryFn: () => fetchTopLots(8, 10),
    refetchInterval: 120_000,
  });

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-sm font-semibold text-white flex items-center gap-2">
          <Flame className="w-4 h-4 text-orange-400" />
          Горячие лоты
          <span className="text-xs text-gray-600 font-normal">по индексу привлекательности</span>
        </h2>
        <Link href="/tenders?is_profitable=true&confidence_level=high&sort_by=deadline"
          className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1">
          Все прибыльные <ArrowRight className="w-3 h-3" />
        </Link>
      </div>

      {isLoading ? (
        <div className="space-y-2">
          {[...Array(5)].map((_, i) => (
            <div key={i} className="h-14 bg-gray-800/50 rounded-xl animate-pulse" />
          ))}
        </div>
      ) : !data?.items?.length ? (
        <div className="text-center py-8 text-gray-600 text-sm">
          Прибыльные лоты появятся после сканирования и AI-анализа
        </div>
      ) : (
        <div className="space-y-2">
          {data.items.map((lot, i) => (
            <LotRow key={lot.id} lot={lot} rank={i + 1} />
          ))}
        </div>
      )}

      {/* Legend */}
      <div className="flex items-center gap-4 mt-4 pt-3 border-t border-gray-800 text-xs text-gray-600">
        <div className="flex items-center gap-1.5">
          <Star className="w-3 h-3 text-green-400" />
          <span>Индекс: маржа × уверенность × срочность</span>
        </div>
        <div className="flex items-center gap-1.5">
          <Clock className="w-3 h-3 text-orange-400" />
          <span>Дней до дедлайна</span>
        </div>
      </div>
    </div>
  );
}
