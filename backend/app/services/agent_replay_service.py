from typing import Dict, Any, List, Optional
from sqlalchemy.orm import Session
from app.models.models import Transaction, Mandate, TransactionDecision
from app.schemas.schemas import AgentReplayResponse


class AgentReplayService:
    """
    Agent Behaviour Replay Service.
    Retrieves decision records and transaction timeline for an AI agent over time.
    Calculates deterministic behaviour consistency without speculative ML models.
    """

    @staticmethod
    def get_agent_replay(db: Session, agent_id: str = "agent_001") -> AgentReplayResponse:
        # Fetch transactions for agent or fallback to all transactions
        txns = db.query(Transaction).filter_by(agent_id=agent_id).order_by(Transaction.timestamp.asc()).all()

        if not txns:
            # Fallback to all transactions if specific agent_id has no records yet
            txns = db.query(Transaction).order_by(Transaction.timestamp.asc()).all()


        mandate_id = txns[0].mandate_id if txns else "mandate_normal_01"
        mandate = db.query(Mandate).filter_by(mandate_id=mandate_id).first()
        mandate_text = mandate.raw_text if mandate else "Weekly groceries up to ₹10,000"

        total_count = len(txns)
        approved_count = 0
        step_up_count = 0
        blocked_count = 0
        hard_violations_count = 0

        timeline: List[Dict[str, Any]] = []

        for t in txns:
            dec = db.query(TransactionDecision).filter_by(transaction_id=t.transaction_id).first()

            final_decision = dec.final_decision if dec else ("APPROVE" if t.state in ("APPROVED", "COMPLETED") else "BLOCK")
            score = dec.intent_fit_score if dec else (85.0 if final_decision == "APPROVE" else 0.0)
            hard_rule = dec.hard_rule_triggered if dec else None

            if final_decision == "APPROVE":
                approved_count += 1
            elif final_decision == "STEP_UP":
                step_up_count += 1
            elif final_decision == "BLOCK":
                blocked_count += 1

            if hard_rule:
                hard_violations_count += 1

            timeline.append({
                "transaction_id": t.transaction_id,
                "timestamp": t.timestamp.isoformat() if t.timestamp else "",
                "amount": t.amount,

                "merchant_id": t.merchant_id,
                "merchant_category": t.merchant_category,
                "stated_intent": t.stated_intent,
                "decision": final_decision,
                "intent_fit_score": score,
                "hard_rule_triggered": hard_rule,
                "state": t.state
            })

        # Deterministic Behaviour Consistency calculation
        if total_count == 0:
            consistency = "HIGH"
        else:
            violation_ratio = (blocked_count + hard_violations_count) / max(1, total_count)
            if violation_ratio <= 0.15:
                consistency = "HIGH"
            elif violation_ratio <= 0.40:
                consistency = "MODERATE"
            else:
                consistency = "LOW"

        return AgentReplayResponse(
            agent_id=agent_id,
            mandate_id=mandate_id,
            mandate_summary=mandate_text,
            total_transactions=total_count,
            approved_count=approved_count,
            step_up_count=step_up_count,
            blocked_count=blocked_count,
            hard_violations_count=hard_violations_count,
            behaviour_consistency=consistency,
            timeline=timeline
        )
