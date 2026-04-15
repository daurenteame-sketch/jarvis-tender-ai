# JARVIS Tender Intelligence System

AI-система для автоматического поиска прибыльных тендеров на GosZakup и Zakup SK.

## Быстрый старт (деплой на сервер)

### 1. Подготовка сервера (Hetzner VPS, Ubuntu 22.04)

```bash
# Обновить систему
apt update && apt upgrade -y

# Клонировать проект
git clone <your-repo> /opt/jarvis
cd /opt/jarvis

# Создать .env файл
cp .env.example .env
nano .env   # Заполнить все значения
```

### 2. Обязательные настройки в .env

| Переменная | Описание | Где получить |
|---|---|---|
| `OPENAI_API_KEY` | Ключ OpenAI для AI-анализа | platform.openai.com |
| `TELEGRAM_BOT_TOKEN` | Токен Telegram бота | @BotFather |
| `TELEGRAM_CHAT_ID` | ID чата для уведомлений | @userinfobot |
| `GOSZAKUP_API_TOKEN` | Токен API GosZakup | goszakup.gov.kz |
| `POSTGRES_PASSWORD` | Пароль базы данных | Придумать |

### 3. Деплой

```bash
chmod +x deploy.sh
./deploy.sh
```

### 4. Результат

После деплоя JARVIS будет доступен по адресу:
- **Дашборд:** https://jarvis.alltame.kz
- **API Docs:** https://jarvis.alltame.kz/api/docs
- Первое сканирование запустится через 15 секунд после старта

## Как работает система

```
Каждый час (автоматически):
1. Сканирование GosZakup + Zakup SK
2. Фильтрация: товары + IT-тендеры
3. Загрузка ТЗ (PDF/DOC)
4. AI-анализ спецификации (GPT-4o)
5. Поиск поставщиков (Китай/Россия/Казахстан)
6. Расчёт: себестоимость + логистика + НДС
7. Если маржа ≥ 50% → Telegram уведомление
8. Генерация заявки в DOCX
9. Отображение в веб-дашборде
```

## Мониторинг

```bash
# Логи бэкенда
docker compose logs -f backend

# Статус всех сервисов
docker compose ps

# Ручной запуск сканирования
curl -X POST https://jarvis.alltame.kz/api/v1/scan/trigger
```

## Структура проекта

```
jarvis-tender-ai/
├── backend/
│   ├── core/           — Конфиг, БД, логирование
│   ├── models/         — SQLAlchemy модели
│   ├── api/routes/     — FastAPI роуты
│   ├── integrations/   — GosZakup, Zakup SK, OpenAI
│   ├── modules/
│   │   ├── scanner/    — Сканирование тендеров
│   │   ├── ai_analyzer/ — AI-анализ ТЗ
│   │   ├── supplier/   — Поиск поставщиков
│   │   ├── logistics/  — Расчёт логистики
│   │   ├── profitability/ — Расчёт маржи
│   │   ├── confidence/ — Оценка уверенности
│   │   ├── notifications/ — Telegram
│   │   └── bid_generator/ — Генерация заявок
│   └── scheduler/      — APScheduler задачи
├── frontend/           — Next.js дашборд
├── infrastructure/
│   ├── nginx/          — Конфиг Nginx + SSL
│   └── certbot/        — SSL сертификаты
├── docker-compose.yml
├── .env.example
├── deploy.sh
└── JARVIS_SYSTEM_SPEC.md
```

## Tech Stack

- **Backend:** Python 3.12 + FastAPI + SQLAlchemy
- **AI:** OpenAI GPT-4o
- **Database:** PostgreSQL 15
- **Scheduler:** APScheduler
- **Notifications:** python-telegram-bot
- **Frontend:** Next.js 14 + TypeScript + Tailwind CSS
- **Deployment:** Docker Compose + Nginx + Let's Encrypt
