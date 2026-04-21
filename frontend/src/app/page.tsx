import Link from 'next/link';
import {
  BrainCircuit, TrendingUp, Download, Bell,
  ArrowRight, CheckCircle2, Zap, BarChart2, Truck,
} from 'lucide-react';

const FEATURES = [
  {
    icon: <Truck className="w-6 h-6 text-blue-400" />,
    title: 'Поиск товара в KZ · RU · CN',
    desc: 'Для каждого тендера — 6-8 ссылок где реально купить товар: Kaspi.kz, Satu.kz, Wildberries, Ozon, Alibaba, 1688, AliExpress.',
    highlight: true,
  },
  {
    icon: <BrainCircuit className="w-6 h-6 text-purple-400" />,
    title: 'AI-анализ тендеров',
    desc: 'GPT-4o анализирует каждый лот: определяет товар, рассчитывает себестоимость и маржу по актуальным ценам Казахстана.',
  },
  {
    icon: <TrendingUp className="w-6 h-6 text-green-400" />,
    title: 'Расчёт прибыльности',
    desc: 'Автоматический расчёт маржи, прибыли и точности оценки. Сразу видно — стоит участвовать или нет.',
  },
  {
    icon: <Bell className="w-6 h-6 text-yellow-400" />,
    title: 'Telegram уведомления',
    desc: 'Мгновенно получайте прибыльные тендеры в Telegram с расчётом маржи и ссылками на поставщиков.',
  },
  {
    icon: <BarChart2 className="w-6 h-6 text-teal-400" />,
    title: 'Аналитика закупок',
    desc: 'План закупок, история тендеров, топ-заказчики. Понимайте рынок государственных закупок КЗ.',
  },
  {
    icon: <Download className="w-6 h-6 text-orange-400" />,
    title: 'Экспорт в Excel',
    desc: 'Выгрузите отфильтрованный список лотов с маржой и бюджетом в один клик. Удобно для команды.',
  },
];

