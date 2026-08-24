import uuid
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from app.models.models import (
    Transaction, StepUpRequest, Mandate, BehaviourProfile, FeedbackEvent, AuditLog, utc_now
)
from app.core.state_machine import (
    TransactionStateMachine, InvalidStateTransitionException, DoubleExecutionException
)
from app.providers.simulation import SimulationProvider, PaymentProviderInterface


class StepUpService:
    """
    Manages Step-Up Confirmation Workflows, Feedback Loops, and Payment Execution Boundary.
    """

    @staticmethod
    def create_step_up_request(db: Session, transaction: Transaction, expiry_minutes: int = 5) -> StepUpRequest:
        now = utc_now()
        step_up_id = f"stepup_{uuid.uuid4().hex[:12]}"
        expires_at = now + timedelta(minutes=expiry_minutes)

        step_up = StepUpRequest(
            step_up_id=step_up_id,
            transaction_id=transaction.transaction_id,
            created_at=now,
            expires_at=expires_at,
            resolution="PENDING"
        )
        db.add(step_up)

        audit = AuditLog(
            audit_id=f"audit_su_created_{step_up_id}",
            transaction_id=transaction.transaction_id,
            mandate_id=transaction.mandate_id,
            user_id=transaction.user_id,
            agent_id=transaction.agent_id,
            event_type="STEP_UP_CREATED",
            payload={
                "step_up_id": step_up_id,
                "expires_at": expires_at.isoformat()
            }
        )
        db.add(audit)
        db.commit()
        db.refresh(step_up)
        return step_up

    @staticmethod
    def resolve_step_up(
        db: Session,
        step_up_id: str,
        user_id: str,
        action: str,  # "APPROVE" | "REJECT" | "EXPIRE"
        provider: Optional[PaymentProviderInterface] = None
    ) -> Dict[str, Any]:
        if provider is None:
            provider = SimulationProvider()

        step_up = db.query(StepUpRequest).filter_by(step_up_id=step_up_id).first()
        if not step_up:
            raise ValueError(f"StepUpRequest '{step_up_id}' not found.")

        if step_up.resolution != "PENDING":
            raise ValueError(f"StepUpRequest '{step_up_id}' is already resolved as '{step_up.resolution}'. Cannot resolve twice.")

        transaction = db.query(Transaction).filter_by(transaction_id=step_up.transaction_id).first()
        if not transaction:
            raise ValueError(f"Transaction '{step_up.transaction_id}' not found.")

        if transaction.user_id != user_id:
            raise ValueError(f"User '{user_id}' is not authorized to resolve transaction '{transaction.transaction_id}'.")

        now = utc_now()
        now_naive = now.astimezone(timezone.utc).replace(tzinfo=None) if now.tzinfo else now

        expires_at = step_up.expires_at
        expires_at_naive = expires_at.astimezone(timezone.utc).replace(tzinfo=None) if (expires_at and expires_at.tzinfo) else expires_at

        # Check for expiry before processing approve/reject
        if action == "APPROVE" and expires_at_naive and now_naive > expires_at_naive:
            action = "EXPIRE"


        if action == "APPROVE":
            step_up.resolution = "APPROVED"
            step_up.resolved_at = now
            db.add(step_up)

            # 1. State transition to USER_APPROVED
            TransactionStateMachine.transition(db, transaction, "USER_APPROVED", reason="User explicitly approved step-up")

            # 2. Strict Payment Execution Boundary: Transition to EXECUTING
            TransactionStateMachine.prepare_for_execution(db, transaction)

            # 3. Call Payment Provider
            pay_result = provider.execute(
                transaction_id=transaction.transaction_id,
                amount=transaction.amount,
                currency=transaction.currency,
                merchant_id=transaction.merchant_id
            )

            if pay_result.get("status") == "SUCCESS":
                # 4. State transition to COMPLETED
                TransactionStateMachine.transition(db, transaction, "COMPLETED", reason="Payment executed successfully")

                # Deduct mandate remaining limit
                mandate = db.query(Mandate).filter_by(mandate_id=transaction.mandate_id).first()
                if mandate:
                    mandate.remaining_limit = max(0.0, mandate.remaining_limit - transaction.amount)
                    db.add(mandate)

                # Record feedback event & update behaviour profile
                StepUpService._apply_feedback(db, transaction, feedback_type="STEP_UP_APPROVED")

                db.commit()
                return {
                    "step_up_id": step_up_id,
                    "resolution": "APPROVED",
                    "transaction_state": "COMPLETED",
                    "provider_reference": pay_result.get("provider_reference")
                }
            else:
                # Payment Provider Failed
                TransactionStateMachine.transition(db, transaction, "FAILED", reason=pay_result.get("failure_reason", "Payment failed"))
                db.commit()
                return {
                    "step_up_id": step_up_id,
                    "resolution": "APPROVED",
                    "transaction_state": "FAILED",
                    "error": pay_result.get("failure_reason")
                }

        elif action == "REJECT":
            step_up.resolution = "REJECTED"
            step_up.resolved_at = now
            db.add(step_up)

            TransactionStateMachine.transition(db, transaction, "USER_REJECTED", reason="User rejected step-up confirmation")
            TransactionStateMachine.transition(db, transaction, "CANCELLED", reason="Cancelled following user rejection")

            StepUpService._apply_feedback(db, transaction, feedback_type="STEP_UP_REJECTED")
            db.commit()
            return {
                "step_up_id": step_up_id,
                "resolution": "REJECTED",
                "transaction_state": "CANCELLED"
            }

        else:  # EXPIRE
            step_up.resolution = "EXPIRED"
            step_up.resolved_at = now
            db.add(step_up)

            TransactionStateMachine.transition(db, transaction, "EXPIRED", reason="Step-up request timed out")
            TransactionStateMachine.transition(db, transaction, "CANCELLED", reason="Cancelled following step-up expiry")

            StepUpService._apply_feedback(db, transaction, feedback_type="STEP_UP_REJECTED")
            db.commit()
            return {
                "step_up_id": step_up_id,
                "resolution": "EXPIRED",
                "transaction_state": "CANCELLED"
            }

    @staticmethod
    def execute_auto_approved(
        db: Session,
        transaction: Transaction,
        provider: Optional[PaymentProviderInterface] = None
    ) -> Dict[str, Any]:
        """
        Executes a transaction that was AUTO_APPROVED by scoring.
        Transitions: APPROVED -> EXECUTING -> COMPLETED (or FAILED).
        """
        if provider is None:
            provider = SimulationProvider()

        if transaction.state != "APPROVED":
            raise InvalidStateTransitionException(
                f"Cannot auto-execute transaction '{transaction.transaction_id}' in state '{transaction.state}'."
            )

        # Transition to EXECUTING
        TransactionStateMachine.prepare_for_execution(db, transaction)

        # Call payment provider
        pay_result = provider.execute(
            transaction_id=transaction.transaction_id,
            amount=transaction.amount,
            currency=transaction.currency,
            merchant_id=transaction.merchant_id
        )

        if pay_result.get("status") == "SUCCESS":
            TransactionStateMachine.transition(db, transaction, "COMPLETED", reason="Auto-approved payment executed successfully")
            mandate = db.query(Mandate).filter_by(mandate_id=transaction.mandate_id).first()
            if mandate:
                mandate.remaining_limit = max(0.0, mandate.remaining_limit - transaction.amount)
                db.add(mandate)

            # Update behaviour profile
            behaviour = db.query(BehaviourProfile).filter_by(user_id=transaction.user_id).first()
            if behaviour:
                behaviour.total_transactions += 1
                behaviour.last_transaction_at = utc_now()
                behaviour.last_updated = utc_now()
                db.add(behaviour)

            db.commit()
            return {
                "transaction_id": transaction.transaction_id,
                "state": "COMPLETED",
                "provider_reference": pay_result.get("provider_reference")
            }
        else:
            TransactionStateMachine.transition(db, transaction, "FAILED", reason=pay_result.get("failure_reason", "Payment failed"))
            db.commit()
            return {
                "transaction_id": transaction.transaction_id,
                "state": "FAILED",
                "error": pay_result.get("failure_reason")
            }

    @staticmethod
    def _apply_feedback(db: Session, transaction: Transaction, feedback_type: str):
        now = utc_now()
        fb = FeedbackEvent(
            feedback_id=f"fb_{uuid.uuid4().hex[:12]}",
            transaction_id=transaction.transaction_id,
            user_id=transaction.user_id,
            feedback_type=feedback_type,
            applied_to_profile=True,
            created_at=now
        )
        db.add(fb)

        behaviour = db.query(BehaviourProfile).filter_by(user_id=transaction.user_id).first()
        if not behaviour:
            return

        if feedback_type == "STEP_UP_APPROVED":
            behaviour.step_up_approved_count += 1
            behaviour.total_transactions += 1
            behaviour.last_transaction_at = now

            # Include merchant in common merchants if not present
            common_m = list(behaviour.common_merchants or [])
            if transaction.merchant_id not in common_m:
                common_m.append(transaction.merchant_id)
                behaviour.common_merchants = common_m

            # Nudge median amount
            if behaviour.median_amount > 0:
                behaviour.median_amount = round((behaviour.median_amount * 0.8) + (transaction.amount * 0.2), 2)
            else:
                behaviour.median_amount = transaction.amount
        else:
            behaviour.step_up_rejected_count += 1
            behaviour.declined_count += 1

        behaviour.last_updated = now
        db.add(behaviour)
