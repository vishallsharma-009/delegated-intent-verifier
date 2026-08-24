import pytest
from datetime import datetime, timezone, timedelta
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.database import Base
from app.models.models import User, Mandate, Transaction, BehaviourProfile, StepUpRequest, FeedbackEvent
from app.services.step_up_service import StepUpService
from app.core.state_machine import DoubleExecutionException, InvalidStateTransitionException

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


def setup_step_up_data(db):
    user = User(user_id="user_su", name="StepUp User")
    db.add(user)

    now = datetime.now(timezone.utc)
    mandate = Mandate(
        mandate_id="mandate_su",
        user_id="user_su",
        raw_text="Weekly grocery",
        total_limit=10000.0,
        remaining_limit=10000.0,
        valid_from=now - timedelta(days=1),
        valid_to=now + timedelta(days=10),
        allowed_categories=["grocery"],
        status="ACTIVE"
    )
    db.add(mandate)

    behaviour = BehaviourProfile(
        user_id="user_su",
        median_amount=500.0,
        mean_amount=500.0,
        amount_std_dev=50.0,
        common_categories=["grocery"],
        common_merchants=["m_bigbasket"],
        total_transactions=5
    )
    db.add(behaviour)
    db.commit()

    txn = Transaction(
        transaction_id="txn_stepup_101",
        idempotency_key="key_stepup_101",
        user_id="user_su",
        mandate_id="mandate_su",
        agent_id="agent_1",
        merchant_id="m_blinkit",
        merchant_category="grocery",
        amount=1500.0,
        stated_intent="groceries",
        state="STEP_UP_REQUIRED"
    )
    db.add(txn)
    db.commit()
    return user, mandate, behaviour, txn, now


def test_step_up_approval_and_execution_flow(db_session):
    user, mandate, behaviour, txn, now = setup_step_up_data(db_session)

    # 1. Create step-up request
    step_up = StepUpService.create_step_up_request(db_session, txn, expiry_minutes=5)
    assert step_up.resolution == "PENDING"

    # 2. User approves step-up
    res = StepUpService.resolve_step_up(db_session, step_up.step_up_id, user_id="user_su", action="APPROVE")

    assert res["resolution"] == "APPROVED"
    assert res["transaction_state"] == "COMPLETED"
    assert res["provider_reference"].startswith("sim_pay_")

    # Verify transaction state in DB
    refreshed_txn = db_session.query(Transaction).filter_by(transaction_id="txn_stepup_101").first()
    assert refreshed_txn.state == "COMPLETED"

    # Verify mandate budget deduction (10000 - 1500 = 8500)
    refreshed_mandate = db_session.query(Mandate).filter_by(mandate_id="mandate_su").first()
    assert refreshed_mandate.remaining_limit == 8500.0

    # Verify feedback event created
    fb = db_session.query(FeedbackEvent).filter_by(transaction_id="txn_stepup_101").first()
    assert fb is not None
    assert fb.feedback_type == "STEP_UP_APPROVED"

    # Verify behaviour profile updated
    refreshed_beh = db_session.query(BehaviourProfile).filter_by(user_id="user_su").first()
    assert refreshed_beh.step_up_approved_count == 1
    assert "m_blinkit" in refreshed_beh.common_merchants


def test_double_resolution_raises_error(db_session):
    user, mandate, behaviour, txn, now = setup_step_up_data(db_session)
    step_up = StepUpService.create_step_up_request(db_session, txn)

    # First resolution succeeds
    StepUpService.resolve_step_up(db_session, step_up.step_up_id, user_id="user_su", action="APPROVE")

    # Second resolution attempt fails with ValueError
    with pytest.raises(ValueError, match="already resolved"):
        StepUpService.resolve_step_up(db_session, step_up.step_up_id, user_id="user_su", action="APPROVE")


def test_step_up_rejection_flow(db_session):
    user, mandate, behaviour, txn, now = setup_step_up_data(db_session)
    step_up = StepUpService.create_step_up_request(db_session, txn)

    res = StepUpService.resolve_step_up(db_session, step_up.step_up_id, user_id="user_su", action="REJECT")

    assert res["resolution"] == "REJECTED"
    assert res["transaction_state"] == "CANCELLED"

    # Verify mandate remaining limit NOT deducted
    refreshed_mandate = db_session.query(Mandate).filter_by(mandate_id="mandate_su").first()
    assert refreshed_mandate.remaining_limit == 10000.0

    # Verify behaviour profile step_up_rejected_count updated
    refreshed_beh = db_session.query(BehaviourProfile).filter_by(user_id="user_su").first()
    assert refreshed_beh.step_up_rejected_count == 1
    assert refreshed_beh.declined_count == 1
