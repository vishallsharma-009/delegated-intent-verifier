import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.database import Base
from app.models.models import User, Mandate, Transaction
from app.core.state_machine import (
    TransactionStateMachine, InvalidStateTransitionException, DoubleExecutionException
)

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


def create_sample_transaction(db, initial_state="RECEIVED"):
    user = User(user_id="user_sm", name="State Machine User")
    db.add(user)
    mandate = Mandate(
        mandate_id="mandate_sm",
        user_id="user_sm",
        raw_text="Test mandate",
        total_limit=10000.0,
        remaining_limit=10000.0,
        valid_from=datetime.now(timezone.utc),
        valid_to=datetime.now(timezone.utc) + timedelta(days=5),
        allowed_categories=["grocery"],
        status="ACTIVE"
    )
    db.add(mandate)
    db.commit()

    txn = Transaction(
        transaction_id="txn_sm_1",
        idempotency_key="key_sm_1",
        user_id="user_sm",
        mandate_id="mandate_sm",
        agent_id="agent_1",
        merchant_id="m_1",
        merchant_category="grocery",
        amount=200.0,
        stated_intent="test intent",
        state=initial_state
    )
    db.add(txn)
    db.commit()
    return txn


def test_valid_step_up_execution_flow(db_session):
    txn = create_sample_transaction(db_session, initial_state="RECEIVED")

    # 1. RECEIVED -> EVALUATING
    TransactionStateMachine.transition(db_session, txn, "EVALUATING")
    assert txn.state == "EVALUATING"

    # 2. EVALUATING -> STEP_UP_REQUIRED
    TransactionStateMachine.transition(db_session, txn, "STEP_UP_REQUIRED")
    assert txn.state == "STEP_UP_REQUIRED"

    # Verify execution is NOT allowed when STEP_UP_REQUIRED
    assert TransactionStateMachine.can_execute_payment(txn) is False

    # 3. STEP_UP_REQUIRED -> USER_APPROVED
    TransactionStateMachine.transition(db_session, txn, "USER_APPROVED")
    assert txn.state == "USER_APPROVED"

    # Verify execution IS allowed when USER_APPROVED
    assert TransactionStateMachine.can_execute_payment(txn) is True

    # 4. USER_APPROVED -> EXECUTING
    TransactionStateMachine.prepare_for_execution(db_session, txn)
    assert txn.state == "EXECUTING"

    # 5. EXECUTING -> COMPLETED
    TransactionStateMachine.transition(db_session, txn, "COMPLETED")
    assert txn.state == "COMPLETED"


def test_invalid_direct_execution_attempt(db_session):
    txn = create_sample_transaction(db_session, initial_state="RECEIVED")

    # Attempting RECEIVED -> EXECUTING directly must fail
    with pytest.raises(InvalidStateTransitionException):
        TransactionStateMachine.prepare_for_execution(db_session, txn)


def test_execution_blocked_states(db_session):
    txn = create_sample_transaction(db_session, initial_state="RECEIVED")
    TransactionStateMachine.transition(db_session, txn, "EVALUATING")
    TransactionStateMachine.transition(db_session, txn, "BLOCKED")

    assert TransactionStateMachine.can_execute_payment(txn) is False
    with pytest.raises(InvalidStateTransitionException):
        TransactionStateMachine.prepare_for_execution(db_session, txn)


def test_double_execution_prevention(db_session):
    txn = create_sample_transaction(db_session, initial_state="RECEIVED")
    TransactionStateMachine.transition(db_session, txn, "EVALUATING")
    TransactionStateMachine.transition(db_session, txn, "APPROVED")

    # First execution attempt succeeds
    TransactionStateMachine.prepare_for_execution(db_session, txn)
    assert txn.state == "EXECUTING"

    # Second execution attempt must raise DoubleExecutionException
    with pytest.raises(DoubleExecutionException):
        TransactionStateMachine.prepare_for_execution(db_session, txn)
