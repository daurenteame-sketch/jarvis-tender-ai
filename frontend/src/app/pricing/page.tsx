'use client';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { CheckCircle, Star, Clock, Zap, Building2, ChevronRight } from 'lucide-react';
import { getSubscription, activateTrial } from '@/lib/api';
import { useToast } from '@/components/ui/Toast';
import { cn } from '@/lib/utils';

const PLANS = [
  {
    key:      'free',
    name:     'Free',
    price:    '0 ₸',
    period:   '',
    desc:     'Старт без рисков',
    color:    'border-gray-700',
    highlight: false,
    features: [
      '5 лотов в день',
      'Базовая аналитика',
      'Telegram уведомления',
      'Поиск по базе тендеров',
    ],
    cta: null,
  },
  {
    key:      'pro',
    name:     'Pro',
    price:    '9 900 ₸',
    period:   '/мес',
    desc:     'Для активных поставщиков',
    color:    'border-blue-500/50',
    highlight: true,
    features: [
      'Без лимитов на лоты',
      'AI-анализ всех тендеров',
      'Email + Telegram уведомления',
      'Фильтры по ключевым словам',
      'Экспорт в Excel (до 5000 строк)',
      'История закупок',
      'План закупок на год',
      'Генерация заявок DOCX',
    ],
    cta: 'https://t.me/jarvis_tender_kz',
  },
  {
    key:      'enterprise',
    name:     'Enterprise',
    price:    'По запросу',
    period:   '',
    desc:     'Для команд и интеграторов',
    color:    'border-purple-500/30',
    highlight: false,
    features: [
      'Несколько пользователей',
      'API доступ',
      'Выделенный менеджер',
      'Кастомные интеграции',
      'SLA 99.9%',
      'Белая метка (White label)',
    ],
    cta: 'https://t.me/jarvis_tender_kz',
  },
];

const FAQ = [
  {
    q: 'Как активировать тариф Pro?',
    a: 'Напишите в Telegram @jarvis_tender_kz — оплата через Kaspi или банковский перевод. Активация в течение часа.',
  },
  {
    q: 'Есть ли пробный период?',
    a: 'Да — 14 дней Pro бесплатно. Активируется одной кнопкой на этой странице.',
  },
  {
    q: 'Можно ли отменить подписку?',
    a: 'Да, в любое время. Доступ сохраняется до конца оплаченного периода.',
  },
  {
    q: 'Откуда берутся данные о тендерах?',
    a: 'GosZakup.gov.kz и Zakup.sk.kz — официальные государственные площадки Казахстана.',
  },
];

