import math
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Tuple, Optional
from sqlalchemy.orm import Session
from app.models.models import Mandate, IntentProfile, BehaviourProfile, Transaction
from app.core.hard_rules import HardRuleEngine
from app.schemas.schemas import ScoreBreakdown


class IntentFitScorer:
    """
    Weighted Intent-Fit Scoring Engine (0-100).
    
    Weights:
      Category match: 20
      Amount deviation: 25
      Frequency deviation: 15
      Merchant familiarity: 15
      Time pattern fit: 5
      Velocity Proximity: 10
      Intent similarity: 10
    """

    @staticmethod
    def evaluate_and_score(
        db: Session,
        transaction_id: str,
        idempotency_key: str,
        user_id: str,
        mandate_id: str,
        agent_id: str,
        merchant_id: str,
        merchant_category: str,
        amount: float,
        timestamp: datetime,
        stated_intent: str
    ) -> Tuple[str, float, ScoreBreakdown, Optional[str], str, str]:
        """
        Main scoring entry point.
        Returns: (final_decision, score, breakdown, hard_rule_triggered, reason_text, ai_explanation)
        
        1. HARD RULES EVALUATION FIRST.
           If hard rule triggered -> score = 0, decision = BLOCK.
        2. IF SAFE -> Compute all 7 scoring components.
        3. Map total score to APPROVE (>=75), STEP_UP (45-74), or BLOCK (<45).
        """

        # 1. HARD RULE CHECK FIRST
        is_violated, rule_name, hard_reason = HardRuleEngine.evaluate(
            db=db,
            transaction_id=transaction_id,
            idempotency_key=idempotency_key,
            user_id=user_id,
            mandate_id=mandate_id,
            agent_id=agent_id,
            merchant_id=merchant_id,
            merchant_category=merchant_category,
            amount=amount,
            timestamp=timestamp,
            stated_intent=stated_intent
        )

        if is_violated:
            zero_breakdown = ScoreBreakdown(
                category_match=0.0,
                amount_deviation=0.0,
                frequency_deviation=0.0,
                merchant_familiarity=0.0,
                time_pattern_fit=0.0,
                velocity_proximity=0.0,
                intent_similarity=0.0
            )
            explanation = f"HARD BLOCK: Transaction violates security rule '{rule_name}'. {hard_reason}"
            return ("BLOCK", 0.0, zero_breakdown, rule_name, hard_reason, explanation)

        # 2. FETCH CONTEXT FOR SCORING
        mandate = db.query(Mandate).filter_by(mandate_id=mandate_id).first()
        intent = db.query(IntentProfile).filter_by(mandate_id=mandate_id).first()
        behaviour = db.query(BehaviourProfile).filter_by(user_id=user_id).first()

        # Component 1: Category match (20)
        c1 = IntentFitScorer._score_category_match(merchant_category, mandate, intent, behaviour)

        # Component 2: Amount deviation (25)
        c2 = IntentFitScorer._score_amount_deviation(amount, intent, behaviour)

        # Component 3: Frequency deviation (15)
        c3 = IntentFitScorer._score_frequency_deviation(db, mandate_id, timestamp, intent)

        # Component 4: Merchant familiarity (15)
        c4 = IntentFitScorer._score_merchant_familiarity(merchant_id, merchant_category, intent, behaviour)

        # Component 5: Time pattern fit (5)
        c5 = IntentFitScorer._score_time_pattern(timestamp, behaviour)

        # Component 6: Velocity Proximity (10) - soft velocity without hard violation
        c6 = IntentFitScorer._score_velocity_proximity(db, user_id, timestamp, transaction_id)

        # Component 7: Intent Similarity (10)
        c7 = IntentFitScorer._score_intent_similarity(stated_intent, intent)

        breakdown = ScoreBreakdown(
            category_match=round(c1, 2),
            amount_deviation=round(c2, 2),
            frequency_deviation=round(c3, 2),
            merchant_familiarity=round(c4, 2),
            time_pattern_fit=round(c5, 2),
            velocity_proximity=round(c6, 2),
            intent_similarity=round(c7, 2)
        )

        total_score = round(c1 + c2 + c3 + c4 + c5 + c6 + c7, 2)

        # 3. DECISION MAPPING
        if total_score >= 75.0:
            final_decision = "APPROVE"
            reason = f"High Intent-Fit score ({total_score:.1f}/100) passes all risk thresholds."
        elif total_score >= 45.0:
            final_decision = "STEP_UP"
            reason = f"Moderate Intent-Fit score ({total_score:.1f}/100) requires human confirmation."
        else:
            final_decision = "BLOCK"
            reason = f"Low Intent-Fit score ({total_score:.1f}/100) indicates significant intent discrepancy."

        # AI EXPLANATION GENERATION
        ai_explanation = IntentFitScorer._generate_explanation(
            final_decision, total_score, breakdown, stated_intent, intent
        )

        return (final_decision, total_score, breakdown, None, reason, ai_explanation)

    @staticmethod
    def _score_category_match(category: str, mandate: Mandate, intent: Optional[IntentProfile], behaviour: Optional[BehaviourProfile]) -> float:
        cat_lower = category.lower().strip()
        allowed = [c.lower().strip() for c in (mandate.allowed_categories or [])]

        if cat_lower not in allowed:
            return 0.0

        if intent and intent.allowed_categories:
            intent_allowed = [c.lower().strip() for c in intent.allowed_categories]
            if cat_lower in intent_allowed:
                return 20.0

        if behaviour and behaviour.common_categories:
            if cat_lower in [c.lower() for c in behaviour.common_categories]:
                return 18.0

        return 12.0

    @staticmethod
    def _score_amount_deviation(amount: float, intent: Optional[IntentProfile], behaviour: Optional[BehaviourProfile]) -> float:
        score_intent = 25.0
        if intent and intent.expected_amount_range and len(intent.expected_amount_range) == 2:
            exp_min, exp_max = intent.expected_amount_range
            if exp_min <= amount <= exp_max:
                score_intent = 25.0
            elif amount < exp_min:
                ratio = (exp_min - amount) / max(1.0, exp_min)
                score_intent = max(0.0, 25.0 * max(0.0, 1.0 - ratio * 2.0))
            else:
                ratio = (amount - exp_max) / max(1.0, exp_max)
                score_intent = max(0.0, 25.0 * max(0.0, 1.0 - ratio * 2.5))

        score_beh = 25.0
        if behaviour and behaviour.median_amount > 0:
            std_dev = max(50.0, behaviour.amount_std_dev)
            diff = abs(amount - behaviour.median_amount)
            score_beh = max(0.0, 25.0 * max(0.0, 1.0 - (diff / (2.0 * std_dev))))

        return round(min(score_intent, score_beh), 2)

    @staticmethod
    def _score_frequency_deviation(db: Session, mandate_id: str, timestamp: datetime, intent: Optional[IntentProfile]) -> float:
        if timestamp.tzinfo is not None:
            ts_naive = timestamp.astimezone(timezone.utc).replace(tzinfo=None)
        else:
            ts_naive = timestamp

        week_start = ts_naive - timedelta(days=7)
        recent_count = db.query(Transaction).filter(
            Transaction.mandate_id == mandate_id,
            Transaction.timestamp >= week_start,
            Transaction.timestamp <= ts_naive,
            Transaction.state.in_(["COMPLETED", "EXECUTING", "APPROVED", "USER_APPROVED", "STEP_UP_REQUIRED"])
        ).count()

        expected = intent.expected_transactions_per_period if intent else 1
        if recent_count <= expected:
            return 15.0
        elif recent_count <= expected + 2:
            return 8.0
        else:
            return 2.0

    @staticmethod
    def _score_merchant_familiarity(merchant_id: str, merchant_category: str, intent: Optional[IntentProfile], behaviour: Optional[BehaviourProfile]) -> float:
        if behaviour and behaviour.common_merchants:
            if merchant_id in behaviour.common_merchants:
                return 15.0

        if intent and intent.typical_merchant_types:
            for t_type in intent.typical_merchant_types:
                if t_type.lower() in merchant_category.lower() or merchant_category.lower() in t_type.lower():
                    return 8.0

        return 2.0

    @staticmethod
    def _score_time_pattern(timestamp: datetime, behaviour: Optional[BehaviourProfile]) -> float:
        hour = timestamp.hour
        if behaviour and behaviour.typical_hour_range and len(behaviour.typical_hour_range) == 2:
            h_start, h_end = behaviour.typical_hour_range
            if h_start <= hour <= h_end:
                return 5.0
            else:
                return 1.0
        
        if 8 <= hour <= 22:
            return 5.0
        return 1.0

    @staticmethod
    def _score_velocity_proximity(db: Session, user_id: str, timestamp: datetime, transaction_id: str) -> float:
        """
        Soft velocity score (weight 10).
        Note: Exact 5-sec duplicate hard rule was already evaluated before scoring!
        This evaluates closeness in 5 seconds to 10 minutes.
        """
        if timestamp.tzinfo is not None:
            ts_naive = timestamp.astimezone(timezone.utc).replace(tzinfo=None)
        else:
            ts_naive = timestamp

        window_start = ts_naive - timedelta(minutes=10)
        recent_txns = db.query(Transaction).filter(
            Transaction.user_id == user_id,
            Transaction.timestamp >= window_start,
            Transaction.timestamp <= ts_naive,
            Transaction.transaction_id != transaction_id
        ).order_by(Transaction.timestamp.desc()).all()

        if not recent_txns:
            return 10.0

        latest = recent_txns[0]
        latest_ts = latest.timestamp
        if latest_ts.tzinfo is not None:
            latest_ts = latest_ts.astimezone(timezone.utc).replace(tzinfo=None)

        secs_ago = (ts_naive - latest_ts).total_seconds()

        if secs_ago > 300:  # > 5 minutes
            return 10.0
        elif secs_ago > 60:  # 1 to 5 minutes
            return 7.0
        elif secs_ago > 10:  # 10 to 60 seconds
            return 4.0
        else:
            return 1.0


    @staticmethod
    def _score_intent_similarity(stated_intent: str, intent: Optional[IntentProfile]) -> float:
        if not stated_intent or not intent:
            return 5.0

        stated_lower = stated_intent.lower()
        purpose_lower = intent.purpose.lower()

        # Stop word filtering for semantic comparison
        stop_words = {"a", "an", "the", "for", "my", "to", "in", "of", "and", "or", "purchase", "random", "buy", "order"}
        stated_words = {w for w in stated_lower.split() if w not in stop_words and len(w) > 2}
        purpose_words = {w for w in purpose_lower.split() if w not in stop_words and len(w) > 2}
        
        overlap = stated_words.intersection(purpose_words)

        if len(overlap) >= 2 or (stated_lower in purpose_lower and len(stated_lower) > 5):
            return 10.0
        elif len(overlap) == 1:
            return 7.0
        else:
            # Check if category is mentioned
            if any(cat in stated_lower for cat in intent.allowed_categories):
                return 4.0
            return 1.0

    @staticmethod
    def _generate_explanation(
        decision: str,
        total_score: float,
        breakdown: ScoreBreakdown,
        stated_intent: str,
        intent: Optional[IntentProfile]
    ) -> str:
        purpose_str = intent.purpose if intent else "mandate purpose"
        if decision == "APPROVE":
            return f"Transaction '{stated_intent}' aligns strongly with mandate '{purpose_str}' (Intent-Fit Score {total_score:.0f}/100)."
        elif decision == "STEP_UP":
            lowest_signals = []
            if breakdown.amount_deviation < 15: lowest_signals.append("atypical amount")
            if breakdown.merchant_familiarity < 10: lowest_signals.append("unfamiliar merchant")
            if breakdown.intent_similarity < 6: lowest_signals.append("intent wording discrepancy")
            if breakdown.time_pattern_fit < 3: lowest_signals.append("off-hours transaction")
            signal_str = ", ".join(lowest_signals) if lowest_signals else "atypical purchasing pattern"
            return f"Transaction '{stated_intent}' requires user approval due to {signal_str} (Intent-Fit Score {total_score:.0f}/100)."
        else:
            return f"Transaction '{stated_intent}' blocked due to low intent consistency ({total_score:.0f}/100) relative to '{purpose_str}'."
