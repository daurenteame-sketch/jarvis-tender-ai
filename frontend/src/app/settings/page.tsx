'use client';
import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Settings, Bell, Filter, CreditCard, CheckCircle, Clock,
  Plus, X, Zap, Star, Building2, AlertCircle, ChevronRight,
} from 'lucide-react';
import {
  getUserSettings, saveUserSettings, getSubscription, activateTrial,
  type FilterSettings, type NotificationSettings,
} from '@/lib/api';
import { formatMoney } from '@/lib/utils';
import { useToast } from '@/components/ui/Toast';
import { cn } from '@/lib/utils';

// ── Constants ─────────────────────────────────────────────────────────────────

const CATEGORIES = [
  { id: 'product',          label: 'Товары / Оборудование' },
  { id: 'software_service', label: 'IT / ПО' },
  { id: 'other',            label: 'Прочие услуги' },
];

const PLATFORMS = [
  { id: 'goszakup', label: 'GosZakup',  badge: 'badge-blue' },
  { id: 'zakupsk',  label: 'Zakup SK',  badge: 'badge-yellow' },
];

const PLAN_LABELS: Record<string, string> = {
  free: 'Бесплатный', trial: 'Пробный', pro: 'Pro', enterprise: 'Enterprise',
};

// ── Plan badge ─────────────────────────────────────────────────────────────────
function PlanBadge({ plan }: { plan: string }) {
  const cls: Record<string, string> = {
    free:       'bg-gray-500/15 text-gray-400 border border-gray-500/25',
    trial:      'badge-blue',
    pro:        'badge-green',
    enterprise: 'badge-purple',
  };
  return (
    <span className={cn('inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-semibold', cls[plan] || cls.free)}>
      {plan === 'pro' && <Star className="w-3 h-3" />}
      {plan === 'trial' && <Clock className="w-3 h-3" />}
      {PLAN_LABELS[plan] || plan}
    </span>
  );
}

// ── Toggle ─────────────────────────────────────────────────────────────────────
function Toggle({ value, onChange }: { value: boolean; onChange: (v: boolean) => void }) {
  return (
    <button
      type="button"
      onClick={() => onChange(!value)}
      className={cn(
        'relative w-11 h-6 rounded-full transition-colors shrink-0',
        value ? 'bg-blue-600' : 'bg-gray-700'
      )}
    >
      <span className={cn(
        'absolute top-0.5 w-5 h-5 bg-white rounded-full shadow transition-transform',
        value ? 'translate-x-5' : 'translate-x-0.5'
      )} />
    </button>
  );
}

// ── Section wrapper ────────────────────────────────────────────────────────────
function Section({ icon: Icon, title, description, children }: {
  icon: React.ElementType; title: string; description?: string; children: React.ReactNode;
}) {
  return (
    <div className="bg-gray-900 rounded-xl border border-gray-800 p-6 space-y-4">
      <div className="flex items-center gap-2">
        <Icon className="w-4 h-4 text-gray-500" />
        <h2 className="font-semibold text-white">{title}</h2>
      </div>
      {description && <p className="text-sm text-gray-500">{description}</p>}
      {children}
    </div>
  );
}

