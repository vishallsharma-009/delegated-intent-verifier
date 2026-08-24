import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.database import Base
from app.models.models import User, Mandate, Transaction
from app.core.hard_rules import HardRuleEngine

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


def setup_base_data(db):
    user = User(user_id="user_001", name="Test User")
    db.add(user)
    
    now = datetime.now(timezone.utc)
    mandate = Mandate(
        mandate_id="mandate_001",
        user_id="user_001",
        raw_text="Groceries up to 3000 weekly",
        total_limit=12000.0,
        remaining_limit=10000.0,
        valid_from=now - timedelta(days=1),
        valid_to=now + timedelta(days=30),
        allowed_categories=["grocery"],
        excluded_categories=["electronics"],
        per_transaction_limit=3000.0,
        max_transactions_per_day=2,
        max_transactions_per_week=5,
        status="ACTIVE"
    )
    db.add(mandate)
    db.commit()
    return user, mandate, now


def test_mandate_not_active(db_session):
    user, mandate, now = setup_base_data(db_session)
    mandate.status = "SUSPENDED"
    db_session.commit()

    is_violated, rule_name, reason = HardRuleEngine.evaluate(
        db=db_session,
        transaction_id="txn_001",
        idempotency_key="key_001",
        user_id="user_001",
        mandate_id="mandate_001",
        agent_id="agent_1",
        merchant_id="m_bigbasket",
        merchant_category="grocery",
        amount=500.0,
        timestamp=now,
        stated_intent="buy milk"
    )
    assert is_violated is True
    assert rule_name == "MANDATE_NOT_ACTIVE"


def test_mandate_expired(db_session):
    user, mandate, now = setup_base_data(db_session)
    mandate.valid_to = now - timedelta(hours=1)
    db_session.commit()

    is_violated, rule_name, reason = HardRuleEngine.evaluate(
        db=db_session,
        transaction_id="txn_001",
        idempotency_key="key_001",
        user_id="user_001",
        mandate_id="mandate_001",
        agent_id="agent_1",
        merchant_id="m_bigbasket",
        merchant_category="grocery",
        amount=500.0,
        timestamp=now,
        stated_intent="buy milk"
    )
    assert is_violated is True
    assert rule_name == "MANDATE_EXPIRED"


def test_remaining_limit_exceeded(db_session):
    user, mandate, now = setup_base_data(db_session)
    mandate.remaining_limit = 200.0
    db_session.commit()

    is_violated, rule_name, reason = HardRuleEngine.evaluate(
        db=db_session,
        transaction_id="txn_001",
        idempotency_key="key_001",
        user_id="user_001",
        mandate_id="mandate_001",
        agent_id="agent_1",
        merchant_id="m_bigbasket",
        merchant_category="grocery",
        amount=500.0,
        timestamp=now,
        stated_intent="buy milk"
    )
    assert is_violated is True
    assert rule_name == "MANDATE_LIMIT_EXCEEDED"


def test_per_transaction_limit_exceeded(db_session):
    user, mandate, now = setup_base_data(db_session)

    is_violated, rule_name, reason = HardRuleEngine.evaluate(
        db=db_session,
        transaction_id="txn_001",
        idempotency_key="key_001",
        user_id="user_001",
        mandate_id="mandate_001",
        agent_id="agent_1",
        merchant_id="m_bigbasket",
        merchant_category="grocery",
        amount=3500.0,  # Cap is 3000
        timestamp=now,
        stated_intent="buy bulk items"
    )
    assert is_violated is True
    assert rule_name == "PER_TRANSACTION_LIMIT_EXCEEDED"


def test_category_excluded(db_session):
    user, mandate, now = setup_base_data(db_session)

    is_violated, rule_name, reason = HardRuleEngine.evaluate(
        db=db_session,
        transaction_id="txn_001",
        idempotency_key="key_001",
        user_id="user_001",
        mandate_id="mandate_001",
        agent_id="agent_1",
        merchant_id="m_croma",
        merchant_category="electronics",  # Excluded
        amount=500.0,
        timestamp=now,
        stated_intent="buy cable"
    )
    assert is_violated is True
    assert rule_name == "CATEGORY_EXCLUDED"


def test_hard_duplicate_velocity_violation(db_session):
    user, mandate, now = setup_base_data(db_session)

    # Seed an existing recent transaction at now - 2 seconds
    past_txn = Transaction(
        transaction_id="txn_past",
        idempotency_key="key_past",
        user_id="user_001",
        mandate_id="mandate_001",
        agent_id="agent_1",
        merchant_id="m_bigbasket",
        merchant_category="grocery",
        amount=500.0,
        timestamp=now - timedelta(seconds=2),
        stated_intent="buy milk",
        state="COMPLETED"
    )
    db_session.add(past_txn)
    db_session.commit()

    # Now evaluate duplicate transaction within 5 seconds
    is_violated, rule_name, reason = HardRuleEngine.evaluate(
        db=db_session,
        transaction_id="txn_new",
        idempotency_key="key_new",
        user_id="user_001",
        mandate_id="mandate_001",
        agent_id="agent_1",
        merchant_id="m_bigbasket",
        merchant_category="grocery",
        amount=500.0,  # Same amount, same merchant within 5 sec
        timestamp=now,
        stated_intent="buy milk again"
    )
    assert is_violated is True
    assert rule_name == "HARD_DUPLICATE_VIOLATION"


def test_legitimate_transaction_passes(db_session):
    user, mandate, now = setup_base_data(db_session)

    is_violated, rule_name, reason = HardRuleEngine.evaluate(
        db=db_session,
        transaction_id="txn_001",
        idempotency_key="key_001",
        user_id="user_001",
        mandate_id="mandate_001",
        agent_id="agent_1",
        merchant_id="m_bigbasket",
        merchant_category="grocery",
        amount=850.0,
        timestamp=now,
        stated_intent="weekly family groceries"
    )
    assert is_violated is False
    assert rule_name is None
    assert reason is None
