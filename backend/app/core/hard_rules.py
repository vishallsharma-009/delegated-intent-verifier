from datetime import datetime, timezone, timedelta
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session
from app.models.models import Mandate, Transaction, User, BehaviourProfile


class HardRuleViolation(Exception):
    """Exception raised when a hard safety rule is triggered."""
    def __init__(self, rule_name: str, reason: str):
        self.rule_name = rule_name
        self.reason = reason
        super().__init__(f"[{rule_name}] {reason}")


class HardRuleEngine:
    """
    Deterministic Safety Rule Engine.
    Must be evaluated BEFORE any scoring.
    Any violation immediately BLOCKS the transaction with score 0.
    """

    @staticmethod
    def evaluate(
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
    ) -> Tuple[bool, Optional[str], Optional[str]]:
        """
        Returns (is_violated, rule_name, reason_text).
        If violated, returns (True, "RULE_NAME", "human readable reason").
        If safe, returns (False, None, None).
        """
        # Ensure timestamp is timezone aware
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)

        # 1. User & Mandate existence and ownership
        mandate = db.query(Mandate).filter_by(mandate_id=mandate_id).first()
        if not mandate:
            return (True, "MANDATE_NOT_FOUND", f"Mandate '{mandate_id}' does not exist.")

        if mandate.user_id != user_id:
            return (True, "MANDATE_OWNERSHIP_MISMATCH", f"Mandate '{mandate_id}' does not belong to user '{user_id}'.")

        # 2. Mandate status check
        if mandate.status != "ACTIVE":
            return (True, "MANDATE_NOT_ACTIVE", f"Mandate status is '{mandate.status}', must be 'ACTIVE'.")

        # 3. Validity window check
        valid_from = mandate.valid_from
        if valid_from.tzinfo is None:
            valid_from = valid_from.replace(tzinfo=timezone.utc)
        valid_to = mandate.valid_to
        if valid_to.tzinfo is None:
            valid_to = valid_to.replace(tzinfo=timezone.utc)

        if not (valid_from <= timestamp <= valid_to):
            return (True, "MANDATE_EXPIRED", f"Transaction time {timestamp.isoformat()} outside mandate valid window [{valid_from.isoformat()}, {valid_to.isoformat()}].")

        # 4. Remaining budget limit check
        if amount > mandate.remaining_limit:
            return (True, "MANDATE_LIMIT_EXCEEDED", f"Transaction amount ₹{amount:.2f} exceeds remaining mandate budget of ₹{mandate.remaining_limit:.2f}.")

        # 5. Per-transaction limit check
        if mandate.per_transaction_limit and amount > mandate.per_transaction_limit:
            return (True, "PER_TRANSACTION_LIMIT_EXCEEDED", f"Transaction amount ₹{amount:.2f} exceeds per-transaction limit of ₹{mandate.per_transaction_limit:.2f}.")

        # 6. Category authorization check
        cat_lower = merchant_category.lower().strip()
        allowed_cats = [c.lower().strip() for c in (mandate.allowed_categories or [])]
        excluded_cats = [c.lower().strip() for c in (mandate.excluded_categories or [])]

        if cat_lower in excluded_cats:
            return (True, "CATEGORY_EXCLUDED", f"Merchant category '{merchant_category}' is explicitly excluded by mandate.")

        if allowed_cats and cat_lower not in allowed_cats:
            return (True, "CATEGORY_NOT_AUTHORIZED", f"Merchant category '{merchant_category}' is not in mandate allowed list {mandate.allowed_categories}.")

        # 7. Allowed merchant ID check (if restriction is set)
        if mandate.allowed_merchant_ids:
            if merchant_id not in mandate.allowed_merchant_ids:
                return (True, "MERCHANT_NOT_AUTHORIZED", f"Merchant '{merchant_id}' is not in mandate allowed merchant list.")

        # 8. Idempotency key duplicate check
        existing_key_txn = db.query(Transaction).filter_by(idempotency_key=idempotency_key).first()
        if existing_key_txn and existing_key_txn.transaction_id != transaction_id:
            return (True, "IDEMPOTENCY_DUPLICATE", f"Idempotency key '{idempotency_key}' was already submitted for transaction '{existing_key_txn.transaction_id}'.")

        # 9. Exact duplicate / velocity violation (same user + amount + merchant within 5 seconds)
        window_start = timestamp - timedelta(seconds=5)
        duplicate_recent = db.query(Transaction).filter(
            Transaction.user_id == user_id,
            Transaction.merchant_id == merchant_id,
            Transaction.amount == amount,
            Transaction.timestamp >= window_start,
            Transaction.timestamp <= timestamp,
            Transaction.transaction_id != transaction_id
        ).first()

        if duplicate_recent:
            return (True, "HARD_DUPLICATE_VIOLATION", f"Duplicate transaction of ₹{amount:.2f} at merchant '{merchant_id}' within 5 seconds of transaction '{duplicate_recent.transaction_id}'.")

        # 10. Frequency cap check (day & week caps)
        if mandate.max_transactions_per_day:
            day_start = timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
            today_count = db.query(Transaction).filter(
                Transaction.mandate_id == mandate_id,
                Transaction.timestamp >= day_start,
                Transaction.timestamp <= timestamp,
                Transaction.state.in_(["COMPLETED", "EXECUTING", "APPROVED", "USER_APPROVED", "STEP_UP_REQUIRED"]),
                Transaction.transaction_id != transaction_id
            ).count()

            if today_count >= mandate.max_transactions_per_day:
                return (True, "DAILY_FREQUENCY_EXCEEDED", f"Daily transaction cap of {mandate.max_transactions_per_day} exceeded (already had {today_count} today).")

        if mandate.max_transactions_per_week:
            week_start = timestamp - timedelta(days=7)
            week_count = db.query(Transaction).filter(
                Transaction.mandate_id == mandate_id,
                Transaction.timestamp >= week_start,
                Transaction.timestamp <= timestamp,
                Transaction.state.in_(["COMPLETED", "EXECUTING", "APPROVED", "USER_APPROVED", "STEP_UP_REQUIRED"]),
                Transaction.transaction_id != transaction_id
            ).count()

            if week_count >= mandate.max_transactions_per_week:
                return (True, "WEEKLY_FREQUENCY_EXCEEDED", f"Weekly transaction cap of {mandate.max_transactions_per_week} exceeded (already had {week_count} in past 7 days).")

        return (False, None, None)
