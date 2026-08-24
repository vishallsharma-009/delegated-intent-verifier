import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Optional, Dict, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from app.db.database import get_db, init_db
from app.models.models import (
    User, Mandate, IntentProfile, BehaviourProfile, Transaction,
    TransactionDecision, StepUpRequest, AuditLog, utc_now
)
from app.schemas.schemas import (
    MandateCreate, MandateResponse, IntentProfileSchema,
    TransactionRequest, TransactionEvaluationResponse, ScoreBreakdown,
    StepUpActionRequest, StepUpResponse, AuditLogSchema, MetricsResponse,
    RedTeamSummary, AgentReplayResponse
)
from app.services.intent_service import IntentExtractionService
from app.core.scoring import IntentFitScorer
from app.services.step_up_service import StepUpService
from app.services.simulation_engine import SimulationEngine
from app.services.synthetic_dataset import SyntheticDatasetGenerator
from app.services.red_team_service import RedTeamSimulator
from app.services.agent_replay_service import AgentReplayService


logger = logging.getLogger("div_api")
logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: initialize database tables
    init_db()
    db = next(get_db())
    try:
        # Seed initial synthetic dataset if DB is empty
        if db.query(User).count() == 0:
            SyntheticDatasetGenerator.seed_synthetic_data(db)
            logger.info("Database initialized and pre-seeded with synthetic dataset.")
    finally:
        db.close()
    yield


app = FastAPI(
    title="Delegated Intent Verifier (DIV) API",
    description="Agentic Payment Trust Layer for AI-Initiated Payments (Razorpay AI Buildathon 2026)",
    version="1.0.0",
    lifespan=lifespan
)

# Enable CORS for React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def read_root():
    return {
        "system": "Delegated Intent Verifier (DIV)",
        "status": "ONLINE",
        "timestamp": utc_now().isoformat()
    }


# =====================================================================
# 1. MANDATES API
# =====================================================================

@app.post("/mandates", response_model=MandateResponse, status_code=status.HTTP_201_CREATED)
def create_mandate(payload: MandateCreate, db: Session = Depends(get_db)):
    """
    Creates a spending mandate and triggers LLM Intent Profile extraction.
    """
    now = utc_now()
    now_naive = now.astimezone(timezone.utc).replace(tzinfo=None)

    # 1. Ensure user exists
    user = db.query(User).filter_by(user_id=payload.user_id).first()
    if not user:
        user = User(user_id=payload.user_id, name=f"User {payload.user_id}")
        db.add(user)
        db.commit()

    # 2. Setup default validity dates if omitted
    valid_from = payload.valid_from or now
    valid_to = payload.valid_to or (now + timedelta(days=30))
    vf_naive = valid_from.astimezone(timezone.utc).replace(tzinfo=None) if valid_from.tzinfo else valid_from
    vt_naive = valid_to.astimezone(timezone.utc).replace(tzinfo=None) if valid_to.tzinfo else valid_to

    mandate_id = f"mandate_{uuid.uuid4().hex[:8]}"
    mandate = Mandate(
        mandate_id=mandate_id,
        user_id=payload.user_id,
        raw_text=payload.raw_text,
        total_limit=payload.total_limit,
        remaining_limit=payload.total_limit,
        valid_from=vf_naive,
        valid_to=vt_naive,
        allowed_categories=payload.allowed_categories,
        excluded_categories=payload.excluded_categories,
        per_transaction_limit=payload.per_transaction_limit,
        max_transactions_per_day=payload.max_transactions_per_day,
        max_transactions_per_week=payload.max_transactions_per_week,
        status="ACTIVE",
        created_at=now_naive
    )
    db.add(mandate)
    db.commit()

    # 3. Trigger LLM Intent Extraction
    extracted_intent = IntentExtractionService.extract_intent(
        raw_text=payload.raw_text,
        total_limit=payload.total_limit,
        allowed_cats=payload.allowed_categories
    )

    intent_id = f"intent_{uuid.uuid4().hex[:8]}"
    intent_profile = IntentProfile(
        intent_id=intent_id,
        mandate_id=mandate_id,
        purpose=extracted_intent.get("purpose", payload.raw_text),
        allowed_categories=extracted_intent.get("allowed_categories", payload.allowed_categories),
        excluded_categories=extracted_intent.get("excluded_categories", payload.excluded_categories),
        expected_amount_range=extracted_intent.get("expected_amount_range", [100.0, payload.total_limit]),
        expected_frequency=extracted_intent.get("expected_frequency", "weekly"),
        expected_transactions_per_period=extracted_intent.get("expected_transactions_per_period", 1),
        typical_merchant_types=extracted_intent.get("typical_merchant_types", ["retail"]),
        time_pattern=extracted_intent.get("time_pattern", "any day"),
        duration=extracted_intent.get("duration", "30_days"),
        notes=extracted_intent.get("notes", "")
    )
    db.add(intent_profile)

    # Ensure behaviour profile exists
    behaviour = db.query(BehaviourProfile).filter_by(user_id=payload.user_id).first()
    if not behaviour:
        behaviour = BehaviourProfile(
            user_id=payload.user_id,
            median_amount=round(payload.total_limit * 0.2, 2),
            mean_amount=round(payload.total_limit * 0.2, 2),
            amount_std_dev=round(payload.total_limit * 0.05, 2),
            common_categories=payload.allowed_categories,
            common_merchants=[],
            total_transactions=0
        )
        db.add(behaviour)

    db.commit()
    db.refresh(mandate)
    return mandate


