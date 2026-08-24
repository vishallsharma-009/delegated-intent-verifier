from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    Column, String, Float, Integer, Boolean, DateTime, ForeignKey, Text, JSON
)
from sqlalchemy.orm import relationship
from app.db.database import Base


def utc_now():
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    user_id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    mandates = relationship("Mandate", back_populates="user", cascade="all, delete-orphan")
    behaviour_profile = relationship("BehaviourProfile", back_populates="user", uselist=False, cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="user", cascade="all, delete-orphan")


class Mandate(Base):
    __tablename__ = "mandates"

    mandate_id = Column(String, primary_key=True, index=True)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False, index=True)
    raw_text = Column(Text, nullable=False)
    total_limit = Column(Float, nullable=False)
    remaining_limit = Column(Float, nullable=False)
    valid_from = Column(DateTime, nullable=False)
    valid_to = Column(DateTime, nullable=False)
    allowed_categories = Column(JSON, nullable=False, default=list)
    excluded_categories = Column(JSON, nullable=False, default=list)
    allowed_merchant_ids = Column(JSON, nullable=True)
    per_transaction_limit = Column(Float, nullable=True)
    max_transactions_per_day = Column(Integer, nullable=True)
    max_transactions_per_week = Column(Integer, nullable=True)
    status = Column(String, nullable=False, default="ACTIVE", index=True)  # ACTIVE, SUSPENDED, REVOKED, EXPIRED
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    revoked_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="mandates")
    intent_profile = relationship("IntentProfile", back_populates="mandate", uselist=False, cascade="all, delete-orphan")
    transactions = relationship("Transaction", back_populates="mandate")


class IntentProfile(Base):
    __tablename__ = "intent_profiles"

    intent_id = Column(String, primary_key=True, index=True)
    mandate_id = Column(String, ForeignKey("mandates.mandate_id"), unique=True, nullable=False, index=True)
    purpose = Column(String, nullable=False)
    allowed_categories = Column(JSON, nullable=False, default=list)
    excluded_categories = Column(JSON, nullable=False, default=list)
    expected_amount_range = Column(JSON, nullable=False)  # [min, max]
    expected_frequency = Column(String, nullable=False, default="weekly")
    expected_transactions_per_period = Column(Integer, nullable=False, default=1)
    typical_merchant_types = Column(JSON, nullable=False, default=list)
    time_pattern = Column(String, nullable=False, default="any day")
    duration = Column(String, nullable=False, default="30_days")
    notes = Column(Text, nullable=True)

    mandate = relationship("Mandate", back_populates="intent_profile")


class BehaviourProfile(Base):
    __tablename__ = "behaviour_profiles"

    user_id = Column(String, ForeignKey("users.user_id"), primary_key=True, index=True)
    median_amount = Column(Float, nullable=False, default=0.0)
    mean_amount = Column(Float, nullable=False, default=0.0)
    amount_std_dev = Column(Float, nullable=False, default=0.0)
    common_categories = Column(JSON, nullable=False, default=list)
    common_merchants = Column(JSON, nullable=False, default=list)
    avg_transactions_per_week = Column(Float, nullable=False, default=0.0)
    typical_hour_range = Column(JSON, nullable=False, default=lambda: [8, 22])
    total_transactions = Column(Integer, nullable=False, default=0)
    declined_count = Column(Integer, nullable=False, default=0)
    step_up_approved_count = Column(Integer, nullable=False, default=0)
    step_up_rejected_count = Column(Integer, nullable=False, default=0)
    last_transaction_at = Column(DateTime(timezone=True), nullable=True)
    last_updated = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    user = relationship("User", back_populates="behaviour_profile")


class Transaction(Base):
    __tablename__ = "transactions"

    transaction_id = Column(String, primary_key=True, index=True)
    idempotency_key = Column(String, unique=True, nullable=False, index=True)
    user_id = Column(String, ForeignKey("users.user_id"), nullable=False, index=True)
    mandate_id = Column(String, ForeignKey("mandates.mandate_id"), nullable=False, index=True)
    agent_id = Column(String, nullable=False)
    merchant_id = Column(String, nullable=False)
    merchant_category = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    currency = Column(String, nullable=False, default="INR")
    timestamp = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    stated_intent = Column(Text, nullable=False)
    payment_method = Column(String, nullable=False, default="UPI")
    # States: RECEIVED, EVALUATING, APPROVED, STEP_UP_REQUIRED, USER_APPROVED, USER_REJECTED, EXPIRED, BLOCKED, EXECUTING, COMPLETED, FAILED, CANCELLED
    state = Column(String, nullable=False, default="RECEIVED", index=True)

    user = relationship("User", back_populates="transactions")
    mandate = relationship("Mandate", back_populates="transactions")
    decision = relationship("TransactionDecision", back_populates="transaction", uselist=False, cascade="all, delete-orphan")
    step_up_request = relationship("StepUpRequest", back_populates="transaction", uselist=False, cascade="all, delete-orphan")


class TransactionDecision(Base):
    __tablename__ = "transaction_decisions"

    decision_id = Column(String, primary_key=True, index=True)
    transaction_id = Column(String, ForeignKey("transactions.transaction_id"), unique=True, nullable=False, index=True)
    intent_fit_score = Column(Float, nullable=False)
    score_breakdown = Column(JSON, nullable=False)
    hard_rule_triggered = Column(String, nullable=True)
    final_decision = Column(String, nullable=False)  # APPROVE, STEP_UP, BLOCK
    reason_text = Column(String, nullable=False)
    ai_explanation_text = Column(Text, nullable=False)
    decided_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)

    transaction = relationship("Transaction", back_populates="decision")


class StepUpRequest(Base):
    __tablename__ = "step_up_requests"

    step_up_id = Column(String, primary_key=True, index=True)
    transaction_id = Column(String, ForeignKey("transactions.transaction_id"), nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    # Resolution: PENDING, APPROVED, REJECTED, EXPIRED
    resolution = Column(String, nullable=False, default="PENDING")
    resolved_at = Column(DateTime(timezone=True), nullable=True)

    transaction = relationship("Transaction", back_populates="step_up_request")


class AuditLog(Base):
    __tablename__ = "audit_logs"

    audit_id = Column(String, primary_key=True, index=True)
    transaction_id = Column(String, nullable=False, index=True)
    mandate_id = Column(String, nullable=False)
    user_id = Column(String, nullable=False)
    agent_id = Column(String, nullable=False)
    event_type = Column(String, nullable=False)  # e.g. TRANSACTION_EVALUATED, STEP_UP_CREATED, STEP_UP_RESOLVED, PAYMENT_EXECUTED
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False, index=True)


class FeedbackEvent(Base):
    __tablename__ = "feedback_events"

    feedback_id = Column(String, primary_key=True, index=True)
    transaction_id = Column(String, ForeignKey("transactions.transaction_id"), nullable=False, index=True)
    user_id = Column(String, nullable=False, index=True)
    feedback_type = Column(String, nullable=False)  # STEP_UP_APPROVED, STEP_UP_REJECTED
    applied_to_profile = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utc_now, nullable=False)
