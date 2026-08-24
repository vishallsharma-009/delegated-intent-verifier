import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.database import Base
from app.services.synthetic_dataset import SyntheticDatasetGenerator
from app.services.simulation_engine import SimulationEngine

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


def test_synthetic_dataset_seeding(db_session):
    res = SyntheticDatasetGenerator.seed_synthetic_data(db_session)
    assert "test_cases" in res
    assert len(res["test_cases"]) >= 6

    # Verify ground-truth coverage
    labels = {tc["ground_truth"] for tc in res["test_cases"]}
    assert "LEGITIMATE" in labels
    assert "AMBIGUOUS" in labels
    assert "DUPLICATE" in labels
    assert "MISALIGNED" in labels
    assert "UNAUTHORIZED" in labels


def test_dynamic_simulation_execution(db_session):
    metrics = SimulationEngine.run_simulation(db_session)

    assert metrics.total_evaluated >= 6
    assert metrics.avg_latency_ms >= 0.0

    # DIV Safety Guarantee: Unsafe Action Rate MUST be 0.0
    assert metrics.div_metrics.unsafe_action_rate == 0.0
    assert metrics.div_metrics.false_approval_rate == 0.0

    # Baseline 1 (Static Limit Only) allows misaligned/unauthorized transactions within budget limit
    assert metrics.baseline_1_metrics.unsafe_action_rate > 0.0

    # Baseline 2 (Simple Rules) allows misaligned transactions that fit inside hard category/amount caps
    assert metrics.baseline_2_metrics.unsafe_action_rate > 0.0

    # Confirm metrics are dynamically computed values
    assert isinstance(metrics.div_metrics.precision, float)
    assert isinstance(metrics.baseline_1_metrics.f1_score, float)
