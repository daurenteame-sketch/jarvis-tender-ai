"""
GPT-4o-mini validator: checks whether found marketplace products match the tender spec.

Takes the tech spec + a list of found products (name, platform, price),
returns the same list with `relevance_score` (0-100) and `match_reason` added.

Only validates type="product" items (real pages with names).
type="search" fallback links pass through unchanged with score=None.

Single batched GPT call → minimal cost and latency.
Redis-cached per (spec_hash, product_names_hash) for 6 hours.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

_CACHE_TTL = 60 * 60 * 6  # 6h


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _val_cache_key(spec: str, names: list[str]) -> str:
    combined = spec + "|" + ",".join(sorted(names))
    h = hashlib.md5(combined.encode()).hexdigest()[:16]
    return f"product_val:{h}"


async def _cache_get(key: str) -> Optional[list]:
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url("redis://redis:6379/0", decode_responses=True)
        val = await r.get(key)
        await r.aclose()
        return json.loads(val) if val else None
    except Exception:
        return None


async def _cache_set(key: str, data: list) -> None:
    try:
        import redis.asyncio as aioredis
        r = aioredis.from_url("redis://redis:6379/0", decode_responses=True)
        await r.setex(key, _CACHE_TTL, json.dumps(data, ensure_ascii=False))
        await r.aclose()
    except Exception:
        pass


# ── GPT validation ────────────────────────────────────────────────────────────

def _build_spec_summary(
    product_name: str,
    characteristics: dict,
    spec_text: str = "",
) -> str:
    """Build a concise spec string to send to GPT."""
    parts = [f"Товар: {product_name}"]
    if characteristics:
        char_lines = []
        for k, v in list(characteristics.items())[:10]:
            char_lines.append(f"  {k}: {v}")
        if char_lines:
            parts.append("Характеристики:\n" + "\n".join(char_lines))
    if spec_text:
        # Include first 400 chars of raw spec for context
        parts.append(f"Описание: {spec_text[:400]}")
    return "\n".join(parts)


async def validate_products(
    product_name: str,
    characteristics: dict,
    products: list[dict],
    spec_text: str = "",
) -> list[dict]:
    """
    Validate found marketplace products against the tender spec using GPT-4o-mini.

    Products with type="search" pass through unchanged (no name to validate).
    Products with type="product" get relevance_score (0-100) and match_reason.

    Returns the list sorted: high-score products first, then search fallbacks.
    """
    if not products:
        return products

    # Separate real product pages from search URL fallbacks
    real = [p for p in products if p.get("type") == "product" and p.get("name")]
    fallbacks = [p for p in products if p not in real]

    if not real:
        return products

    # Check cache
    spec_summary = _build_spec_summary(product_name, characteristics, spec_text)
    names = [p["name"] for p in real]
    cache_key = _val_cache_key(spec_summary, names)
    cached = await _cache_get(cache_key)
    if cached is not None:
        logger.info("Product validation cache hit", product=product_name[:40])
        # Merge cached scores back into products, then append fallbacks
        name_to_score = {item["name"]: item for item in cached}
        for p in real:
            match = name_to_score.get(p["name"])
            if match:
                p["relevance_score"] = match.get("relevance_score")
                p["match_reason"] = match.get("match_reason", "")
        real.sort(key=lambda x: -(x.get("relevance_score") or 0))
        return real + fallbacks

    # Build GPT prompt
    product_list_str = "\n".join(
        f"{i+1}. [{p['platform']}] {p['name']}" + (
            f" — {p['price_kzt']:,} ₸" if p.get("price_kzt") else
            f" — {p['price_rub']:,} ₽" if p.get("price_rub") else ""
        )
        for i, p in enumerate(real)
    )

    prompt = f"""Ты эксперт по закупкам в Казахстане. Оцени соответствие найденных товаров технической спецификации тендера.

СПЕЦИФИКАЦИЯ ТЕНДЕРА:
{spec_summary}

НАЙДЕННЫЕ ТОВАРЫ:
{product_list_str}

Для каждого товара дай оценку соответствия 0-100:
- 90-100: точное совпадение (правильный тип, материал, характеристики)
- 70-89: хорошее совпадение, незначительные отличия
- 50-69: частичное совпадение, похожий товар но не все характеристики
- 30-49: слабое совпадение, тот же класс товаров но много отличий
- 0-29: не соответствует спецификации

Ответь СТРОГО в JSON формате (без markdown):
[
  {{"index": 1, "score": 85, "reason": "Смеситель однорукояточный, материал латунь — соответствует"}},
  {{"index": 2, "score": 40, "reason": "Смеситель, но двухвентильный и пластик — не соответствует"}}
]"""

    scores: list[dict] = []
    try:
        from openai import AsyncOpenAI
        from core.config import settings

        client = AsyncOpenAI(api_key=settings.openai_api_key)
        resp = await client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=400,
            timeout=15.0,
        )
        raw = resp.choices[0].message.content or ""

        # Strip markdown fences if present
        raw = re.sub(r"```(?:json)?", "", raw).strip()

        scores = json.loads(raw)
        logger.info("Product validation done", product=product_name[:40], count=len(scores))

    except Exception as exc:
        logger.warning("Product validation failed", error=str(exc)[:120])
        # Return products unchanged if GPT fails
        for p in real:
            p.setdefault("relevance_score", None)
            p.setdefault("match_reason", "")
        return real + fallbacks

    # Apply scores to products
    score_map = {item["index"]: item for item in scores}
    for i, p in enumerate(real):
        match = score_map.get(i + 1, {})
        p["relevance_score"] = match.get("score")
        p["match_reason"] = match.get("reason", "")

    # Cache the scored names
    await _cache_set(cache_key, [
        {"name": p["name"], "relevance_score": p.get("relevance_score"), "match_reason": p.get("match_reason", "")}
        for p in real
    ])

    # Filter: remove products scoring below threshold (irrelevant results)
    _THRESHOLD = 50
    relevant = [p for p in real if (p.get("relevance_score") or 0) >= _THRESHOLD]
    # If GPT filtered everything out, fall back to showing the best ones anyway
    if not relevant and real:
        relevant = sorted(real, key=lambda x: -(x.get("relevance_score") or 0))[:2]

    # Sort: highest score first, then price within same score band
    relevant.sort(key=lambda x: (-(x.get("relevance_score") or 0), x.get("price_kzt") or x.get("price_rub") or 999_999))

    return relevant + fallbacks
