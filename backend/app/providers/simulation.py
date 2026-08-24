import uuid
from datetime import datetime, timezone
from typing import Dict, Any


class PaymentProviderInterface:
    def execute(self, transaction_id: str, amount: float, currency: str, merchant_id: str) -> Dict[str, Any]:
        raise NotImplementedError


class SimulationProvider(PaymentProviderInterface):
    """
    Default simulation payment provider.
    Instantly returns mocked payment execution success/failure.
    """

    def execute(self, transaction_id: str, amount: float, currency: str, merchant_id: str) -> Dict[str, Any]:
        ref_id = f"sim_pay_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        
        # Simple rule: amounts <= 0 or invalid amounts fail
        if amount <= 0:
            return {
                "status": "FAILED",
                "provider_reference": ref_id,
                "executed_at": now,
                "failure_reason": "Invalid payment amount"
            }

        return {
            "status": "SUCCESS",
            "provider_reference": ref_id,
            "executed_at": now
        }


class RazorpayTestProvider(PaymentProviderInterface):
    """
    Stub adapter for Razorpay Test Mode API integration.
    """

    def execute(self, transaction_id: str, amount: float, currency: str, merchant_id: str) -> Dict[str, Any]:
        ref_id = f"rzp_test_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        return {
            "status": "SUCCESS",
            "provider_reference": ref_id,
            "executed_at": now,
            "mode": "RAZORPAY_TEST_STUB"
        }
