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

# Short marking  e.g. "LED-12", "T8-18W", "MR16-7", "ТРВ-5", "GU10-9W"
# — letters + dash + digits + optional unit suffix, ≥3 letters or has digits
# Matches a lot of real-world part numbers that _LAT is too strict for.
_SHORT_MARK = re.compile(
    r'\b([A-Z]{2,5}[-–]\d{1,4}(?:[A-Z]{1,4})?)\b'
)

# ── Discriminator attributes — what differs Lamp G13 18W from Lamp E27 9W ──
# These are the parameters that turn "8 random lamps from Kaspi" into
# "the right lamp". Each finds a single normalised token to inject into
# the supplier search query. Order matters — most discriminating first.

# Lamp socket / base type — for product category "лампа"
# G13, E27, E14, E40, GU10, GU5.3, MR16, GX53, T8, T5, R7s, B22
_SOCKET = re.compile(
    r'\b(?:цоколь[ая]?\s+|тип\s+цоколя\s+)?'
    r'(G\s?\d{1,2}(?:\.\d)?|E\s?\d{1,2}|GU\s?\d{1,2}(?:\.\d)?|GX\s?\d{1,2}|'
    r'MR\s?\d{1,2}|R7s|B\s?\d{1,2}|T\s?\d{1,2})\b',
    re.IGNORECASE,
)

# Power: 18 Вт, 100W, 0.5 кВт, 250mW
_POWER = re.compile(
    r'\b(\d+(?:[.,]\d+)?)\s*(к?[Вв]т|к?W|mW|МВт)\b'
)

# Voltage: 220 В, 12V, 24В DC
_VOLTAGE = re.compile(
    r'\b(\d+(?:[.,]\d+)?)\s*(В|V)\b(?:\s*(AC|DC|постоянн|переменн)\w*)?'
)

# Ingress protection: IP65, IP67, IP44, IP20
_IP = re.compile(r'\b(IP[\s-]?\d{2})\b', re.IGNORECASE)

# Paper / sheet format: A4, A3, B5 — accepts both Latin A/B and Cyrillic
# А/В (U+0410 / U+0412) since Russian goszakup specs mix both, and the
# Cyrillic glyphs look identical to the user. Result is normalised to
# Latin in _extract_key_attributes for consistent search queries.
_PAPER = re.compile(r'(?:^|[^\wА-Яа-я])([ABАВ]\d)(?=[\s.,;:)\]]|$)', re.IGNORECASE)

# Density: 80 г/м2, 150 г/м²
_DENSITY = re.compile(r'\b(\d+)\s*г/м[²2]\b')

# Length / size hints in mm/cm/m: "1200 мм", "L=600", "длина 4 м"
_LENGTH = re.compile(
    r'\b(?:L\s*=\s*|длина[ой]?\s+|размер\s+)?(\d+(?:[.,]\d+)?)\s*(мм|см|м)\b',
    re.IGNORECASE,
)

# Capacity / load: 5 т, 50 кг, 100 л
_CAPACITY = re.compile(
    r'\b(\d+(?:[.,]\d+)?)\s*(т|кг|л|m³|м³)\b(?!\w)',
    re.IGNORECASE,
)

# Generic prefixes to strip from lot titles
_TITLE_PREFIXES = re.compile(
    r'^(поставка|приобретение|закупка|оказание|выполнение|предоставление)'
    r'[\s,]+',
    re.IGNORECASE,
)


# ── public API ─────────────────────────────────────────────────────────────────

def _parse_spec_table(spec: str) -> dict[str, str]:
    """
    Parse structured spec text (key: value lines) into a dict.
    Handles the goszakup table format produced by pdfplumber extraction.
    """
    result: dict[str, str] = {}
    for line in spec.splitlines():
        idx = line.find(':')
        if 0 < idx < 200:
            k = line[:idx].strip().lower()
            v = line[idx + 1:].replace(':', '', 1).strip()
            if k and v:
                result[k] = v
    return result


# Fields that carry product identity from goszakup spec table
_SPEC_NAME_KEYS  = ('наименование лота', 'наименование закупки')
_SPEC_DESC_KEYS  = ('описание лота', 'дополнительное описание лота')
_SPEC_TECH_KEYS  = ('описание и требуемые', 'функциональные', 'характеристики')

