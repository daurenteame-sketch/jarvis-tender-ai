# Smoke check — 30 секунд после `docker-compose up`

После каждого рестарта Docker'а пройди этот чеклист. Если хоть одна галка не ставится — **это регрессия**, не закрывай сессию пока не починим.

## 1. Контейнеры подняты

```bash
docker compose ps
```
Ожидание: 4 контейнера в статусе `Up (healthy)` — postgres, redis, backend, frontend.

## 2. Backend отвечает

```bash
curl -s http://localhost:8000/health
```
Ожидание: `{"status":"ok"}` или аналог.

## 3. Frontend грузится

Открыть http://localhost:3000 — должна появиться лендинг-страница (без сайдбара).

## 4. Логин админа

http://localhost:3000/login → `admin@tender.ai` / `admin123` → попадаем на `/dashboard`.

## 5. Тест на лоте (главная проверка регрессий)

Открыть любой лот из `/tenders`. На странице лота проверить **по очереди**:

- [ ] **Спека на русском** — без банковских гарантий, без казахского текста
- [ ] **Кнопка «Открыть PDF»** работает — открывается PDF в новой вкладке
- [ ] **Кнопка «Скачать PDF»** работает — скачивается файл
- [ ] **Поставщики ≥ 5** — должны быть как минимум: Kaspi, Satu, 1688, Alibaba, плюс Wildberries/Ozon если запрос на русском
- [ ] **Score badges** — на каждой карточке товара цветной % (зелёный/амбер/красный)
- [ ] **Реальные страницы товара** — клик по Kaspi/Satu открывает **конкретный товар** (не страницу поиска). Проверь URL: `kaspi.kz/shop/p/...` или `satu.kz/p...`

## 6. Если поставщиков ≤ 3 — это норма ТОЛЬКО при первом открытии лота

Playwright стреляет в фоне ~10-20 сек, кладёт в Redis. **Перезагрузи страницу через 30 сек** — должны появиться остальные. Если на втором открытии всё ещё ≤3 — Playwright упал, смотри логи backend.

## 7. Логи backend на ошибки

```bash
docker compose logs backend --tail=100 | grep -iE "error|traceback|playwright|redis"
```
Ожидание: ни одного `Traceback` за последние 100 строк.

---

## Если что-то не работает — порядок диагностики

1. `git log --oneline -5` — какой коммит сейчас активен? Совпадает с CHANGELOG?
2. `docker compose ps` — все 4 healthy?
3. Образы свежие? `docker compose images` — даты сборки backend/frontend
4. Если backend старый: `docker compose up -d --build backend`
5. Если frontend старый: `docker compose up -d --build frontend`
6. Полная пересборка: `docker compose down && docker compose up -d --build`
7. **НЕ запускать `docker compose down -v`** — флаг `-v` снесёт `redis_data` и `postgres_data` volumes
