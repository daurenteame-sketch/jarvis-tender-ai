"""
OpenAI API client for AI-powered tender analysis.
"""
import asyncio
import json
import re
from typing import Optional
import structlog
from openai import AsyncOpenAI

from core.config import settings

logger = structlog.get_logger(__name__)


# ── Regex fallback: extract numbers + units from raw text ─────────────────────

# Pass 1 — number followed by a known unit
_UNIT_RE = re.compile(
    r'(\d+(?:[.,]\d+)?'                                          # integer or decimal
    r'(?:\s*[-–×xхXX]\s*\d+(?:[.,]\d+)?)?)'                    # optional range/dimension
    r'\s*'
    r'(г/м²|г/м2|g/m²|g/m2'                                    # paper weight (must come first)
    r'|мм²|мм2|mm²|mm2'                                         # cross-section area
    r'|л/мин|м³/ч|м3/ч|м³/час|m³/h'                            # flow rate
    r'|об/мин|rpm'                                               # rotational speed
    r'|кВт·ч|кВтч|kWh'                                          # energy
    r'|кВт|кW'                                                   # power (kW before kV/W)
    r'|кВ'                                                       # kilovolt
    r'|Вт|W(?!\w)'                                              # watt
    r'|МПа|кПа|ПА(?!\w)|Па(?!\w)|бар|bar(?!\w)|atm'            # pressure
    r'|кГц|МГц|Гц|kHz|MHz|Hz(?!\w)'                            # frequency
    r'|кОм|МОм|Ом(?!\w)'                                        # resistance
    r'|мкФ|нФ|мФ|Ф(?!\w)'                                      # capacitance
    r'|кг(?!\w)|г(?!\w)'                                        # mass
    r'|мл(?!\w)|л(?!\w)'                                        # volume
    r'|°C|℃|°F'                                                 # temperature
    r'|мм(?!\w)|см(?!\w)|дм(?!\w)'                             # short lengths
    r'|[АA](?!\w)'                                              # amperes А/A (after longer units)
    r'|В(?!\w)|V(?!\w)'                                         # volts В/V
    r'|%'                                                        # percent
    r')',
    re.UNICODE | re.IGNORECASE,
)

# Pass 2 — standard format / size codes that have no numeric prefix
#   A4, A3, B5, IP65, ISO9001, DN50, PN16, R1/2", G3/4" …
_FORMAT_RE = re.compile(
    r'\b('
    r'[AB]\d(?!\d)'                                              # A4, A3, B5, …
    r'|IP\d{2}'                                                  # IP65, IP67
    r'|DN\s*\d+'                                                 # DN50, DN100
    r'|Ду\s*\d+'                                                 # Ду50
    r'|PN\s*\d+'                                                 # PN16
    r'|R\s*\d+[/\d]*"?'                                         # R1/2"
    r'|G\s*\d+[/\d]*"?'                                         # G3/4"
    r'|(?:ISO|ГОСТ|ТУ)\s*[\d\-]+'                               # standards
    r')',
    re.UNICODE | re.IGNORECASE,
)

# ── Descriptive-phrase patterns (non-numeric fallback) ────────────────────────

# Standard / norm references that include numbers (ГОСТ 12345, ТУ 1234-001, ISO 9001)
_STD_RE = re.compile(
    r'\b(?:ГОСТ|ТУ|ISO|ИСО|СТ\s+РК)\s*[\d][\d\.\-]*',
    re.UNICODE | re.IGNORECASE,
)

# Material keywords (Cyrillic)
_MATERIAL_RE = re.compile(
    r'\b('
    r'сталь(?:н(?:ой|ая|ое|ых))?'
    r'|нержавею(?:щ(?:ий|ая|ее|их))?'
    r'|чугун(?:н(?:ый|ая|ое))?'
    r'|алюмини(?:й|евый|евая|евое)'
    r'|латун(?:н(?:ый|ая|ое))?'
    r'|медн(?:ый|ая|ое)?|медь'
    r'|пластик(?:овый|овая|овое)?'
    r'|резин(?:овый|овая|овое)?|резина'
    r'|полиэтилен(?:овый)?'
    r'|полипропилен(?:овый)?'
    r'|поликарбонат(?:овый)?'
    r'|полиамид|нейлон|тефлон|текстолит'
    r'|дерев(?:янный|янная|янное)?'
    r'|цинк(?:овый|ован(?:ый|ая|ое))?'
    r'|хром(?:ированный|ированная)?'
    r'|стеклопластик|углепластик'
    r')',
    re.UNICODE | re.IGNORECASE,
)

# Purpose phrase: "для [gerund/noun up to 3 words]"
_PURPOSE_RE = re.compile(
    r'для\s+((?:[а-яёА-ЯЁ][\w]*\s*){1,3})',
    re.UNICODE | re.IGNORECASE,
)

# Type / class / series label
_TYPE_RE = re.compile(
    r'\b(?:тип|класс|серия|исполнение|марка|вид)\s*:?\s*([А-ЯЁA-Z0-9][^\s,;\.]{0,20})',
    re.UNICODE | re.IGNORECASE,
)

# Brand detection — Latin capitalised word (≥2 chars), not a common English word
_LATIN_BRAND_RE = re.compile(
    r'\b([A-Z][A-Za-z0-9]{1,20}(?:\s+[A-Z][A-Za-z0-9]{1,20}){0,2})\b',
    re.UNICODE,
)
# Words to exclude from brand detection (common English / abbrev)
_NON_BRAND = {
    "the", "and", "for", "with", "from", "not", "are", "gost",
    "iso", "iec", "din", "tu", "st", "rk", "no", "id", "ip",
    "ok", "at", "be", "do", "in", "of", "on", "up", "us",
    "to", "by", "as", "an", "or", "if",
}

# Common product-type nouns (Cyrillic) — first meaningful noun in the title/spec
_PRODUCT_TYPE_RE = re.compile(
    r'\b(клей|насос|кабель|провод|труба|клапан|вентиль|задвижка'
    r'|светильник|лампа|прожектор|выключатель|розетка|щит|автомат'
    r'|реле|контактор|трансформатор|инвертор|преобразователь'
    r'|двигатель|мотор|насос|помпа|компрессор|вентилятор'
    r'|датчик|счётчик|манометр|термометр|термостат'
    r'|краска|грунтовка|шпатлёвка|лак|эмаль|герметик|клей'
    r'|перчатки|очки|каска|жилет|костюм|сапоги|ботинки'
    r'|ключ|гайковёрт|дрель|болгарка|шуруповёрт|молоток|плоскогубцы|кусачки|клещи'
    r'|шкаф|стол|стул|тумба|стеллаж|полка|ящик|контейнер'
    r'|принтер|сканер|монитор|компьютер|ноутбук|планшет|телефон'
    r'|огнетушитель|пожарный|аптечка|носилки'
    r'|ткань|ткани|материал|средство|препарат|раствор|смесь'
    r'|кондиционер|холодильник|нагреватель|обогреватель'
    r'|оборудование|устройство|прибор|аппарат|агрегат|установка|система)',
    re.UNICODE | re.IGNORECASE,
)

