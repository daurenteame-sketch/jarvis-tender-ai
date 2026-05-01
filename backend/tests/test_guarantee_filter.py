"""
Regression tests for the bank-guarantee text detector.

History: lots whose only attached document is a guarantee template
(price_offers_guarantee_2025.docx, "Шаблон.docx") repeatedly leaked into
technical_spec_text. Each fix would clear the DB but a new scan would
re-poison it because the filter only ran on auto-extract, not on scan
write. Now the filter lives in modules.parser.guarantee_filter and is
called from BOTH paths. These tests pin its behaviour so future edits
can't silently weaken it.
"""
import sys
from pathlib import Path

# Allow `pytest backend/tests` to find the modules under backend/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.parser.guarantee_filter import looks_like_guarantee_text


# ── Positive cases — must be detected as guarantee ────────────────────────────

def test_detects_full_guarantee_template_with_marker_block():
    """The actual 2.8K template that landed in lot d44c61ad."""
    text = (
        "[ДОКУМЕНТ: Обеспечение заявки]\n"
        "___________________________________\n"
        "Форма ____________________________________\n"
        "Банковская гарантия\n"
        "Бенефициар банка ____________________\n"
        "Гарантодатель ___________________\n"
        "Сумма гарантии _____________________________\n"
    )
    assert looks_like_guarantee_text(text)


def test_detects_template_by_underscores_plus_keyword():
    """Even without explicit marker block, lots of placeholders + 'обеспечени' wins."""
    text = (
        "Форма обеспечения заявки\n"
        "Наименование _______________________\n"
        "Адрес ________________________\n"
        "Сумма ________________________\n"
        "Дата ________________________\n"
        "Подпись ________________________\n"
    )
    assert looks_like_guarantee_text(text)


def test_detects_two_markers_anywhere_in_head():
    """Banking vocabulary is enough on its own — no underscores needed."""
    text = (
        "Договор поручительства. Бенефициар обязуется. "
        "Гарантодатель банка несёт ответственность за исполнение."
    )
    assert looks_like_guarantee_text(text)


# ── Negative cases — real specs must NOT be flagged ───────────────────────────

def test_does_not_flag_real_lamp_spec():
    """Goszakup spec table for a lamp lot. No banking vocabulary, no placeholders."""
    text = (
        "Номер закупки: № 16910204-1\n"
        "Наименование лота: Лампа светодиодная\n"
        "Описание лота: тип цоколя G13, мощность 18 Вт\n"
        "Дополнительное описание лота: Лампа LED-12, ECO T8 линейная\n"
        "Количество: 100\n"
        "Срок поставки: в течении 20 календарных дней\n"
    )
    assert not looks_like_guarantee_text(text)


def test_does_not_flag_real_paint_spec():
    """Lot d44c61ad's correct spec — Alina Paint enamel."""
    text = (
        "Номер закупки: № 16930179-1\n"
        "Наименование закупки: Alina Paint Эмаль матовая Emalika 3 кг\n"
        "Наименование лота: Эмаль\n"
        "Количество: 20\n"
        "Места поставки: 751710000, г.Алматы\n"
    )
    assert not looks_like_guarantee_text(text)


def test_does_not_flag_spec_with_isolated_underscores():
    """Specs sometimes contain a single '___' separator — not a template."""
    text = (
        "Наименование лота: Кабель\n"
        "___\n"
        "Марка: ВВГнг-LS 3х2.5 мм²\n"
        "ГОСТ: 31996-2012\n"
        "Длина: 100 м\n"
    )
    assert not looks_like_guarantee_text(text)


def test_handles_empty_input():
    assert not looks_like_guarantee_text("")
    assert not looks_like_guarantee_text(None)
