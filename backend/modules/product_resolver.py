"""
Product Resolver — two-stage product identification for tender specifications.

Stage 1  (regex, always runs):
  Extract ГОСТ/ТУ standard, model/marking, cable designation, pipe sizing,
  and key parameters directly from raw specification text.

Stage 2  (enrichment, uses AI data when available):
  Merge regex findings with AI-extracted fields (product_name, brand_model,
  technical_params) to produce the most precise identification possible.

Returns a ResolvedProduct dict with:
  product_name  — best human-readable name for display
  model         — specific marking/model code (e.g. "ВВГнг-LS 3×2.5")
  standard      — ГОСТ / ТУ / ISO number if found
  parameters    — key technical params dict
  search_query  — optimised supplier search string (≤120 chars)
  source        — where the name came from: "ai_model" | "regex" | "ai_name" | "title"

The search_query is what SupplierDiscoveryEngine uses for URL building.
It combines the most specific parts: model + standard, or product_name + standard.

No AI calls. No DB access. No external dependencies.  Never raises.
"""
from __future__ import annotations

import re
from typing import Optional

# ── regex patterns ─────────────────────────────────────────────────────────────

# Standards
_GOST = re.compile(r'ГОСТ\s+Р?\s*\d{4,6}[-–]\d{2,4}(?:[-–]\d+)?', re.IGNORECASE)
_TU   = re.compile(r'ТУ\s+[\d\.]+[-–][\d\.\-]+', re.IGNORECASE)
_ISO  = re.compile(r'ISO\s+\d{4,6}(?:[-–]\d+)?', re.IGNORECASE)

# Cable / wire  e.g. "ВВГнг-LS 3×2.5 мм²", "NYY 4x10"
_CABLE = re.compile(
    r'\b([А-ЯЁA-Z]{2,8}(?:нг)?(?:[-–](?:LS|HF|LS[-–]HF|FRLS|FRHF))?)\s*'
    r'(\d+\s*[x×xх]\s*\d+(?:[.,]\d+)?(?:\s*(?:мм|mm)²?)?)',
    re.IGNORECASE,
)

# Pipe sizing  e.g. "Ду50/PN16", "DN 80"
_DN = re.compile(r'(?:Ду|DN|ДУ)\s*\d+(?:\s*/\s*(?:PN|Ру|РУ)\s*\d+)?', re.IGNORECASE)

# Cyrillic model  e.g. "ЦНС 38-44", "АИР 80А2", "ВЦ 10-56-5"
_CYR = re.compile(r'\b([А-ЯЁ]{2,5}\s*\d+[А-ЯЁ]?\d*\s*[-–/]\s*[А-ЯЁ0-9][-А-ЯЁA-Z0-9/\- ]{1,20})\b')

# Latin model  e.g. "ACS580-01-012A-4", "CM3-5 A-R-A-E"
_LAT = re.compile(r'\b([A-Z]{1,6}\d+[A-Z0-9]*[-–/][A-Z0-9][-A-Z0-9/\-]{2,25})\b')

# Generic prefixes to strip from lot titles
_TITLE_PREFIXES = re.compile(
    r'^(поставка|приобретение|закупка|оказание|выполнение|предоставление)'
    r'[\s,]+',
    re.IGNORECASE,
)


# ── public API ─────────────────────────────────────────────────────────────────

def resolve_product(
    spec_text:          str  = "",
    title:              str  = "",
    ai_product_name:    str  = "",
    ai_brand_model:     str  = "",
    ai_brand:           str  = "",   # explicit brand field from AI analysis
    ai_technical_params: Optional[dict] = None,
) -> dict:
    """
    Resolve structured product identity from all available data sources.

    Args:
        spec_text:           raw technical specification text from the lot
        title:               lot title (fallback if spec_text is empty)
        ai_product_name:     product_name field from TenderLotAnalysis (may be generic)
        ai_brand_model:      brand_model field from TenderLotAnalysis (usually specific)
        ai_technical_params: technical_params JSON from TenderLotAnalysis

    Returns dict with keys:
        product_name  str       display name
        model         str|None  marking / model code
        standard      str|None  ГОСТ / ТУ / ISO
        parameters    dict      key technical specs
        search_query  str       optimised search string for supplier URLs
        source        str       "ai_model" | "regex" | "ai_name" | "title"
    """
    spec = (spec_text or "").strip()
    params = dict(ai_technical_params or {})

    # ── Stage 1: extract standard and model from spec text ──────────────────────
    standard = _extract_standard(spec)
    regex_model, regex_name = _extract_model_and_name(spec, standard)

    # ── Stage 2: determine product_name (priority chain) ────────────────────────
    product_name: str = ""
    model:        Optional[str] = None
    source:       str = "title"

    # 2a. AI brand_model — most specific when it looks like a real code
    if ai_brand_model and _looks_specific(ai_brand_model):
        product_name = _clean(ai_brand_model)
        model = product_name
        source = "ai_model"

    # 2b. Regex extraction — cable designation or model code from spec text
    elif regex_model:
        product_name = regex_model
        model = regex_model
        source = "regex"

    # 2c. AI product_name — use only when it looks specific (has numbers / codes)
    elif ai_product_name and _looks_specific(ai_product_name):
        product_name = _clean(ai_product_name)
        model = None
        source = "ai_name"

    # 2d. regex_name — broader context line (e.g. line containing ГОСТ)
    elif regex_name:
        product_name = regex_name
        model = None
        source = "regex"

    # 2e. AI product_name regardless of specificity (better than raw title)
    elif ai_product_name:
        product_name = _clean(ai_product_name)
        source = "ai_name"

    # 2f. Cleaned title — last resort
    else:
        product_name = _clean_title(title)
        source = "title"

    if not product_name:
        product_name = "product"
        source = "title"

    # ── Stage 3: build parameters dict ──────────────────────────────────────────
    if not params and spec:
        params = _extract_inline_params(spec)

    # ── Stage 4: build search_query ─────────────────────────────────────────────
    parts = [product_name]
    if model and model != product_name:
        parts.append(model)
    if standard:
        parts.append(standard)
    search_query = _shorten(" ".join(dict.fromkeys(parts)), 120)   # dedup + truncate

    brand_out = ai_brand.strip() or None

    return {
        "product_name":  _shorten(product_name, 200),
        "model":         _shorten(model, 160) if model else None,
        "brand":         brand_out,
        "standard":      standard,
        "parameters":    params,
        "search_query":  search_query,
        "source":        source,
    }


