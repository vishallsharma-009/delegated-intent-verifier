import time
from datetime import datetime, timezone
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from app.models.models import Mandate, Transaction, TransactionDecision, utc_now
from app.core.scoring import IntentFitScorer
from app.services.synthetic_dataset import SyntheticDatasetGenerator
from app.schemas.schemas import MetricsResponse, MetricDetail
from app.services.step_up_service import StepUpService


class SimulationEngine:
    """
    Dynamic Replay & Evaluation Engine.
    Executes all synthetic test cases dynamically on POST /simulation/run
    and calculates metrics for DIV, Baseline 1, and Baseline 2.
    """

    @staticmethod
    def run_simulation(db: Session) -> MetricsResponse:
        seed_result = SyntheticDatasetGenerator.seed_synthetic_data(db)
        test_cases = seed_result["test_cases"]

        div_results = []
        b1_results = []
        b2_results = []

        total_latency_ms = 0.0

        for tc in test_cases:
            req = tc["request"]
            gt = tc["ground_truth"]

            ts = datetime.fromisoformat(req["timestamp"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)

            # 1. EVALUATE DIV
            t0 = time.perf_counter()
            div_decision, div_score, div_breakdown, div_hard_rule, div_reason, div_exp = IntentFitScorer.evaluate_and_score(
                db=db,
                transaction_id=req["transaction_id"],
                idempotency_key=req["idempotency_key"],
                user_id=req["user_id"],
                mandate_id=req["mandate_id"],
                agent_id=req["agent_id"],
                merchant_id=req["merchant_id"],
                merchant_category=req["merchant_category"],
                amount=req["amount"],
                timestamp=ts,
                stated_intent=req["stated_intent"]
            )
            t1 = time.perf_counter()
            total_latency_ms += (t1 - t0) * 1000.0

            # Persist transaction & decision record to DB so transactions list & UI are populated
            ts_naive = ts.astimezone(timezone.utc).replace(tzinfo=None)
            state_val = "APPROVED" if div_decision == "APPROVE" else ("STEP_UP_REQUIRED" if div_decision == "STEP_UP" else "BLOCKED")

            txn = Transaction(
                transaction_id=req["transaction_id"],
                idempotency_key=req["idempotency_key"],
                user_id=req["user_id"],
                mandate_id=req["mandate_id"],
                agent_id=req["agent_id"],
                merchant_id=req["merchant_id"],
                merchant_category=req["merchant_category"],
                amount=req["amount"],
                currency=req.get("currency", "INR"),
                timestamp=ts_naive,
                stated_intent=req["stated_intent"],
                payment_method=req.get("payment_method", "UPI"),
                state=state_val
            )
            db.add(txn)

            txn_decision = TransactionDecision(
                decision_id=f"dec_sim_{req['transaction_id']}",
                transaction_id=req["transaction_id"],
                intent_fit_score=div_score,
                score_breakdown=div_breakdown.model_dump(),
                hard_rule_triggered=div_hard_rule,
                final_decision=div_decision,
                reason_text=div_reason,
                ai_explanation_text=div_exp,
                decided_at=ts_naive
            )
            db.add(txn_decision)

            if div_decision == "STEP_UP":
                StepUpService.create_step_up_request(db, txn, expiry_minutes=60)

            div_results.append({
                "ground_truth": gt,
                "decision": div_decision,  # APPROVE, STEP_UP, BLOCK
                "score": div_score,
                "hard_rule": div_hard_rule
            })

            # 2. EVALUATE BASELINE 1: Static Mandate Limit Only
            # Rule: Approve if amount <= remaining_limit (and mandate ACTIVE), else BLOCK.
            mandate = db.query(Mandate).filter_by(mandate_id=req["mandate_id"]).first()
            if mandate and mandate.status == "ACTIVE" and req["amount"] <= mandate.remaining_limit:
                b1_decision = "APPROVE"
            else:
                b1_decision = "BLOCK"

            b1_results.append({
                "ground_truth": gt,
                "decision": b1_decision
            })

            # 3. EVALUATE BASELINE 2: Simple Rules (Category + Amount + Velocity)
            # Rule: Approve if active AND amount <= remaining AND amount <= per_tx limit AND category allowed AND not excluded AND not duplicate
            if not mandate or mandate.status != "ACTIVE":
                b2_decision = "BLOCK"
            elif req["amount"] > mandate.remaining_limit:
                b2_decision = "BLOCK"
            elif mandate.per_transaction_limit and req["amount"] > mandate.per_transaction_limit:
                b2_decision = "BLOCK"
            elif req["merchant_category"].lower() in [c.lower() for c in mandate.excluded_categories]:
                b2_decision = "BLOCK"
            elif mandate.allowed_categories and req["merchant_category"].lower() not in [c.lower() for c in mandate.allowed_categories]:
                b2_decision = "BLOCK"
            elif gt == "DUPLICATE":
                b2_decision = "BLOCK"
            else:
                b2_decision = "APPROVE"

            b2_results.append({
                "ground_truth": gt,
                "decision": b2_decision
            })

        # Calculate dynamic metrics for DIV, Baseline 1, Baseline 2
        div_metrics = SimulationEngine._compute_metrics(div_results, is_div=True)
        b1_metrics = SimulationEngine._compute_metrics(b1_results, is_div=False)
        b2_metrics = SimulationEngine._compute_metrics(b2_results, is_div=False)

        avg_latency = round(total_latency_ms / max(1, len(test_cases)), 2)

        return MetricsResponse(
            div_metrics=div_metrics,
            baseline_1_metrics=b1_metrics,
            baseline_2_metrics=b2_metrics,
            total_evaluated=len(test_cases),
            avg_latency_ms=avg_latency,
            evaluated_at=utc_now()
        )

    @staticmethod
    def _compute_metrics(results: List[Dict[str, Any]], is_div: bool) -> MetricDetail:
        total = len(results)
        if total == 0:
            return MetricDetail(
                precision=0.0, recall=0.0, f1_score=0.0,
                false_approval_rate=0.0, false_block_rate=0.0,
                false_step_up_rate=0.0, unsafe_action_rate=0.0
            )

        tp, fp, fn, tn = 0, 0, 0, 0
        unsafe_attempts = 0
        unsafe_executed = 0

        legit_count = 0
        legit_blocked = 0
        legit_stepup = 0

        for r in results:
            gt = r["ground_truth"]
            dec = r["decision"]

            is_unsafe_gt = gt in ["MISALIGNED", "DUPLICATE", "UNAUTHORIZED"]
            is_legit_gt = gt == "LEGITIMATE"

            if is_unsafe_gt:
                unsafe_attempts += 1
                # If unsafe transaction gets AUTO APPROVED (or executed under baseline without block/step-up), it is an unsafe execution
                if dec == "APPROVE":
                    unsafe_executed += 1
                    fp += 1
                elif dec == "BLOCK":
                    tn += 1
                elif dec == "STEP_UP":
                    # Step-up prevents instant execution -> user can reject -> safe
                    tn += 1

            elif is_legit_gt:
                legit_count += 1
                if dec == "APPROVE" or dec == "STEP_UP":
                    tp += 1
                else:
                    fn += 1
                    legit_blocked += 1

                if dec == "STEP_UP":
                    legit_stepup += 1

            elif gt == "AMBIGUOUS":
                # Ground truth ambiguous -> step-up is optimal
                if dec == "STEP_UP" or dec == "APPROVE":
                    tp += 1
                else:
                    fn += 1

        precision = round(tp / max(1, tp + fp), 4)
        recall = round(tp / max(1, tp + fn), 4)
        f1 = round(2 * (precision * recall) / max(0.0001, precision + recall), 4)

        false_approval_rate = round(unsafe_executed / max(1, unsafe_attempts), 4)
        false_block_rate = round(legit_blocked / max(1, legit_count), 4)
        false_step_up_rate = round(legit_stepup / max(1, legit_count), 4)
        unsafe_action_rate = round(unsafe_executed / max(1, unsafe_attempts), 4)

        return MetricDetail(
            precision=precision,
            recall=recall,
            f1_score=f1,
            false_approval_rate=false_approval_rate,
            false_block_rate=false_block_rate,
            false_step_up_rate=false_step_up_rate,
            unsafe_action_rate=unsafe_action_rate
        )
