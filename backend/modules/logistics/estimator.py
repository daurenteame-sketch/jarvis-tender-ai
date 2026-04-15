"""
Logistics & Tax Estimator.
Calculates shipping, customs, and VAT for different supply routes.

VAT (НДС): 16% base rate (includes standard 12% + agent/broker fees).
Applied on: product_cost + shipping + customs (full landed cost).
"""
import uuid
from typing import Optional
import structlog

from core.config import settings
from core.database import async_session_factory
from models.logistics import LogisticsEstimate

logger = structlog.get_logger(__name__)

# Logistics rates by origin country
LOGISTICS_RATES = {
    "CN": {
        "shipping_rate":      0.12,   # 12% of product cost (sea/rail to KZ)
        "customs_duty_rate":  0.05,   # 5% average import duty
        "broker_fee_rate":    0.015,  # 1.5% customs broker fee
        "lead_time_days":     30,
        "route":              "Китай → Казахстан (авто/ж/д)",
    },
    "RU": {
        "shipping_rate":      0.06,   # 6% (EEU, cheaper logistics)
        "customs_duty_rate":  0.0,    # EEU = no customs duty
        "broker_fee_rate":    0.005,  # 0.5% minimal doc fee
        "lead_time_days":     14,
        "route":              "Россия → Казахстан",
    },
    "KZ": {
        "shipping_rate":      0.03,   # 3% local delivery
        "customs_duty_rate":  0.0,
        "broker_fee_rate":    0.0,
        "lead_time_days":     7,
        "route":              "Казахстан (местная доставка)",
    },
}

# VAT rate from config (Kazakhstan НДС = 16% as of 2024)
VAT_RATE = settings.VAT_RATE


class LogisticsEstimator:
    async def estimate(
        self,
        product_cost_kzt: float,
        origin_country: str = "CN",
        custom_duty_rate: Optional[float] = None,
        lot_id: Optional[uuid.UUID] = None,
        tender_id: Optional[uuid.UUID] = None,
    ) -> dict:
        """
        Calculate full logistics costs for a given origin country.

        Returns dict with all cost components.
        """
        rates = LOGISTICS_RATES.get(origin_country, LOGISTICS_RATES["CN"])

        shipping_cost = product_cost_kzt * rates["shipping_rate"]

        duty_rate     = custom_duty_rate if custom_duty_rate is not None else rates["customs_duty_rate"]
        customs_duty  = product_cost_kzt * duty_rate

        broker_fee    = product_cost_kzt * rates["broker_fee_rate"]

        # VAT (НДС) base = product + shipping + customs + broker
        vat_base   = product_cost_kzt + shipping_cost + customs_duty + broker_fee
        vat_amount = vat_base * VAT_RATE

        total_logistics = shipping_cost + customs_duty + broker_fee + vat_amount

        result = {
            "origin_country":  origin_country,
            "shipping_cost":   round(shipping_cost, 2),
            "customs_duty":    round(customs_duty + broker_fee, 2),  # merge broker into customs
            "vat_amount":      round(vat_amount, 2),
            "total_logistics": round(total_logistics, 2),
            "lead_time_days":  rates["lead_time_days"],
            "route":           rates["route"],
            "vat_rate":        VAT_RATE,
        }

        # Save to database
        async with async_session_factory() as session:
            estimate = LogisticsEstimate(
                lot_id=lot_id,
                tender_id=tender_id,
                **{k: v for k, v in result.items()
                   if k not in ("vat_rate",)},  # skip non-model fields
            )
            session.add(estimate)
            await session.commit()

        logger.debug(
            "Logistics estimated",
            lot_id=str(lot_id) if lot_id else None,
            origin=origin_country,
            shipping=round(shipping_cost, 0),
            customs=round(customs_duty, 0),
            vat=round(vat_amount, 0),
            total=round(total_logistics, 0),
        )

        return result
