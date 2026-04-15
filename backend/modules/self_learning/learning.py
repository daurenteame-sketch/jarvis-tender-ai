"""
Self-Learning System — tracks user actions and improves predictions over time.
"""
import uuid
from typing import Optional
import structlog
from sqlalchemy import select, func

from core.database import async_session_factory
from models.user_action import UserAction
from models.profitability import ProfitabilityAnalysis

logger = structlog.get_logger(__name__)


class SelfLearningSystem:
    async def record_action(
        self,
        tender_id: uuid.UUID,
        user_id: uuid.UUID,
        action: str,
        actual_bid_amount: Optional[float] = None,
        notes: Optional[str] = None,
    ) -> UserAction:
        """Record a user action on a tender."""
        async with async_session_factory() as session:
            user_action = UserAction(
                tender_id=tender_id,
                user_id=user_id,
                action=action,
                actual_bid_amount=actual_bid_amount,
                notes=notes,
            )
            session.add(user_action)
            await session.commit()
            await session.refresh(user_action)

        logger.info(
            "User action recorded",
            tender_id=str(tender_id),
            action=action,
        )
        return user_action

    async def get_learning_stats(self) -> dict:
        """Get learning statistics for model improvement."""
        async with async_session_factory() as session:
            # Count actions by type
            actions_result = await session.execute(
                select(UserAction.action, func.count(UserAction.id).label("count"))
                .group_by(UserAction.action)
            )
            actions = {row.action: row.count for row in actions_result}

            # Win rate
            submitted = actions.get("bid_submitted", 0)
            won = actions.get("won", 0)
            win_rate = (won / submitted * 100) if submitted > 0 else 0

            # Average profit margin for won tenders
            won_actions = await session.execute(
                select(UserAction)
                .where(UserAction.action == "won")
                .limit(100)
            )
            won_list = won_actions.scalars().all()

            profitable_count = 0
            total_margin = 0.0
            for action in won_list:
                prof = await session.execute(
                    select(ProfitabilityAnalysis)
                    .where(ProfitabilityAnalysis.tender_id == action.tender_id)
                )
                p = prof.scalar_one_or_none()
                if p and p.profit_margin_percent:
                    total_margin += float(p.profit_margin_percent)
                    profitable_count += 1

            avg_margin = (total_margin / profitable_count) if profitable_count > 0 else 0

        return {
            "actions": actions,
            "win_rate_percent": round(win_rate, 1),
            "avg_winning_margin": round(avg_margin, 1),
            "total_bids_submitted": submitted,
            "total_won": won,
        }
