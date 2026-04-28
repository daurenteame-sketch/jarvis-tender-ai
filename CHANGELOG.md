# Changelog

Журнал изменений по сессиям. Последняя запись сверху.

Формат: `YYYY-MM-DD — session N — что починили / commit hash`.

---

## 2026-04-28 — session 5 — git hygiene + commit накопленных правок

- Обнаружено: все правки sessions 3+4 лежали на диске, но **не были закоммичены**.
  Это и есть главная причина ощущения «откатов» между сессиями.
- Зафиксированы единым коммитом 12 файлов (sessions 3+4): `1c078db`
- `.gitignore` дополнен: `tsconfig.tsbuildinfo` больше не трекается
- Добавлен `CHANGELOG.md` (этот файл)
- Добавлен `SMOKE_CHECK.md` — 30-секундный чеклист после `docker-compose up`

**Должно работать после `docker-compose up -d --build`:**
- Открытие лота: автозагрузка спеки в течение 20 сек (если её ещё не было)
- Спека на русском, без банковских гарантий и казахского
- Кнопки «Открыть PDF» / «Скачать PDF» (через `/lots/{id}/techspec-pdf`)
- Поставщики: Kaspi (реальная страница товара), Satu (реальная), 1688, Alibaba, Wildberries, Ozon, AliExpress
- Score badges на карточках товаров (зелёный ≥70, амбер 50-69, красный <50)
- Telegram-бот с фильтрами категорий по юзерам

---

## 2026-04 (до этого) — sessions 3-4 (теперь в коммите 1c078db)

- Playwright-скрейпинг Kaspi.kz и Satu.kz с Redis 6ч кешем
- GPT product validator (relevance score 0-100, threshold 50%)
- Авто-извлечение технической спеки при первом открытии лота
- PDF proxy с fallback по `lot.documents` / `tender.documents`
- Фильтрация спеки: убирает банковские гарантии и казахский
- Marketplace links section + score badges на странице лота
- OpenAI quota circuit breaker (1ч cooldown на 429)
- Telegram bot multi-user с фильтрами категорий
- Procurement plan / purchase history / pricing pages

---

## 2026-04 (раньше) — session 2

- Marketplace links (7 платформ KZ/RU/CN), Suppliers page rebuild
- Procurement / purchase history / pricing
- Sidebar reorganized: Основное / Закупки / Аккаунт

---

## 2026-04 (ранний) — session 1, commit `1a2ef2c`

- HotLots widget, opportunity score, Excel export
- Category profitability, confidence breakdown
- Web price enhancer
