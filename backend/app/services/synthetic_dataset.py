import uuid
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any
from sqlalchemy.orm import Session
from app.models.models import (
    User, Mandate, IntentProfile, BehaviourProfile, Transaction, TransactionDecision, AuditLog, StepUpRequest, utc_now
)



class SyntheticDatasetGenerator:
    """
    Generates synthetic dataset covering the 6 user archetypes with ground-truth test cases.
    Ground-truth labels: LEGITIMATE, AMBIGUOUS, MISALIGNED, DUPLICATE, UNAUTHORIZED.
    """

    @staticmethod
    def seed_synthetic_data(db: Session) -> Dict[str, Any]:
        now = utc_now()
        now_naive = now.astimezone(timezone.utc).replace(tzinfo=None)

        # Clear existing synthetic data to ensure idempotent seeding
        db.query(AuditLog).delete()
        db.query(StepUpRequest).delete()
        db.query(TransactionDecision).delete()
        db.query(Transaction).delete()
        db.query(IntentProfile).delete()
        db.query(Mandate).delete()
        db.query(BehaviourProfile).delete()
        db.query(User).delete()
        db.commit()


        test_cases = []

        # ARCHETYPE 1: Normal User (Grocery focus, steady cadence)
        u1 = User(user_id="user_normal_01", name="Anita Sharma (Normal User)")
        db.add(u1)
        m1 = Mandate(
            mandate_id="mandate_norm_01",
            user_id="user_normal_01",
            raw_text="Weekly grocery shopping up to ₹3,000",
            total_limit=12000.0,
            remaining_limit=9500.0,
            valid_from=now_naive - timedelta(days=15),
            valid_to=now_naive + timedelta(days=15),
            allowed_categories=["grocery"],
            excluded_categories=["electronics", "gambling"],
            per_transaction_limit=3000.0,
            max_transactions_per_day=2,
            max_transactions_per_week=2,
            status="ACTIVE"
        )
        db.add(m1)
        i1 = IntentProfile(
            intent_id="intent_norm_01",
            mandate_id="mandate_norm_01",
            purpose="weekly family grocery runs",
            allowed_categories=["grocery"],
            excluded_categories=["electronics", "gambling"],
            expected_amount_range=[500.0, 2500.0],
            expected_frequency="weekly",
            expected_transactions_per_period=1,
            typical_merchant_types=["online grocery", "supermarket"],
            time_pattern="daytime 9am-8pm",
            duration="30_days"
        )
        db.add(i1)
        b1 = BehaviourProfile(
            user_id="user_normal_01",
            median_amount=820.0,
            mean_amount=840.0,
            amount_std_dev=180.0,
            common_categories=["grocery"],
            common_merchants=["merchant_bigbasket", "merchant_zepto"],
            avg_transactions_per_week=1.1,
            typical_hour_range=[9, 20],
            total_transactions=12
        )
        db.add(b1)

        # Test case 1.1: Legitimate weekly grocery order
        test_cases.append({
            "test_id": "tc_01_legit",
            "ground_truth": "LEGITIMATE",
            "request": {
                "transaction_id": "txn_tc_01",
                "idempotency_key": "idemp_tc_01",
                "user_id": "user_normal_01",
                "mandate_id": "mandate_norm_01",
                "agent_id": "grocery_bot_v1",
                "merchant_id": "merchant_bigbasket",
                "merchant_category": "grocery",
                "amount": 850.0,
                "currency": "INR",
                "timestamp": (now_naive - timedelta(hours=2)).isoformat(),
                "stated_intent": "weekly family grocery refill",
                "payment_method": "UPI"
            }
        })

        # ARCHETYPE 2: Diverse User (Groceries + Food Delivery)
        u2 = User(user_id="user_diverse_02", name="Rahul Verma (Diverse User)")
        db.add(u2)
        m2 = Mandate(
            mandate_id="mandate_div_02",
            user_id="user_diverse_02",
            raw_text="Food and groceries up to ₹5,000 per month",
            total_limit=15000.0,
            remaining_limit=12000.0,
            valid_from=now_naive - timedelta(days=10),
            valid_to=now_naive + timedelta(days=20),
            allowed_categories=["grocery", "food_delivery"],
            excluded_categories=["electronics"],
            per_transaction_limit=2500.0,
            status="ACTIVE"
        )
        db.add(m2)
        i2 = IntentProfile(
            intent_id="intent_div_02",
            mandate_id="mandate_div_02",
            purpose="weekly groceries and casual food delivery",
            allowed_categories=["grocery", "food_delivery"],
            excluded_categories=["electronics"],
            expected_amount_range=[200.0, 2000.0],
            expected_frequency="weekly",
            expected_transactions_per_period=2,
            typical_merchant_types=["supermarket", "restaurant"],
            time_pattern="any day",
            duration="30_days"
        )
        db.add(i2)
        b2 = BehaviourProfile(
            user_id="user_diverse_02",
            median_amount=600.0,
            mean_amount=650.0,
            amount_std_dev=250.0,
            common_categories=["grocery", "food_delivery"],
            common_merchants=["merchant_swiggy", "merchant_blinkit"],
            avg_transactions_per_week=2.5,
            typical_hour_range=[10, 22],
            total_transactions=18
        )
        db.add(b2)

        # Test case 2.1: Legitimate Swiggy food order
        test_cases.append({
            "test_id": "tc_02_legit",
            "ground_truth": "LEGITIMATE",
            "request": {
                "transaction_id": "txn_tc_02",
                "idempotency_key": "idemp_tc_02",
                "user_id": "user_diverse_02",
                "mandate_id": "mandate_div_02",
                "agent_id": "food_agent_v2",
                "merchant_id": "merchant_swiggy",
                "merchant_category": "food_delivery",
                "amount": 450.0,
                "currency": "INR",
                "timestamp": (now_naive - timedelta(hours=4)).isoformat(),
                "stated_intent": "weekend dinner order",
                "payment_method": "UPI"
            }
        })

        # ARCHETYPE 3: Unusual One-Time Purchase (Ground truth: AMBIGUOUS -> STEP-UP)
        u3 = User(user_id="user_unusual_03", name="Priya Patel (One-Time Big Buyer)")
        db.add(u3)
        m3 = Mandate(
            mandate_id="mandate_unu_03",
            user_id="user_unusual_03",
            raw_text="Groceries and household essentials up to ₹4,000",
            total_limit=12000.0,
            remaining_limit=10000.0,
            valid_from=now_naive - timedelta(days=5),
            valid_to=now_naive + timedelta(days=25),
            allowed_categories=["grocery"],
            excluded_categories=["electronics"],
            per_transaction_limit=3500.0,
            status="ACTIVE"
        )
        db.add(m3)
        i3 = IntentProfile(
            intent_id="intent_unu_03",
            mandate_id="mandate_unu_03",
            purpose="routine weekly grocery purchases",
            allowed_categories=["grocery"],
            excluded_categories=["electronics"],
            expected_amount_range=[400.0, 1500.0],
            expected_frequency="weekly",
            expected_transactions_per_period=1,
            typical_merchant_types=["supermarket"],
            time_pattern="daytime",
            duration="30_days"
        )
        db.add(i3)
        b3 = BehaviourProfile(
            user_id="user_unusual_03",
            median_amount=650.0,
            mean_amount=680.0,
            amount_std_dev=120.0,
            common_categories=["grocery"],
            common_merchants=["merchant_bigbasket"],
            total_transactions=15
        )
        db.add(b3)

        # Test case 3.1: Unusual large stock-up order (Plausible but atypical amount & new merchant) -> AMBIGUOUS (STEP_UP)
        test_cases.append({
            "test_id": "tc_03_ambiguous",
            "ground_truth": "AMBIGUOUS",
            "request": {
                "transaction_id": "txn_tc_03",
                "idempotency_key": "idemp_tc_03",
                "user_id": "user_unusual_03",
                "mandate_id": "mandate_unu_03",
                "agent_id": "shopping_bot_v1",
                "merchant_id": "merchant_nature_basket",  # New merchant
                "merchant_category": "grocery",
                "amount": 2850.0,  # High amount relative to median 650
                "currency": "INR",
                "timestamp": (now_naive - timedelta(minutes=45)).isoformat(),
                "stated_intent": "bulk pantry stock-up before trip",
                "payment_method": "UPI"
            }
        })

        # ARCHETYPE 4: Malfunctioning Agent (Ground truth: DUPLICATE -> HARD BLOCK)
        u4 = User(user_id="user_malfunc_04", name="Siddharth Roy (Malfunctioning Agent)")
        db.add(u4)
        m4 = Mandate(
            mandate_id="mandate_mal_04",
            user_id="user_malfunc_04",
            raw_text="Daily coffee and snacks up to ₹500",
            total_limit=3000.0,
            remaining_limit=2500.0,
            valid_from=now_naive - timedelta(days=2),
            valid_to=now_naive + timedelta(days=10),
            allowed_categories=["grocery", "food_delivery"],
            excluded_categories=[],
            per_transaction_limit=500.0,
            status="ACTIVE"
        )
        db.add(m4)
        i4 = IntentProfile(
            intent_id="intent_mal_04",
            mandate_id="mandate_mal_04",
            purpose="daily coffee and snack runs",
            allowed_categories=["grocery", "food_delivery"],
            excluded_categories=[],
            expected_amount_range=[50.0, 300.0],
            expected_frequency="daily",
            expected_transactions_per_period=1,
            typical_merchant_types=["cafe"],
            time_pattern="mornings",
            duration="30_days"
        )
        db.add(i4)
        b4 = BehaviourProfile(
            user_id="user_malfunc_04",
            median_amount=150.0,
            mean_amount=160.0,
            amount_std_dev=30.0,
            common_categories=["food_delivery"],
            common_merchants=["merchant_starbucks"],
            total_transactions=8
        )
        db.add(b4)

        # Seed initial transaction 2 seconds ago
        past_mal_txn = Transaction(
            transaction_id="txn_mal_prior",
            idempotency_key="idemp_mal_prior",
            user_id="user_malfunc_04",
            mandate_id="mandate_mal_04",
            agent_id="buggy_agent_v9",
            merchant_id="merchant_starbucks",
            merchant_category="food_delivery",
            amount=280.0,
            currency="INR",
            timestamp=now_naive - timedelta(seconds=2),
            stated_intent="morning coffee order",
            payment_method="UPI",
            state="COMPLETED"
        )
        db.add(past_mal_txn)

        # Test case 4.1: Buggy agent fires exact duplicate 2 seconds later -> DUPLICATE (HARD BLOCK)
        test_cases.append({
            "test_id": "tc_04_duplicate",
            "ground_truth": "DUPLICATE",
            "request": {
                "transaction_id": "txn_tc_04",
                "idempotency_key": "idemp_tc_04_fresh",
                "user_id": "user_malfunc_04",
                "mandate_id": "mandate_mal_04",
                "agent_id": "buggy_agent_v9",
                "merchant_id": "merchant_starbucks",
                "merchant_category": "food_delivery",
                "amount": 280.0,
                "currency": "INR",
                "timestamp": now_naive.isoformat(),
                "stated_intent": "morning coffee order retry",
                "payment_method": "UPI"
            }
        })

        # ARCHETYPE 5: Misaligned Agent (Ground truth: MISALIGNED -> STEP-UP or BLOCK)
        u5 = User(user_id="user_misalign_05", name="Vikram Singh (Misaligned Agent)")
        db.add(u5)
        m5 = Mandate(
            mandate_id="mandate_mis_05",
            user_id="user_misalign_05",
            raw_text="Weekly grocery up to ₹3,000",
            total_limit=12000.0,
            remaining_limit=10000.0,
            valid_from=now_naive - timedelta(days=1),
            valid_to=now_naive + timedelta(days=30),
            allowed_categories=["grocery"],
            excluded_categories=["electronics"],
            per_transaction_limit=3000.0,
            status="ACTIVE"
        )
        db.add(m5)
        i5 = IntentProfile(
            intent_id="intent_mis_05",
            mandate_id="mandate_mis_05",
            purpose="weekly family grocery order ₹500 to ₹1500",
            allowed_categories=["grocery"],
            excluded_categories=["electronics"],
            expected_amount_range=[500.0, 1500.0],
            expected_frequency="weekly",
            expected_transactions_per_period=1,
            typical_merchant_types=["online grocery"],
            time_pattern="daytime",
            duration="30_days"
        )
        db.add(i5)
        b5 = BehaviourProfile(
            user_id="user_misalign_05",
            median_amount=700.0,
            mean_amount=720.0,
            amount_std_dev=100.0,
            common_categories=["grocery"],
            common_merchants=["merchant_bigbasket"],
            total_transactions=10
        )
        db.add(b5)

        # Test case 5.1: Agent orders bulk items pushing amount to edge of limit, off expected pattern -> MISALIGNED (STEP_UP / BLOCK)
        test_cases.append({
            "test_id": "tc_05_misaligned",
            "ground_truth": "MISALIGNED",
            "request": {
                "transaction_id": "txn_tc_05",
                "idempotency_key": "idemp_tc_05",
                "user_id": "user_misalign_05",
                "mandate_id": "mandate_mis_05",
                "agent_id": "rogue_agent_v3",
                "merchant_id": "merchant_wholesale_mart",
                "merchant_category": "grocery",
                "amount": 2950.0,  # Within mandate max limit 3000, but far outside intent expected 500-1500
                "currency": "INR",
                "timestamp": (now_naive - timedelta(hours=1)).isoformat(),
                "stated_intent": "one-off wholesale bulk order",
                "payment_method": "UPI"
            }
        })

        # ARCHETYPE 6: Unauthorized Violation (Ground truth: UNAUTHORIZED -> HARD BLOCK)
        u6 = User(user_id="user_unauth_06", name="Neha Kapoor (Unauthorized Attempts)")
        db.add(u6)
        m6 = Mandate(
            mandate_id="mandate_unauth_06",
            user_id="user_unauth_06",
            raw_text="Weekly groceries up to ₹2,000",
            total_limit=8000.0,
            remaining_limit=1500.0,  # Only 1500 left
            valid_from=now_naive - timedelta(days=5),
            valid_to=now_naive + timedelta(days=25),
            allowed_categories=["grocery"],
            excluded_categories=["electronics", "gambling"],
            per_transaction_limit=2000.0,
            status="ACTIVE"
        )
        db.add(m6)
        i6 = IntentProfile(
            intent_id="intent_unauth_06",
            mandate_id="mandate_unauth_06",
            purpose="weekly groceries",
            allowed_categories=["grocery"],
            excluded_categories=["electronics"],
            expected_amount_range=[400.0, 1500.0],
            expected_frequency="weekly",
            expected_transactions_per_period=1,
            typical_merchant_types=["supermarket"],
            time_pattern="daytime",
            duration="30_days"
        )
        db.add(i6)
        b6 = BehaviourProfile(
            user_id="user_unauth_06",
            median_amount=600.0,
            mean_amount=620.0,
            amount_std_dev=100.0,
            common_categories=["grocery"],
            common_merchants=["merchant_zepto"],
            total_transactions=6
        )
        db.add(b6)

        # Test case 6.1: Excluded category (electronics purchase attempt) -> UNAUTHORIZED (HARD BLOCK)
        test_cases.append({
            "test_id": "tc_06_unauth_cat",
            "ground_truth": "UNAUTHORIZED",
            "request": {
                "transaction_id": "txn_tc_06",
                "idempotency_key": "idemp_tc_06",
                "user_id": "user_unauth_06",
                "mandate_id": "mandate_unauth_06",
                "agent_id": "hacked_agent_x",
                "merchant_id": "merchant_croma",
                "merchant_category": "electronics",  # Excluded category
                "amount": 1200.0,
                "currency": "INR",
                "timestamp": now_naive.isoformat(),
                "stated_intent": "purchase headphones",
                "payment_method": "UPI"
            }
        })

        # Test case 6.2: Amount exceeds remaining limit -> UNAUTHORIZED (HARD BLOCK)
        test_cases.append({
            "test_id": "tc_07_unauth_limit",
            "ground_truth": "UNAUTHORIZED",
            "request": {
                "transaction_id": "txn_tc_07",
                "idempotency_key": "idemp_tc_07",
                "user_id": "user_unauth_06",
                "mandate_id": "mandate_unauth_06",
                "agent_id": "greedy_agent_y",
                "merchant_id": "merchant_zepto",
                "merchant_category": "grocery",
                "amount": 2500.0,  # Exceeds remaining budget 1500 & per-tx limit 2000
                "currency": "INR",
                "timestamp": now_naive.isoformat(),
                "stated_intent": "expensive party grocery order",
                "payment_method": "UPI"
            }
        })

        db.commit()
        return {"test_cases": test_cases}