# Key adjective / property words (non-numeric descriptors worth keeping)
_ADJECTIVE_RE = re.compile(
    r'\b(высокопрочн\w+|жаростойк\w+|морозостойк\w+|влагостойк\w+|водостойк\w+'
    r'|огнестойк\w+|химическ\w+стойк\w+|антикоррозийн\w+'
    r'|многоразов\w+|одноразов\w+'
    r'|усиленн\w+|закалённ\w+|армированн\w+'
    r'|прозрачн\w+|непрозрачн\w+'
    r'|гибк\w+|жёстк\w+'
    r'|пружинн\w+|самозажимн\w+|разъёмн\w+)',
    re.UNICODE | re.IGNORECASE,
)

# First meaningful sentence (ends with . ! ?)
_SENTENCE_RE = re.compile(
    r'([А-ЯЁA-Z][^.!?\n]{20,200}[.!?])',
    re.UNICODE,
)


def _extract_chars_regex(text: str) -> Optional[str]:
    """
    Multi-pass fallback that extracts measurable specs from raw text.

    Pass 1 — number+unit pairs  (e.g. "80 г/м²", "32A", "2.5мм²")
    Pass 2 — format/size codes  (e.g. "A4", "IP65", "DN50")
    Pass 3 — broad simple units (мм, см, м, кг, г, в, w, л, мл) case-insensitive
    Pass 4 — bare numbers (last resort, max 3) when passes 1-3 found nothing

    Returns a compact comma-joined string, or None only when the text is
    truly devoid of any measurable or identifying data.
    """
    scan = text[:3000]
    seen: list[str] = []

    # Pass 1: number + known unit
    for m in _UNIT_RE.finditer(scan):
        num  = m.group(1).replace(' ', '')
        unit = m.group(2)
        pair = f"{num} {unit}".strip()
        if pair not in seen:
            seen.append(pair)
        if len(seen) >= 7:
            break

    # Pass 2: format / size codes (A4, IP65, DN50, …)
    for m in _FORMAT_RE.finditer(scan):
        token = m.group(1).strip()
        if token not in seen:
            seen.append(token)
        if len(seen) >= 7:
            break

    # Pass 3: broader simple units (catches мм, см, м, кг, г, в, w, л, мл)
    if not seen:
        _BROAD_RE = re.compile(r'(\d+)\s*(мм|см|м|кг|г|шт|в|w|л|мл)', re.IGNORECASE | re.UNICODE)
        for m in _BROAD_RE.finditer(scan):
            pair = f"{m.group(1)} {m.group(2)}"
            if pair not in seen:
                seen.append(pair)
            if len(seen) >= 5:
                break

    # Pass 4: bare integers — absolute last resort
    if not seen:
        for m in re.finditer(r'\b(\d+(?:[.,]\d+)?)\b', scan):
            n = m.group(1)
            if n not in seen and not n.startswith('0'):
                seen.append(n)
            if len(seen) >= 3:
                break

    return ", ".join(seen) if seen else None


def _detect_brand_from_text(text: str) -> Optional[str]:
    """
    Detect a brand name from text by finding capitalised Latin word sequences
    that don't look like common English words or abbreviations.
    Returns the first plausible brand token, or None.
    """
    scan = text[:1_500]
    for m in _LATIN_BRAND_RE.finditer(scan):
        candidate = m.group(1)
        # Reject if all words are on the exclusion list
        words = candidate.lower().split()
        if all(w in _NON_BRAND for w in words):
            continue
        # Reject single uppercase abbreviations of 2 chars (IP, DN, PN, …)
        if len(candidate) <= 2:
            continue
        return candidate
    return None


def _extract_descriptive_phrases(text: str) -> Optional[str]:
    """
    Non-numeric fallback: extract meaningful descriptive characteristics when
    the spec contains no measurable values (tools, cosmetics, materials, etc.).

    Collection order (highest signal first):
      1. Brand — Latin capitalised word(s) e.g. "Kryolan", "WAGO", "Henkel"
      2. Product type noun — клей, насос, клещи, кондиционер, …
      3. ГОСТ / ТУ / ISO standard references
      4. Material keywords — сталь, резина, алюминий, …
      5. Purpose phrases — "для демонтажа", "для монтажа кабелей"
      6. Key adjective properties — высокопрочный, многоразовый, …
      7. Type / class / series labels — "тип А", "класс 1"
      8. First meaningful sentence (≥20 chars) as a last-resort description

    Returns up to 7 items comma-joined, or None if nothing found.
    """
    scan = text[:2_500]
    parts: list[str] = []
    seen_prefixes: set[str] = set()

    def _add(token: str, max_len: int = 50) -> bool:
        """Add token if unique and within length; return True when list is full."""
        t = token.strip()
        if not t or len(t) > max_len:
            return False
        key = t[:6].lower()
        if key in seen_prefixes:
            return False
        seen_prefixes.add(key)
        parts.append(t)
        return len(parts) >= 7

    # 1. Brand from Latin capitalised words (e.g. "Kryolan", "Schneider Electric")
    brand = _detect_brand_from_text(scan)
    if brand:
        _add(brand)

    # 2. Product type noun
    for m in _PRODUCT_TYPE_RE.finditer(scan):
        if _add(m.group(0)):
            break

    # 3. Standard references — ГОСТ 12345, ТУ 1234-001, ISO 9001
    for m in _STD_RE.finditer(scan):
        if _add(m.group(0)):
            break

    # 4. Material keywords
    for m in _MATERIAL_RE.finditer(scan):
        if _add(m.group(0)):
            break

    # 5. Purpose phrases: "для демонтажа", "для монтажа кабелей"
    for m in _PURPOSE_RE.finditer(scan):
        phrase = "для " + m.group(1).strip()
        if _add(phrase, max_len=35):
            break

    # 6. Key adjective / property words
    for m in _ADJECTIVE_RE.finditer(scan):
        if _add(m.group(0)):
            break

    # 7. Type / class / series
    for m in _TYPE_RE.finditer(scan):
        if _add(m.group(0)):
            break

    # 8. Last resort: first meaningful sentence from the spec
    if not parts:
        for m in _SENTENCE_RE.finditer(scan):
            sentence = m.group(1).strip()
            if len(sentence) >= 20:
                parts.append(sentence[:120])
                break

    return ", ".join(parts) if parts else None