export default function PricingPage() {
  const qc = useQueryClient();
  const { toast } = useToast();

  const { data: subscription } = useQuery({
    queryKey: ['subscription'],
    queryFn:  getSubscription,
  });

  const trialMutation = useMutation({
    mutationFn: activateTrial,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['subscription'] });
      toast('Пробный период активирован! 14 дней Pro бесплатно.', 'success');
    },
    onError: () => toast('Пробный период уже был использован', 'error'),
  });

  const plan     = subscription?.plan || 'free';
  const isActive = (key: string) => plan === key || (key === 'pro' && plan === 'trial');

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-10">

      {/* Header */}
      <div className="text-center space-y-2">
        <h1 className="text-3xl font-bold text-white">Тарифные планы</h1>
        <p className="text-gray-400">Выберите подходящий план для вашего бизнеса</p>
        {plan === 'trial' && (
          <div className="inline-flex items-center gap-2 mt-2 px-4 py-2 rounded-full bg-blue-500/10 border border-blue-500/30 text-blue-300 text-sm">
            <Clock className="w-4 h-4" />
            Пробный период активен · осталось {subscription?.days_left ?? '?'} дней
          </div>
        )}
      </div>

      {/* Trial CTA for free users */}
      {plan === 'free' && !subscription?.trial_used && (
        <div className="rounded-xl border border-blue-500/30 bg-blue-500/5 p-5 flex flex-col sm:flex-row items-center gap-4 justify-between">
          <div>
            <p className="font-semibold text-white">Попробуйте Pro бесплатно</p>
            <p className="text-sm text-gray-400 mt-0.5">14 дней полного доступа без ограничений — без карты</p>
          </div>
          <button
            onClick={() => trialMutation.mutate()}
            disabled={trialMutation.isPending}
            className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 text-white font-semibold px-5 py-2.5 rounded-xl transition-colors disabled:opacity-50 shrink-0"
          >
            <Zap className="w-4 h-4" />
            {trialMutation.isPending ? 'Активация...' : 'Активировать Trial'}
          </button>
        </div>
      )}

      {/* Plan cards */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
        {PLANS.map(p => (
          <div
            key={p.key}
            className={cn(
              'relative rounded-2xl border-2 bg-gray-900 p-6 flex flex-col gap-4',
              p.color,
              p.highlight && 'ring-2 ring-blue-500/30',
            )}
          >
            {p.highlight && (
              <div className="absolute -top-3 left-1/2 -translate-x-1/2 px-3 py-0.5 bg-blue-600 rounded-full text-xs font-bold text-white">
                Популярный
              </div>
            )}
            {isActive(p.key) && (
              <div className="absolute -top-3 right-4 px-3 py-0.5 bg-green-600 rounded-full text-xs font-bold text-white">
                Ваш план
              </div>
            )}

            {/* Plan header */}
            <div>
              <div className="flex items-center gap-2 mb-1">
                {p.key === 'pro' && <Star className="w-4 h-4 text-blue-400" />}
                {p.key === 'enterprise' && <Building2 className="w-4 h-4 text-purple-400" />}
                <h2 className="text-xl font-bold text-white">{p.name}</h2>
              </div>
              <p className="text-gray-500 text-sm">{p.desc}</p>
            </div>

            {/* Price */}
            <div>
              <span className="text-3xl font-bold text-white">{p.price}</span>
              {p.period && <span className="text-gray-500 text-sm ml-1">{p.period}</span>}
            </div>

            {/* Features */}
            <ul className="space-y-2 flex-1">
              {p.features.map(f => (
                <li key={f} className="flex items-start gap-2 text-sm text-gray-300">
                  <CheckCircle className="w-4 h-4 text-green-400 shrink-0 mt-0.5" />
                  {f}
                </li>
              ))}
            </ul>

            {/* CTA */}
            <div className="pt-2">
              {isActive(p.key) ? (
                <div className="w-full text-center py-2.5 rounded-xl bg-green-500/10 border border-green-500/30 text-green-400 text-sm font-medium">
                  Активен
                </div>
              ) : p.cta ? (
                <a
                  href={p.cta}
                  target="_blank"
                  rel="noreferrer"
                  className={cn(
                    'flex items-center justify-center gap-2 w-full py-2.5 rounded-xl text-sm font-semibold transition-colors',
                    p.highlight
                      ? 'bg-blue-600 hover:bg-blue-500 text-white'
                      : 'border border-gray-700 text-gray-400 hover:bg-gray-800 hover:text-white'
                  )}
                >
                  Подключить
                  <ChevronRight className="w-4 h-4" />
                </a>
              ) : (
                <div className="w-full text-center py-2.5 rounded-xl bg-gray-800 text-gray-500 text-sm">
                  Текущий план
                </div>
              )}
            </div>
          </div>
        ))}
      </div>

      {/* Feature comparison table */}
      <div className="bg-gray-900 rounded-2xl border border-gray-800 overflow-hidden">
        <div className="p-5 border-b border-gray-800">
          <h2 className="font-semibold text-white">Сравнение возможностей</h2>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800">
                <th className="text-left px-5 py-3 text-gray-500 font-medium">Функция</th>
                {PLANS.map(p => (
                  <th key={p.key} className="px-4 py-3 text-center text-gray-400 font-medium">{p.name}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-800/60">
              {[
                ['Лотов в день',                     '5',   '∞',    '∞'],
                ['Telegram уведомления',             '✓',   '✓',    '✓'],
                ['Email уведомления',                '—',   '✓',    '✓'],
                ['AI-анализ тендеров',               '—',   '✓',    '✓'],
                ['Экспорт Excel',                    '—',   '✓',    '✓'],
                ['История закупок',                  '—',   '✓',    '✓'],
                ['План закупок',                     '—',   '✓',    '✓'],
                ['Генерация заявок',                 '—',   '✓',    '✓'],
                ['API доступ',                       '—',   '—',    '✓'],
                ['Несколько пользователей',          '—',   '—',    '✓'],
                ['Выделенный менеджер',              '—',   '—',    '✓'],
              ].map(([feature, ...values]) => (
                <tr key={feature} className="hover:bg-gray-800/30 transition-colors">
                  <td className="px-5 py-3 text-gray-300">{feature}</td>
                  {values.map((v, i) => (
                    <td key={i} className="px-4 py-3 text-center">
                      {v === '✓' ? (
                        <CheckCircle className="w-4 h-4 text-green-400 mx-auto" />
                      ) : v === '—' ? (
                        <span className="text-gray-700">—</span>
                      ) : (
                        <span className="text-gray-300 font-medium">{v}</span>
                      )}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* FAQ */}
      <div className="space-y-3">
        <h2 className="font-semibold text-white text-lg">Часто задаваемые вопросы</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {FAQ.map(({ q, a }) => (
            <div key={q} className="bg-gray-900 rounded-xl border border-gray-800 p-4 space-y-1">
              <p className="font-medium text-white text-sm">{q}</p>
              <p className="text-sm text-gray-400">{a}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Contact */}
      <div className="text-center pb-8">
        <p className="text-gray-500 text-sm">
          Вопросы по тарифам?{' '}
          <a href="https://t.me/jarvis_tender_kz" target="_blank" rel="noreferrer" className="text-blue-400 hover:text-blue-300 transition-colors">
            Напишите нам в Telegram
          </a>
        </p>
      </div>
    </div>
  );
}
