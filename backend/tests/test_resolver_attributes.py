"""
Regression tests for product_resolver discriminator attribute extraction.

History: generic search queries like "Лампа светодиодная" returned 8
unrelated lamps from Kaspi (E27, smart, MR16) — only one was the right
G13 18 Вт T8 tube. Commit a5b8ec7 added _extract_key_attributes and
wired its output into search_query. These tests ensure the regexes
don't drift — every fix here that breaks an old case will fail loudly.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.product_resolver import (
    _extract_key_attributes,
    resolve_product,
)


# ── Lamp lots — socket type is THE single discriminator ───────────────────────

def test_lamp_g13_18w_extracted():
    spec = "Описание: тип цоколя G13, мощность 18 Вт, лампа LED-12 ECO T8 линейная, длина 1200 мм"
    attrs = _extract_key_attributes(spec)
    assert attrs.get("socket") == "G13"
    assert attrs.get("power") == "18 Вт"
    assert attrs.get("length") == "1200 мм"


def test_lamp_e27_extracted():
    spec = "Лампа светодиодная, цоколь E27, мощность 9 Вт, 220 В"
    attrs = _extract_key_attributes(spec)
    assert attrs.get("socket") == "E27"
    assert attrs.get("power") == "9 Вт"
    assert attrs.get("voltage") == "220 В"


def test_socket_requires_lamp_context():
    """B22 inside a model number must NOT be detected as a socket — needs a cue word."""
    spec = "Контроллер ACS580-01-012A-4 B22 модель"
    attrs = _extract_key_attributes(spec)
    assert "socket" not in attrs


# ── Tow rope / tools — capacity + length ──────────────────────────────────────

def test_tow_rope_capacity_and_length():
    spec = "Трос буксировочный ленточный, нагрузка 5 т, длина 4 м, ширина 80 мм"
    attrs = _extract_key_attributes(spec)
    assert attrs.get("capacity") == "5 т"
    assert attrs.get("length") == "4 м"


# ── Paper — Cyrillic А4 must be normalised to Latin A4 ────────────────────────

def test_photo_paper_cyrillic_a4_normalises_to_latin():
    spec = "Глянцевая самоклеющаяся фотобумага А4 150 г/м2 50 листов"
    attrs = _extract_key_attributes(spec)
    assert attrs.get("format") == "A4", "Cyrillic А4 must normalise to Latin A4"
    assert attrs.get("density") == "150 г/м2"


def test_office_paper_latin_a4():
    spec = "Бумага офисная A4 80 г/м2"
    attrs = _extract_key_attributes(spec)
    assert attrs.get("format") == "A4"
    assert attrs.get("density") == "80 г/м2"


# ── Outdoor luminaire — IP rating is critical for outdoor use ─────────────────

def test_luminaire_ip65_extracted():
    spec = "Светильник светодиодный 36 Вт, IP65, 220 В, длина 600 мм"
    attrs = _extract_key_attributes(spec)
    assert attrs.get("ip") == "IP65"
    assert attrs.get("power") == "36 Вт"


# ── Search query enrichment — the whole point of the feature ──────────────────

def test_search_query_has_socket_and_power_for_lamp():
    """A lamp's search_query must include G13 + Вт so Kaspi returns the right lamp."""
    r = resolve_product(
        spec_text="Описание: тип цоколя G13, мощность 18 Вт",
        title="Лампа светодиодная",
    )
    q = r["search_query"]
    assert "G13" in q
    assert "Вт" in q


def test_search_query_has_capacity_for_tow_rope():
    r = resolve_product(
        spec_text="Тип буксировочный ленточный, нагрузка 5 т, длина 4 м",
        title="Трос буксировочный",
    )
    q = r["search_query"]
    assert "5 т" in q
    assert "4 м" in q


def test_resolved_dict_exposes_key_attributes():
    """Frontend / validator depend on resolved.key_attributes being present."""
    r = resolve_product(spec_text="цоколь G13, мощность 18 Вт", title="Лампа")
    assert "key_attributes" in r
    assert r["key_attributes"]["socket"] == "G13"
