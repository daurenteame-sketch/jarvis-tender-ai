# AI Development Rules – Jarvis Tender AI

## ⚠ Locked Invariants — Don't Break These (Session 5, 2026-05-01)

These behaviours have already regressed multiple times. Each is now
covered by a regression test under `backend/tests/`. **If a test starts
failing, fix the code, not the test.** Skipping or "relaxing" a test
silently re-opens a bug that cost the user real money and time.

| # | Invariant | Test file |
|---|---|---|
| 1 | `looks_like_guarantee_text` rejects bank-guarantee templates by content (banking markers ≥2 OR ≥5 underscore stretches + гаранти/обеспечени). Used in `goszakup_scanner`, `sk_scanner`, AND `_refresh_spec_text` — all 3 paths must call it, otherwise scan re-poisons what auto-extract just cleaned. | `tests/test_guarantee_filter.py` |
| 2 | `_extract_key_attributes` pulls socket type / power / IP / paper format / density / length / capacity from spec text and these tokens land in `resolved_product.search_query`. Without this, Kaspi/Satu return generic mush and the GPT validator burns tokens cleaning up. Cyrillic А4 must normalise to Latin A4. Socket detection requires a context cue (цоколь / лампа / patron) so model numbers like B22 don't false-positive. | `tests/test_resolver_attributes.py` |
| 3 | `quantity_extracted` is coerced to `Decimal` from strings like "30 пачек" before hitting the NUMERIC column — otherwise `/reanalyze` 500s and the analysis row never lands. | `tests/test_quantity_coercion.py` |
| 4 | DEV_MODE cap = 10 lots / $1 hard / $0.50 soft per run. `DEV_MODE=true` disables the hourly auto-scan so the platform can't burn credit unattended. The cost guard is wired into EVERY OpenAI call site (`integrations/openai_client/client._guard_call`), not just the batch pipeline. | smoke-test asserts `will_analyze=10` |
| 5 | Lot detail page uses `staleTime: 0, refetchOnMount: 'always'` and auto-retries once 4s after open if `technical_spec_text` is empty — this is what makes auto-extract feel synchronous in the UI. | smoke-test confirms tech spec rendered for 3 lots |
| 6 | `restart: unless-stopped` on every docker-compose service so containers come back after Docker Desktop / Windows reboot without manual action. | manual: `docker ps` after reboot |

## Role of the AI

You are an AI software engineer working on the Jarvis Tender AI platform.

Your job is to:

- Build features
- Fix bugs
- Improve architecture
- Maintain system stability

Never break existing working functionality.

---

## Project Stack

Backend:
FastAPI

Frontend:
Next.js

Database:
PostgreSQL

Cache:
Redis

Infrastructure:
Docker + Docker Compose

---

## Development Rules

1. Fix problems step-by-step.
2. Do not rewrite large parts of the system unless necessary.
3. Always inspect logs before changing code.
4. Prefer small safe fixes over large risky refactors.
5. Keep Docker environment stable.

---

## Workflow

When implementing a feature:

1. Understand the requirement
2. Check existing code
3. Implement minimal working version
4. Verify Docker build
5. Improve if needed

---

## Priority

1. Stability
2. Correctness
3. Performance
4. Features

Never sacrifice stability for speed.