@app.get("/mandates/{mandate_id}", response_model=MandateResponse)
def get_mandate(mandate_id: str, db: Session = Depends(get_db)):
    mandate = db.query(Mandate).filter_by(mandate_id=mandate_id).first()
    if not mandate:
        raise HTTPException(status_code=404, detail=f"Mandate '{mandate_id}' not found.")
    return mandate


@app.get("/mandates", response_model=List[MandateResponse])
def list_mandates(user_id: Optional[str] = Query(default=None), db: Session = Depends(get_db)):
    query = db.query(Mandate)
    if user_id:
        query = query.filter_by(user_id=user_id)
    return query.order_by(Mandate.created_at.desc()).all()


@app.post("/mandates/{mandate_id}/revoke", response_model=MandateResponse)
def revoke_mandate(mandate_id: str, db: Session = Depends(get_db)):
    mandate = db.query(Mandate).filter_by(mandate_id=mandate_id).first()
    if not mandate:
        raise HTTPException(status_code=404, detail=f"Mandate '{mandate_id}' not found.")

    if mandate.status == "REVOKED":
        return mandate

    mandate.status = "REVOKED"
    mandate.revoked_at = utc_now().astimezone(timezone.utc).replace(tzinfo=None)

    # Cancel any pending step-up requests for transactions under this mandate
    pending_stepups = db.query(StepUpRequest).join(Transaction).filter(
        Transaction.mandate_id == mandate_id,
        StepUpRequest.resolution == "PENDING"
    ).all()

    for su in pending_stepups:
        su.resolution = "EXPIRED"
        su.resolved_at = utc_now().astimezone(timezone.utc).replace(tzinfo=None)
        su.transaction.state = "CANCELLED"
        db.add(su)

    db.add(mandate)
    db.commit()
    db.refresh(mandate)
    return mandate


# =====================================================================
# 2. TRANSACTIONS & EVALUATION API
# =====================================================================