# ── internal helpers ───────────────────────────────────────────────────────────

def _clean(s: str) -> str:
    return " ".join(s.split()).strip()


def _shorten(s: str, n: int) -> str:
    s = _clean(s)
    return s[:n].rstrip() if len(s) > n else s


def _looks_specific(text: str) -> bool:
    """True when text contains digits / standard codes → likely a real identifier."""
    t = text.strip()
    if not t or len(t) > 250:
        return False
    if not re.search(r'\d', t):
        return False
    if re.match(r'^\d+[\s.,]*$', t):  # reject bare numbers
        return False
    return True


def _clean_title(title: str) -> str:
    """Strip generic procurement prefixes from lot title."""
    t = _clean(title)
    t = _TITLE_PREFIXES.sub("", t)
    return t.strip().rstrip(".,;").strip()


def _get_line(text: str, start: int, end: int, extra: int = 60) -> str:
    ls = text.rfind('\n', 0, start)
    ls = ls + 1 if ls >= 0 else 0
    le = text.find('\n', end)
    le = le if le >= 0 else end + extra
    return _clean(text[ls:le])


def _extract_standard(spec: str) -> Optional[str]:
    """Return first ГОСТ / ТУ / ISO standard found in spec text."""
    if not spec:
        return None
    for pat in (_GOST, _TU, _ISO):
        m = pat.search(spec)
        if m:
            return _clean(m.group(0))
    return None


def _extract_model_and_name(spec: str, standard: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """
    Returns (model_code, context_name).
    model_code: the tightest identifier (cable designation, model code).
    context_name: the full line surrounding a standard marker.
    """
    if not spec:
        return None, None

    model:        Optional[str] = None
    context_name: Optional[str] = None

    # Cable designation (highest specificity for cable tenders)
    cable_m = _CABLE.search(spec)
    if cable_m:
        designation = _clean(cable_m.group(0))
        # Attach nearest ГОСТ within 300 chars
        window = spec[cable_m.start(): cable_m.start() + 300]
        gost_m = _GOST.search(window)
        if gost_m:
            model = _shorten(f"{designation} {gost_m.group(0)}", 160)
        else:
            model = _shorten(designation, 160)
        return model, None

    # ГОСТ / ТУ context line
    for pat in (_GOST, _TU):
        m = pat.search(spec)
        if m:
            line = _get_line(spec, m.start(), m.end())
            if len(line) >= 5:
                context_name = _shorten(line, 160)
                break

    # Cyrillic model code
    cyr_m = _CYR.search(spec)
    if cyr_m:
        model = _shorten(_clean(cyr_m.group(0)), 100)

    # Latin model code (only if no Cyrillic found)
    if not model:
        lat_m = _LAT.search(spec)
        if lat_m:
            model = _shorten(_clean(lat_m.group(0)), 100)

    # Pipe sizing
    if not model:
        dn_m = _DN.search(spec)
        if dn_m:
            line = _get_line(spec, dn_m.start(), dn_m.end(), extra=40)
            model = _shorten(line, 120)

    return model, context_name


def _extract_inline_params(spec: str) -> dict:
    """
    Extract simple KEY: VALUE pairs from spec text (≤10 entries).
    Used as fallback when AI technical_params is empty.
    """
    params: dict = {}
    pattern = re.compile(r'^([^:\n]{3,40}):\s*(.{1,80})$', re.MULTILINE)
    for m in pattern.finditer(spec[:3000]):
        key = _clean(m.group(1))
        val = _clean(m.group(2))
        if key and val and len(params) < 10:
            params[key] = val
    return params
