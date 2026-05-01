"""
Bank-guarantee template detector.

Some goszakup lots ship their only document as a price-offer guarantee
template — a Word file full of `_____` placeholders, "бенефициар",
"гарантодатель", etc. Filename filters catch the obvious cases
(price_offers_guarantee_2025.docx, "Обеспечение заявки.docx"), but
neutrally-named files slip through. Detect by content so this never
lands in technical_spec_text and poisons AI prompts / supplier search.

Used by:
  - modules.scanner.goszakup_scanner — write path during scan
  - modules.scanner.sk_scanner       — same, for zakupsk
  - api.routes.lots._refresh_spec_text — auto-extract on lot open
"""
from __future__ import annotations

import re

_GUARANTEE_BODY_MARKERS = (
    "[документ: обеспечение",
    "банковская гарантия",
    "бенефициар",
    "гарантодател",
    "сумма гарантии",
    "срок действия гарантии",
    "обеспечение заявки",
)

_PLACEHOLDER_RE = re.compile(r"_{4,}")  # ≥ 4 underscores in a row


def looks_like_guarantee_text(text: str) -> bool:
    """
    Returns True if `text` looks like a bank-guarantee template.

    Heuristics (any one trips the detector):
      - ≥ 2 banking-vocabulary markers in the first 2 KB
      - ≥ 5 stretches of 4+ underscores AND the word "гаранти"/"обеспечени"
        appears anywhere in the head (form templates are mostly blanks)
    """
    if not text:
        return False
    head = text[:2000].lower()
    hits = sum(1 for m in _GUARANTEE_BODY_MARKERS if m in head)
    if hits >= 2:
        return True
    if len(_PLACEHOLDER_RE.findall(head)) >= 5 and re.search(r"гаранти|обеспечени", head):
        return True
    return False