// ── Main ──────────────────────────────────────────────────────────────────────
export default function SettingsPage() {
  const qc = useQueryClient();
  const { toast } = useToast();

  const { data: savedSettings, isLoading: settingsLoading } = useQuery({
    queryKey: ['user-settings'],
    queryFn: getUserSettings,
  });
  const { data: subscription, isLoading: subLoading } = useQuery({
    queryKey: ['subscription'],
    queryFn: getSubscription,
  });

  const [filters, setFilters] = useState<FilterSettings>({
    categories: [], keywords: [], exclude_keywords: [],
    platforms: ['goszakup'], min_budget: null, max_budget: null, min_margin: null, regions: [],
  });
  const [notif, setNotif] = useState<NotificationSettings>({
    telegram: true, email: false, min_profit_for_notify: 200000,
  });
  const [newKeyword, setNewKeyword] = useState('');
  const [newExclude, setNewExclude] = useState('');

  useEffect(() => {
    if (savedSettings) {
      setFilters(savedSettings.filters);
      setNotif(savedSettings.notifications);
    }
  }, [savedSettings]);

  const saveMutation = useMutation({
    mutationFn: () => saveUserSettings({ filters, notifications: notif }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['user-settings'] });
      toast('Настройки сохранены', 'success');
    },
    onError: () => toast('Ошибка сохранения', 'error'),
  });

  const trialMutation = useMutation({
    mutationFn: activateTrial,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['subscription'] });
      toast('Пробный период активирован! 14 дней Pro бесплатно.', 'success');
    },
    onError: () => toast('Пробный период уже был использован', 'error'),
  });

  const toggleCategory = (id: string) =>
    setFilters(f => ({ ...f, categories: f.categories.includes(id) ? f.categories.filter(c => c !== id) : [...f.categories, id] }));

  const togglePlatform = (id: string) =>
    setFilters(f => ({ ...f, platforms: f.platforms.includes(id) ? f.platforms.filter(p => p !== id) : [...f.platforms, id] }));

  const addKeyword = () => {
    const kw = newKeyword.trim().toLowerCase();
    if (kw && !filters.keywords.includes(kw)) setFilters(f => ({ ...f, keywords: [...f.keywords, kw] }));
    setNewKeyword('');
  };
  const addExclude = () => {
    const kw = newExclude.trim().toLowerCase();
    if (kw && !filters.exclude_keywords.includes(kw)) setFilters(f => ({ ...f, exclude_keywords: [...f.exclude_keywords, kw] }));
    setNewExclude('');
  };

  if (settingsLoading || subLoading) {
    return (
      <div className="p-8 flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500" />
      </div>
    );
  }

  const plan = subscription?.plan || 'free';

  return (
    <div className="p-6 max-w-3xl mx-auto space-y-5">
      {/* Header */}
      <div className="flex items-center gap-3 mb-2">
        <div className="w-10 h-10 bg-blue-500/10 rounded-xl flex items-center justify-center border border-blue-500/20">
          <Settings className="w-5 h-5 text-blue-400" />
        </div>
        <div>
          <h1 className="text-2xl font-bold text-white">Настройки</h1>
          <p className="text-sm text-gray-500">Фильтры, уведомления и подписка</p>
        </div>
      </div>

      {/* ── Subscription ──────────────────────────────────────────────────── */}
      <div className={cn(
        'rounded-xl border-2 p-6',
        plan === 'pro'        ? 'border-green-500/40 bg-green-500/5' :
        plan === 'enterprise' ? 'border-purple-500/40 bg-purple-500/5' :
        plan === 'trial'      ? 'border-blue-500/40 bg-blue-500/5' :
                                'border-gray-700 bg-gray-900'
      )}>
        <div className="flex items-start justify-between gap-4">
          <div className="flex items-center gap-3">
            <CreditCard className={cn('w-5 h-5', plan === 'pro' ? 'text-green-400' : plan === 'trial' ? 'text-blue-400' : 'text-gray-500')} />
            <div>
              <div className="flex items-center gap-2">
                <span className="font-semibold text-white">Ваш тариф</span>
                <PlanBadge plan={plan} />
              </div>
              {subscription?.days_left != null && (
                <p className="text-sm text-gray-400 mt-0.5">
                  Осталось дней: <strong className="text-gray-200">{subscription.days_left}</strong>
                  {plan === 'trial' && <span className="text-gray-500"> (пробный период)</span>}
                </p>
              )}
              {plan === 'free' && (
                <p className="text-sm text-gray-500 mt-0.5">
                  До {subscription?.limits?.lots_per_day} лотов в день · базовая аналитика
                </p>
              )}
            </div>
          </div>

          <div className="flex gap-2 flex-wrap justify-end shrink-0">
            {plan === 'free' && !subscription?.trial_used && (
              <button
                onClick={() => trialMutation.mutate()}
                disabled={trialMutation.isPending}
                className="flex items-center gap-1.5 bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium px-3 py-1.5 rounded-lg transition-colors disabled:opacity-50"
              >
                <Zap className="w-3.5 h-3.5" />
                {trialMutation.isPending ? 'Активация...' : 'Попробовать Pro'}
              </button>
            )}
            {plan !== 'pro' && plan !== 'enterprise' && (
              <a
                href="https://t.me/jarvis_tender_kz"
                target="_blank"
                rel="noreferrer"
                className="flex items-center gap-1.5 text-sm font-medium px-3 py-1.5 rounded-lg border border-gray-700 text-gray-400 hover:bg-gray-800 transition-colors"
              >
                {plan === 'trial' ? <><Star className="w-3.5 h-3.5" />Купить Pro</> : 'О Pro'}
                <ChevronRight className="w-3.5 h-3.5" />
              </a>
            )}
          </div>
        </div>

        {/* Feature list */}
        {(subscription?.features || []).length > 0 && (
          <div className="mt-4 grid grid-cols-2 gap-2">
            {(subscription?.features || []).map((f: string) => (
              <div key={f} className="flex items-center gap-1.5 text-sm text-gray-400">
                <CheckCircle className="w-3.5 h-3.5 text-green-500 shrink-0" />
                {f}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* ── Pricing cards ─────────────────────────────────────────────────── */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        {[
          {
            name: 'Free', price: '0 ₸/мес', color: 'border-gray-700',
            features: ['5 лотов в день', 'Базовая аналитика', 'Telegram уведомления'],
            cta: null, active: plan === 'free',
          },
          {
            name: 'Pro', price: '9 900 ₸/мес', color: 'border-blue-500/40',
            features: ['Без лимитов', 'AI-анализ всех лотов', 'Email + Telegram', 'Фильтры по ключевым словам', 'Экспорт в Excel'],
            cta: 'https://t.me/jarvis_tender_kz', active: plan === 'pro' || plan === 'trial',
          },
          {
            name: 'Enterprise', price: 'По запросу', color: 'border-purple-500/30',
            features: ['Несколько пользователей', 'API доступ', 'Выделенный менеджер', 'Кастомные интеграции'],
            cta: 'https://t.me/jarvis_tender_kz', active: plan === 'enterprise',
          },
        ].map(p => (
          <div key={p.name} className={cn('rounded-xl border p-4 bg-gray-900 relative', p.color, p.active && 'ring-1 ring-offset-0 ring-offset-gray-950')}>
            {p.active && (
              <span className="absolute -top-2 left-3 text-[10px] font-bold bg-blue-600 text-white px-2 py-0.5 rounded-full">
                Ваш план
              </span>
            )}
            <p className="font-bold text-white text-base">{p.name}</p>
            <p className="text-blue-400 font-semibold text-sm mt-0.5 mb-3">{p.price}</p>
            <ul className="space-y-1.5">
              {p.features.map(f => (
                <li key={f} className="flex items-center gap-1.5 text-xs text-gray-400">
                  <CheckCircle className="w-3 h-3 text-green-500 shrink-0" />
                  {f}
                </li>
              ))}
            </ul>
            {p.cta && !p.active && (
              <a
                href={p.cta} target="_blank" rel="noreferrer"
                className="mt-3 block w-full text-center py-1.5 rounded-lg bg-blue-600/20 border border-blue-500/30 text-blue-400 text-xs font-medium hover:bg-blue-600/30 transition-colors"
              >
                Подключить
              </a>
            )}
          </div>
        ))}
      </div>

      {/* ── Platforms ─────────────────────────────────────────────────────── */}
      <Section icon={Building2} title="Платформы" description="Откуда получать тендеры">
        <div className="flex flex-wrap gap-3">
          {PLATFORMS.map(({ id, label, badge }) => {
            const active = filters.platforms.includes(id);
            return (
              <button
                key={id}
                onClick={() => togglePlatform(id)}
                className={cn(
                  'flex items-center gap-2 px-4 py-2.5 rounded-xl border-2 text-sm font-medium transition-all',
                  active
                    ? 'border-blue-500/60 bg-blue-500/10 text-blue-300'
                    : 'border-gray-700 text-gray-500 hover:border-gray-600'
                )}
              >
                <div className={cn('w-2 h-2 rounded-full', active ? 'bg-blue-400' : 'bg-gray-600')} />
                {label}
              </button>
            );
          })}
        </div>
      </Section>

      {/* ── Categories ────────────────────────────────────────────────────── */}
      <Section icon={Filter} title="Категории" description="Оставьте пустым — будут показаны все категории">
        <div className="flex flex-wrap gap-3">
          {CATEGORIES.map(({ id, label }) => {
            const active = filters.categories.includes(id);
            return (
              <button
                key={id}
                onClick={() => toggleCategory(id)}
                className={cn(
                  'px-4 py-2.5 rounded-xl border-2 text-sm font-medium transition-all',
                  active
                    ? 'border-blue-500/60 bg-blue-500/10 text-blue-300'
                    : 'border-gray-700 text-gray-500 hover:border-gray-600'
                )}
              >
                {label}
              </button>
            );
          })}
        </div>
      </Section>

      {/* ── Keywords ──────────────────────────────────────────────────────── */}
      <Section icon={Filter} title="Ключевые слова">
        {/* Include */}
        <div className="space-y-2">
          <p className="text-sm font-medium text-gray-300">Искать тендеры, содержащие:</p>
          <div className="flex gap-2">
            <input
              value={newKeyword}
              onChange={e => setNewKeyword(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && addKeyword()}
              placeholder="принтер, ноутбук, мебель..."
              className="input flex-1"
            />
            <button onClick={addKeyword} className="p-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg transition-colors">
              <Plus className="w-4 h-4" />
            </button>
          </div>
          <div className="flex flex-wrap gap-2 min-h-[32px]">
            {filters.keywords.map(kw => (
              <span key={kw} className="flex items-center gap-1.5 badge-blue text-sm px-3 py-1 rounded-full">
                {kw}
                <button onClick={() => setFilters(f => ({ ...f, keywords: f.keywords.filter(k => k !== kw) }))} className="hover:text-blue-200 transition-colors">
                  <X className="w-3 h-3" />
                </button>
              </span>
            ))}
            {filters.keywords.length === 0 && (
              <span className="text-sm text-gray-600 italic">Все слова (фильтр не задан)</span>
            )}
          </div>
        </div>

        {/* Exclude */}
        <div className="space-y-2 pt-3 border-t border-gray-800">
          <p className="text-sm font-medium text-gray-300">Исключить тендеры со словами:</p>
          <div className="flex gap-2">
            <input
              value={newExclude}
              onChange={e => setNewExclude(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && addExclude()}
              placeholder="услуги, обслуживание..."
              className="input flex-1"
            />
            <button onClick={addExclude} className="p-2 bg-red-600/80 hover:bg-red-600 text-white rounded-lg transition-colors">
              <Plus className="w-4 h-4" />
            </button>
          </div>
          <div className="flex flex-wrap gap-2 min-h-[32px]">
            {filters.exclude_keywords.map(kw => (
              <span key={kw} className="flex items-center gap-1.5 badge-red text-sm px-3 py-1 rounded-full">
                {kw}
                <button onClick={() => setFilters(f => ({ ...f, exclude_keywords: f.exclude_keywords.filter(k => k !== kw) }))} className="hover:text-red-200 transition-colors">
                  <X className="w-3 h-3" />
                </button>
              </span>
            ))}
            {filters.exclude_keywords.length === 0 && (
              <span className="text-sm text-gray-600 italic">Ничего не исключено</span>
            )}
          </div>
        </div>
      </Section>

      {/* ── Budget & Margin ────────────────────────────────────────────────── */}
      <Section icon={CreditCard} title="Бюджет и маржа">
        <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-gray-400">Мин. бюджет (₸)</label>
            <input
              type="number"
              value={filters.min_budget ?? ''}
              onChange={e => setFilters(f => ({ ...f, min_budget: e.target.value ? Number(e.target.value) : null }))}
              placeholder="500 000"
              className="input w-full"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-gray-400">Макс. бюджет (₸)</label>
            <input
              type="number"
              value={filters.max_budget ?? ''}
              onChange={e => setFilters(f => ({ ...f, max_budget: e.target.value ? Number(e.target.value) : null }))}
              placeholder="50 000 000"
              className="input w-full"
            />
          </div>
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-gray-400">Мин. маржа (%)</label>
            <input
              type="number"
              value={filters.min_margin ?? ''}
              onChange={e => setFilters(f => ({ ...f, min_margin: e.target.value ? Number(e.target.value) : null }))}
              placeholder="30" min={0} max={100}
              className="input w-full"
            />
          </div>
        </div>
        {(filters.min_budget || filters.max_budget) && (
          <p className="text-xs text-gray-600">
            Диапазон: {filters.min_budget ? formatMoney(filters.min_budget) : '0'} — {filters.max_budget ? formatMoney(filters.max_budget) : '∞'}
          </p>
        )}
      </Section>

      {/* ── Notifications ─────────────────────────────────────────────────── */}
      <Section icon={Bell} title="Уведомления">
        <div className="space-y-2">
          {[
            { key: 'telegram' as const, label: 'Telegram уведомления', desc: 'Получать новые прибыльные тендеры в Telegram' },
            { key: 'email'    as const, label: 'Email уведомления',    desc: 'Ежедневный дайджест прибыльных тендеров' },
          ].map(({ key, label, desc }) => (
            <div key={key} className="flex items-center justify-between p-3 rounded-xl border border-gray-800 hover:bg-gray-800/40 transition-colors">
              <div>
                <p className="text-sm font-medium text-gray-200">{label}</p>
                <p className="text-xs text-gray-500">{desc}</p>
              </div>
              <Toggle value={notif[key]} onChange={v => setNotif(n => ({ ...n, [key]: v }))} />
            </div>
          ))}
        </div>
        <div className="space-y-1.5">
          <label className="text-sm font-medium text-gray-400">Уведомлять только если прибыль больше (₸)</label>
          <input
            type="number"
            value={notif.min_profit_for_notify}
            onChange={e => setNotif(n => ({ ...n, min_profit_for_notify: Number(e.target.value) }))}
            className="input w-full sm:w-64"
          />
          <p className="text-xs text-gray-600">Текущий порог: {formatMoney(notif.min_profit_for_notify)}</p>
        </div>
      </Section>

      {/* Save */}
      <div className="flex items-center gap-4 pb-8">
        <button
          onClick={() => saveMutation.mutate()}
          disabled={saveMutation.isPending}
          className="btn-primary flex items-center gap-2 px-6 py-2.5 disabled:opacity-50"
        >
          {saveMutation.isPending ? (
            <><div className="w-4 h-4 border-2 border-white/30 border-t-white rounded-full animate-spin" />Сохранение...</>
          ) : (
            'Сохранить настройки'
          )}
        </button>
      </div>
    </div>
  );
}
