import os
import pytest
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.database import Base, get_db
from app.main import app
from app.models.models import (
    User, Mandate, IntentProfile, BehaviourProfile, Transaction,
    TransactionDecision, StepUpRequest, AuditLog
)

TEST_DB_FILE = "./test_div_database.db"
TEST_DATABASE_URL = f"sqlite:///{TEST_DB_FILE}"

test_engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(autouse=True)
def setup_db():
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=test_engine)
        if os.path.exists(TEST_DB_FILE):
            try:
                os.remove(TEST_DB_FILE)
            except Exception:
                pass



client = TestClient(app)


def test_root_endpoint():
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ONLINE"


def test_create_and_get_mandate():
    payload = {
        "user_id": "user_api_01",
        "raw_text": "Weekly grocery budget up to ₹3,000",
        "total_limit": 12000.0,
        "allowed_categories": ["grocery"],
        "excluded_categories": ["electronics"],
        "per_transaction_limit": 3000.0
    }
    resp = client.post("/mandates", json=payload)
    assert resp.status_code == 201
    data = resp.json()
    assert data["user_id"] == "user_api_01"
    assert data["total_limit"] == 12000.0
    assert data["intent_profile"] is not None
    assert "grocery" in data["intent_profile"]["allowed_categories"]

    mandate_id = data["mandate_id"]
    get_resp = client.get(f"/mandates/{mandate_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["mandate_id"] == mandate_id


def test_transaction_evaluate_and_step_up_flow():
    # 1. Create mandate
    m_resp = client.post("/mandates", json={
        "user_id": "user_api_02",
        "raw_text": "Weekly grocery shopping up to ₹3,000",
        "total_limit": 10000.0,
        "allowed_categories": ["grocery"],
        "excluded_categories": ["electronics"],
        "per_transaction_limit": 3000.0
    })
    mandate_id = m_resp.json()["mandate_id"]

    # 2. Evaluate high-amount transaction that triggers STEP_UP
    eval_payload = {
        "idempotency_key": "idemp_api_001",
        "user_id": "user_api_02",
        "mandate_id": mandate_id,
        "agent_id": "agent_api_1",
        "merchant_id": "merchant_unknown",
        "merchant_category": "grocery",
        "amount": 2850.0,
        "currency": "INR",
        "stated_intent": "bulk pantry stock-up"
    }
    eval_resp = client.post("/transactions/evaluate", json=eval_payload)
    assert eval_resp.status_code == 200
    eval_data = eval_resp.json()
    assert eval_data["final_decision"] == "STEP_UP"
    assert eval_data["state"] == "STEP_UP_REQUIRED"
    assert eval_data["step_up_id"] is not None

    txn_id = eval_data["transaction_id"]

    # 3. Fetch audit trail
    audit_resp = client.get(f"/audit/{txn_id}")
    assert audit_resp.status_code == 200
    assert len(audit_resp.json()) >= 1

    # 4. User approves step-up
    approve_resp = client.post(f"/transactions/{txn_id}/approve", json={"user_id": "user_api_02"})
    assert approve_resp.status_code == 200
    assert approve_resp.json()["resolution"] == "APPROVED"

    # 5. Verify transaction state updated to COMPLETED
    get_txn_resp = client.get(f"/transactions/{txn_id}")
    assert get_txn_resp.status_code == 200
    assert get_txn_resp.json()["state"] == "COMPLETED"


def test_simulation_run_returns_dynamic_metrics():
    resp = client.post("/simulation/run")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_evaluated"] >= 6
    assert data["div_metrics"]["unsafe_action_rate"] == 0.0
    assert data["baseline_1_metrics"]["unsafe_action_rate"] > 0.0
    assert data["baseline_2_metrics"]["unsafe_action_rate"] > 0.0
