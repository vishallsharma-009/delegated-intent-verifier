import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.database import Base
from app.models.models import (
    User, Mandate, IntentProfile, BehaviourProfile,
    Transaction, TransactionDecision, StepUpRequest, AuditLog, FeedbackEvent
)

# Setup in-memory sqlite database for testing
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


def test_user_and_behaviour_profile_creation(db_session):
    user = User(user_id="user_001", name="Test User")
    db_session.add(user)
    db_session.commit()

    profile = BehaviourProfile(
        user_id="user_001",
        median_amount=500.0,
        mean_amount=550.0,
        amount_std_dev=50.0,
        common_categories=["grocery"],
        common_merchants=["merchant_bigbasket"],
        avg_transactions_per_week=1.5,
        typical_hour_range=[9, 20],
        total_transactions=5
    )
    db_session.add(profile)
    db_session.commit()

    fetched_user = db_session.query(User).filter_by(user_id="user_001").first()
    assert fetched_user is not None
    assert fetched_user.name == "Test User"
    assert fetched_user.behaviour_profile.median_amount == 500.0
    assert fetched_user.behaviour_profile.common_categories == ["grocery"]


def test_mandate_and_intent_profile_relationship(db_session):
    user = User(user_id="user_002", name="Alice")
    db_session.add(user)
    db_session.commit()

    now = datetime.now(timezone.utc)
    mandate = Mandate(
        mandate_id="mandate_001",
        user_id="user_002",
        raw_text="Weekly grocery up to 3000",
        total_limit=12000.0,
        remaining_limit=12000.0,
        valid_from=now,
        valid_to=now + timedelta(days=30),
        allowed_categories=["grocery"],
        excluded_categories=["electronics"],
        per_transaction_limit=3000.0,
        max_transactions_per_week=1,
        status="ACTIVE"
    )
    db_session.add(mandate)
    db_session.commit()

    intent = IntentProfile(
        intent_id="intent_001",
        mandate_id="mandate_001",
        purpose="household weekly grocery shopping",
        allowed_categories=["grocery"],
        excluded_categories=["electronics"],
        expected_amount_range=[500.0, 3000.0],
        expected_frequency="weekly",
        expected_transactions_per_period=1,
        typical_merchant_types=["supermarket"],
        time_pattern="any day",
        duration="30_days"
    )
    db_session.add(intent)
    db_session.commit()

    fetched_mandate = db_session.query(Mandate).filter_by(mandate_id="mandate_001").first()
    assert fetched_mandate is not None
    assert fetched_mandate.intent_profile is not None
    assert fetched_mandate.intent_profile.purpose == "household weekly grocery shopping"


def test_transaction_idempotency_constraint(db_session):
    user = User(user_id="user_003", name="Bob")
    db_session.add(user)
    
    now = datetime.now(timezone.utc)
    mandate = Mandate(
        mandate_id="mandate_002",
        user_id="user_003",
        raw_text="Test mandate",
        total_limit=5000.0,
        remaining_limit=5000.0,
        valid_from=now,
        valid_to=now + timedelta(days=10),
        allowed_categories=["grocery"],
        excluded_categories=[],
        status="ACTIVE"
    )

    db_session.add(mandate)
    db_session.commit()

    txn1 = Transaction(
        transaction_id="txn_101",
        idempotency_key="key_abc123",
        user_id="user_003",
        mandate_id="mandate_002",
        agent_id="agent_1",
        merchant_id="m_1",
        merchant_category="grocery",
        amount=100.0,
        stated_intent="buy milk",
        state="RECEIVED"
    )
    db_session.add(txn1)
    db_session.commit()

    # Adding second transaction with same idempotency key should raise IntegrityError
    txn2 = Transaction(
        transaction_id="txn_102",
        idempotency_key="key_abc123",
        user_id="user_003",
        mandate_id="mandate_002",
        agent_id="agent_1",
        merchant_id="m_1",
        merchant_category="grocery",
        amount=100.0,
        stated_intent="buy milk duplicate",
        state="RECEIVED"
    )
    db_session.add(txn2)
    with pytest.raises(Exception):
        db_session.commit()
    db_session.rollback()


def test_audit_log_creation(db_session):
    log = AuditLog(
        audit_id="audit_001",
        transaction_id="txn_101",
        mandate_id="mandate_002",
        user_id="user_003",
        agent_id="agent_1",
        event_type="TRANSACTION_EVALUATED",
        payload={"score": 85.0, "decision": "APPROVE"}
    )
    db_session.add(log)
    db_session.commit()

    fetched_log = db_session.query(AuditLog).filter_by(audit_id="audit_001").first()
    assert fetched_log is not None
    assert fetched_log.payload["decision"] == "APPROVE"
