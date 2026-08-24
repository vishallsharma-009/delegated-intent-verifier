import pytest
from datetime import datetime, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.database import Base
from app.services.red_team_service import RedTeamSimulator
from app.services.synthetic_dataset import SyntheticDatasetGenerator

TEST_DATABASE_URL = "sqlite:///:memory:"

@pytest.fixture
def db_session():
    engine = create_engine(TEST_DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    try:
        SyntheticDatasetGenerator.seed_synthetic_data(db)
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_red_team_attack_execution(db_session):
    summary = RedTeamSimulator.run_red_team_attacks(db_session)

    assert summary.attacks_run == 6
    assert summary.blocked >= 3
    assert summary.unsafe_actions == 0
    assert summary.disclaimer is not None

    # Check attack results structure
    attack_names = [res.attack_name for res in summary.results]
    assert "Duplicate Payment Attack" in attack_names
    assert "Mandate Limit Attack" in attack_names
    assert "Category Switching Attack" in attack_names
    assert "Malformed Agent Request" in attack_names

    for r in summary.results:
        assert r.decision in ("BLOCK", "STEP_UP", "APPROVE", "REJECTED")
        if r.decision == "BLOCK":
            assert r.hard_rule_triggered is not None or r.intent_fit_score < 45.0
