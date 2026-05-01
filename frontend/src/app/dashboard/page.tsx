'use client';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  TrendingUp, Target, DollarSign, Zap, RefreshCw,
  Calculator, BrainCircuit, History, ArrowRight,
  BarChart2, Sparkles, ShieldCheck, Clock,
} from 'lucide-react';
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, BarChart, Bar,
} from 'recharts';
import { StatCard } from '@/components/dashboard/StatCard';
import { HotLots } from '@/components/dashboard/HotLots';
import {
  fetchDashboardSummary, fetchTrends, fetchTopCategories,
  triggerScan, getScanStatus, triggerRecalculate, getRecalculateStatus,
  getAnalyzeEstimate, triggerAnalyzeLots, getAnalyzeStatus, getAiCostLog,
  fetchLots,
} from '@/lib/api';
import { formatMoney, formatDate, marginColor, confidenceColor } from '@/lib/utils';
import { useToast } from '@/components/ui/Toast';
import { useAuth } from '@/contexts/AuthContext';
import Link from 'next/link';
import { useState, useEffect, useCallback } from 'react';

const MODES = [
  { id: 'fast',     label: 'Быстрый',  limit: 10,  cls: 'border-blue-500/50   bg-blue-500/10   text-blue-300' },
  { id: 'standard', label: 'Стандарт', limit: 50,  cls: 'border-purple-500/50 bg-purple-500/10 text-purple-300' },
  { id: 'full',     label: 'Полный',   limit: 100, cls: 'border-orange-500/50 bg-orange-500/10 text-orange-300' },
] as const;

