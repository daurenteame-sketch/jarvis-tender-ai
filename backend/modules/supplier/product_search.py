"""
Product Search Service — finds REAL product page URLs across KZ/RU/CN marketplaces.

Strategy:
  1. Wildberries (RU) — undocumented public API → returns real product page URLs
  2. Kaspi.kz (KZ)   — search URL (closest to product with spec query)
  3. Ozon (RU)       — search URL with spec query
  4. Alibaba (CN)    — search URL with English query
  5. 1688.com (CN)   — search URL (Chinese/pinyin)
  6. AliExpress (CN) — search URL with English query

Wildberries is the ONLY platform where we can get real product IDs
(and thus real product page URLs) without authentication.
For all others we generate optimized search URLs that open a search results page
as close as possible to the target product.
"""
from __future__ import annotations

import asyncio
import re
import urllib.parse
from typing import Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)

# Timeout for external requests
_HTTP_TIMEOUT = 8.0

# WB search API variants (try in order until one returns results)
_WB_SEARCH_URLS = [
    # v5 with spp cookie
    "https://search.wb.ru/exactmatch/ru/common/v5/search?query={query}&resultset=catalog&sort=popular&page=1&limit={limit}",
    # v4 fallback
    "https://search.wb.ru/exactmatch/ru/common/v4/search?query={query}&resultset=catalog&sort=popular&page=1&limit={limit}",
]
_WB_PRODUCT_URL = "https://www.wildberries.ru/catalog/{id}/detail.aspx"

# Generic words to strip from search queries (reduce noise)
_NOISE_RU = frozenset({
    "поставка", "поставки", "закупка", "приобретение", "товар", "изделие",
    "продукция", "продукт", "материал", "оборудование", "оснащение",
    "единица", "штука", "штук", "шт", "комплект", "набор", "гост",
    "технических", "требованиям", "согласно", "соответствии",
})

_NOISE_EN = frozenset({
    "supply", "purchase", "item", "product", "equipment", "unit", "set",
    "delivery", "procurement",
})


def _clean_query(name: str, max_words: int = 6) -> str:
    """
    Strip noise words and limit query length for better marketplace search results.
    Preserves numbers, brands, and model identifiers.
    """
    # Remove parenthetical specs like "(220В, 50Гц)" — keep numbers + units
    name = re.sub(r"\s*\([^)]{30,}\)", "", name)  # only remove long parens
    # Normalize whitespace
    tokens = name.split()
    cleaned = []
    for tok in tokens:
        tl = tok.lower().strip(",.;:-/")
        if tl in _NOISE_RU or tl in _NOISE_EN:
            continue
        cleaned.append(tok)
    # Limit to max_words most meaningful tokens (prefer the first ones which carry the noun)
    result = " ".join(cleaned[:max_words])
    return result.strip() or name[:60]


def _extract_spec_query(product_name: str, characteristics: dict) -> str:
    """
    Build an enriched query from product name + key spec values.
    E.g. "Ноутбук Dell i7 16GB 512GB" instead of just "Ноутбук"
    """
    base = _clean_query(product_name)
    spec_tokens: list[str] = []

    # Extract key spec values (short values only — numbers, brands, models)
    for key, val in (characteristics or {}).items():
        val_str = str(val).strip()
        # Skip overly long values, "Yes/No" style values, and duplicates
        if not val_str or len(val_str) > 30:
            continue
        if val_str.lower() in ("да", "нет", "yes", "no", "true", "false", "-", "—"):
            continue
        # Include values that look like numbers/units/brands (short)
        if len(val_str) <= 20:
            spec_tokens.append(val_str)
        if len(spec_tokens) >= 3:
            break

    if spec_tokens:
        enriched = base + " " + " ".join(spec_tokens)
        return enriched[:100]
    return base


# ── Wildberries product search (real product page URLs) ──────────────────────

async def search_wildberries(query: str, limit: int = 4) -> list[dict]:
    """
    Search Wildberries and return real product page URLs.

    Returns list of:
      {"url": "https://wildberries.ru/catalog/{id}/detail.aspx",
       "name": "...", "price_rub": 1234, "brand": "...", "type": "product"}

    Falls back to empty list if WB API is unavailable or returns no results
    (geo-blocked IPs, etc.) — the caller adds a search URL fallback instead.
    """
    if not query:
        return []

    q_encoded = urllib.parse.quote_plus(query)
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        "Origin": "https://www.wildberries.ru",
        "Referer": "https://www.wildberries.ru/",
    }

    products: list = []
    for url_tpl in _WB_SEARCH_URLS:
        url = url_tpl.format(query=q_encoded, limit=limit)
        try:
            async with httpx.AsyncClient(timeout=_HTTP_TIMEOUT, follow_redirects=True) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()
                # v5: top-level "products", v4: data.products
                products = (
                    data.get("products")
                    or (data.get("data") or {}).get("products")
                    or []
                )
                if products:
                    break   # got results — stop trying
        except Exception as exc:
            logger.warning("WB search endpoint failed", url=url[:80], error=str(exc)[:80])
            continue

    results = []
    for p in products[:limit]:
        pid = p.get("id")
        if not pid:
            continue
        price_rub = round((p.get("salePriceU") or p.get("priceU") or 0) / 100, 0)
        results.append({
            "url":       _WB_PRODUCT_URL.format(id=pid),
            "name":      p.get("name", "")[:80],
            "brand":     p.get("brand", ""),
            "price_rub": int(price_rub),
            "type":      "product",
            "platform":  "Wildberries",
            "country":   "RU",
        })

    logger.info("WB search", query=query[:50], found=len(results))
    return results