@app.post("/transactions/evaluate", response_model=TransactionEvaluationResponse)
def evaluate_transaction(payload: TransactionRequest, db: Session = Depends(get_db)):
    """
    Core Evaluation Endpoint.
    1. Idempotency Check: Returns existing decision if idempotency key was already evaluated.
    2. Hard Safety Rules Check (Evaluated BEFORE scoring).
    3. Intent-Fit Scoring Engine (0-100).
    4. Policy Decision Mapping (APPROVE / STEP_UP / BLOCK).
    5. Payment Execution Boundary (Executes payment ONLY if APPROVED).
    """
    now = utc_now()
    now_naive = now.astimezone(timezone.utc).replace(tzinfo=None)
    ts = payload.timestamp or now
    ts_naive = ts.astimezone(timezone.utc).replace(tzinfo=None) if ts.tzinfo else ts

    # 1. Idempotency enforcement
    existing_txn = db.query(Transaction).filter_by(idempotency_key=payload.idempotency_key).first()
    if existing_txn and existing_txn.decision:
        step_up_id = existing_txn.step_up_request.step_up_id if existing_txn.step_up_request else None
        return TransactionEvaluationResponse(
            transaction_id=existing_txn.transaction_id,
            idempotency_key=existing_txn.idempotency_key,
            state=existing_txn.state,
            final_decision=existing_txn.decision.final_decision,
            intent_fit_score=existing_txn.decision.intent_fit_score,
            score_breakdown=ScoreBreakdown(**existing_txn.decision.score_breakdown),
            hard_rule_triggered=existing_txn.decision.hard_rule_triggered,
            reason_text=existing_txn.decision.reason_text,
            ai_explanation_text=existing_txn.decision.ai_explanation_text,
            step_up_id=step_up_id,
            payment_reference=None
        )

    txn_id = payload.transaction_id or f"txn_{uuid.uuid4().hex[:10]}"

    # Create Transaction record in RECEIVED state
    transaction = Transaction(
        transaction_id=txn_id,
        idempotency_key=payload.idempotency_key,
        user_id=payload.user_id,
        mandate_id=payload.mandate_id,
        agent_id=payload.agent_id,
        merchant_id=payload.merchant_id,
        merchant_category=payload.merchant_category,
        amount=payload.amount,
        currency=payload.currency,
        timestamp=ts_naive,
        stated_intent=payload.stated_intent,
        payment_method=payload.payment_method,
        state="EVALUATING"
    )
    db.add(transaction)
    db.commit()

    # 2. Run Hard Rules & Intent-Fit Scoring
    decision, score, breakdown, hard_rule, reason, ai_exp = IntentFitScorer.evaluate_and_score(
        db=db,
        transaction_id=txn_id,
        idempotency_key=payload.idempotency_key,
        user_id=payload.user_id,
        mandate_id=payload.mandate_id,
        agent_id=payload.agent_id,
        merchant_id=payload.merchant_id,
        merchant_category=payload.merchant_category,
        amount=payload.amount,
        timestamp=ts,
        stated_intent=payload.stated_intent
    )

    # 3. Store Decision Record
    decision_id = f"dec_{uuid.uuid4().hex[:10]}"
    txn_decision = TransactionDecision(
        decision_id=decision_id,
        transaction_id=txn_id,
        intent_fit_score=score,
        score_breakdown=breakdown.model_dump(),
        hard_rule_triggered=hard_rule,
        final_decision=decision,
        reason_text=reason,
        ai_explanation_text=ai_exp,
        decided_at=now_naive
    )
    db.add(txn_decision)

    # Write Audit Log
    audit = AuditLog(
        audit_id=f"audit_eval_{txn_id}",
        transaction_id=txn_id,
        mandate_id=payload.mandate_id,
        user_id=payload.user_id,
        agent_id=payload.agent_id,
        event_type="TRANSACTION_EVALUATED",
        payload={
            "decision": decision,
            "score": score,
            "hard_rule": hard_rule,
            "breakdown": breakdown.model_dump(),
            "reason": reason
        },
        created_at=now_naive
    )
    db.add(audit)
    db.commit()

    step_up_id = None
    pay_ref = None

    # 4. Handle Decision Workflows & Payment Boundary
    if decision == "APPROVE":
        transaction.state = "APPROVED"
        db.add(transaction)
        db.commit()

        # Execute Auto-Approved Payment
        exec_res = StepUpService.execute_auto_approved(db, transaction)
        pay_ref = exec_res.get("provider_reference")

    elif decision == "STEP_UP":
        transaction.state = "STEP_UP_REQUIRED"
        db.add(transaction)
        db.commit()

        # Create Step-Up Request for User Confirmation UI
        su = StepUpService.create_step_up_request(db, transaction, expiry_minutes=5)
        step_up_id = su.step_up_id

    else:  # BLOCK
        transaction.state = "BLOCKED"
        db.add(transaction)
        db.commit()

    db.refresh(transaction)

    return TransactionEvaluationResponse(
        transaction_id=transaction.transaction_id,
        idempotency_key=transaction.idempotency_key,
        state=transaction.state,
        final_decision=decision,
        intent_fit_score=score,
        score_breakdown=breakdown,
        hard_rule_triggered=hard_rule,
        reason_text=reason,
        ai_explanation_text=ai_exp,
        step_up_id=step_up_id,
        payment_reference=pay_ref
    )


