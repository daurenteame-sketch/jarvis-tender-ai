"""
Spec text extractor — deterministic, regex-based product identifier extraction.

No AI, no external calls.  Used to derive "exact_product" for the lot detail API.

Priority chain:
  1. brand_model from TenderLotAnalysis (AI already extracted it — use if it looks specific)
  2. Regex patterns in technical_spec_text (ГОСТ, cable designations, model codes, ТУ)
  3. product_name from TenderLotAnalysis, only when it contains numbers/codes
  4. None  → UI shows "Модель не указана"
"""
from __future__ import annotations

import re
from typing import Optional


# ── Regex patterns ─────────────────────────────────────────────────────────────

# ГОСТ / ГОСТ Р  (e.g. "ГОСТ 31996-2012", "ГОСТ Р 58412-2019")
_GOST = re.compile(
    r'ГОСТ\s+Р?\s*\d{4,6}[-–]\d{2,4}(?:[-–]\d+)?',
    re.IGNORECASE,
)

# ТУ codes  (e.g. "ТУ 16.К71-335-2004")
_TU = re.compile(
    r'ТУ\s+[\d\.]+[-–][\d\.\-]+',
    re.IGNORECASE,
)

# Cable/wire designations  (e.g. "ВВГнг-LS 3x2.5", "КВВГ 7×1.5", "NYY 4x10")
_CABLE = re.compile(
    r'\b([А-ЯЁA-Z]{2,8}(?:нг)?(?:[-–](?:LS|HF|LS[-–]HF|FRLS|FRHF))?)\s*'
    r'(\d+\s*[x×xх]\s*\d+(?:[.,]\d+)?(?:\s*(?:мм|mm)²?)?)',
    re.IGNORECASE,
)

# Pipe sizing  (e.g. "Ду50", "DN 50/PN16", "Ду 80/Ру 16")
_DN = re.compile(
    r'(?:Ду|DN|ДУ)\s*\d+(?:\s*/\s*(?:PN|Ру|РУ)\s*\d+)?',
    re.IGNORECASE,
)

# Cyrillic model codes  (e.g. "ЦНС 38-44", "АИР 80А2", "ВЦ 10-56-5")
_CYR_MODEL = re.compile(
    r'\b([А-ЯЁ]{2,5}\s*\d+[А-ЯЁ]?\d*\s*[-–/]\s*[А-ЯЁ0-9][-А-ЯЁA-Z0-9/\- ]{1,20})\b',
)

# Latin model codes  (e.g. "CM3-5 A-R-A-E", "ACS580-01-012A-4", "WEG W21 90L")
_LAT_MODEL = re.compile(
    r'\b([A-Z]{1,5}\d+[A-Z0-9]*[-–/][A-Z0-9][-A-Z0-9/\-]{2,25})\b',
)


# ── Public API ──────────────────────────────────────────────────────────────────

def extract_product_identifier(
    spec_text:    Optional[str] = None,
    brand_model:  Optional[str] = None,
    product_name: Optional[str] = None,
) -> Optional[str]:
    """
    Return the most specific product identifier available, or None.
    None means the caller should show "Модель не указана".
    """
    # 1. brand_model wins if it looks specific (has digits / standard codes)
    if brand_model:
        cleaned = _clean(brand_model)
        if cleaned and _is_specific(cleaned):
            return _shorten(cleaned, 160)

    # 2. Regex extraction from raw spec text
    if spec_text:
        found = _scan_text(spec_text[:4000])
        if found:
            return found

    # 3. product_name — only if it looks like a code, not a generic noun
    if product_name:
        cleaned = _clean(product_name)
        if cleaned and _is_specific(cleaned):
            return _shorten(cleaned, 160)

    return None


# ── Internal helpers ──────────────────────────────────────────────────────────

def _clean(s: str) -> str:
    return " ".join(s.split()).strip()


def _shorten(s: str, n: int) -> str:
    return s[:n].rstrip() if len(s) > n else s


def _is_specific(text: str) -> bool:
    """True when the string contains digits/standard codes → likely a real identifier."""
    if len(text) < 3 or len(text) > 250:
        return False
    # Must contain at least one digit
    if not re.search(r'\d', text):
        return False
    # Reject pure numbers
    if re.match(r'^\d+[\s.,]*$', text):
        return False
    return True


def _get_line(text: str, match_start: int, match_end: int, extra: int = 60) -> str:
    """Return the full line(s) surrounding a regex match, trimmed."""
    line_start = text.rfind('\n', 0, match_start)
    line_start = line_start + 1 if line_start >= 0 else 0
    line_end   = text.find('\n', match_end)
    line_end   = line_end if line_end >= 0 else match_end + extra
    return _clean(text[line_start:line_end])


def _scan_text(text: str) -> Optional[str]:
    """Try patterns in priority order and return the best match."""

    # ── 1. Cable + ГОСТ (most specific combination) ──
    cable_m = _CABLE.search(text)
    if cable_m:
        designation = _clean(cable_m.group(0))
        # Try to attach the nearest ГОСТ within 300 chars
        window = text[cable_m.start(): cable_m.start() + 300]
        gost_m = _GOST.search(window)
        if gost_m:
            return _shorten(f"{designation} {gost_m.group(0)}", 160)
        return _shorten(designation, 160)

    # ── 2. ГОСТ with surrounding product name ──
    gost_m = _GOST.search(text)
    if gost_m:
        line = _get_line(text, gost_m.start(), gost_m.end())
        if len(line) >= 5:
            return _shorten(line, 160)

    # ── 3. ТУ with context ──
    tu_m = _TU.search(text)
    if tu_m:
        line = _get_line(text, tu_m.start(), tu_m.end())
        if len(line) >= 5:
            return _shorten(line, 160)

    # ── 4. Pipe sizing ──
    dn_m = _DN.search(text)
    if dn_m:
        line = _get_line(text, dn_m.start(), dn_m.end(), extra=40)
        return _shorten(line, 120)

    # ── 5. Cyrillic model code ──
    cyr_m = _CYR_MODEL.search(text)
    if cyr_m:
        return _shorten(_clean(cyr_m.group(0)), 100)

    # ── 6. Latin model code ──
    lat_m = _LAT_MODEL.search(text)
    if lat_m:
        return _shorten(_clean(lat_m.group(0)), 100)

    return None
