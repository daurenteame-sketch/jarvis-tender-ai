"""
GosZakup.gov.kz GraphQL API client.

Authentication:
  1. Go to https://goszakup.gov.kz/ru/user/auth_ru
  2. Login, copy Bearer JWT from Authorization header
  3. Set GOSZAKUP_API_TOKEN in .env

GraphQL endpoint: https://ows.goszakup.gov.kz/app/graphql
Rate limits: ~10 req/sec, max 100 items per query page
"""
from __future__ import annotations

import asyncio
from typing import AsyncIterator, Optional
import httpx
import structlog

from core.config import settings
from integrations.goszakup.queries import QUERY_ANNOUNCES, STATUS_PUBLISHED

logger = structlog.get_logger(__name__)

SPEC_EXTENSIONS = {".pdf", ".doc", ".docx", ".xls", ".xlsx", ".txt"}


class GosZakupClient:
    """
    Async GraphQL client for goszakup.gov.kz.
    Streams normalised tender + lot dicts.

    Usage:
        async with GosZakupClient() as client:
            async for tender in client.stream_published_tenders():
                process(tender)
    """

    def __init__(self):
        self.graphql_url = settings.GOSZAKUP_API_URL
        self.token = settings.GOSZAKUP_API_TOKEN
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "GosZakupClient":
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=60.0, write=10.0, pool=5.0),
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            limits=httpx.Limits(max_connections=5, max_keepalive_connections=3),
        )
        return self

    async def __aexit__(self, *_) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    # ── Core GraphQL executor ────────────────────────────────────────────────

    async def _gql(self, query: str, variables: dict) -> dict:
        last_error: Optional[Exception] = None
        for attempt in range(settings.REQUEST_RETRY_COUNT):
            try:
                resp = await self._client.post(
                    self.graphql_url,
                    json={"query": query, "variables": variables},
                )
                if resp.status_code == 429:
                    wait = 2 ** attempt + 1
                    logger.warning("GosZakup rate limited", wait_s=wait)
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                payload = resp.json()
                if "errors" in payload:
                    logger.warning("GosZakup GraphQL errors", errors=payload["errors"])
                return payload.get("data", {})
            except httpx.TimeoutException as e:
                last_error = e
                await asyncio.sleep(2 ** attempt)
            except httpx.HTTPStatusError as e:
                last_error = e
                if e.response.status_code in (401, 403):
                    logger.error("GosZakup auth failed — check GOSZAKUP_API_TOKEN")
                    raise
                if attempt == settings.REQUEST_RETRY_COUNT - 1:
                    raise
                await asyncio.sleep(2 ** attempt)
            except Exception as e:
                last_error = e
                if attempt == settings.REQUEST_RETRY_COUNT - 1:
                    raise
                await asyncio.sleep(2 ** attempt)
        raise last_error or RuntimeError("GosZakup request failed after retries")

    # ── Public API ───────────────────────────────────────────────────────────

    async def fetch_published_batch(self, limit: int = 100, offset: int = 0) -> list[dict]:
        data = await self._gql(
            QUERY_ANNOUNCES,
            {"limit": limit, "offset": offset, "filter": {"statusId": STATUS_PUBLISHED}},
        )
        announces = data.get("Announces") or []
        return [self._normalise_announce(a) for a in announces if a and a.get("id")]

    async def stream_published_tenders(
        self, max_tenders: int = 500, start_offset: int = 0
    ) -> AsyncIterator[dict]:
        """
        Async generator. Yields one normalised tender dict per announce.
        Each dict contains a 'lots' list with individual lots.
        """
        batch_size = 100
        offset = start_offset
        fetched = 0

        while fetched < max_tenders:
            batch = await self.fetch_published_batch(
                limit=min(batch_size, max_tenders - fetched),
                offset=offset,
            )
            if not batch:
                break
            for tender in batch:
                yield tender
                fetched += 1
            if len(batch) < batch_size:
                break
            offset += batch_size
            await asyncio.sleep(0.12)  # stay within ~8 req/sec

        logger.debug("GosZakup stream complete", fetched=fetched)

    async def download_document(self, url: str, max_size_mb: float = 10.0) -> Optional[bytes]:
        if not url:
            return None
        try:
            head = await self._client.head(url, follow_redirects=True)
            cl = int(head.headers.get("content-length", 0))
            if cl > max_size_mb * 1024 * 1024:
                logger.warning("Document too large, skipping", url=url)
                return None
        except Exception:
            pass
        try:
            resp = await self._client.get(url, follow_redirects=True)
            resp.raise_for_status()
            if len(resp.content) > max_size_mb * 1024 * 1024:
                return None
            return resp.content
        except Exception as e:
            logger.warning("Document download failed", url=url, error=str(e))
            return None

    # ── Normalisation ─────────────────────────────────────────────────────────

    def _normalise_announce(self, raw: dict) -> dict:
        customer = raw.get("customer") or {}
        region = customer.get("region") or {}
        buy_way = raw.get("refBuyWay") or {}
        lots = [self._normalise_lot(l) for l in (raw.get("Lots") or []) if l and l.get("id")]
        ann_docs = self._extract_docs(raw.get("Files") or [])
        return {
            "platform": "goszakup",
            "external_id": str(raw["id"]),
            "announce_number": raw.get("numberAnno", ""),
            "status": "published",
            "title": (raw.get("nameRu") or raw.get("nameKz") or "").strip(),
            "description": "",
            "budget": _to_float(raw.get("summ")),
            "currency": "KZT",
            "published_at": _norm_date(raw.get("publishDate")),
            "deadline_at": _norm_date(raw.get("endDate")),
            "customer_name": (customer.get("nameRu") or "").strip(),
            "customer_bin": (raw.get("customerBin") or customer.get("bin") or "").strip(),
            "customer_region": (region.get("nameRu") or "").strip(),
            "procurement_method": (buy_way.get("nameRu") or "").strip(),
            "lots": lots,
            "documents": ann_docs,
            "raw_data": {
                "id": raw.get("id"),
                "numberAnno": raw.get("numberAnno"),
                "statusId": raw.get("statusId"),
                "buyWayId": (buy_way or {}).get("id"),
            },
        }

    def _normalise_lot(self, raw_lot: dict) -> dict:
        unit_ref = raw_lot.get("refUnit") or {}
        lot_docs = self._extract_docs(raw_lot.get("Files") or [])
        return {
            "lot_external_id": str(raw_lot["id"]),
            "title": (raw_lot.get("nameRu") or raw_lot.get("nameKz") or "").strip(),
            "description": (raw_lot.get("descriptionRu") or "").strip(),
            "quantity": _to_float(raw_lot.get("count")),
            "unit": (unit_ref.get("nameRu") or unit_ref.get("code") or "шт").strip(),
            "budget": _to_float(raw_lot.get("amount")),
            "currency": "KZT",
            "documents": lot_docs,
            "raw_data": {
                "id": raw_lot.get("id"),
                "count": raw_lot.get("count"),
                "amount": raw_lot.get("amount"),
                "unitCode": unit_ref.get("code"),
            },
        }

    def _extract_docs(self, files: list) -> list[dict]:
        docs = []
        for f in (files or []):
            if not f:
                continue
            path = (f.get("filePath") or "").strip()
            if not path:
                continue
            url = path.split("?")[0]
            if url.startswith("/"):
                url = f"https://goszakup.gov.kz{url}"
            ext_raw = f.get("extension") or ""
            if not ext_raw and "." in url:
                ext_raw = url.rsplit(".", 1)[-1]
            name = f.get("nameRu") or f.get("name") or url.split("/")[-1]
            if not ext_raw and name and "." in name:
                ext_raw = name.rsplit(".", 1)[-1]
            ext = ("." + ext_raw.lower().lstrip(".")) if ext_raw else ""
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