@app.post("/transactions/{transaction_id}/approve", response_model=StepUpResponse)
def approve_step_up(transaction_id: str, payload: StepUpActionRequest, db: Session = Depends(get_db)):
    """
    User approves a pending step-up confirmation request.
    Executes payment provider ONLY after USER_APPROVED.
    """
    su = db.query(StepUpRequest).filter_by(transaction_id=transaction_id, resolution="PENDING").first()
    if not su:
        # Check if StepUpRequest was already resolved (idempotency check)
        already_su = db.query(StepUpRequest).filter_by(transaction_id=transaction_id).first()
        if already_su and already_su.resolution in ["APPROVED", "REJECTED", "EXPIRED"]:
            return already_su

        # Check if transaction exists and is in STEP_UP_REQUIRED state
        txn = db.query(Transaction).filter_by(transaction_id=transaction_id).first()
        if txn:
            if txn.state in ["COMPLETED", "USER_APPROVED", "EXECUTING"]:
                if txn.step_up_request:
                    return txn.step_up_request
            elif txn.state == "STEP_UP_REQUIRED":
                su = StepUpService.create_step_up_request(db, txn, expiry_minutes=15)

        if not su:
            raise HTTPException(status_code=404, detail=f"No pending Step-Up request found for transaction '{transaction_id}'.")

    try:
        res = StepUpService.resolve_step_up(db, su.step_up_id, user_id=payload.user_id, action="APPROVE")
        db.refresh(su)
        return su
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/transactions/{transaction_id}/reject", response_model=StepUpResponse)
def reject_step_up(transaction_id: str, payload: StepUpActionRequest, db: Session = Depends(get_db)):
    """
    User rejects a pending step-up confirmation request.
    Cancels transaction without executing payment provider.
    """
    su = db.query(StepUpRequest).filter_by(transaction_id=transaction_id, resolution="PENDING").first()
    if not su:
        already_su = db.query(StepUpRequest).filter_by(transaction_id=transaction_id).first()
        if already_su and already_su.resolution in ["APPROVED", "REJECTED", "EXPIRED"]:
            return already_su

        txn = db.query(Transaction).filter_by(transaction_id=transaction_id).first()
        if txn:
            if txn.state in ["CANCELLED", "USER_REJECTED"]:
                if txn.step_up_request:
                    return txn.step_up_request
            elif txn.state == "STEP_UP_REQUIRED":
                su = StepUpService.create_step_up_request(db, txn, expiry_minutes=15)

        if not su:
            raise HTTPException(status_code=404, detail=f"No pending Step-Up request found for transaction '{transaction_id}'.")

    try:
        res = StepUpService.resolve_step_up(db, su.step_up_id, user_id=payload.user_id, action="REJECT")
        db.refresh(su)
        return su
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/transactions/{transaction_id}")
def get_transaction(transaction_id: str, db: Session = Depends(get_db)):
    txn = db.query(Transaction).filter_by(transaction_id=transaction_id).first()
    if not txn:
        raise HTTPException(status_code=404, detail=f"Transaction '{transaction_id}' not found.")

    step_up = txn.step_up_request
    decision = txn.decision

    return {
        "transaction_id": txn.transaction_id,
        "idempotency_key": txn.idempotency_key,
        "user_id": txn.user_id,
        "mandate_id": txn.mandate_id,
        "agent_id": txn.agent_id,
        "merchant_id": txn.merchant_id,
        "merchant_category": txn.merchant_category,
        "amount": txn.amount,
        "currency": txn.currency,
        "timestamp": txn.timestamp.isoformat(),
        "stated_intent": txn.stated_intent,
        "payment_method": txn.payment_method,
        "state": txn.state,
        "decision": {
            "final_decision": decision.final_decision if decision else None,
            "intent_fit_score": decision.intent_fit_score if decision else None,
            "score_breakdown": decision.score_breakdown if decision else None,
            "hard_rule_triggered": decision.hard_rule_triggered if decision else None,
            "reason_text": decision.reason_text if decision else None,
            "ai_explanation_text": decision.ai_explanation_text if decision else None,
        } if decision else None,
        "step_up_request": {
            "step_up_id": step_up.step_up_id,
            "resolution": step_up.resolution,
            "expires_at": step_up.expires_at.isoformat()
        } if step_up else None
    }


