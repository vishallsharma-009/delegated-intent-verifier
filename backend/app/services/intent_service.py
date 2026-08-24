import os
import json
import logging
from typing import Dict, Any, Optional
from datetime import datetime, timezone
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)


SYSTEM_INTENT_PROMPT = """
You are extracting structured spending intent for a payment verification engine.
Given the user's natural language mandate prompt, extract a JSON object with EXACTLY the following keys:
- purpose: string (short description of intended spending)
- allowed_categories: list of lowercase category strings (e.g. ["grocery"])
- excluded_categories: list of lowercase category strings
- expected_amount_range: list of 2 numbers [min_amount, max_amount]
- expected_frequency: string (e.g. "weekly", "daily", "monthly", "one-time")
- expected_transactions_per_period: integer
- typical_merchant_types: list of merchant type strings
- time_pattern: string (e.g. "any day", "weekdays", "mornings")
- duration: string (e.g. "30_days", "7_days")
- notes: string

Return ONLY a single valid JSON object. Do not include markdown code block syntax if possible, or wrap in standard ```json ... ```.
Do not invent numeric limits that loosen explicit mandate parameters.
"""


class IntentExtractionService:
    """
    LLM-powered intent extraction from natural language mandates.
    Includes robust fallback if LLM API keys are not provided.
    """

    @staticmethod
    def extract_intent(raw_text: str, total_limit: float, allowed_cats: Optional[list] = None) -> Dict[str, Any]:
        api_key = os.getenv("OPENAI_API_KEY") or os.getenv("GEMINI_API_KEY")
        
        if api_key:
            try:
                if os.getenv("OPENAI_API_KEY"):
                    extracted = IntentExtractionService._call_openai(raw_text, api_key)
                    if extracted:
                        return IntentExtractionService._sanitize_intent(extracted, total_limit, allowed_cats)
                elif os.getenv("GEMINI_API_KEY"):
                    extracted = IntentExtractionService._call_gemini(raw_text, api_key)
                    if extracted:
                        return IntentExtractionService._sanitize_intent(extracted, total_limit, allowed_cats)
            except Exception as e:
                logger.warning(f"LLM extraction failed, using heuristic fallback: {e}")

        # Rule-based / heuristic extraction fallback
        return IntentExtractionService._heuristic_extract(raw_text, total_limit, allowed_cats)

    @staticmethod
    def _call_openai(raw_text: str, api_key: str) -> Optional[Dict[str, Any]]:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        body = {
            "model": "gpt-4o-mini",
            "messages": [
                {"role": "system", "content": SYSTEM_INTENT_PROMPT},
                {"role": "user", "content": raw_text}
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.1
        }
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            return json.loads(content)

    @staticmethod
    def _call_gemini(raw_text: str, api_key: str) -> Optional[Dict[str, Any]]:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
        headers = {"Content-Type": "application/json"}
        body = {
            "contents": [{
                "parts": [{"text": f"{SYSTEM_INTENT_PROMPT}\n\nUser Mandate: {raw_text}"}]
            }],
            "generationConfig": {
                "response_mime_type": "application/json"
            }
        }
        req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            content = data["candidates"][0]["content"]["parts"][0]["text"]
            return json.loads(content)

    @staticmethod
    def _heuristic_extract(raw_text: str, total_limit: float, allowed_cats: Optional[list] = None) -> Dict[str, Any]:
        text_lower = raw_text.lower()
        
        # Purpose
        purpose = raw_text.strip()

        # Category parsing
        categories = allowed_cats or []
        if not categories:
            if "grocery" in text_lower or "groceries" in text_lower:
                categories = ["grocery"]
            elif "food" in text_lower or "swiggy" in text_lower or "zomato" in text_lower:
                categories = ["food_delivery"]
            elif "travel" in text_lower or "cab" in text_lower or "uber" in text_lower:
                categories = ["travel"]
            else:
                categories = ["general"]

        # Expected frequency & amount estimation
        if "week" in text_lower:
            freq = "weekly"
            expected_txs = 1
            min_amt = max(100.0, total_limit * 0.1)
            max_amt = min(total_limit, total_limit * 0.4)
        elif "day" in text_lower or "daily" in text_lower:
            freq = "daily"
            expected_txs = 7
            min_amt = 50.0
            max_amt = min(total_limit, 500.0)
        else:
            freq = "monthly"
            expected_txs = 4
            min_amt = max(100.0, total_limit * 0.05)
            max_amt = total_limit

        return {
            "purpose": purpose,
            "allowed_categories": categories,
            "excluded_categories": ["gambling", "luxury", "electronics"] if "grocery" in categories else [],
            "expected_amount_range": [round(min_amt, 2), round(max_amt, 2)],
            "expected_frequency": freq,
            "expected_transactions_per_period": expected_txs,
            "typical_merchant_types": [f"online {c}" for c in categories],
            "time_pattern": "any day, typical business hours",
            "duration": "30_days",
            "notes": "Extracted from mandate"
        }

    @staticmethod
    def _sanitize_intent(extracted: Dict[str, Any], total_limit: float, allowed_cats: Optional[list]) -> Dict[str, Any]:
        # Ensure correct types and fallback bounds
        purpose = str(extracted.get("purpose", "general spending mandate"))
        cats = extracted.get("allowed_categories", allowed_cats or ["general"])
        if not isinstance(cats, list):
            cats = [str(cats)]

        amt_range = extracted.get("expected_amount_range", [100.0, total_limit])
        if not isinstance(amt_range, list) or len(amt_range) < 2:
            amt_range = [50.0, total_limit]
        
        return {
            "purpose": purpose,
            "allowed_categories": cats,
            "excluded_categories": extracted.get("excluded_categories", []),
            "expected_amount_range": [float(amt_range[0]), float(amt_range[1])],
            "expected_frequency": str(extracted.get("expected_frequency", "weekly")),
            "expected_transactions_per_period": int(extracted.get("expected_transactions_per_period", 1)),
            "typical_merchant_types": extracted.get("typical_merchant_types", ["retail"]),
            "time_pattern": str(extracted.get("time_pattern", "any day")),
            "duration": str(extracted.get("duration", "30_days")),
            "notes": str(extracted.get("notes", ""))
        }
