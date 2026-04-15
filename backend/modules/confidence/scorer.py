"""
Confidence Scorer — calculates overall confidence score for tender analysis.
"""
from core.config import settings


class ConfidenceScorer:
    """
    Weights:
    - spec_clarity: 30%
    - supplier_match: 30%
    - logistics_reliability: 20%
    - price_accuracy: 20%
    """

    SPEC_CLARITY_SCORES = {
        "clear": 1.0,
        "partial": 0.6,
        "vague": 0.2,
    }

    def score(
        self,
        spec_clarity: str,
        supplier_match_score: float,
        logistics_reliability: float,
        price_accuracy: float,
    ) -> tuple[float, str]:
        """
        Calculate confidence score and level.
        Returns (score: 0.0-1.0, level: 'high'|'medium'|'low')
        """
        spec_score = self.SPEC_CLARITY_SCORES.get(spec_clarity, 0.3)

        weighted_score = (
            spec_score * 0.30
            + supplier_match_score * 0.30
            + logistics_reliability * 0.20
            + price_accuracy * 0.20
        )

        weighted_score = max(0.0, min(1.0, weighted_score))

        if weighted_score >= settings.HIGH_CONFIDENCE_THRESHOLD:
            level = "high"
        elif weighted_score >= settings.MEDIUM_CONFIDENCE_THRESHOLD:
            level = "medium"
        else:
            level = "low"

        return weighted_score, level

    def level_to_russian(self, level: str) -> str:
        return {"high": "высокая", "medium": "средняя", "low": "низкая"}.get(level, level)
