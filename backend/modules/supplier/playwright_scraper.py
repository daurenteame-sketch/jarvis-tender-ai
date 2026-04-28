"""
Playwright-based scraper for Kaspi.kz and Satu.kz.

Uses a real headless Chromium browser to bypass JS-rendering and bot protection.
Each scrape takes 5-12 seconds — results are cached in Redis (TTL 6 hours).

Public API:
  scrape_kaspi(query, limit=2) -> list[dict]
  scrape_satu(query, limit=2)  -> list[dict]

Each dict: {url, name, price_kzt, platform, country, type="product"}
"""
from __future__ import annotations

import asyncio
import json
import re
import hashlib
from typing import Optional

import structlog

logger = structlog.get_logger(__name__)

_CACHE_TTL = 60 * 60 * 6   # 6 hours
_PW_TIMEOUT = 15_000        # ms — page load timeout
_SELECTOR_TIMEOUT = 8_000   # ms — element wait timeout


# ── Redis cache helpers ───────────────────────────────────────────────────────

def _cache_key(platform: str, query: str) -> str:
    h = hashlib.md5(query.lower().encode()).hexdigest()[:12]
    return f"pw_scrape:{platform}:{h}"


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


# ── Kaspi.kz scraper ─────────────────────────────────────────────────────────

async def scrape_kaspi(query: str, limit: int = 2) -> list[dict]:
    """
    Open Kaspi.kz search sorted by price, return top `limit` product pages.
    Results are cached in Redis for 6 hours.
    """
    if not query:
        return []

    key = _cache_key("kaspi", query)
    cached = await _cache_get(key)
    if cached is not None:
        logger.info("Kaspi scrape cache hit", query=query[:40])
        return cached

    try:
        results = await _do_scrape_kaspi(query, limit)
    except Exception as exc:
        logger.warning("Kaspi scrape failed", query=query[:40], error=str(exc)[:120])
        results = []

    if results:
        await _cache_set(key, results)

    return results


async def _do_scrape_kaspi(query: str, limit: int) -> list[dict]:
    from playwright.async_api import async_playwright
    import urllib.parse

    q = urllib.parse.quote_plus(query)
    # sort=1 = price low to high on Kaspi
    url = f"https://kaspi.kz/shop/search/?text={q}&c=750000000&sort=1"

    results: list[dict] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
                "--disable-background-networking",
                "--single-process",
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="ru-KZ",
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        try:
            await page.goto(url, timeout=_PW_TIMEOUT, wait_until="domcontentloaded")

            # Wait for product cards to appear
            await page.wait_for_selector(
                "[data-product-id], .item-card, .catalog-item",
                timeout=_SELECTOR_TIMEOUT,
            )

            # Extract product cards
            cards = await page.query_selector_all(
                "[data-product-id], .item-card, article.catalog-item"
            )

            for card in cards[:limit * 3]:
                try:
                    # Product link
                    link_el = await card.query_selector("a[href*='/shop/p/']")
                    if not link_el:
                        link_el = await card.query_selector("a[href]")
                    if not link_el:
                        continue
                    href = await link_el.get_attribute("href") or ""
                    if not href or "/shop/p/" not in href:
                        continue
                    product_url = href if href.startswith("http") else f"https://kaspi.kz{href}"

                    # Product name
                    name_el = await card.query_selector(
                        "[class*='item__title'], [class*='name'], [class*='title']"
                    )
                    name = ""
                    if name_el:
                        name = (await name_el.inner_text()).strip()[:80]

                    # Price — card contains "Цена\n49 899 ₸\n..." so grab first number ≥1000
                    price_kzt = 0
                    price_el = await card.query_selector("[class*='price']")
                    if price_el:
                        raw = await price_el.inner_text()
                        nums = re.findall(r'\d[\d\s]*\d', raw)
                        for n in nums:
                            val = int(re.sub(r'\s', '', n))
                            if val >= 100:
                                price_kzt = val
                                break

                    if not product_url:
                        continue

                    results.append({
                        "url":       product_url,
                        "name":      name or query[:60],
                        "brand":     "",
                        "price_kzt": price_kzt or None,
                        "price_rub": None,
                        "type":      "product",
                        "platform":  "Kaspi.kz",
                        "country":   "KZ",
                    })

                    if len(results) >= limit:
                        break

                except Exception:
                    continue

        except Exception as exc:
            logger.warning("Kaspi page interaction failed", error=str(exc)[:120])
        finally:
            await browser.close()

    # Sort by price (cheapest first, None prices last)
    results.sort(key=lambda x: x["price_kzt"] or 999_999_999)
    logger.info("Kaspi scrape done", query=query[:40], found=len(results))
    return results[:limit]


