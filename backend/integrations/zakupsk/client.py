"""
Zakup.sk.kz client — Samruk-Kazyna procurement portal.

zakup.sk.kz does not publish an official GraphQL API.
This client uses their public REST endpoints that power the web interface.
If endpoints change, the scraping fallback activates.

Base URL: https://zakup.sk.kz
Known REST endpoints:
  GET /ext-api/lots?statusId=1&page=0&size=100
  GET /ext-api/lots/{id}
  GET /ext-api/lots/{id}/files
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator, Optional
import httpx
import structlog

from core.config import settings

logger = structlog.get_logger(__name__)

ZAKUPSK_BASE = "https://zakup.sk.kz"
SPEC_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx"}

# Status IDs on zakup.sk.kz
STATUS_PUBLISHED = 1
STATUS_ACCEPTING = 2


class ZakupSKClient:
    """
    Async REST client for zakup.sk.kz (Samruk-Kazyna procurement).

    Usage:
        async with ZakupSKClient() as client:
            async for tender in client.stream_published_tenders():
                process(tender)
    """

    def __init__(self):
        self.base_url = settings.ZAKUPSK_API_URL or ZAKUPSK_BASE
        self.token = settings.ZAKUPSK_API_TOKEN
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "ZakupSKClient":
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; JARVIS-TenderBot/1.0)",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=45.0, write=10.0, pool=5.0),
            headers=headers,
            follow_redirects=True,
            limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
        )
        return self

    async def __aexit__(self, *_) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── REST helpers ──────────────────────────────────────────────────────────

    async def _get(self, path: str, params: dict | None = None) -> dict | list | None:
        url = f"{self.base_url}/{path.lstrip('/')}"
        last_error: Optional[Exception] = None

        for attempt in range(settings.REQUEST_RETRY_COUNT):
            try:
                resp = await self._client.get(url, params=params or {})
                if resp.status_code == 429:
                    await asyncio.sleep(2 ** attempt + 1)
                    continue
                if resp.status_code == 404:
                    return None
                resp.raise_for_status()
                return resp.json()
            except httpx.TimeoutException as e:
                last_error = e
                await asyncio.sleep(2 ** attempt)
            except Exception as e:
                last_error = e
                if attempt == settings.REQUEST_RETRY_COUNT - 1:
                    raise
                await asyncio.sleep(2 ** attempt)

        logger.warning("ZakupSK request failed", url=url, error=str(last_error))
        return None

    # ── Public API ────────────────────────────────────────────────────────────

    async def fetch_published_page(self, page: int = 0, size: int = 100) -> list[dict]:
        """
        Fetch one page of published lots/tenders.
        Tries the public REST API first (works without auth for basic fields).
        If ZAKUPSK_API_TOKEN is set, uses it for extended fields.
        """
        # Try ext-api (public endpoint, no auth needed for basic lot data)
        data = await self._get(
            "ext-api/lots",
            params={"statusId": STATUS_PUBLISHED, "page": page, "size": size},
        )

        # Fallback: try alternate endpoint shape
        if data is None:
            data = await self._get(
                "api/tenders",
                params={"status": "published", "page": page + 1, "per_page": size},
            )

        if data is None and not self.token:
            logger.warning(
                "ZakupSK: public API returned no data. "
                "For full access set ZAKUPSK_API_TOKEN in .env"
            )

        if data is None:
            return []

        # Handle both list and {content: [...]} shapes
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("content") or data.get("data") or data.get("items") or []
        else:
            items = []

        return [self._normalise_item(item) for item in items if item]

    async def stream_published_tenders(
        self, max_tenders: int = 500, start_page: int = 0
    ) -> AsyncIterator[dict]:
        """Async generator — yields normalised tender dicts."""
        page = start_page
        fetched = 0
        page_size = 100

        while fetched < max_tenders:
            batch = await self.fetch_published_page(page=page, size=page_size)
            if not batch:
                break
            for item in batch:
                yield item
                fetched += 1
            if len(batch) < page_size:
                break
            page += 1
            await asyncio.sleep(0.15)

        logger.debug("ZakupSK stream complete", fetched=fetched)

    async def download_document(self, url: str, max_size_mb: float = 10.0) -> Optional[bytes]:
        if not url:
            return None
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
            if len(resp.content) > max_size_mb * 1024 * 1024:
                return None
            return resp.content
        except Exception as e:
            logger.warning("ZakupSK doc download failed", url=url, error=str(e))
            return None

    # ── Normalisation ─────────────────────────────────────────────────────────

    def _normalise_item(self, raw: dict) -> dict:
        """
        Normalise a ZakupSK lot/tender item to unified internal format.
        ZakupSK items are already at the lot level (one item = one procurement unit).
        We wrap it in a single-lot announce structure for API consistency.
        """
        item_id = str(raw.get("id") or raw.get("number") or "")
        title = (
            raw.get("subject")
            or raw.get("nameRu")
            or raw.get("name")
            or raw.get("title")
            or ""
        ).strip()
        description = (raw.get("description") or raw.get("technicalSpec") or "").strip()
        budget = _to_float(raw.get("budget") or raw.get("amount") or raw.get("summ"))

        customer = raw.get("customer") or {}
        customer_name = (
            customer.get("nameRu") or customer.get("name") or raw.get("customer_name") or ""
        ).strip()
        customer_bin = (
            customer.get("bin") or raw.get("customer_bin") or raw.get("customerBin") or ""
        ).strip()

        published_at = _norm_date(raw.get("publishedDate") or raw.get("published_date") or raw.get("publishDate"))
        deadline_at = _norm_date(raw.get("deadline") or raw.get("endDate") or raw.get("end_date"))

        # Documents attached to this lot
        documents = self._extract_docs(raw.get("files") or raw.get("documents") or [])
        quantity = _to_float(raw.get("count") or raw.get("quantity"))
        unit = (raw.get("unit") or raw.get("refUnit") or {})
        unit_name = unit.get("nameRu") if isinstance(unit, dict) else str(unit or "шт")

        # Build single-lot announce wrapper
        lot = {
            "lot_external_id": item_id,
            "title": title,
            "description": description,
            "quantity": quantity,
            "unit": unit_name or "шт",
            "budget": budget,
            "currency": raw.get("currency", "KZT"),
            "documents": documents,
            "raw_data": {"id": raw.get("id"), "status": raw.get("status")},
        }

        return {
            "platform": "zakupsk",
            "external_id": item_id,
            "announce_number": str(raw.get("number") or item_id),
            "status": "published",
            "title": title,
            "description": description,
            "budget": budget,
            "currency": raw.get("currency", "KZT"),
            "published_at": published_at,
            "deadline_at": deadline_at,
            "customer_name": customer_name,
            "customer_bin": customer_bin,
            "customer_region": "",
            "procurement_method": raw.get("procurementMethod") or raw.get("method") or "",
            "lots": [lot],
            "documents": documents,
            "raw_data": {
                "id": raw.get("id"),
                "number": raw.get("number"),
                "status": raw.get("status"),
            },
        }

    def _extract_docs(self, files: list) -> list[dict]:
        docs = []
        for f in (files or []):
            if not f:
                continue
            url = f.get("url") or f.get("filePath") or f.get("path") or ""
            if not url:
                continue
            name = f.get("name") or f.get("nameRu") or url.split("/")[-1]
            ext = ("." + url.rsplit(".", 1)[-1].lower()) if "." in url else ""
            docs.append({
                "url": url,
                "name": name,
                "extension": ext,
                "is_spec": ext in SPEC_EXTENSIONS,
            })
        return docs


def _to_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        v = float(str(value).replace(" ", "").replace(",", "."))
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def _norm_date(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    return value.replace(" ", "T") if " " in value else value
