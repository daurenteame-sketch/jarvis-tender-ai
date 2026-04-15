"""
GosZakup.gov.kz — public HTML scraper (no API token required).

Scrapes the public tender search page:
  https://goszakup.gov.kz/ru/search/lots?filter[statusId]=2

Provides the same normalised dict format as the GraphQL client
so it can be used as a drop-in fallback.
"""
from __future__ import annotations

import asyncio
import re
from typing import AsyncIterator, Optional

import httpx
import structlog

logger = structlog.get_logger(__name__)

BASE_URL = "https://goszakup.gov.kz"
SEARCH_URL = f"{BASE_URL}/ru/search/lots"
ANNOUNCE_URL = f"{BASE_URL}/ru/announce/index"

# BeautifulSoup is optional; we use regex-based parsing for zero extra deps
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}


class GosZakupWebScraper:
    """
    Public web scraper for goszakup.gov.kz.
    Works without an API token by parsing the public search HTML pages.

    Usage:
        async with GosZakupWebScraper() as scraper:
            async for tender in scraper.stream_published_tenders(max_pages=5):
                process(tender)
    """

    def __init__(self):
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "GosZakupWebScraper":
        self._client = httpx.AsyncClient(
            headers=_HEADERS,
            timeout=httpx.Timeout(connect=15.0, read=45.0, write=10.0, pool=5.0),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=3, max_keepalive_connections=2),
        )
        return self

    async def __aexit__(self, *_) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── Public API ────────────────────────────────────────────────────────────

    async def stream_published_tenders(
        self, max_pages: int = 10, start_page: int = 1
    ) -> AsyncIterator[dict]:
        """
        Async generator — yields one normalised tender dict per announce.
        Fetches up to max_pages of the public lot search.
        """
        seen_announce_ids: set[str] = set()

        for page in range(start_page, start_page + max_pages):
            try:
                rows = await self._fetch_lot_page(page)
            except Exception as exc:
                logger.warning("GosZakup scrape page failed", page=page, error=str(exc))
                break

            if not rows:
                break

            # Group rows by announce_id
            announce_groups: dict[str, list[dict]] = {}
            for row in rows:
                aid = row["announce_id"]
                announce_groups.setdefault(aid, []).append(row)

            for announce_id, lot_rows in announce_groups.items():
                if announce_id in seen_announce_ids:
                    continue
                seen_announce_ids.add(announce_id)

                # Fetch detail page for published_at and deadline
                detail = await self._fetch_announce_detail(announce_id)
                await asyncio.sleep(0.3)  # polite rate limit

                tender = self._build_tender(announce_id, lot_rows, detail)
                yield tender

            await asyncio.sleep(0.5)

    # ── HTML fetchers ─────────────────────────────────────────────────────────

    async def _fetch_lot_page(self, page: int) -> list[dict]:
        """Fetch one page of the lot search table and return parsed rows."""
        resp = await self._client.get(
            SEARCH_URL,
            params={"filter[statusId]": "2", "page": str(page)},
        )
        if resp.status_code != 200:
            logger.warning("GosZakup search page error", page=page, status=resp.status_code)
            return []
        return _parse_lot_rows(resp.text)

    async def _fetch_announce_detail(self, announce_id: str) -> dict:
        """Fetch announce detail page for published_at, deadline_at, and document links."""
        try:
            resp = await self._client.get(f"{ANNOUNCE_URL}/{announce_id}")
            if resp.status_code != 200:
                return {}
            return _parse_announce_detail(resp.text)
        except Exception as exc:
            logger.debug("GosZakup detail fetch failed", announce_id=announce_id, error=str(exc))
            return {}

    async def download_document(self, url: str, max_size_mb: float = 10.0) -> Optional[bytes]:
        """Download a document from a URL. Compatible with GosZakupClient interface."""
        if not url:
            return None
        if url.startswith("/"):
            url = BASE_URL + url
        try:
            resp = await self._client.get(url, follow_redirects=True)
            resp.raise_for_status()
            if len(resp.content) > max_size_mb * 1024 * 1024:
                logger.warning("Document too large, skipping", url=url)
                return None
            return resp.content
        except Exception as e:
            logger.warning("Document download failed", url=url, error=str(e))
            return None

    # ── Builder ───────────────────────────────────────────────────────────────

    def _build_tender(
        self,
        announce_id: str,
        lot_rows: list[dict],
        detail: dict,
    ) -> dict:
        first = lot_rows[0]
        # Announce-level documents (ТЗ is typically attached here)
        ann_docs = detail.get("documents", [])
        lots = [
            {
                "lot_external_id": r["lot_id"],
                "title": r["lot_title"] or r["title"],
                "description": "",
                "quantity": r.get("quantity"),
                "unit": "шт",
                "budget": r.get("budget"),
                "currency": "KZT",
                # Share announce-level docs with every lot — ТЗ covers all lots
                "documents": ann_docs,
                "raw_data": {"lot_id": r["lot_id"], "announce_id": announce_id},
            }
            for r in lot_rows
            if r.get("lot_id")
        ]

        return {
            "platform": "goszakup",
            "external_id": announce_id,
            "announce_number": first.get("announce_number", announce_id),
            "status": "published",
            "title": first.get("title", "").strip() or "(без названия)",
            "description": "",
            "budget": first.get("budget"),
            "currency": "KZT",
            "published_at": detail.get("published_at"),
            "deadline_at": detail.get("deadline_at"),
            "customer_name": first.get("customer_name", ""),
            "customer_bin": "",
            "customer_region": "",
            "procurement_method": first.get("procurement_method", ""),
            "lots": lots,
            "documents": [],
            "raw_data": {"announce_id": announce_id, "source": "web_scraper"},
        }


