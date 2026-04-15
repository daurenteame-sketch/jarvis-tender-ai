"""
Mock tender scanner — get_new_tenders() returns test data for dev/demo.

Replace MOCK_TENDERS with real parser calls when ready.
Filter/profitability logic stays the same regardless of data source.
"""
from __future__ import annotations

MOCK_TENDERS: list[dict] = [
    {
        "title": "Поставка алюкобонд фасадных панелей для административного здания",
        "price": 45_000_000,
        "url": "https://goszakup.gov.kz/ru/announce/index/123456",
        "source": "goszakup",
    },
    {
        "title": "Монтаж фасада жилого комплекса с применением фцп панелей",
        "price": 28_500_000,
        "url": "https://goszakup.gov.kz/ru/announce/index/234567",
        "source": "goszakup",
    },
    {
        "title": "Поставка медицинского оборудования для поликлиники",
        "price": 12_000_000,
        "url": "https://goszakup.gov.kz/ru/announce/index/456789",
        "source": "goszakup",
    },
    {
        "title": "Закупка строительных материал для ремонта школы",
        "price": 800_000,       # < 1M, но есть слово "материал" → profitable
        "url": "https://zakup.sk.kz/tender/567890",
        "source": "zakupsk",
    },
    {
        "title": "Аренда офисного помещения на год",
        "price": 500_000,       # < 1M и нет ключевых слов → NOT profitable
        "url": "https://zakup.sk.kz/tender/345678",
        "source": "zakupsk",
    },
]

FILTER_KEYWORDS: list[str] = ["поставка", "оборудование", "материал"]
MIN_PRICE: int = 1_000_000


def _is_profitable(tender: dict) -> bool:
    title_lower = tender["title"].lower()
    has_keyword = any(kw in title_lower for kw in FILTER_KEYWORDS)
    return tender["price"] > MIN_PRICE or has_keyword


def get_new_tenders() -> list[dict]:
    """
    Return only profitable tenders with `profitable` field set.

    Profitable criteria:
      - price > 1 000 000
      - OR title contains one of FILTER_KEYWORDS: ["поставка", "оборудование", "материал"]

    Each returned dict has: title, price, url, source, profitable=True.
    """
    result: list[dict] = []
    for tender in MOCK_TENDERS:
        profitable = _is_profitable(tender)
        if profitable:
            result.append({**tender, "profitable": True})
    return result