@app.get("/transactions")
def list_transactions(user_id: Optional[str] = Query(default=None), limit: int = Query(default=20), db: Session = Depends(get_db)):
    query = db.query(Transaction)
    if user_id:
        query = query.filter_by(user_id=user_id)
    txns = query.order_by(Transaction.timestamp.desc()).limit(limit).all()

    res = []
    for txn in txns:
        decision = txn.decision
        step_up = txn.step_up_request
        res.append({
            "transaction_id": txn.transaction_id,
            "idempotency_key": txn.idempotency_key,
            "user_id": txn.user_id,
            "mandate_id": txn.mandate_id,
            "agent_id": txn.agent_id,
            "merchant_id": txn.merchant_id,
            "merchant_category": txn.merchant_category,
            "amount": txn.amount,
            "timestamp": txn.timestamp.isoformat(),
            "stated_intent": txn.stated_intent,
            "state": txn.state,
            "final_decision": decision.final_decision if decision else "UNKNOWN",
            "intent_fit_score": decision.intent_fit_score if decision else 0.0,
            "score_breakdown": decision.score_breakdown if decision else {},
            "ai_explanation_text": decision.ai_explanation_text if decision else "",
            "step_up_id": step_up.step_up_id if step_up else None,
            "step_up_resolution": step_up.resolution if step_up else None
        })
    return res


# =====================================================================
# 3. AUDIT & EVALUATION SIMULATION API
# =====================================================================

@app.get("/audit/{transaction_id}", response_model=List[AuditLogSchema])
def get_audit_trail(transaction_id: str, db: Session = Depends(get_db)):
    """
    Returns full append-only audit trail for a single transaction.
    """
    logs = db.query(AuditLog).filter_by(transaction_id=transaction_id).order_by(AuditLog.created_at.asc()).all()
    if not logs:
        raise HTTPException(status_code=404, detail=f"No audit logs found for transaction '{transaction_id}'.")
    return logs


@app.get("/metrics", response_model=MetricsResponse)
def get_metrics(db: Session = Depends(get_db)):
    """
    Returns dynamically computed evaluation metrics.
    """
    return SimulationEngine.run_simulation(db)


@app.post("/simulation/run", response_model=MetricsResponse)
def run_simulation(db: Session = Depends(get_db)):
    """
    Batch-replays synthetic dataset and returns dynamically calculated comparison metrics.
    Enforces Correction 2: Benchmark numbers are NEVER hardcoded.
    """
    return SimulationEngine.run_simulation(db)


# =====================================================================
# 4. RED-TEAM & AGENT REPLAY PRODUCT UPGRADES
# =====================================================================

@app.post("/red-team/run", response_model=RedTeamSummary)
def run_red_team_attacks(mandate_id: Optional[str] = Query(default=None), db: Session = Depends(get_db)):
    """
    Executes Agent Red-Team / Attack Simulator against existing DIV pipeline.
    Runs 6 attack scenarios and dynamically calculates attack metrics.
    """
    return RedTeamSimulator.run_red_team_attacks(db, mandate_id=mandate_id)


@app.get("/agents/{agent_id}/replay", response_model=AgentReplayResponse)
def get_agent_replay(agent_id: str = "agent_001", db: Session = Depends(get_db)):
    """
    Returns Agent Behaviour Replay timeline and deterministic consistency level.
    """
    return AgentReplayService.get_agent_replay(db, agent_id=agent_id)