def _extract_tz_from_full(full_text: str) -> str:
    """
    Pull the ТЕХНИЧЕСКОЕ ЗАДАНИЕ section out of a pre-merged full_text string.
    Returns the section text, or the whole full_text if the marker isn't found.
    """
    marker = "ТЕХНИЧЕСКОЕ ЗАДАНИЕ:"
    idx = full_text.find(marker)
    if idx == -1:
        return full_text
    return full_text[idx + len(marker):].strip()


def _ensure_characteristics(
    characteristics: Optional[str],
    full_text: str,
    fallback_description: str = "",
) -> str:
    """
    Guarantee characteristics is always a non-empty string.

    Priority:
      1. AI value already filled → use it
      2. Numeric regex on full_text (numbers + units, format codes)
      3. Descriptive phrases (ГОСТ, materials, purpose, type/class)
      4. First 100 chars of fallback_description (title)
      5. Return "" — UI hides the field when empty
    """
    if characteristics and characteristics.strip():
        return characteristics.strip()

    # Step 2: numeric / format codes
    numeric = _extract_chars_regex(full_text)
    if numeric:
        print(f"[ensure_characteristics] numeric regex: {numeric}", flush=True)
        return numeric

    # Step 3: descriptive phrases (for non-numeric specs like tools, materials)
    descriptive = _extract_descriptive_phrases(full_text)
    if descriptive:
        print(f"[ensure_characteristics] descriptive phrases: {descriptive}", flush=True)
        return descriptive

    # Step 4: title as last-resort snippet
    snippet = fallback_description.strip()[:100]
    if snippet:
        print(f"[ensure_characteristics] title snippet: {snippet!r}", flush=True)
        return snippet

    return ""


# ── Quota circuit breaker ──────────────────────────────────────────────────────
# When OpenAI returns 429 / insufficient_quota, we mark the key as exhausted
# for QUOTA_BACKOFF_SECONDS so subsequent calls skip the API entirely and fall
# through to the catalog / hash fallback — avoiding pointless round-trips.

import time as _time

_quota_exhausted_until: float = 0.0          # epoch seconds
_QUOTA_BACKOFF_SECONDS: float = 3600.0       # retry after 1 hour


def _is_quota_exhausted() -> bool:
    return _time.monotonic() < _quota_exhausted_until


def _mark_quota_exhausted() -> None:
    global _quota_exhausted_until
    _quota_exhausted_until = _time.monotonic() + _QUOTA_BACKOFF_SECONDS
    logger.warning("OpenAI quota exhausted — disabling for 1 hour")


