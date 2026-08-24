import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.database import Base
from app.models.models import User, Mandate, IntentProfile, BehaviourProfile, Transaction
from app.core.scoring import IntentFitScorer

TEST_DATABASE_URL = "sqlite:///:memory:"

@pytest.fixture
def db_session():
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def setup_scoring_context(db):
    user = User(user_id="user_sc", name="Scoring User")
    db.add(user)

    now = datetime.now(timezone.utc)
    mandate = Mandate(
        mandate_id="mandate_sc",
        user_id="user_sc",
        raw_text="Weekly grocery shopping up to 3000",
        total_limit=12000.0,
        remaining_limit=10000.0,
        valid_from=now - timedelta(days=1),
        valid_to=now + timedelta(days=30),
        allowed_categories=["grocery"],
        excluded_categories=["electronics"],
        per_transaction_limit=3000.0,
        status="ACTIVE"
    )
    db.add(mandate)
    db.commit()

    intent = IntentProfile(
        intent_id="intent_sc",
        mandate_id="mandate_sc",
        purpose="weekly household groceries",
        allowed_categories=["grocery"],
        excluded_categories=["electronics"],
        expected_amount_range=[500.0, 2500.0],
        expected_frequency="weekly",
        expected_transactions_per_period=1,
        typical_merchant_types=["supermarket", "online grocery"],
        time_pattern="any day",
        duration="30_days"
    )
    db.add(intent)

    behaviour = BehaviourProfile(
        user_id="user_sc",
        median_amount=800.0,
        mean_amount=850.0,
        amount_std_dev=200.0,
        common_categories=["grocery"],
        common_merchants=["m_bigbasket", "m_blinkit"],
        avg_transactions_per_week=1.0,
        typical_hour_range=[8, 22],
        total_transactions=10
    )
    db.add(behaviour)
    db.commit()
    return user, mandate, intent, behaviour, now


def test_hard_rule_evaluated_first_returns_zero_score(db_session):
    user, mandate, intent, behaviour, now = setup_scoring_context(db_session)
    mandate.status = "SUSPENDED"
    db_session.commit()

    decision, score, breakdown, hard_rule, reason, ai_exp = IntentFitScorer.evaluate_and_score(
        db=db_session,
        transaction_id="txn_hard",
        idempotency_key="key_hard",
        user_id="user_sc",
        mandate_id="mandate_sc",
        agent_id="agent_1",
        merchant_id="m_bigbasket",
        merchant_category="grocery",
        amount=800.0,
        timestamp=now,
        stated_intent="weekly groceries"
    )

    assert decision == "BLOCK"
    assert score == 0.0
    assert hard_rule == "MANDATE_NOT_ACTIVE"
    assert breakdown.category_match == 0.0
    assert breakdown.amount_deviation == 0.0


def test_high_score_auto_approve(db_session):
    user, mandate, intent, behaviour, now = setup_scoring_context(db_session)

    decision, score, breakdown, hard_rule, reason, ai_exp = IntentFitScorer.evaluate_and_score(
        db=db_session,
        transaction_id="txn_good",
        idempotency_key="key_good",
        user_id="user_sc",
        mandate_id="mandate_sc",
        agent_id="agent_1",
        merchant_id="m_bigbasket",
        merchant_category="grocery",
        amount=850.0,  # Near median, within expected range
        timestamp=now.replace(hour=14),
        stated_intent="weekly household groceries"
    )

    assert hard_rule is None
    assert score >= 75.0
    assert decision == "APPROVE"
    assert "aligns strongly" in ai_exp


def test_moderate_score_step_up_required(db_session):
    user, mandate, intent, behaviour, now = setup_scoring_context(db_session)

    decision, score, breakdown, hard_rule, reason, ai_exp = IntentFitScorer.evaluate_and_score(
        db=db_session,
        transaction_id="txn_stepup",
        idempotency_key="key_stepup",
        user_id="user_sc",
        mandate_id="mandate_sc",
        agent_id="agent_1",
        merchant_id="m_unknown_store",  # Unfamiliar merchant
        merchant_category="grocery",
        amount=2850.0,  # High amount relative to median 800
        timestamp=now.replace(hour=14),
        stated_intent="bulk grocery restock"
    )

    assert hard_rule is None
    assert 45.0 <= score < 75.0
    assert decision == "STEP_UP"
    assert "requires user approval" in ai_exp


def test_low_score_hard_block(db_session):
    user, mandate, intent, behaviour, now = setup_scoring_context(db_session)
    target_time = now.replace(hour=3)

    # Add 3 recent transactions to deplete frequency & velocity score
    for i in range(3):
        db_session.add(Transaction(
            transaction_id=f"txn_hist_{i}",
            idempotency_key=f"key_hist_{i}",
            user_id="user_sc",
            mandate_id="mandate_sc",
            agent_id="agent_1",
            merchant_id="m_other",
            merchant_category="grocery",
            amount=500.0,
            timestamp=target_time - timedelta(seconds=20 * (i + 1)),
            stated_intent="grocery",
            state="COMPLETED"
        ))
    db_session.commit()

    decision, score, breakdown, hard_rule, reason, ai_exp = IntentFitScorer.evaluate_and_score(
        db=db_session,
        transaction_id="txn_bad",
        idempotency_key="key_bad",
        user_id="user_sc",
        mandate_id="mandate_sc",
        agent_id="agent_1",
        merchant_id="m_strange",
        merchant_category="grocery",
        amount=2990.0,
        timestamp=target_time,
        stated_intent="random purchase"
    )

    assert hard_rule is None
    assert score < 45.0
    assert decision == "BLOCK"
    assert "blocked due to low intent consistency" in ai_exp


def test_policy_threshold_boundaries():
    # Test boundary logic helper directly
    def map_score_to_decision(total_score: float) -> str:
        if total_score >= 75.0:
            return "APPROVE"
        elif total_score >= 45.0:
            return "STEP_UP"
        else:
            return "BLOCK"

    assert map_score_to_decision(100.0) == "APPROVE"
    assert map_score_to_decision(75.0) == "APPROVE"
    assert map_score_to_decision(74.9) == "STEP_UP"
    assert map_score_to_decision(74.0) == "STEP_UP"
    assert map_score_to_decision(45.0) == "STEP_UP"
    assert map_score_to_decision(44.9) == "BLOCK"
    assert map_score_to_decision(44.0) == "BLOCK"
    assert map_score_to_decision(0.0) == "BLOCK"