const STEPS = [
  { num: '01', title: 'Регистрируйтесь', desc: 'Создайте аккаунт за 30 секунд — без карты.' },
  { num: '02', title: 'Запустите сканирование', desc: 'Система сама найдёт тендеры на всех площадках КЗ.' },
  { num: '03', title: 'Получите AI-анализ', desc: 'GPT-4o рассчитает маржу и отберёт прибыльные лоты.' },
  { num: '04', title: 'Участвуйте и зарабатывайте', desc: 'Выгружайте список в Excel, подавайте заявки.' },
];

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-gray-950 text-gray-100">
      {/* ── Nav ──────────────────────────────────────────────────────────── */}
      <nav className="border-b border-gray-800 bg-gray-950/80 backdrop-blur sticky top-0 z-50">
        <div className="max-w-6xl mx-auto px-6 h-16 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <BrainCircuit className="w-6 h-6 text-blue-400" />
            <span className="font-bold text-white text-lg">Jarvis Tender AI</span>
          </div>
          <div className="flex items-center gap-3">
            <Link href="/auth/login" className="text-sm text-gray-400 hover:text-white transition-colors px-3 py-2">
              Войти
            </Link>
            <Link href="/auth/register"
              className="text-sm bg-blue-600 hover:bg-blue-500 text-white font-medium px-4 py-2 rounded-lg transition-colors">
              Попробовать бесплатно
            </Link>
          </div>
        </div>
      </nav>

      {/* ── Hero ─────────────────────────────────────────────────────────── */}
      <section className="max-w-6xl mx-auto px-6 pt-24 pb-20 text-center">
        <div className="inline-flex items-center gap-2 bg-blue-500/10 border border-blue-500/20 rounded-full px-4 py-1.5 text-blue-300 text-sm mb-8">
          <Zap className="w-3.5 h-3.5" />
          AI-платформа для тендеров в Казахстане
        </div>

        <h1 className="text-5xl sm:text-6xl font-extrabold text-white mb-6 leading-tight">
          Находите прибыльные<br />
          <span className="text-transparent bg-clip-text bg-gradient-to-r from-blue-400 to-purple-400">
            тендеры за минуты
          </span>
        </h1>

        <p className="text-xl text-gray-400 max-w-2xl mx-auto mb-10 leading-relaxed">
          Jarvis автоматически сканирует все площадки госзакупок КЗ,<br />
          рассчитывает маржу с помощью GPT-4o и показывает только выгодные тендеры.
        </p>

        <div className="flex flex-col sm:flex-row items-center justify-center gap-4 mb-16">
          <Link href="/auth/register"
            className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 text-white font-semibold px-8 py-4 rounded-xl text-lg transition-colors shadow-lg shadow-blue-600/20">
            Начать бесплатно
            <ArrowRight className="w-5 h-5" />
          </Link>
          <Link href="/auth/login"
            className="flex items-center gap-2 border border-gray-700 hover:border-gray-500 text-gray-300 hover:text-white font-medium px-8 py-4 rounded-xl text-lg transition-colors">
            Войти в систему
          </Link>
        </div>

        {/* Stats row */}
        <div className="grid grid-cols-3 gap-8 max-w-2xl mx-auto">
          {[
            { label: 'Лотов в базе', value: '15 000+' },
            { label: 'Маркетплейсов', value: '7' },
            { label: 'Площадок КЗ', value: '2+' },
          ].map(s => (
            <div key={s.label} className="text-center">
              <p className="text-3xl font-bold text-white">{s.value}</p>
              <p className="text-sm text-gray-500 mt-1">{s.label}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── Marketplace highlight ────────────────────────────────────────── */}
      <section className="max-w-6xl mx-auto px-6 py-16">
        <div className="bg-gradient-to-br from-blue-500/10 to-purple-500/10 border border-blue-500/20 rounded-3xl p-10">
          <div className="flex flex-col lg:flex-row items-center gap-10">
            <div className="flex-1">
              <div className="inline-flex items-center gap-2 bg-blue-500/15 border border-blue-500/25 rounded-full px-3 py-1 text-blue-300 text-xs mb-4">
                <Zap className="w-3 h-3" /> Ключевая фича
              </div>
              <h2 className="text-3xl font-bold text-white mb-4">
                Найдите где купить товар<br />за секунды
              </h2>
              <p className="text-gray-400 leading-relaxed mb-6">
                Для каждого тендера Jarvis автоматически ищет товар на 7 маркетплейсах —
                Kaspi.kz, Satu.kz, Wildberries, Ozon, Alibaba, 1688, AliExpress.
                Ссылки ведут на реальные страницы товаров с фотографиями.
              </p>
              <div className="flex flex-wrap gap-2">
                {['🇰🇿 Kaspi.kz', '🇰🇿 Satu.kz', '🇷🇺 Wildberries', '🇷🇺 Ozon', '🇨🇳 Alibaba', '🇨🇳 1688.com', '🇨🇳 AliExpress'].map(p => (
                  <span key={p} className="text-xs px-3 py-1.5 bg-gray-800 border border-gray-700 rounded-lg text-gray-300">{p}</span>
                ))}
              </div>
            </div>
            <div className="flex-1 max-w-sm w-full">
              <div className="bg-gray-900 rounded-2xl border border-gray-700 p-5 space-y-2.5">
                <p className="text-xs text-gray-500 mb-3">Где купить: <span className="text-white">Принтер лазерный HP</span></p>
                {[
                  { flag: '🇰🇿', name: 'Kaspi.kz', badge: 'KZ', color: 'text-yellow-400' },
                  { flag: '🇷🇺', name: 'Wildberries', badge: 'RU', color: 'text-purple-400' },
                  { flag: '🇨🇳', name: 'Alibaba.com', badge: 'CN', color: 'text-orange-400' },
                  { flag: '🇨🇳', name: 'AliExpress', badge: 'CN', color: 'text-orange-300' },
                ].map(item => (
                  <div key={item.name} className="flex items-center justify-between bg-gray-800/60 rounded-lg px-3 py-2">
                    <div className="flex items-center gap-2">
                      <span className="text-base">{item.flag}</span>
                      <span className={`text-sm font-medium ${item.color}`}>{item.name}</span>
                    </div>
                    <span className="text-xs text-gray-500">Открыть →</span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* ── Features ─────────────────────────────────────────────────────── */}
      <section className="bg-gray-900/50 border-y border-gray-800">
        <div className="max-w-6xl mx-auto px-6 py-20">
          <h2 className="text-3xl font-bold text-white text-center mb-4">Всё что нужно для участия в тендерах</h2>
          <p className="text-gray-500 text-center mb-12">Один инструмент заменяет ручной мониторинг, таблицы и расчёты</p>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
            {FEATURES.map((f: any) => (
              <div key={f.title} className={`border rounded-2xl p-6 transition-colors ${
                f.highlight
                  ? 'bg-blue-500/5 border-blue-500/30 hover:border-blue-400/50'
                  : 'bg-gray-900 border-gray-800 hover:border-gray-600'
              }`}>
                <div className={`w-12 h-12 rounded-xl flex items-center justify-center mb-4 ${
                  f.highlight ? 'bg-blue-500/15' : 'bg-gray-800'
                }`}>
                  {f.icon}
                </div>
                <h3 className="font-semibold text-white mb-2">{f.title}</h3>
                <p className="text-gray-500 text-sm leading-relaxed">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── How it works ─────────────────────────────────────────────────── */}
      <section className="max-w-6xl mx-auto px-6 py-20">
        <h2 className="text-3xl font-bold text-white text-center mb-4">Как это работает</h2>
        <p className="text-gray-500 text-center mb-12">От регистрации до первого прибыльного тендера — 4 шага</p>
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
          {STEPS.map(s => (
            <div key={s.num} className="relative">
              <div className="text-5xl font-black text-gray-800 mb-3">{s.num}</div>
              <h3 className="font-semibold text-white mb-2">{s.title}</h3>
              <p className="text-gray-500 text-sm leading-relaxed">{s.desc}</p>
            </div>
          ))}
        </div>
      </section>

      {/* ── CTA ──────────────────────────────────────────────────────────── */}
      <section className="max-w-6xl mx-auto px-6 pb-24">
        <div className="bg-gradient-to-br from-blue-600/20 to-purple-600/20 border border-blue-500/20 rounded-3xl p-12 text-center">
          <h2 className="text-3xl font-bold text-white mb-4">Готовы найти прибыльные тендеры?</h2>
          <p className="text-gray-400 mb-8 max-w-xl mx-auto">
            Регистрация занимает 30 секунд. Первые тендеры с расчётом маржи появятся через 5 минут после запуска сканирования.
          </p>
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link href="/auth/register"
              className="flex items-center gap-2 bg-blue-600 hover:bg-blue-500 text-white font-semibold px-8 py-4 rounded-xl text-lg transition-colors">
              Создать аккаунт бесплатно
              <ArrowRight className="w-5 h-5" />
            </Link>
          </div>
          <div className="flex items-center justify-center gap-6 mt-8 text-sm text-gray-500">
            {['Без кредитной карты', 'Мгновенный доступ', 'Отмена в любой момент'].map(t => (
              <div key={t} className="flex items-center gap-1.5">
                <CheckCircle2 className="w-4 h-4 text-green-500" />
                {t}
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* ── Footer ───────────────────────────────────────────────────────── */}
      <footer className="border-t border-gray-800 py-8">
        <div className="max-w-6xl mx-auto px-6 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="flex items-center gap-2 text-gray-500">
            <BrainCircuit className="w-4 h-4" />
            <span className="text-sm">Jarvis Tender AI · Казахстан</span>
          </div>
          <div className="flex items-center gap-6 text-sm text-gray-600">
            <Link href="/auth/login" className="hover:text-gray-400 transition-colors">Войти</Link>
            <Link href="/auth/register" className="hover:text-gray-400 transition-colors">Регистрация</Link>
          </div>
        </div>
      </footer>
    </div>
  );
}
