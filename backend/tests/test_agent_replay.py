import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.database import Base
from app.services.agent_replay_service import AgentReplayService
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


def test_agent_replay_summary(db_session):
    replay = AgentReplayService.get_agent_replay(db_session, agent_id="agent_001")

    assert replay.agent_id == "agent_001"
    assert replay.total_transactions > 0
    assert replay.behaviour_consistency in ("HIGH", "MODERATE", "LOW")
    assert len(replay.timeline) == replay.total_transactions

    for item in replay.timeline:
        assert "transaction_id" in item
        assert "stated_intent" in item
        assert "decision" in item
        assert "intent_fit_score" in item
