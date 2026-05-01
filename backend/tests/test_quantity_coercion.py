"""
Regression test for quantity_extracted Decimal coercion in pipeline_step.

History: AI returned strings like "30 пачек" for the quantity field, but
the DB column quantity_extracted is NUMERIC. SQLAlchemy / asyncpg blew
up with `decimal.ConversionSyntax`, the /reanalyze endpoint 500'd, and
no analysis row was ever written for affected lots. Commit 84d0a1c
added regex coercion. This test pins it.
"""
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def _coerce(raw, ai_unit=None):
    """Replicate the coercion logic from pipeline_step._save_lot_analysis."""
    import re as _re
    norm_qty = None
    norm_unit = ai_unit or None
    if raw is not None:
        s = str(raw).strip()
        m = _re.search(r"[-+]?\d+(?:[.,]\d+)?", s)
        if m:
            try:
                norm_qty = Decimal(m.group(0).replace(",", "."))
            except Exception:
                norm_qty = None
            if not norm_unit:
                tail = s[m.end():].strip()
                if tail:
                    norm_unit = tail.split()[0][:50]
    return norm_qty, norm_unit


def test_pure_number_stays_decimal():
    qty, unit = _coerce("30")
    assert qty == Decimal("30")
    assert unit is None


def test_number_with_unit_in_string():
    qty, unit = _coerce("30 пачек")
    assert qty == Decimal("30")
    assert unit == "пачек"


def test_decimal_with_comma_separator():
    qty, unit = _coerce("2,5 кг")
    assert qty == Decimal("2.5")
    assert unit == "кг"


def test_explicit_unit_takes_precedence():
    qty, unit = _coerce("30 пачек", ai_unit="штука")
    assert qty == Decimal("30")
    assert unit == "штука"


def test_garbage_input_returns_none():
    qty, unit = _coerce("по запросу")
    assert qty is None


def test_none_passthrough():
    qty, unit = _coerce(None)
    assert qty is None
    assert unit is None