# ── Search URL builders per platform ─────────────────────────────────────────

def _kaspi_url(query_ru: str) -> dict:
    q = urllib.parse.quote_plus(_clean_query(query_ru, max_words=5))
    return {
        "url":      f"https://kaspi.kz/shop/search/?text={q}&c=750000000",
        "platform": "Kaspi.kz",
        "country":  "KZ",
        "type":     "search",
    }


def _ozon_url(query_ru: str) -> dict:
    q = urllib.parse.quote_plus(_clean_query(query_ru, max_words=6))
    return {
        "url":      f"https://www.ozon.ru/search/?text={q}&from_global=true",
        "platform": "Ozon",
        "country":  "RU",
        "type":     "search",
    }


def _wildberries_search_url(query_ru: str) -> dict:
    """Fallback: WB search page URL (when API fails)."""
    q = urllib.parse.quote_plus(_clean_query(query_ru, max_words=6))
    return {
        "url":      f"https://www.wildberries.ru/catalog/0/search.aspx?search={q}",
        "platform": "Wildberries",
        "country":  "RU",
        "type":     "search",
    }


def _alibaba_url(query_en: str) -> dict:
    q = urllib.parse.quote_plus(_clean_query(query_en or "", max_words=6))
    return {
        "url":      f"https://www.alibaba.com/trade/search?SearchText={q}&tab=all&SearchSource=SearchBar",
        "platform": "Alibaba.com",
        "country":  "CN",
        "type":     "search",
    }


def _1688_url(query: str) -> dict:
    """1688 accepts both Russian cyrillic and English in the query."""
    q = urllib.parse.quote_plus(_clean_query(query, max_words=5))
    return {
        "url":      f"https://s.1688.com/selloffer/offer_search.htm?keywords={q}",
        "platform": "1688.com",
        "country":  "CN",
        "type":     "search",
    }


def _aliexpress_url(query_en: str) -> dict:
    q = urllib.parse.quote_plus(_clean_query(query_en or "", max_words=6))
    return {
        "url":      f"https://www.aliexpress.com/wholesale?SearchText={q}&SortType=total_tranpro_desc",
        "platform": "AliExpress",
        "country":  "CN",
        "type":     "search",
    }


def _satu_url(query_ru: str) -> dict:
    q = urllib.parse.quote_plus(_clean_query(query_ru, max_words=5))
    return {
        "url":      f"https://satu.kz/search?search_term={q}",
        "platform": "Satu.kz",
        "country":  "KZ",
        "type":     "search",
    }


# ── Main API ──────────────────────────────────────────────────────────────────

async def get_product_links(
    product_name: str,
    characteristics: Optional[dict] = None,
    product_name_en: str = "",
    max_links: int = 8,
) -> list[dict]:
    """
    Return 3-8 marketplace links for a product.

    Each entry:
      {
        "platform": "Wildberries",
        "country": "RU",
        "url": "https://...",
        "type": "product" | "search",   # product = real product page
        "name": "...",                   # only for type=product
        "price_rub": 1234,               # only for type=product (WB)
        "brand": "...",                  # only for type=product
      }

    "product" type links open actual product pages with photos.
    "search" type links open a search results page pre-filtered for the product.
    """
    characteristics = characteristics or {}
    spec_query = _extract_spec_query(product_name, characteristics)
    query_en = product_name_en or product_name

    # Static search links — always included regardless of WB API result
    static_links = [
        _kaspi_url(spec_query),
        _satu_url(spec_query),
        _ozon_url(spec_query),
        _alibaba_url(query_en),
        _1688_url(query_en),
        _aliexpress_url(query_en),
    ]

    # Try to get real WB product pages via API (with timeout)
    wb_products: list[dict] = []
    try:
        wb_products = await asyncio.wait_for(
            search_wildberries(spec_query, limit=3),
            timeout=6.0,
        )
    except (asyncio.TimeoutError, Exception) as exc:
        logger.warning("WB product search timed out or failed", error=str(exc)[:80])

    # If WB API returned no real products, add a WB search URL fallback
    if not wb_products:
        static_links.insert(2, _wildberries_search_url(spec_query))

    # Combine: real product pages first (WB), then search pages
    combined = []
    for p in wb_products:
        combined.append(p)
    for s in static_links:
        combined.append(s)

    return combined[:max_links]


# ── Sync wrapper for use in non-async context ─────────────────────────────────

def get_product_links_sync(
    product_name: str,
    characteristics: Optional[dict] = None,
    product_name_en: str = "",
    max_links: int = 8,
) -> list[dict]:
    """Synchronous wrapper around get_product_links."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Already in async context — should use await get_product_links() directly
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    asyncio.run,
                    get_product_links(product_name, characteristics, product_name_en, max_links),
                )
                return future.result(timeout=10)
        else:
            return loop.run_until_complete(
                get_product_links(product_name, characteristics, product_name_en, max_links)
            )
    except Exception as exc:
        logger.warning("get_product_links_sync failed", error=str(exc)[:100])
        return []
