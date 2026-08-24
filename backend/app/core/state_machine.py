from typing import Set, Dict
from sqlalchemy.orm import Session
from app.models.models import Transaction, Mandate, AuditLog, utc_now


# Valid state transitions lookup
VALID_TRANSITIONS: Dict[str, Set[str]] = {
    "RECEIVED": {"EVALUATING"},
    "EVALUATING": {"APPROVED", "STEP_UP_REQUIRED", "BLOCKED"},
    "APPROVED": {"EXECUTING"},  # Auto-approved transactions move immediately to EXECUTING
    "STEP_UP_REQUIRED": {"USER_APPROVED", "USER_REJECTED", "EXPIRED", "CANCELLED"},
    "USER_APPROVED": {"EXECUTING"},  # Step-up approved by user moves to EXECUTING
    "USER_REJECTED": {"CANCELLED"},
    "EXPIRED": {"CANCELLED"},
    "BLOCKED": set(),       # Terminal state
    "EXECUTING": {"COMPLETED", "FAILED"},
    "COMPLETED": set(),     # Terminal state
    "FAILED": set(),        # Terminal state
    "CANCELLED": set()      # Terminal state
}

# States from which payment execution is permitted
PERMITTED_EXECUTION_STATES: Set[str] = {"APPROVED", "USER_APPROVED"}


class InvalidStateTransitionException(Exception):
    """Raised when an illegal transaction state transition is attempted."""
    pass


class DoubleExecutionException(Exception):
    """Raised when payment execution is attempted more than once."""
    pass


class TransactionStateMachine:
    """
    Enforces strict payment execution boundary and state machine invariants.
    """

    @staticmethod
    def transition(
        db: Session,
        transaction: Transaction,
        target_state: str,
        reason: str = ""
    ) -> Transaction:
        current_state = transaction.state

        if target_state not in VALID_TRANSITIONS.get(current_state, set()):
            raise InvalidStateTransitionException(
                f"Invalid state transition from '{current_state}' to '{target_state}' for transaction '{transaction.transaction_id}'."
            )

        transaction.state = target_state
        db.add(transaction)

        # Audit log entry for state change
        audit = AuditLog(
            audit_id=f"audit_st_{transaction.transaction_id}_{utc_now().timestamp()}",
            transaction_id=transaction.transaction_id,
            mandate_id=transaction.mandate_id,
            user_id=transaction.user_id,
            agent_id=transaction.agent_id,
            event_type="STATE_TRANSITION",
            payload={
                "from_state": current_state,
                "to_state": target_state,
                "reason": reason
            }
        )
        db.add(audit)
        db.commit()
        db.refresh(transaction)
        return transaction

    @staticmethod
    def can_execute_payment(transaction: Transaction) -> bool:
        """
        SimulationProvider.execute() must ONLY be called when current state is APPROVED or USER_APPROVED.
        It must NEVER be called when state is STEP_UP_REQUIRED, USER_REJECTED, EXPIRED, BLOCKED, FAILED, CANCELLED, COMPLETED.
        """
        return transaction.state in PERMITTED_EXECUTION_STATES

    @staticmethod
    def prepare_for_execution(db: Session, transaction: Transaction) -> Transaction:
        """
        Atomically checks state and transitions into EXECUTING.
        Raises DoubleExecutionException if transaction is already EXECUTING, COMPLETED, or invalid.
        """
        if transaction.state == "EXECUTING" or transaction.state == "COMPLETED":
            raise DoubleExecutionException(
                f"Transaction '{transaction.transaction_id}' is already in '{transaction.state}' state and cannot execute twice."
            )

        if not TransactionStateMachine.can_execute_payment(transaction):
            raise InvalidStateTransitionException(
                f"Cannot execute payment for transaction '{transaction.transaction_id}' in state '{transaction.state}'."
            )

        return TransactionStateMachine.transition(
            db, transaction, "EXECUTING", reason="Payment execution initiated by authorized provider"
        )