export default function DashboardPage() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const { user } = useAuth();

  const [recalcState, setRecalcState] = useState<any>(null);
  const [scanState, setScanState] = useState<any>(null);
  const [analyzeMode, setAnalyzeMode] = useState<'fast' | 'standard' | 'full'>('standard');
  const [analyzeEstimate, setAnalyzeEstimate] = useState<any>(null);
  const [analyzeState, setAnalyzeState] = useState<any>(null);
  const [showAiPanel, setShowAiPanel] = useState(false);
  const [showCostLog, setShowCostLog] = useState(false);
  const [costLog, setCostLog] = useState<any>(null);

  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ['dashboard-summary'],
    queryFn: fetchDashboardSummary,
    refetchInterval: 60_000,
  });

  const { data: trends } = useQuery({
    queryKey: ['trends', 30],
    queryFn: () => fetchTrends(30),
  });

  const { data: categories } = useQuery({
    queryKey: ['top-categories'],
    queryFn: fetchTopCategories,
  });

  const { data: profitableLots } = useQuery({
    queryKey: ['lots-profitable-preview'],
    queryFn: () => fetchLots({ is_profitable: true, confidence_level: 'high', per_page: 5 }),
  });

  // ── Recalculate ───────────────────────────────────────────────────────────
  const pollRecalcStatus = useCallback(async () => {
    try {
      const s = await getRecalculateStatus();
      setRecalcState(s);
      if (s.running) setTimeout(pollRecalcStatus, 1000);
      else if (s.finished) {
        qc.invalidateQueries({ queryKey: ['dashboard-summary'] });
        toast('Пересчёт прибыльности завершён', 'success');
      }
    } catch {}
  }, [qc, toast]);

  useEffect(() => {
    getRecalculateStatus().then(s => { if (s.running || s.finished) setRecalcState(s); }).catch(() => {});
  }, []);

  const handleRecalculate = async () => {
    try {
      setRecalcState({ running: true, pct: 0, done: 0, total: 0, finished: false });
      await triggerRecalculate();
      setTimeout(pollRecalcStatus, 800);
    } catch {
      toast('Ошибка запуска пересчёта', 'error');
      setRecalcState(null);
    }
  };

  const pollScanStatus = useCallback(async () => {
    try {
      const s = await getScanStatus();
      setScanState(s);
      if (s.running) {
        setTimeout(pollScanStatus, 1500);
      } else if (s.finished) {
        qc.invalidateQueries({ queryKey: ['dashboard-summary'] });
        qc.invalidateQueries({ queryKey: ['lots-profitable-preview'] });
        if (s.error) {
          toast(`Сканирование завершилось с ошибкой: ${s.error}`, 'error');
        } else {
          const msg = `Сканирование завершено. Новых лотов: ${s.lots_new ?? 0}`;
          toast(msg, 'success');
        }
      }
    } catch {}
  }, [qc, toast]);

  // On first mount: if a scan is already running (e.g. user reloaded the
  // page mid-scan), pick it up so the progress bar continues from where it was.
  useEffect(() => {
    getScanStatus().then(s => {
      if (s.running || s.finished) {
        setScanState(s);
        if (s.running) setTimeout(pollScanStatus, 1500);
      }
    }).catch(() => {});
  }, [pollScanStatus]);

  const handleTriggerScan = async () => {
    try {
      const r = await triggerScan();
      if (r.status === 'already_running') {
        toast('Сканирование уже выполняется', 'info');
        setTimeout(pollScanStatus, 500);
        return;
      }
      // Optimistic: start polling immediately so the bar appears without delay
      setScanState({
        running: true,
        finished: false,
        total: r.total ?? 0,
        done: 0,
        pct: 5,
        tenders_new: 0,
        lots_new: 0,
        error: null,
      });
      setTimeout(pollScanStatus, 800);
    } catch (e: any) {
      const msg = e?.response?.data?.detail || 'Ошибка запуска сканирования';
      toast(msg, 'error');
      setScanState(null);
    }
  };

  // ── AI Analysis ───────────────────────────────────────────────────────────
  useEffect(() => {
    getAnalyzeEstimate(analyzeMode).then(setAnalyzeEstimate).catch(() => {});
  }, [analyzeMode]);

  useEffect(() => {
    getAnalyzeStatus().then(s => { if (s.running || s.finished) setAnalyzeState(s); }).catch(() => {});
  }, []);

  const pollAnalyzeStatus = useCallback(async () => {
    try {
      const s = await getAnalyzeStatus();
      setAnalyzeState(s);
      if (s.running) setTimeout(pollAnalyzeStatus, 1200);
      else if (s.finished) {
        qc.invalidateQueries({ queryKey: ['dashboard-summary'] });
        qc.invalidateQueries({ queryKey: ['lots-profitable-preview'] });
        toast(`AI-анализ завершён. Обработано: ${s.done} лотов`, 'success');
      }
    } catch {}
  }, [qc, toast]);

  const handleAnalyze = async () => {
    try {
      setAnalyzeState({ running: true, total: analyzeEstimate?.will_analyze ?? 0, done: 0, pct: 0,
                        mode: analyzeMode, cost_estimate_usd: analyzeEstimate?.cost_estimate_usd ?? 0,
                        cost_actual_usd: 0, finished: false, skipped: 0, errors: 0, model: analyzeEstimate?.model ?? '' });
      await triggerAnalyzeLots(analyzeMode);
      setTimeout(pollAnalyzeStatus, 800);
    } catch {
      toast('Ошибка запуска AI-анализа', 'error');
      setAnalyzeState(null);
    }
  };

  const handleShowCostLog = async () => {
    if (!showCostLog && !costLog) {
      try { setCostLog(await getAiCostLog()); } catch {}
    }
    setShowCostLog(v => !v);
  };

  const greeting = () => {
    const h = new Date().getHours();
    if (h < 12) return 'Доброе утро';
    if (h < 18) return 'Добрый день';
    return 'Добрый вечер';
  };

  return (
    <div className="p-6 max-w-screen-xl mx-auto">

      {/* ── Header ────────────────────────────────────────────────────────── */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold text-white">
            {greeting()}{user?.company_name ? `, ${user.company_name}` : ''} 👋
          </h1>
          <p className="text-gray-400 text-sm mt-1">
            {summary?.last_scan_at
              ? `Последнее сканирование: ${formatDate(summary.last_scan_at)}`
              : 'Загрузка данных...'}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={handleRecalculate}
            disabled={recalcState?.running}
            className="btn-secondary flex items-center gap-2 text-sm"
          >
            <Calculator className="w-4 h-4" />
            Пересчитать маржу
          </button>
          <button
            onClick={() => setShowAiPanel(v => !v)}
            className="btn-secondary flex items-center gap-2 text-sm"
          >
            <BrainCircuit className="w-4 h-4 text-purple-400" />
            AI-анализ
          </button>
          <button onClick={handleTriggerScan} className="btn-primary flex items-center gap-2 text-sm">
            <RefreshCw className="w-4 h-4" />
            Сканировать
          </button>
        </div>
      </div>

      {/* ── Progress bars ─────────────────────────────────────────────────── */}
      {scanState && (scanState.running || scanState.finished) && (
        <div
          className={`card mb-4 border ${
            scanState.error
              ? 'border-red-700/40 bg-red-500/5'
              : scanState.finished
              ? 'border-green-700/40 bg-green-500/5'
              : 'border-blue-700/40 bg-blue-500/5'
          }`}
        >
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-gray-200">
              {scanState.error
                ? '❌ Ошибка сканирования'
                : scanState.finished
                ? '✅ Сканирование завершено'
                : '🔄 Сканирование запущено... (макс. ' + (scanState.total || 20) + ' тендеров)'}
            </span>
            <span className="text-xs text-gray-400">
              {scanState.finished
                ? `${scanState.done} / ${scanState.total}`
                : `${scanState.pct}%`}
            </span>
          </div>
          <div className="w-full bg-gray-800 rounded-full h-1.5">
            <div
              className={`h-1.5 rounded-full transition-all ${
                scanState.error
                  ? 'bg-red-500'
                  : scanState.finished
                  ? 'bg-green-500'
                  : 'bg-blue-500'
              }`}
              style={{ width: `${scanState.pct}%` }}
            />
          </div>
          {scanState.finished && !scanState.error && (
            <div className="flex gap-6 mt-2 text-xs">
              <span className="text-green-400">
                Новых лотов: <strong>{scanState.lots_new}</strong>
              </span>
              <span className="text-gray-400">
                Новых тендеров: <strong>{scanState.tenders_new}</strong>
              </span>
              <button
                type="button"
                onClick={() => setScanState(null)}
                className="ml-auto text-gray-500 hover:text-gray-300 text-xs"
              >
                Скрыть
              </button>
            </div>
          )}
          {scanState.error && (
            <p className="text-xs text-red-300 mt-2">{scanState.error}</p>
          )}
        </div>
      )}

      {recalcState && (recalcState.running || recalcState.finished) && (
        <div className={`card mb-4 border ${recalcState.finished ? 'border-green-700/40 bg-green-500/5' : 'border-blue-700/40 bg-blue-500/5'}`}>
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm font-medium text-gray-200">
              {recalcState.finished ? '✅ Пересчёт завершён' : '⚙️ Пересчёт прибыльности...'}
            </span>
            <span className="text-xs text-gray-400">{recalcState.done} / {recalcState.total} ({recalcState.pct}%)</span>
          </div>
          <div className="w-full bg-gray-800 rounded-full h-1.5">
            <div className={`h-1.5 rounded-full transition-all ${recalcState.finished ? 'bg-green-500' : 'bg-blue-500'}`}
              style={{ width: `${recalcState.pct}%` }} />
          </div>
          {recalcState.finished && (
            <div className="flex gap-6 mt-2 text-xs">
              <span className="text-green-400">Прибыльных: <strong>{recalcState.profitable}</strong></span>
              <span className="text-gray-400">Не прибыльных: <strong>{recalcState.not_profitable}</strong></span>
            </div>
          )}
        </div>
      )}

      {/* ── AI Analysis Panel ─────────────────────────────────────────────── */}
      {showAiPanel && (
        <div className="card mb-4 border-purple-700/30 bg-purple-500/5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="font-semibold text-white flex items-center gap-2">
              <BrainCircuit className="w-4 h-4 text-purple-400" />
              AI-анализ тендеров
              <span className="text-xs text-gray-500 font-normal">(GPT-4o · ~$0.007/лот)</span>
            </h2>
            <button onClick={handleShowCostLog} className="text-xs text-gray-500 hover:text-gray-300 flex items-center gap-1">
              <History className="w-3.5 h-3.5" />
              История расходов
            </button>
          </div>

          <div className="flex gap-2 mb-4">
            {MODES.map(m => (
              <button key={m.id} onClick={() => setAnalyzeMode(m.id)}
                disabled={analyzeState?.running}
                className={`flex-1 rounded-lg border px-3 py-2.5 text-sm font-medium transition-all disabled:opacity-40
                  ${analyzeMode === m.id ? m.cls : 'border-gray-700 text-gray-400 hover:border-gray-600'}`}>
                <div>{m.label}</div>
                <div className="text-xs opacity-60">до {m.limit} лотов</div>
              </button>
            ))}
          </div>

          {analyzeEstimate && !analyzeState?.running && !analyzeState?.finished && (
            <div className="rounded-lg bg-gray-800 border border-gray-700 px-4 py-3 mb-3">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm text-gray-300">
                    Будет проанализировано: <strong className="text-white">{analyzeEstimate.will_analyze}</strong> лотов
                  </p>
                  <p className="text-xs text-gray-500 mt-0.5">
                    Стоимость: ~<strong className={analyzeEstimate.cost_estimate_usd > 0.5 ? 'text-orange-400' : 'text-green-400'}>
                      ${analyzeEstimate.cost_estimate_usd?.toFixed(3)}
                    </strong>
                    {' · '}{analyzeEstimate.model}
                  </p>
                </div>
                <button onClick={handleAnalyze} disabled={analyzeEstimate.will_analyze === 0}
                  className="btn-primary text-sm flex items-center gap-1.5 disabled:opacity-40">
                  <Sparkles className="w-3.5 h-3.5" />
                  Запустить
                </button>
              </div>
            </div>
          )}

          {analyzeState && (analyzeState.running || analyzeState.finished) && (
            <div className={`rounded-lg border px-4 py-3 ${analyzeState.finished ? 'border-green-700/40 bg-green-500/5' : 'border-purple-700/40 bg-purple-500/5'}`}>
              <div className="flex items-center justify-between mb-2">
                <span className="text-sm font-medium text-gray-200">
                  {analyzeState.finished ? '✅ Анализ завершён' : '🧠 Анализирую...'}
                </span>
                <span className="text-xs text-gray-400">{analyzeState.done} / {analyzeState.total} ({analyzeState.pct}%)</span>
              </div>
              <div className="w-full bg-gray-800 rounded-full h-1.5 mb-2">
                <div className={`h-1.5 rounded-full transition-all ${analyzeState.finished ? 'bg-green-500' : 'bg-purple-500'}`}
                  style={{ width: `${analyzeState.pct}%` }} />
              </div>
              <div className="flex justify-between text-xs text-gray-500">
                <span>Пропущено: {analyzeState.skipped} · Ошибок: {analyzeState.errors}</span>
                {analyzeState.finished && <span className="text-orange-400">Потрачено: ${analyzeState.cost_actual_usd?.toFixed(3)}</span>}
              </div>
            </div>
          )}

          {showCostLog && costLog && (
            <div className="mt-3 pt-3 border-t border-gray-700">
              <div className="flex justify-between text-xs text-gray-400 mb-2">
                <span>Всего лотов: <strong className="text-gray-200">{costLog.total_lots_analyzed}</strong></span>
                <span>Всего потрачено: <strong className="text-orange-400">${costLog.total_cost_usd?.toFixed(3)}</strong></span>
              </div>
              {costLog.recent_runs?.map((r: any, i: number) => (
                <div key={i} className="flex justify-between text-xs py-1 border-b border-gray-800 last:border-0 text-gray-400">
                  <span>{new Date(r.timestamp).toLocaleString('ru', { day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit' })} · {r.mode} · {r.lots_processed} лотов</span>
                  <span className="text-orange-400">${r.cost_usd?.toFixed(3)}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Stat cards ────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-2 xl:grid-cols-4 gap-4 mb-6">
        <StatCard
          title="Всего лотов"
          value={summaryLoading ? '...' : (summary?.total_lots ?? 0).toLocaleString('ru')}
          subtitle={`Сегодня: +${summary?.lots_today ?? 0}`}
          icon={<Target className="w-4 h-4" />}
          color="blue"
        />
        <StatCard
          title="Прибыльных"
          value={summaryLoading ? '...' : (summary?.profitable_lots ?? 0).toLocaleString('ru')}
          subtitle={`Сегодня: +${summary?.profitable_today ?? 0}`}
          icon={<TrendingUp className="w-4 h-4" />}
          color="green"
        />
        <StatCard
          title="Высокая уверенность"
          value={summaryLoading ? '...' : (summary?.high_confidence ?? 0).toLocaleString('ru')}
          subtitle="AI рекомендует"
          icon={<ShieldCheck className="w-4 h-4" />}
          color="yellow"
        />
        <StatCard
          title="Средняя маржа"
          value={summaryLoading ? '...' : `${summary?.avg_margin ?? 0}%`}
          subtitle={`Объём: ${formatMoney(summary?.total_budget_scanned)}`}
          icon={<DollarSign className="w-4 h-4" />}
          color="purple"
        />
      </div>

      {/* ── Charts ────────────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-4 mb-6">
        {/* Trend chart */}
        <div className="card xl:col-span-2">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-white flex items-center gap-2">
              <BarChart2 className="w-4 h-4 text-blue-400" />
              Динамика за 30 дней
            </h2>
          </div>
          {trends && trends.length > 0 ? (
            <ResponsiveContainer width="100%" height={200}>
              <AreaChart data={trends} margin={{ top: 4, right: 4, left: -24, bottom: 0 }}>
                <defs>
                  <linearGradient id="colorTotal" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#3b82f6" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#3b82f6" stopOpacity={0} />
                  </linearGradient>
                  <linearGradient id="colorProfit" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#10b981" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="date" tickFormatter={d => d.slice(5)} tick={{ fontSize: 10 }} />
                <YAxis tick={{ fontSize: 10 }} />
                <Tooltip
                  formatter={(v: any, n: string) => [v, n === 'tenders_found' ? 'Найдено' : 'Прибыльных']}
                  contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 8, color: '#f3f4f6' }}
                />
                <Area type="monotone" dataKey="tenders_found" stroke="#3b82f6" fill="url(#colorTotal)" strokeWidth={2} />
                <Area type="monotone" dataKey="profitable_found" stroke="#10b981" fill="url(#colorProfit)" strokeWidth={2} />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[200px] flex items-center justify-center text-gray-600 text-sm">
              Данных пока нет — запустите сканирование
            </div>
          )}
        </div>

        {/* Top categories */}
        <div className="card">
          <h2 className="text-sm font-semibold text-white mb-4 flex items-center gap-2">
            <Zap className="w-4 h-4 text-yellow-400" />
            Топ категории
          </h2>
          {categories && categories.length > 0 ? (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={categories.slice(0, 6)} layout="vertical" margin={{ top: 0, right: 8, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 10 }} />
                <YAxis type="category" dataKey="category" tick={{ fontSize: 9 }} width={60}
                  tickFormatter={c => ({ product: 'Товар', software_service: 'IT', other: 'Прочее' }[c as string] || c)} />
                <Tooltip formatter={(v: any) => [v, 'Лотов']}
                  contentStyle={{ background: '#111827', border: '1px solid #374151', borderRadius: 8, color: '#f3f4f6' }} />
                <Bar dataKey="count" fill="#3b82f6" radius={[0, 4, 4, 0]} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[200px] flex items-center justify-center text-gray-600 text-sm">Нет данных</div>
          )}
        </div>
      </div>

      {/* ── Hot Lots Widget ────────────────────────────────────────────────── */}
      <HotLots />

      {/* ── Quick links ───────────────────────────────────────────────────── */}
      <div className="mt-4 flex flex-wrap gap-2">
        <Link href="/tenders?is_profitable=true&confidence_level=high" className="btn-success text-sm flex items-center gap-1.5">
          <TrendingUp className="w-3.5 h-3.5" />
          Прибыльные тендеры
        </Link>
        <Link href="/tenders?category=software_service" className="btn-secondary text-sm">IT-тендеры</Link>
        <Link href="/tenders?platform=goszakup" className="btn-secondary text-sm">GosZakup</Link>
        <Link href="/tenders?platform=zakupsk" className="btn-secondary text-sm">Zakup SK</Link>
        <Link href="/analytics" className="btn-secondary text-sm flex items-center gap-1.5">
          <BarChart2 className="w-3.5 h-3.5" />
          Аналитика
        </Link>
      </div>
    </div>
  );
}
