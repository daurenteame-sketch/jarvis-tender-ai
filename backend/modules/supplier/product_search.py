"""
Product Search Service — finds REAL product page URLs across KZ/RU/CN marketplaces.

Strategy:
  1. Wildberries (RU) — public JSON API → direct product pages + prices in RUB
  2. Kaspi.kz (KZ)   — DuckDuckGo site:kaspi.kz search → direct product pages
  3. Satu.kz (KZ)    — DuckDuckGo site:satu.kz search → direct product pages
  4. Ozon (RU)       — search URL with spec query
  5. Alibaba (CN)    — search URL with English query
  6. 1688.com (CN)   — search URL (only when query is Latin/English)
  7. AliExpress (CN) — search URL with English query

WB and DDG-found pages are type="product" (direct product page, no price for DDG).
Others are type="search" (search results page).
"""
from __future__ import annotations

import asyncio
import re
import urllib.parse
from typing import Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)

_HTTP_TIMEOUT = 8.0

_WB_SEARCH_URLS = [
    "https://search.wb.ru/exactmatch/ru/common/v5/search?query={query}&resultset=catalog&sort=popular&page=1&limit={limit}",
    "https://search.wb.ru/exactmatch/ru/common/v4/search?query={query}&resultset=catalog&sort=popular&page=1&limit={limit}",
]
_WB_PRODUCT_URL = "https://www.wildberries.ru/catalog/{id}/detail.aspx"

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

_COMMON_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "ru-RU,ru;q=0.9,kk;q=0.8,en;q=0.7",
}


def _clean_query(name: str, max_words: int = 6) -> str:
    name = re.sub(r"\s*\([^)]{30,}\)", "", name)
    tokens = name.split()
    cleaned = []
    for tok in tokens:
        tl = tok.lower().strip(",.;:-/")
        if tl in _NOISE_RU or tl in _NOISE_EN:
            continue
        cleaned.append(tok)
    result = " ".join(cleaned[:max_words])
    return result.strip() or name[:60]


def _extract_spec_query(product_name: str, characteristics: dict) -> str:
    base = _clean_query(product_name)
    spec_tokens: list[str] = []
    for key, val in (characteristics or {}).items():
        val_str = str(val).strip()
        if not val_str or len(val_str) > 30:
            continue
        if val_str.lower() in ("да", "нет", "yes", "no", "true", "false", "-", "—"):
            continue
        if len(val_str) <= 20:
            spec_tokens.append(val_str)
        if len(spec_tokens) >= 3:
            break
    if spec_tokens:
        return (base + " " + " ".join(spec_tokens))[:100]
    return base


# ── Wildberries ───────────────────────────────────────────────────────────────

async def search_wildberries(query: str, limit: int = 3) -> list[dict]:
    """Search WB public API — returns real product pages sorted by popularity."""
    if not query:
        return []

    q_encoded = urllib.parse.quote_plus(query)
    headers = {
        **_COMMON_HEADERS,
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
                products = (
                    data.get("products")
                    or (data.get("data") or {}).get("products")
                    or []
                )
                if products:
                    break
        except Exception as exc:
            logger.warning("WB search failed", url=url[:80], error=str(exc)[:80])

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
            "price_kzt": None,
            "type":      "product",
            "platform":  "Wildberries",
            "country":   "RU",
        })

    # Sort cheapest first
    results.sort(key=lambda x: x["price_rub"])
    logger.info("WB search", query=query[:50], found=len(results))
    return results


# ── Playwright scrapers — cache-first, background-on-miss ────────────────────

async def _pw_scrape_kaspi(query: str, limit: int) -> list[dict]:
    """
    Returns cached Kaspi products instantly.
    On cache miss: fires background Playwright scrape (writes to cache),
    returns [] so the caller falls back to search URL immediately.
    """
    from modules.supplier.playwright_scraper import scrape_kaspi, _cache_key, _cache_get
    cached = await _cache_get(_cache_key("kaspi", query))
    if cached is not None:
        return cached
    # No cache — start background scrape, return empty now
    asyncio.ensure_future(scrape_kaspi(query, limit))
    return []


async def _pw_scrape_satu(query: str, limit: int) -> list[dict]:
    """
    Returns cached Satu products instantly.
    On cache miss: fires background Playwright scrape, returns [] immediately.
    """
    from modules.supplier.playwright_scraper import scrape_satu, _cache_key, _cache_get
    cached = await _cache_get(_cache_key("satu", query))
    if cached is not None:
        return cached
    asyncio.ensure_future(scrape_satu(query, limit))
    return []


# ── Search URL builders ───────────────────────────────────────────────────────

def _kaspi_url(query_ru: str) -> dict:
    q = urllib.parse.quote_plus(_clean_query(query_ru, max_words=5))
    # sort=1 = price ascending on Kaspi
    return {
        "url":      f"https://kaspi.kz/shop/search/?text={q}&c=750000000&sort=1",
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


def _has_cyrillic(text: str) -> bool:
    return bool(re.search(r'[А-ЯЁа-яё]', text))


def _1688_url(query: str) -> Optional[dict]:
    """Returns None when query is Cyrillic — 1688.com only works with Latin/Chinese."""
    cleaned = _clean_query(query, max_words=5)
    if _has_cyrillic(cleaned):
        return None  # skip — will show empty results on 1688
    q = urllib.parse.quote_plus(cleaned)
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
    Return marketplace links for a product — real product pages where available.

    Each entry:
      {
        "platform": "Kaspi.kz",
        "country":  "KZ",
        "url":      "https://...",
        "type":     "product" | "search",
        "name":     "...",        # product title (type=product only)
        "price_kzt": 12500,       # KZT price (Kaspi/Satu)
        "price_rub": 3490,        # RUB price (WB)
        "brand":    "...",
      }
    """
    characteristics = characteristics or {}
    spec_query = _extract_spec_query(product_name, characteristics)
    query_en = product_name_en or product_name

    # Run all real-product searches in parallel
    # Playwright scrapers use Redis cache (6h TTL) so repeat calls are instant
    gathered = await asyncio.gather(
        asyncio.wait_for(search_wildberries(spec_query, limit=2),    timeout=8.0),
        asyncio.wait_for(_pw_scrape_kaspi(spec_query, limit=2),      timeout=20.0),
        asyncio.wait_for(_pw_scrape_satu(spec_query, limit=2),       timeout=20.0),
        return_exceptions=True,
    )
    wb_products    = gathered[0] if not isinstance(gathered[0], Exception) else []
    kaspi_products = gathered[1] if not isinstance(gathered[1], Exception) else []
    satu_products  = gathered[2] if not isinstance(gathered[2], Exception) else []

    # Fallback search URLs for platforms where scraping found nothing
    _link_1688 = _1688_url(query_en)  # None when query is Cyrillic
    fallback_links: list[dict] = [x for x in [
        _kaspi_url(spec_query)              if not kaspi_products else None,
        _satu_url(spec_query)               if not satu_products  else None,
        _wildberries_search_url(spec_query) if not wb_products    else None,
        _ozon_url(spec_query),
        _alibaba_url(query_en),
        _link_1688,
        _aliexpress_url(query_en),
    ] if x is not None]

    # KZ real pages first (Kaspi, Satu), then WB, then search fallbacks
    combined: list[dict] = kaspi_products + satu_products + list(wb_products) + fallback_links
    return combined[:max_links]


# ── Sync wrapper ──────────────────────────────────────────────────────────────

def get_product_links_sync(
    product_name: str,
    characteristics: Optional[dict] = None,
    product_name_en: str = "",
    max_links: int = 8,
) -> list[dict]:
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
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
