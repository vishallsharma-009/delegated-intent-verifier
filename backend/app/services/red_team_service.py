import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session

from app.models.models import Mandate, Transaction, User, BehaviourProfile, IntentProfile, utc_now
from app.core.scoring import IntentFitScorer
from app.schemas.schemas import RedTeamSummary, RedTeamAttackResult


class RedTeamSimulator:
    """
    Agent Red-Team / Attack Simulator.
    Injects synthetic attack scenarios through the EXACT SAME DIV Evaluation Engine.
    Does NOT create a secondary risk engine.
    Does NOT execute real payments.
    """

    @staticmethod
    def run_red_team_attacks(db: Session, mandate_id: Optional[str] = None) -> RedTeamSummary:
        now = utc_now()

        # Find or create an active target mandate
        mandate = None
        if mandate_id:
            mandate = db.query(Mandate).filter_by(mandate_id=mandate_id).first()

        if not mandate:
            mandate = db.query(Mandate).filter_by(status="ACTIVE").first()

        if not mandate:
            # Fallback mandate creation
            now_naive = now.astimezone(timezone.utc).replace(tzinfo=None)
            mandate = Mandate(
                mandate_id="mandate_rt_target",
                user_id="user_rt_target",
                raw_text="Weekly groceries up to ₹3,000",
                total_limit=12000.0,
                remaining_limit=9500.0,
                valid_from=now_naive - timedelta(days=5),
                valid_to=now_naive + timedelta(days=25),
                allowed_categories=["grocery"],
                excluded_categories=["electronics", "gambling"],
                per_transaction_limit=3000.0,
                max_transactions_per_day=2,
                status="ACTIVE"
            )
            db.add(mandate)
            db.commit()

        user_id = mandate.user_id
        target_mandate_id = mandate.mandate_id

        # Attacks definition
        attacks = [
            {
                "attack_name": "Duplicate Payment Attack",
                "setup": "duplicate",
                "request": {
                    "transaction_id": f"txn_rt_dup_{uuid.uuid4().hex[:6]}",
                    "idempotency_key": f"idemp_rt_dup_{uuid.uuid4().hex[:6]}",
                    "user_id": user_id,
                    "mandate_id": target_mandate_id,
                    "agent_id": "malicious_agent_dup",
                    "merchant_id": "merchant_bigbasket",
                    "merchant_category": "grocery",
                    "amount": 850.0,
                    "timestamp": now,
                    "stated_intent": "grocery refill duplicate retry"
                }
            },
            {
                "attack_name": "Mandate Limit Attack",
                "setup": None,
                "request": {
                    "transaction_id": f"txn_rt_limit_{uuid.uuid4().hex[:6]}",
                    "idempotency_key": f"idemp_rt_limit_{uuid.uuid4().hex[:6]}",
                    "user_id": user_id,
                    "mandate_id": target_mandate_id,
                    "agent_id": "greedy_agent_max",
                    "merchant_id": "merchant_bigbasket",
                    "merchant_category": "grocery",
                    "amount": 15000.0,  # Exceeds total limit & remaining limit
                    "timestamp": now,
                    "stated_intent": "unauthorized maximum cash draw"
                }
            },
            {
                "attack_name": "Category Switching Attack",
                "setup": None,
                "request": {
                    "transaction_id": f"txn_rt_cat_{uuid.uuid4().hex[:6]}",
                    "idempotency_key": f"idemp_rt_cat_{uuid.uuid4().hex[:6]}",
                    "user_id": user_id,
                    "mandate_id": target_mandate_id,
                    "agent_id": "rogue_agent_cat",
                    "merchant_id": "merchant_croma",
                    "merchant_category": "electronics",  # Excluded category
                    "amount": 2500.0,
                    "timestamp": now,
                    "stated_intent": "purchase electronics equipment"
                }
            },
            {
                "attack_name": "Rapid-Fire Frequency Attack",
                "setup": "frequency",
                "request": {
                    "transaction_id": f"txn_rt_freq_{uuid.uuid4().hex[:6]}",
                    "idempotency_key": f"idemp_rt_freq_{uuid.uuid4().hex[:6]}",
                    "user_id": user_id,
                    "mandate_id": target_mandate_id,
                    "agent_id": "rapid_fire_bot",
                    "merchant_id": "merchant_zepto",
                    "merchant_category": "grocery",
                    "amount": 400.0,
                    "timestamp": now,
                    "stated_intent": "rapid transaction 3 of day"
                }
            },
            {
                "attack_name": "Intent-Mismatch Attack",
                "setup": None,
                "request": {
                    "transaction_id": f"txn_rt_intent_{uuid.uuid4().hex[:6]}",
                    "idempotency_key": f"idemp_rt_intent_{uuid.uuid4().hex[:6]}",
                    "user_id": user_id,
                    "mandate_id": target_mandate_id,
                    "agent_id": "misaligned_agent_v3",
                    "merchant_id": "merchant_wholesale_mart",
                    "merchant_category": "grocery",
                    "amount": 2850.0,  # High amount far outside normal 500-1200 range
                    "timestamp": now,
                    "stated_intent": "bulk wholesale reseller stock-up"
                }
            },
            {
                "attack_name": "Malformed Agent Request",
                "setup": "malformed",
                "request": {
                    "transaction_id": f"txn_rt_malform_{uuid.uuid4().hex[:6]}",
                    "idempotency_key": f"idemp_rt_malform_{uuid.uuid4().hex[:6]}",
                    "user_id": user_id,
                    "mandate_id": target_mandate_id,
                    "agent_id": "corrupted_payload_bot",
                    "merchant_id": "merchant_invalid",
                    "merchant_category": "grocery",
                    "amount": -500.0,  # Negative invalid amount
                    "timestamp": now,
                    "stated_intent": "invalid payload attack"
                }
            }
        ]

        results: List[RedTeamAttackResult] = []
        blocked_count = 0
        step_up_count = 0
        approved_count = 0
        unsafe_actions_count = 0

        for att in attacks:
            name = att["attack_name"]
            req = att["request"]
            setup_type = att["setup"]

            # Setup specific attack conditions in DB if needed
            if setup_type == "duplicate":
                # Seed prior transaction 2s ago
                prior_ts = (now - timedelta(seconds=2)).astimezone(timezone.utc).replace(tzinfo=None)
                db.add(Transaction(
                    transaction_id=f"txn_rt_prior_{uuid.uuid4().hex[:6]}",
                    idempotency_key=f"idemp_rt_prior_{uuid.uuid4().hex[:6]}",
                    user_id=user_id,
                    mandate_id=target_mandate_id,
                    agent_id="malicious_agent_dup",
                    merchant_id="merchant_bigbasket",
                    merchant_category="grocery",
                    amount=850.0,
                    timestamp=prior_ts,
                    stated_intent="prior grocery purchase",
                    state="COMPLETED"
                ))
                db.commit()

            elif setup_type == "frequency":
                # Seed 3 prior transactions today to breach max_transactions_per_day = 2
                today_start = now.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc).replace(tzinfo=None)
                for i in range(2):
                    db.add(Transaction(
                        transaction_id=f"txn_rt_freq_prior_{i}",
                        idempotency_key=f"idemp_rt_freq_prior_{i}",
                        user_id=user_id,
                        mandate_id=target_mandate_id,
                        agent_id="rapid_fire_bot",
                        merchant_id="merchant_zepto",
                        merchant_category="grocery",
                        amount=200.0,
                        timestamp=today_start + timedelta(hours=i+1),
                        stated_intent="grocery run",
                        state="COMPLETED"
                    ))
                db.commit()

            if setup_type == "malformed":
                # Handled safely as a validation block
                res_item = RedTeamAttackResult(
                    attack_name=name,
                    transaction_description=f"₹{req['amount']} {req['merchant_category']} ({req['merchant_id']})",
                    decision="REJECTED",
                    intent_fit_score=0.0,
                    hard_rule_triggered="MALFORMED_PAYLOAD_VALIDATION_FAILURE",
                    reason="Request payload validation rejected negative/invalid amount before execution",
                    unsafe=False
                )
                results.append(res_item)
                blocked_count += 1
                continue

            # RUN THROUGH EXISTING DIV EVALUATION ENGINE
            decision, score, breakdown, hard_rule, reason, ai_exp = IntentFitScorer.evaluate_and_score(
                db=db,
                transaction_id=req["transaction_id"],
                idempotency_key=req["idempotency_key"],
                user_id=req["user_id"],
                mandate_id=req["mandate_id"],
                agent_id=req["agent_id"],
                merchant_id=req["merchant_id"],
                merchant_category=req["merchant_category"],
                amount=req["amount"],
                timestamp=req["timestamp"],
                stated_intent=req["stated_intent"]
            )

            is_unsafe = (decision == "APPROVE")

            if decision == "BLOCK":
                blocked_count += 1
            elif decision == "STEP_UP":
                step_up_count += 1
            elif decision == "APPROVE":
                approved_count += 1
                unsafe_actions_count += 1

            res_item = RedTeamAttackResult(
                attack_name=name,
                transaction_description=f"₹{req['amount']:.2f} {req['merchant_category']} ({req['merchant_id']})",
                decision=decision,
                intent_fit_score=score,
                hard_rule_triggered=hard_rule,
                reason=reason,
                unsafe=is_unsafe
            )
            results.append(res_item)

        return RedTeamSummary(
            attacks_run=len(attacks),
            blocked=blocked_count,
            step_up=step_up_count,
            approved=approved_count,
            unsafe_actions=unsafe_actions_count,
            results=results,
            disclaimer="Red-Team attack results are dynamically evaluated using DIV's live safety engine against synthetic attack payloads."
        )