# ── Satu.kz scraper ───────────────────────────────────────────────────────────

async def scrape_satu(query: str, limit: int = 2) -> list[dict]:
    """
    Open Satu.kz search sorted by cheapest, return top `limit` product pages.
    Results are cached in Redis for 6 hours.
    """
    if not query:
        return []

    key = _cache_key("satu", query)
    cached = await _cache_get(key)
    if cached is not None:
        logger.info("Satu scrape cache hit", query=query[:40])
        return cached

    try:
        results = await _do_scrape_satu(query, limit)
    except Exception as exc:
        logger.warning("Satu scrape failed", query=query[:40], error=str(exc)[:120])
        results = []

    if results:
        await _cache_set(key, results)

    return results


async def _do_scrape_satu(query: str, limit: int) -> list[dict]:
    """
    Satu.kz is a pure React SPA. Strategy:
    1. Load search page (sorted by cheapest)
    2. Wait for any product card links to appear in the DOM
    3. Extract URL + name from the first N product links
    4. Open each product page to get the price
    """
    from playwright.async_api import async_playwright
    import urllib.parse

    q = urllib.parse.quote_plus(query)
    url = f"https://satu.kz/search?search_term={q}&sort_by=cheapest"

    results: list[dict] = []

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-extensions",
                "--single-process",
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="ru-KZ",
            viewport={"width": 1280, "height": 900},
        )
        page = await context.new_page()

        try:
            await page.goto(url, timeout=_PW_TIMEOUT, wait_until="networkidle")

            # Give React time to render product cards
            await page.wait_for_timeout(2000)

            # Find all product links on the page (Satu product URLs contain /p<digits>)
            html = await page.content()
            product_urls_raw = re.findall(
                r'href=["\']((https://satu\.kz)?/p\d+[^"\'<>\s]{0,120})["\']',
                html,
            )

            seen: set[str] = set()
            product_hrefs: list[str] = []
            for match in product_urls_raw:
                href = match[0]
                full = href if href.startswith("http") else f"https://satu.kz{href}"
                # Filter out search/category pages
                if full in seen or "search" in full or "catalog" in full:
                    continue
                seen.add(full)
                product_hrefs.append(full)
                if len(product_hrefs) >= limit * 2:
                    break

            # For each product URL, open the page and extract price + name
            for product_url in product_hrefs[:limit]:
                try:
                    prod_page = await context.new_page()
                    await prod_page.goto(product_url, timeout=_PW_TIMEOUT, wait_until="domcontentloaded")
                    await prod_page.wait_for_timeout(1500)

                    prod_html = await prod_page.content()
                    await prod_page.close()

                    # Extract title
                    title_m = re.search(r'<title[^>]*>([^<]{5,120})</title>', prod_html)
                    name = title_m.group(1).strip()[:80] if title_m else query[:60]
                    # Strip " — satu.kz" suffix
                    name = re.sub(r'\s*[–—-]\s*satu\.kz.*$', '', name, flags=re.IGNORECASE).strip()

                    # Extract price (look for ₸ patterns)
                    prices = re.findall(r'(\d[\d\s]{1,8})\s*₸', prod_html)
                    price_kzt = 0
                    for p in prices:
                        val = int(re.sub(r'\s', '', p))
                        if val >= 100:
                            price_kzt = val
                            break

                    results.append({
                        "url":       product_url,
                        "name":      name,
                        "brand":     "",
                        "price_kzt": price_kzt or None,
                        "price_rub": None,
                        "type":      "product",
                        "platform":  "Satu.kz",
                        "country":   "KZ",
                    })
                except Exception:
                    continue

        except Exception as exc:
            logger.warning("Satu page interaction failed", error=str(exc)[:120])
        finally:
            await browser.close()

    results.sort(key=lambda x: x["price_kzt"] or 999_999_999)
    logger.info("Satu scrape done", query=query[:40], found=len(results))
    return results[:limit]