# ── HTML parsers (regex-based, no extra deps) ─────────────────────────────────

def _parse_lot_rows(html: str) -> list[dict]:
    """
    Parse the second <tbody> (lot data rows) from the search page.
    Returns list of raw row dicts.
    """
    tbodies = re.findall(r"<tbody[^>]*>(.*?)</tbody>", html, re.DOTALL)
    if len(tbodies) < 2:
        return []

    rows_html = re.findall(r"<tr[^>]*>(.*?)</tr>", tbodies[1], re.DOTALL)
    result = []

    for row_html in rows_html:
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.DOTALL)
        if len(cells) < 5:
            continue

        # NOTE: The portal's first <td> (announce number) is NOT closed before
        # the second <td> (announce link) opens, so the regex captures both
        # together in cells[0].  Real mapping after regex capture:
        #   cells[0] = announce_number + announce_link + title + customer_name
        #   cells[1] = lot subpriceoffer link + lot title
        #   cells[2] = quantity
        #   cells[3] = budget
        #   cells[4] = procurement_method
        #   cells[5] = status (optional)
        combined = cells[0]

        # Announce number: first <strong> text
        ann_num_m = re.search(r"<strong>(.*?)</strong>", combined, re.DOTALL)
        announce_number = _strip_tags(ann_num_m.group(1)).strip() if ann_num_m else ""

        # Announce ID from /ru/announce/index/ID href
        announce_link = re.search(r'href="/ru/announce/index/(\d+)"', combined)
        announce_id = announce_link.group(1) if announce_link else ""

        # Title: second <strong> content (linked title)
        strongs = re.findall(r"<strong>(.*?)</strong>", combined, re.DOTALL)
        raw_title = _strip_tags(strongs[1]).strip() if len(strongs) >= 2 else (
            _strip_tags(strongs[0]).strip() if strongs else ""
        )
        title = re.sub(r"^\d+-\d+\s+", "", raw_title).strip()

        # Customer name from <small>Заказчик: NAME<br>
        customer_match = re.search(r"Заказчик:</b>\s*(.*?)<br", combined, re.DOTALL)
        customer_name = _strip_tags(customer_match.group(1)).strip() if customer_match else ""

        # Cell 1: lot subpriceoffer link + lot title
        lot_link = re.search(
            r'href="[^"]+/(\d+)/(\d+)"[^>]*><strong>(.*?)</strong>', cells[1], re.DOTALL
        )
        lot_id = lot_link.group(2) if lot_link else ""
        lot_title = _strip_tags(lot_link.group(3)).strip() if lot_link else ""

        # Cell 2: quantity
        qty_text = _strip_tags(cells[2]).strip().replace("\xa0", "").replace(" ", "")
        quantity = _to_float(qty_text)

        # Cell 3: budget  (<strong>AMOUNT</strong>)
        budget_match = re.search(r"<strong>(.*?)</strong>", cells[3], re.DOTALL)
        budget_text = _strip_tags(budget_match.group(1)) if budget_match else _strip_tags(cells[3])
        budget = _to_float(budget_text.replace("\xa0", "").replace(" ", ""))

        # Cell 4: procurement method
        procurement_method = _strip_tags(cells[4]).strip()

        if not announce_id:
            continue

        result.append({
            "announce_id": announce_id,
            "announce_number": announce_number,
            "title": title,
            "customer_name": customer_name,
            "lot_id": lot_id,
            "lot_title": lot_title,
            "quantity": quantity,
            "budget": budget,
            "procurement_method": procurement_method,
        })

    return result


_SPEC_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".txt"}


def _parse_announce_detail(html: str) -> dict:
    """
    Extract published_at, deadline_at, and document links from an announce detail page.

    Form-group pattern: <label>LABEL</label> ... value="VALUE"
    File links: any <a href="..."> whose path ends with a spec extension.
    """
    groups = re.findall(
        r"<label[^>]*>\s*(.*?)\s*</label>.*?value=\"([^\"]+)\"",
        html,
        re.DOTALL,
    )
    data: dict[str, str] = {}
    for label, value in groups:
        label = _strip_tags(label).strip()
        data[label] = value.strip()

    # Extract all file attachment links from the page
    documents: list[dict] = []
    seen_urls: set[str] = set()
    for href in re.findall(r'href=["\']([^"\']+)["\']', html, re.IGNORECASE):
        # Normalise to lowercase path for extension check
        path = href.split("?")[0].lower()
        ext = ""
        for e in _SPEC_EXTENSIONS:
            if path.endswith(e):
                ext = e
                break
        if not ext:
            continue
        # Resolve relative URLs
        url = (BASE_URL + href) if href.startswith("/") else href
        if url in seen_urls:
            continue
        seen_urls.add(url)
        name = href.rstrip("/").split("/")[-1]
        documents.append({
            "url": url,
            "name": name,
            "extension": ext,
            "is_spec": True,
        })

    return {
        "published_at": data.get("Дата публикации объявления"),
        "deadline_at": data.get("Срок окончания приема заявок"),
        "documents": documents,
    }


def _strip_tags(html: str) -> str:
    """Remove all HTML tags from a string."""
    return re.sub(r"<[^>]+>", "", html or "").strip()


def _to_float(value: str) -> Optional[float]:
    if not value:
        return None
    clean = re.sub(r"[^\d.,]", "", value).replace(",", ".")
    try:
        v = float(clean)
        return v if v > 0 else None
    except (ValueError, TypeError):
        return None