# Material/attribute words worth keeping in the search query
_MATERIAL_WORDS = re.compile(
    r'\b(хром|нержавеющ|латун|сталь|пластик|резин|алюмин|медн|чугун|'
    r'белый|черный|матов|глянц|led|rgb|встраив|накладн|однорук|двухрук|'
    r'термостат|смесит|душ|кран|вентил|насос|помп|мотор|датчик|контрол)\w*\b',
    re.IGNORECASE,
)


def _build_query_from_table(table: dict[str, str], title: str) -> str:
    """
    Build a precise search query from parsed spec table fields.
    E.g. "Смеситель для душа хром латунь" instead of "Смеситель"
    """
    name = ""
    for k in _SPEC_NAME_KEYS:
        for key in table:
            if k in key:
                name = table[key]
                break
        if name:
            break

    desc_parts: list[str] = []
    for k in _SPEC_DESC_KEYS:
        for key in table:
            if k in key and table[key] and table[key] != name:
                desc_parts.append(table[key])
                break

    tech = ""
    for k in _SPEC_TECH_KEYS:
        for key in table:
            if k in key:
                tech = table[key]
                break
        if tech:
            break

    # Combine name + description into base query
    combined = " ".join(filter(None, [name or title, *desc_parts, tech]))

    # Extract material/attribute keywords from combined text
    materials = list(dict.fromkeys(
        m.group(0).lower() for m in _MATERIAL_WORDS.finditer(combined)
    ))

    base = name or title
    enriched = base
    if desc_parts:
        short_desc = desc_parts[0].split(',')[0].strip()
        enriched = f"{base} {short_desc}"

    # Add materials/attributes not already present in enriched
    enriched_lower = enriched.lower()
    extra = [m for m in materials if m not in enriched_lower][:2]
    if extra:
        enriched = enriched + " " + " ".join(extra)

    # Deduplicate words while preserving order
    seen: set[str] = set()
    words = []
    for w in enriched.split():
        wl = w.lower()
        if wl not in seen:
            seen.add(wl)
            words.append(w)

    return _shorten(" ".join(words), 100)


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

    # ── Stage 0: parse structured spec table (goszakup key:value format) ────────
    spec_table = _parse_spec_table(spec) if spec else {}

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
    if not params:
        if spec_table:
            # Use parsed table directly — already key:value structured
            _SKIP = {'номер закупки', 'наименование закупки', 'номер лота',
                     'места поставки', 'срок поставки', 'единица измерения', 'количество'}
            params = {k: v for k, v in spec_table.items()
                      if k not in _SKIP and len(v) < 200}
        elif spec:
            params = _extract_inline_params(spec)

    # ── Stage 3b: pull discriminator attributes from spec + AI params ──────────
    # These (socket type, power, IP, paper format, length, capacity, …) are
    # the things that turn a generic "Лампа светодиодная" search into a
    # precise "Лампа светодиодная G13 18 Вт 1200 мм" search. Source order:
    # spec text first (richest), then AI technical_params values, then title
    # — so explicit numbers in the goszakup PDF win over AI guesses.
    attr_source = "\n".join(filter(None, [
        spec,
        " ".join(str(v) for v in (ai_technical_params or {}).values()),
        title,
    ]))
    key_attrs = _extract_key_attributes(attr_source)

    # Stash them under namespaced keys so they don't clobber regular params
    for k, v in key_attrs.items():
        params.setdefault(f"_attr_{k}", v)

    # ── Stage 4: build search_query ─────────────────────────────────────────────
    if spec_table and source in ("ai_name", "title"):
        # Structured spec available — build enriched query from table
        search_query = _build_query_from_table(spec_table, product_name)
    else:
        parts = [product_name]
        if model and model != product_name:
            parts.append(model)
        if standard:
            parts.append(standard)
        search_query = _shorten(" ".join(dict.fromkeys(parts)), 120)

    # Inject discriminator attributes into the supplier search query.
    # This is the whole point of Stage 3b — making "G13 18 Вт" land in
    # the Kaspi URL, not just sit in a parameters dict nobody reads.
    search_query = _merge_attrs_into_query(search_query, key_attrs)

    brand_out = ai_brand.strip() or None

    return {
        "product_name":  _shorten(product_name, 200),
        "model":         _shorten(model, 160) if model else None,
        "brand":         brand_out,
        "standard":      standard,
        "parameters":    params,
        "key_attributes": key_attrs,
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


def _extract_key_attributes(text: str) -> dict[str, str]:
    """
    Pull the handful of attributes that actually distinguish similar products
    on a marketplace — socket type, power, voltage, IP rating, paper format,
    density, characteristic length, load capacity. These are what we'll add
    to the supplier search query so Kaspi/Satu return the RIGHT lamp/cable/
    bag, not eight random ones with the same generic name.

    Returns a small dict of normalised tokens. Each value is suitable to
    drop into a search string verbatim (e.g. "G13", "18 Вт", "IP65", "А4").
    Empty dict if nothing matches.
    """
    if not text:
        return {}
    out: dict[str, str] = {}
    sample = text[:6000]  # cap regex work on huge specs

    # Socket type — the single biggest discriminator for lamps
    m = _SOCKET.search(sample)
    if m:
        token = m.group(1).upper().replace(" ", "")
        # Skip false positives like "B22" inside model numbers — require it
        # to be near a lamp/socket cue word
        ctx_lo = max(0, m.start() - 80)
        ctx = sample[ctx_lo:m.end() + 40].lower()
        if any(w in ctx for w in ("цокол", "лампа", "патрон", "socket", "base")):
            out["socket"] = token

    # Power — only first match; gpt analyzers tend to repeat it
    m = _POWER.search(sample)
    if m:
        unit = m.group(2).replace("в", "В").replace("т", "т")  # normalise
        # Keep Latin form when source was W/kW (matches marketplace listings better)
        if "W" in m.group(2) or "w" in m.group(2):
            unit = m.group(2).upper().replace("MW", "mW")
        out["power"] = f"{m.group(1).replace(',', '.')} {unit}"

    # Voltage — useful for transformers, drivers, motors
    m = _VOLTAGE.search(sample)
    if m:
        out["voltage"] = f"{m.group(1)} {m.group(2)}"

    # IP rating
    m = _IP.search(sample)
    if m:
        out["ip"] = m.group(1).upper().replace(" ", "").replace("-", "")

    # Paper format (А4 in Cyrillic looks identical to A4 — normalise to Latin
    # so the same query token matches both Cyrillic and Latin marketplace SKUs)
    m = _PAPER.search(sample)
    if m:
        token = m.group(1).upper()
        token = token.replace("А", "A").replace("В", "B")  # Cyrillic → Latin
        out["format"] = token

    # Paper / sheet density — emit ASCII-safe form (no superscript ²) so it
    # doesn't break URL encoding / log printing; "г/м2" matches marketplace
    # listings just as well as "г/м²".
    m = _DENSITY.search(sample)
    if m:
        out["density"] = f"{m.group(1)} г/м2"

    # Length — often critical for cables, lamps (T8 600mm vs 1200mm), pipes
    m = _LENGTH.search(sample)
    if m:
        unit = m.group(2)
        out["length"] = f"{m.group(1).replace(',', '.')} {unit}"

    # Load capacity — for tow ropes, slings, hoists
    m = _CAPACITY.search(sample)
    if m:
        out["capacity"] = f"{m.group(1).replace(',', '.')} {m.group(2)}"

    return out


def _merge_attrs_into_query(query: str, attrs: dict[str, str]) -> str:
    """
    Append discriminator attributes to a search query, but only those not
    already present (case-insensitive substring check). Cap the final string
    so marketplace search engines don't choke.
    """
    if not attrs:
        return query
    q_lower = query.lower()
    additions = []
    # Order matters: most-discriminating first so they survive the length cap
    for key in ("socket", "power", "format", "density", "ip", "voltage",
                "length", "capacity"):
        v = attrs.get(key)
        if not v:
            continue
        if v.lower() in q_lower:
            continue
        additions.append(v)
    if not additions:
        return query
    enriched = (query + " " + " ".join(additions)).strip()
    return _shorten(enriched, 140)