class OpenAIClient:
    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self.model = settings.OPENAI_MODEL

    async def analyze_tender_specification(
        self,
        title: str,
        description: str,
        spec_text: str,
        quantity: Optional[float] = None,
    ) -> dict:
        """
        Analyze tender specification and extract structured product info.
        Returns structured JSON with product details.
        """
        prompt = f"""You are an expert procurement analyst. Analyze this government tender specification and extract detailed product/service information.

TENDER TITLE: {title}

DESCRIPTION: {description[:2000] if description else 'N/A'}

TECHNICAL SPECIFICATION:
{spec_text[:6000] if spec_text else 'N/A'}

Extract and return a JSON object with these exact fields:
{{
  "product_name": "EXACT product name as written in the specification — copy verbatim including GOST/ISO standard numbers, grades, types, and all technical identifiers (e.g. 'Кабель ВВГнг-LS 3x2.5 мм² ГОСТ 31996-2012', 'Насос ЦНС 38-44 ТУ 3631-001'). NEVER use generic/simplified names like 'Кабель специализированный' or 'Насос центробежный'. If multiple products, name the main one.",
  "product_name_en": "product name in English including model/standard (e.g. 'Cable VVGng-LS 3x2.5 mm² GOST 31996-2012')",
  "category": "product OR software_service OR other",
  "brand_model": "brand AND/OR model/type explicitly stated in spec. For pharmaceuticals: dosage form + strength (e.g. 'таблетки 5мг', 'раствор 30мг/мл'). For equipment: full model code (e.g. 'ABB ACS580-01-012A-4'). null ONLY if spec has absolutely no form/type/model information.",
  "dimensions": "physical dimensions if relevant, null otherwise",
  "technical_params": {{
    "key": "value pairs of ALL technical parameters from the spec"
  }},
  "materials": "materials/grades specification if relevant, null otherwise",
  "quantity": {quantity or "null"},
  "unit": "unit of measurement (шт, м, кг, м2, комплект, etc.)",
  "analogs_allowed": true/false/null,
  "spec_clarity": "clear OR partial OR vague",
  "key_requirements": ["list", "of", "key", "requirements from spec"],
  "summary_ru": "ОБЯЗАТЕЛЬНО 2-3 содержательных предложения на русском: что это за товар, его назначение/применение, ключевые характеристики или требования. Даже если ТЗ минимальное — опиши природу товара и типичное применение. НЕ писать 'Техническая спецификация не указана' — вместо этого описать что известно о товаре по названию.",
  "exact_product_match": "КОНКРЕТНАЯ КОММЕРЧЕСКАЯ МОДЕЛЬ товара, наиболее точно соответствующая ТЗ. Для ноутбуков — конкретная модель: 'Lenovo IdeaPad 3 Gen 8 15ABA7 (Ryzen 5 7520U, 16GB, 512GB SSD)'. Для электроники без марки — предложи наиболее вероятную конкретную модель. null только если определить невозможно.",
  "is_software_related": true/false,
  "software_type": "website/mobile_app/erp/crm/ai/chatbot/portal/platform/other OR null",
  "estimated_complexity": "simple/medium/complex for software, null for products"
}}

CRITICAL RULES:
1. product_name — EXACT verbatim identifier from spec. Include all codes, GOST, grade, type.
   BAD: "Кабель специализированный"  GOOD: "Кабель ВВГнг-LS 3x2.5 мм² ГОСТ 31996-2012"
2. brand_model — for pharmaceuticals always fill with dosage form+strength if inferable from name.
   For equipment extract ONLY if explicitly written. null = truly no form/model info at all.
3. summary_ru — MUST be 2-3 informative sentences. NEVER write "спецификация не указана".
4. technical_params — include ALL numeric parameters (voltage, power, size, grade, standards).
5. category: "product"=physical goods; "software_service"=websites/apps/software; "other"=services.
6. exact_product_match — for laptops/computers/electronics ALWAYS fill in. Match the spec to a specific commercial model available in 2024-2025.

If a field is not mentioned in the specification, use null."""

        if _is_quota_exhausted():
            logger.debug("analyze_tender_specification skipped — quota exhausted")
            return self._default_analysis(title)

        try:
            print(f"OPENAI REQUEST SENT: analyze_tender_specification | model={self.model} | title={title[:60]}", flush=True)
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are a procurement analysis expert. Always respond with valid JSON only, no markdown.",
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=settings.OPENAI_MAX_TOKENS,
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
            print(f"OPENAI RESPONSE OK: analyze_tender_specification | tokens={response.usage.total_tokens}", flush=True)
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.error("Failed to parse AI response as JSON", error=str(e))
            return self._default_analysis(title)
        except Exception as e:
            err_str = str(e)
            if "insufficient_quota" in err_str or "429" in err_str:
                _mark_quota_exhausted()
            logger.error("OpenAI API error", error=err_str[:120])
            return self._default_analysis(title)

    async def identify_product(
        self,
        full_text: str = "",
        title: str = "",
        spec_text: str = "",      # raw ТЗ text — used for focused regex fallback
        description: str = "",    # legacy compat
    ) -> dict:
        """
        Structured product identification from tender text.

        Caller should pass:
          full_text  — pre-merged title + description + spec (primary input for AI)
          spec_text  — the ТЗ portion alone (used by regex fallback when AI returns empty)
          title      — short lot title (used as minimum fallback label)

        Returns:
          {
            "strict": {
              "product_name": str,
              "brand":         str | None,
              "model":         str | None,
              "characteristics": str | None,
              "quantity":      str | None,
            },
            "ai_suggestion": {
              "suggested_model": str | None,
              "confidence":      int,
            }
          }
        """
        # ── 1. Resolve input text ────────────────────────────────────────────
        input_text = full_text.strip()
        spec_only  = spec_text.strip()   # kept separate for regex priority

        # Legacy fallback: build from parts if full_text was not provided
        if not input_text:
            parts: list[str] = []
            if title.strip():
                parts.append(f"ЗАГОЛОВОК: {title.strip()}")
            if description.strip():
                parts.append(f"ОПИСАНИЕ ЛОТА:\n{description.strip()[:3000]}")
            if spec_only:
                parts.append(f"ТЕХНИЧЕСКОЕ ЗАДАНИЕ:\n{spec_only[:6000]}")
            input_text = "\n\n".join(parts)

        # Hard floor: at minimum use the title
        if len(input_text) < 50:
            input_text = f"ЗАГОЛОВОК: {title.strip() or 'нет данных'}"
            print(
                f"[identify_product] WARNING: input too short — using title only: {input_text!r}",
                flush=True,
            )

        # Cap at 10 000 chars to avoid overly long prompts
        if len(input_text) > 10_000:
            input_text = input_text[:7500] + "\n...[truncated]...\n" + input_text[-2500:]

        print(
            f"\n{'='*64}\n"
            f"[identify_product] INPUT: {len(input_text)} chars  spec_only: {len(spec_only)} chars\n"
            f"PREVIEW: {input_text[:500]}{'...' if len(input_text) > 500 else ''}\n"
            f"{'='*64}",
            flush=True,
        )

        # ── 2. Split text into sections for the prompt ───────────────────────
        # Extract each labelled section so the prompt can present them separately.
        # If full_text is already merged we pull them apart; if spec_only is set
        # use it directly.
        def _section(label: str, text: str, max_chars: int) -> str:
            """Return a titled block, capped at max_chars."""
            t = text.strip()[:max_chars]
            return f"{label}\n{t}" if t else ""

        # The ТЗ section is the richest — place it first in the prompt, capped
        # at 7 000 chars so the AI focuses on it rather than scanning the whole blob.
        tz_section = _section(
            "══════════ ТЕХНИЧЕСКОЕ ЗАДАНИЕ (ОСНОВНОЙ ИСТОЧНИК) ══════════",
            spec_only or _extract_tz_from_full(input_text),
            7_000,
        )
        title_line     = f"ЗАГОЛОВОК: {title.strip()}" if title.strip() else ""
        desc_section   = _section("ОПИСАНИЕ ЛОТА:", description.strip() or "", 1_000)

        # Compose prompt sections — ТЗ always first
        prompt_body_parts = [p for p in [tz_section, title_line, desc_section] if p]
        prompt_body = "\n\n".join(prompt_body_parts) or input_text  # fallback to full blob

        # ── 3. Prompt ────────────────────────────────────────────────────────
        prompt = f"""Ты — эксперт по государственным закупкам Казахстана.

⚠️ ПРИОРИТЕТ ИСТОЧНИКОВ:
  1. ТЕХНИЧЕСКОЕ ЗАДАНИЕ — главный источник характеристик, марки и модели.
  2. ОПИСАНИЕ ЛОТА — вспомогательный.
  3. ЗАГОЛОВОК — только если ТЗ отсутствует.

{prompt_body}

════════════════════════════════════════════════════════════════

ЗАДАЧА: извлечь структурированную карточку товара. Сканируй ВЕСЬ текст ТЗ целиком.

━━━━━━━━ БАЗОВЫЕ ПОЛЯ ━━━━━━━━

1. product_name — ПОЛНОЕ наименование товара из ТЗ.
   ❌ "Смазка", "Кабель"  — слишком коротко
   ✅ "Смазка пластичная Литол-24 ГОСТ 21150-87, ведро 5 кг"
   ✅ "Кабель силовой медный ВВГнг-LS ГОСТ 31996-2012"
   Включай: ГОСТ, тип, класс, исполнение, бренд, назначение — всё что есть в тексте.

2. brand — торговая марка / производитель.
   Ищи ЗАГЛАВНЫЕ ЛАТИНСКИЕ слова и кириллические марки.
   null только если в тексте НЕТ ни одного упоминания марки.

3. model — конкретный артикул / тип / ГОСТ-марка если ЯВНО указана.
   Примеры: "Литол-24", "ВВГнг-LS 3x2.5", "ACS580-01", "М400", "5 кг"
   null если не указан явно.

4. characteristics — ВСЕ ключевые параметры одной строкой через запятую.
   ══ ОБЯЗАТЕЛЬНОЕ ПОЛЕ — никогда не возвращай null ══
   Для смазок: "литиевая основа, -40...+120°C, ведро 5 кг, ГОСТ 21150-87"
   Для кабелей: "3×2.5мм², 220В, ГОСТ 31996-2012"
   Для электроники: "15.6" IPS, 16GB DDR4, 512GB SSD, Win11 Pro, 2кг"
   Для мебели: "металлический каркас, 120×60×75 см, нагрузка 100 кг"
   null — ЗАПРЕЩЕНО.

5. quantity — количество и единица из текста. null если не указано.

6. product_type — ОДНО слово: тип товара.
   "смазка", "кабель", "насос", "ноутбук", "принтер", "стол" и т.д.
   НЕЛЬЗЯ: "товар", "изделие", "продукция" — слишком общо.

7. normalized_name — краткое название (до 60 символов) для отображения.

━━━━━━━━ КАРТОЧКА ТОВАРА (ГЛАВНОЕ) ━━━━━━━━

8. key_specs — ОБЯЗАТЕЛЬНЫЙ массив параметров для отображения в карточке.
   Формат: [{{"label": "Название", "value": "Значение"}}]

   Для СМАЗКИ/МАСЛА:
   [{{"label":"Тип","value":"автомобильная смазка"}},
    {{"label":"Основа","value":"литиевая"}},
    {{"label":"Фасовка","value":"ведро 5 кг"}},
    {{"label":"Температура","value":"-40...+120°C"}},
    {{"label":"Стандарт","value":"ГОСТ 21150-87"}}]

   Для НОУТБУКА:
   [{{"label":"Дисплей","value":"15.6\" IPS Full HD"}},
    {{"label":"Процессор","value":"4+ ядра 2.0+ ГГц"}},
    {{"label":"ОЗУ","value":"16 ГБ DDR4"}},
    {{"label":"Накопитель","value":"512 ГБ SSD"}},
    {{"label":"ОС","value":"Windows 11 Pro"}},
    {{"label":"Вес","value":"до 2.2 кг"}}]

   Для КАБЕЛЯ:
   [{{"label":"Марка","value":"ВВГнг-LS"}},
    {{"label":"Сечение","value":"3×2.5 мм²"}},
    {{"label":"Напряжение","value":"660В"}},
    {{"label":"Стандарт","value":"ГОСТ 31996-2012"}}]

   ПРАВИЛА: 3–7 параметров, только важные. Всегда включай стандарт (ГОСТ/ТУ) если есть.
   ЗАПРЕЩЕНО возвращать пустой массив [].

9. procurement_hint — ЧТО ИСКАТЬ при закупке (строка, до 80 символов).
   Это готовая поисковая фраза для нахождения товара у поставщиков.
   Примеры:
   "Литол-24 ГОСТ 21150-87, ведро 5 кг" (для смазки)
   "ноутбук 15.6\" 16GB DDR4 512GB SSD Win11 Pro 2024" (для ноутбука)
   "кабель ВВГнг-LS 3×2.5мм² ГОСТ 31996-2012" (для кабеля)
   "насос ЦНС 38-44 центробежный секционный" (для насоса)

10. is_standard_based — true если товар определяется ГОСТ/ТУ/стандартом (не конкретным брендом).
    true: смазка Литол-24 ГОСТ, кабель ВВГнг, цемент М400
    false: ноутбук Lenovo, смазка Mobil 1, принтер HP

11. possible_suppliers — массив 3–5 реальных брендов/поставщиков этого товара.
    Для смазки Литол-24: ["Gazpromneft Литол-24", "Лукойл Литол-24", "Роснефть Литол-24", "Sintec Литол-24"]
    Для ноутбука 15.6": ["Lenovo IdeaPad 3", "Acer Aspire 5", "ASUS VivoBook 15", "HP 255 G9"]
    Для кабеля ВВГнг: ["Камкабель", "ЭКЗ", "Nexans", "Prysmian"]
    Для лекарства: ["Отечественный производитель", "Россия", "Индия (генерик)"]
    ЗАПРЕЩЕНО возвращать пустой массив [].

12. suggested_model — конкретная модель/марка для закупки.
    Для стандартизированных: "Литол-24 ГОСТ 21150-87" или "ВВГнг-LS 3×2.5мм²"
    Для ноутбука: "Lenovo IdeaPad 3 Gen 8 (Ryzen 5, 16GB, 512GB)" или "Acer Aspire 5 A515-58M"
    Для принтера: "HP LaserJet Pro M15a" или "Canon LBP6030"
    null только если совсем невозможно определить.

13. confidence — уверенность в suggested_model (0–100).
    Стандартизированный товар с ГОСТ: 75–90%
    Ноутбук/электроника с чёткими характеристиками: 60–80%
    Товар без чётких параметров: 20–40%

Верни JSON строго этого формата:
{{
  "product_name": "полное наименование",
  "brand": "марка или null",
  "model": "артикул/тип или null",
  "characteristics": "параметры через запятую — НИКОГДА не null",
  "quantity": "количество или null",
  "product_type": "одно слово — тип товара",
  "normalized_name": "краткое понятное название до 60 символов",
  "key_specs": [{{"label": "Параметр", "value": "Значение"}}],
  "procurement_hint": "что искать при закупке",
  "is_standard_based": true,
  "possible_suppliers": ["Бренд 1", "Бренд 2", "Бренд 3"],
  "suggested_model": "конкретная модель/марка",
  "confidence": 75
}}"""

        # ── 4. Regex fallback — precomputed before API call ──────────────────
        # Prioritise spec_only for regex; fall back to full input_text.
        _regex_source = spec_only or input_text
        _fallback_chars = (
            _extract_chars_regex(_regex_source)
            or _extract_chars_regex(input_text)
        )
        _fallback = {
            "strict": {
                "product_name": title or "Неизвестный товар",
                "brand": None,
                "model": None,
                "characteristics": _ensure_characteristics(
                    _fallback_chars, _regex_source, fallback_description=title
                ),
                "quantity": None,
            },
            "ai_suggestion": {"suggested_model": None, "confidence": 0},
        }

        # ── 5. Call API ──────────────────────────────────────────────────────
        if _is_quota_exhausted():
            logger.debug("identify_product skipped — quota exhausted")
            return _fallback

        try:
            print(
                f"[identify_product] → API request | model={self.model} | "
                f"prompt_body={len(prompt_body)} chars",
                flush=True,
            )
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Ты эксперт по государственным закупкам Казахстана. "
                            "Техническое задание — ГЛАВНЫЙ источник данных. "
                            "Characteristics — ОБЯЗАТЕЛЬНОЕ поле: если есть числа — все числа с единицами; "
                            "если чисел нет (инструменты, материалы) — назначение, материал, тип, ГОСТ. "
                            "null в characteristics ЗАПРЕЩЁН. "
                            "Отвечай только валидным JSON без комментариев."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=1800,
                temperature=0.0,
                response_format={"type": "json_object"},
            )

            raw_content = response.choices[0].message.content
            print(
                f"\n[identify_product] ← RAW RESPONSE ({response.usage.total_tokens} tokens):\n"
                f"{raw_content}\n",
                flush=True,
            )
            raw = json.loads(raw_content)

            # ── 6. Sanitize ──────────────────────────────────────────────────
            def _s(v: object) -> Optional[str]:
                """Return stripped string or None."""
                return str(v).strip() if v and str(v).strip() else None

            product_name      = _s(raw.get("product_name")) or title or "Неизвестный товар"
            brand             = _s(raw.get("brand"))
            model             = _s(raw.get("model"))
            quantity          = _s(raw.get("quantity"))
            suggested_model   = _s(raw.get("suggested_model"))
            conf_raw          = raw.get("confidence", 0)
            product_type      = _s(raw.get("product_type"))
            normalized_name   = _s(raw.get("normalized_name"))
            procurement_hint  = _s(raw.get("procurement_hint"))
            is_standard_based = bool(raw.get("is_standard_based", False))

            # key_specs: list of {label, value} dicts
            _raw_specs = raw.get("key_specs")
            key_specs: list = []
            if isinstance(_raw_specs, list):
                for item in _raw_specs:
                    if isinstance(item, dict) and item.get("label") and item.get("value"):
                        key_specs.append({
                            "label": str(item["label"]).strip(),
                            "value": str(item["value"]).strip(),
                        })

            # possible_suppliers: list of strings
            _raw_supp = raw.get("possible_suppliers")
            possible_suppliers: list = []
            if isinstance(_raw_supp, list):
                possible_suppliers = [str(s).strip() for s in _raw_supp if str(s).strip()]

            # characteristics may come back as a list ["a","b"] or a plain string
            _raw_chars = raw.get("characteristics")
            if isinstance(_raw_chars, list):
                characteristics = ", ".join(
                    str(item).strip() for item in _raw_chars if str(item).strip()
                ) or None
            else:
                characteristics = _s(_raw_chars)

            # If AI returned brand embedded in characteristics (e.g. "Kryolan, для усов")
            # and brand field is empty, try to detect brand from characteristics
            if not brand and characteristics:
                brand = _detect_brand_from_text(characteristics)
            # Also try detecting brand from spec text if still empty
            if not brand and spec_only:
                brand = _detect_brand_from_text(spec_only)

            # ── 7. Guarantee characteristics — regex on spec first ───────────
            if not characteristics:
                # Try spec_only first (richest, most focused)
                characteristics = _extract_chars_regex(spec_only) if spec_only else None
                if characteristics:
                    print(
                        f"[identify_product] characteristics null → regex on spec: {characteristics}",
                        flush=True,
                    )
            characteristics = _ensure_characteristics(
                characteristics, _regex_source, fallback_description=title
            )

            conf = max(0, min(100, int(conf_raw) if conf_raw else 0))

            print(f"PRODUCT TYPE:    {product_type!r}", flush=True)
            print(f"NORMALIZED NAME: {normalized_name!r}", flush=True)

            result = {
                "strict": {
                    "product_name":      product_name,
                    "brand":             brand,
                    "model":             model,
                    "characteristics":   characteristics,
                    "quantity":          quantity,
                    "product_type":      product_type,
                    "normalized_name":   normalized_name,
                    "key_specs":         key_specs,
                    "procurement_hint":  procurement_hint,
                    "is_standard_based": is_standard_based,
                    "possible_suppliers": possible_suppliers,
                },
                "ai_suggestion": {
                    "suggested_model": suggested_model,
                    "confidence":      conf,
                },
            }
            print(
                f"[identify_product] FINAL: {json.dumps(result, ensure_ascii=False)}\n"
                f"FINAL characteristics: {characteristics!r}\n"
                f"FINAL brand:           {brand!r}\n"
                f"FINAL model:           {model!r}",
                flush=True,
            )
            return result

        except json.JSONDecodeError as e:
            logger.error("identify_product: JSON parse error", error=str(e))
            return _fallback
        except Exception as e:
            err_str = str(e)
            if "insufficient_quota" in err_str or "429" in err_str:
                _mark_quota_exhausted()
            logger.error("identify_product: API error", error=err_str[:120])
            return _fallback

    async def search_product_web(
        self,
        product_name: str,
        characteristics: str = "",
        quantity: float = 1,
    ) -> dict:
        """
        Search for real wholesale prices using OpenAI web search (gpt-4o-search-preview).
        Priority: KZ market → RU market → CN market.

        Returns structured dict with:
          exact_match    bool   — found the specific model (not an analog)
          model_found    str    — identified model/article
          kz_kzt         float  — KZ market unit price in KZT (kaspi.kz, satu.kz, etc.)
          ru_kzt         float  — Russian market unit price in KZT (ozon.ru, wildberries.ru)
          china_usd      float  — Chinese market unit price in USD (alibaba.com)
          price_min_kzt  float  — minimum found unit price in KZT across all markets
          price_max_kzt  float  — maximum found unit price in KZT across all markets
          best_market    str    — "KZ" | "RU" | "CN"
          supplier_links list   — 3-5 direct URLs where product was found
          confidence     int    — 0-100

        IMPORTANT: All prices are per UNIT (шт/кг/м/л), NOT total.
        """
        qty_str = str(int(quantity)) if quantity and quantity >= 1 else "1"

        search_prompt = f"""Найди РЕАЛЬНЫЕ оптовые цены на товар для государственной закупки Казахстана.

ТОВАР: {product_name}
{("ХАРАКТЕРИСТИКИ: " + characteristics[:500]) if characteristics else ""}
КОЛИЧЕСТВО: {qty_str} единиц

ЗАДАЧА: Найди точную модель/артикул и ОПТОВЫЕ цены за ЕДИНИЦУ товара.

ПРИОРИТЕТ ПОИСКА:
1. Казахстан: kaspi.kz, satu.kz, market.kz, mz.kz — СНАЧАЛА ЭТО
2. Россия: wildberries.ru, ozon.ru, tiu.ru, market.yandex.ru
3. Китай: alibaba.com, 1688.com — В ПОСЛЕДНЮЮ ОЧЕРЕДЬ

ПРАВИЛА:
- exact_match = true ТОЛЬКО если нашёл именно эту модель/артикул (не аналог)
- Цена за ЕДИНИЦУ (штука/кг/м/л), НЕ за весь тендер
- Для продуктов питания, стройматериалов, канцтоваров — ищи КЗ/РУ рынок
- Для электроники без бренда — Китай допустим
- supplier_links: добавь ПРЯМЫЕ ссылки на товар на сайтах поставщиков (3-5 штук)

В конце ответа выведи ТОЛЬКО этот JSON-блок:
```json
{{
  "model_found": "точная модель/артикул или описание аналога",
  "exact_match": true,
  "kz_kzt": null,
  "ru_kzt": null,
  "china_usd": null,
  "price_min_kzt": 0,
  "price_max_kzt": 0,
  "best_market": "KZ",
  "supplier_links": [],
  "confidence": 0
}}
```
Заполни все поля реальными данными. null = не найдено на этом рынке."""

        if _is_quota_exhausted():
            logger.debug("search_product_web skipped — quota exhausted")
            return {}

        try:
            response = await self.client.chat.completions.create(
                model=settings.OPENAI_SEARCH_MODEL,
                messages=[{"role": "user", "content": search_prompt}],
                max_tokens=1500,
            )
            content = response.choices[0].message.content or ""

            print(f"\n[search_product_web] RAW ({len(content)} chars):\n{content[:800]}\n", flush=True)

            # ── Extract JSON block from response ──────────────────────────────
            parsed: dict = {}
            # Try ```json ... ``` block first
            json_block = re.search(r'```json\s*(\{.*?\})\s*```', content, re.DOTALL)
            if json_block:
                try:
                    parsed = json.loads(json_block.group(1))
                except json.JSONDecodeError:
                    pass

            # Fallback: find last { ... } in the response
            if not parsed:
                brace_match = re.search(r'\{[^{}]*"model_found"[^{}]*\}', content, re.DOTALL)
                if brace_match:
                    try:
                        parsed = json.loads(brace_match.group(0))
                    except json.JSONDecodeError:
                        pass

            # Deep fallback: largest JSON object
            if not parsed:
                for m in re.finditer(r'\{', content):
                    depth, end = 0, m.start()
                    for i, ch in enumerate(content[m.start():], m.start()):
                        if ch == '{': depth += 1
                        elif ch == '}':
                            depth -= 1
                            if depth == 0:
                                end = i + 1
                                break
                    candidate = content[m.start():end]
                    if '"model_found"' in candidate or '"confidence"' in candidate:
                        try:
                            parsed = json.loads(candidate)
                            break
                        except json.JSONDecodeError:
                            continue

            def _f(key: str) -> Optional[float]:
                v = parsed.get(key)
                if v is None:
                    return None
                try:
                    return float(str(v).replace(",", ".").replace(" ", ""))
                except (ValueError, TypeError):
                    return None

            model_found    = str(parsed.get("model_found", "")).strip() or None
            exact_match    = bool(parsed.get("exact_match", False))
            kz_kzt         = _f("kz_kzt")
            ru_kzt         = _f("ru_kzt")
            china_usd      = _f("china_usd")
            price_min_kzt  = _f("price_min_kzt")
            price_max_kzt  = _f("price_max_kzt")
            best_market    = str(parsed.get("best_market", "CN")).upper()
            confidence_raw = parsed.get("confidence", 0)
            confidence     = max(0, min(100, int(float(confidence_raw)) if confidence_raw else 0))

            # supplier_links: combine parsed links + annotation citations
            supplier_links: list[str] = []
            raw_links = parsed.get("supplier_links", [])
            if isinstance(raw_links, list):
                supplier_links = [str(u).strip() for u in raw_links if str(u).strip()]

            citations: list = []
            annotations = getattr(response.choices[0].message, "annotations", None)
            if annotations:
                for ann in annotations:
                    url_cit = getattr(ann, "url_citation", None)
                    if url_cit:
                        url = getattr(url_cit, "url", "")
                        title = getattr(url_cit, "title", "")
                        citations.append({"url": url, "title": title})
                        if url and url not in supplier_links:
                            supplier_links.append(url)

            # Penalise confidence when no exact match
            if not exact_match:
                confidence = min(confidence, 60)

            print(
                f"[search_product_web] model={model_found!r} exact={exact_match} "
                f"kz={kz_kzt} ru={ru_kzt} cn_usd={china_usd} conf={confidence} "
                f"links={len(supplier_links)}",
                flush=True,
            )

            return {
                "identified_model": model_found,
                "exact_match":      exact_match,
                "kz_kzt":           kz_kzt,
                "ru_kzt":           ru_kzt,
                "china_usd":        china_usd,
                "price_min_kzt":    price_min_kzt,
                "price_max_kzt":    price_max_kzt,
                "best_market":      best_market,
                "supplier_links":   supplier_links[:5],
                "confidence":       confidence,
                "citations":        citations,
            }
        except asyncio.CancelledError:
            raise
        except Exception as e:
            err_str = str(e)
            if "insufficient_quota" in err_str or "429" in err_str:
                _mark_quota_exhausted()
            logger.error("Web product search failed", error=err_str[:120])
            return {}

    async def search_suppliers_ai(
        self,
        product_name: str,
        technical_params: dict,
        quantity: Optional[float] = None,
        budget_kzt: float = 0,
        key_requirements: Optional[list] = None,
        spec_clarity: str = "vague",
    ) -> dict:
        """
        Use AI training-data knowledge to estimate real wholesale market prices.
        Budget is intentionally NOT passed to avoid price anchoring bias.
        Prioritises KZ and RU markets for domestically-produced goods.
        """
        params_str = json.dumps(technical_params, ensure_ascii=False, indent=2)
        qty_str = str(int(quantity)) if quantity else "1"
        req_str = "\n".join(f"- {r}" for r in (key_requirements or [])) or "не указаны"

        prompt = f"""Ты — эксперт по закупкам СНГ. Оцени ОПТОВУЮ РЫНОЧНУЮ ЦЕНУ товара для государственной закупки Казахстана.

ТОВАР: {product_name}
ТЕХНИЧЕСКИЕ ПАРАМЕТРЫ: {params_str}
ТРЕБОВАНИЯ: {req_str}
ЯСНОСТЬ СПЕЦИФИКАЦИИ: {spec_clarity}
КОЛИЧЕСТВО: {qty_str} единиц

ШАГИ:

1. ИДЕНТИФИКАЦИЯ: Определи конкретную коммерческую модель/артикул.
   - Ноутбук 15.6" 16GB/512GB Win11 Pro → "Lenovo IdeaPad 3 Gen 8" или "Acer Aspire 5 A515-58M"
   - Принтер лазерный A4 → "HP LaserJet Pro M15a" или "Canon LBP6030"
   - Курица охлаждённая → местные КЗ производители (Алель, Бауыржан, Мерей)

2. ВЫБОР РЫНКА (в зависимости от товара):
   КЗ (Казахстан) — для: продуктов питания, стройматериалов, канцтоваров, мебели, одежды, хозтоваров
   РУ (Россия) — для: промышленного оборудования, автозапчастей, спецматериалов, многих стройматериалов
   КН (Китай) — для: электроники, IT-оборудования, инструментов, крепежа, спецоборудования

3. ЦЕНЫ — реальные оптовые 2024-2025:
   - Ноутбук 15.6" 16GB/512GB Win11 Pro: ~$280-350 (CN wholesale)
   - МФУ лазерное A4: ~$80-150 (CN wholesale)
   - Монитор 24" FHD: ~$70-100 (CN wholesale)
   - Курица охлаждённая: ~1200-1600 ₸/кг (KZ wholesale)
   - Бумага А4, пачка 500л: ~1500-2000 ₸ (KZ/RU)
   - Цемент: ~100-140 ₸/кг (KZ)
   - Ноутбук в РУ: на 15-25% дороже чем CN из-за логистики
   - В КЗ розница обычно на 20-30% выше РУ оптовой

ВАЖНО: НЕ используй бюджет тендера для расчёта цены. Оцени реальную рыночную стоимость.

Верни JSON:
{{
  "identified_model": "конкретная коммерческая модель (строка)",
  "identification_confidence": 70,
  "exact_match": false,
  "best_source_country": "KZ|RU|CN",
  "estimated_unit_price_usd": {{
    "china": {{"min": 0, "max": 0, "likely": 0}},
    "russia": {{"min": 0, "max": 0, "likely": 0}},
    "kazakhstan": {{"min": 0, "max": 0, "likely": 0}}
  }},
  "estimated_unit_price_kzt": {{
    "kazakhstan": 0,
    "russia": 0
  }},
  "best_source_country": "CN",
  "lead_time_days": {{"china": 30, "russia": 14, "kazakhstan": 7}},
  "customs_duty_rate": 0.05,
  "notes": "обоснование цены и источника"
}}"""

        if _is_quota_exhausted():
            logger.debug("search_suppliers_ai skipped — quota exhausted")
            return {}

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Ты эксперт по закупкам СНГ. "
                            "Для продуктов питания, стройматериалов, канцтоваров — "
                            "всегда указывай КЗ/РУ цены как приоритет. "
                            "Respond with valid JSON only, no markdown."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=1500,
                temperature=0.1,
                response_format={"type": "json_object"},
            )
            raw = json.loads(response.choices[0].message.content)
            print(f"[search_suppliers_ai] model={raw.get('identified_model')!r} "
                  f"src={raw.get('best_source_country')} "
                  f"cn_likely={((raw.get('estimated_unit_price_usd') or {}).get('china') or {}).get('likely')}",
                  flush=True)
            return raw
        except Exception as e:
            err_str = str(e)
            if "insufficient_quota" in err_str or "429" in err_str:
                _mark_quota_exhausted()
            logger.error("Supplier AI search failed", error=err_str[:120])
            return {}

    async def generate_bid_proposal(
        self,
        tender_data: dict,
        analysis: dict,
        company_name: str = "Ваша компания",
    ) -> str:
        """Generate a draft bid proposal text in Russian."""
        prompt = f"""You are an expert in government procurement bid writing in Kazakhstan.

TENDER INFORMATION:
Title: {tender_data.get('title', '')}
Budget: {tender_data.get('budget', 0):,.0f} KZT
Deadline: {tender_data.get('deadline_at', 'N/A')}
Customer: {tender_data.get('customer_name', '')}

PRODUCT ANALYSIS:
Product: {analysis.get('product_name', '')}
Technical Summary: {analysis.get('summary_ru', '')}
Key Requirements: {', '.join(analysis.get('key_requirements', []))}

Generate a professional bid proposal document in Russian language. Include:
1. Сопроводительное письмо (Cover letter)
2. Технические характеристики предлагаемого товара/услуги
3. Таблица соответствия требованиям ТЗ
4. Ценовое предложение
5. Сроки поставки
6. Гарантийные обязательства

Company name: {company_name}
Keep it professional, concise, and compliant with Kazakhstan public procurement requirements."""

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "You are an expert in Kazakhstan government procurement. Write professional bid proposals.",
                    },
                    {"role": "user", "content": prompt},
                ],
                max_tokens=3000,
                temperature=0.3,
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error("Bid generation failed", error=str(e))
            return f"Коммерческое предложение по тендеру: {tender_data.get('title', '')}"

    async def classify_tender_category(self, title: str, description: str) -> str:
        """Quick category classification: product | software_service | other"""
        prompt = f"""Classify this tender into exactly one category:
- "product": physical goods/equipment/materials
- "software_service": websites, mobile apps, software, systems, platforms, CRM, ERP, AI, chatbots, portals, information systems, automation
- "other": all other services

Title: {title}
Description: {description[:500] if description else ''}

Respond with JSON: {{"category": "product|software_service|other", "confidence": 0.0-1.0}}"""

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=100,
                temperature=0.0,
                response_format={"type": "json_object"},
            )
            data = json.loads(response.choices[0].message.content)
            return data.get("category", "other")
        except Exception:
            return self._classify_by_keywords(title + " " + (description or ""))

    def _classify_by_keywords(self, text: str) -> str:
        """Fallback keyword-based classification."""
        text_lower = text.lower()
        software_keywords = [
            "сайт", "веб", "портал", "приложение", "мобильное", "программ",
            "система", "автоматизац", "цифров", "платформ", "crm", "erp",
            "информационн", "разработк", "сервис", "api", "интеграц",
            "website", "web", "portal", "app", "software", "system",
            "chatbot", "чат-бот", "ai", "ии", "искусственный интеллект",
        ]
        for kw in software_keywords:
            if kw in text_lower:
                return "software_service"
        return "product"

    async def ask_assistant(self, user_message: str) -> Optional[str]:
        """General tender assistant query used as fallback when DB search returns nothing."""
        if any(word in user_message.lower() for word in ["привет", "hello", "hi"]):
            return None
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {
                        "role": "system",
                        "content": "Ты умный тендерный ассистент. Отвечай кратко, по делу, помогай анализировать закупки, цены, маржу и поставщиков.",
                    },
                    {"role": "user", "content": user_message},
                ],
                max_tokens=1000,
                temperature=0.7,
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error("OpenAI assistant query failed", error=str(e))
            return None

    def _default_analysis(self, title: str) -> dict:
        return {
            "product_name": title,
            "product_name_en": title,
            "category": "product",
            "brand_model": None,
            "dimensions": None,
            "technical_params": {},
            "materials": None,
            "quantity": None,
            "unit": "шт",
            "analogs_allowed": None,
            "spec_clarity": "vague",
            "key_requirements": [],
            "summary_ru": title,
            "is_software_related": False,
            "software_type": None,
            "estimated_complexity": None,
        }
