import pytest
from app.services.intent_service import IntentExtractionService


def test_heuristic_intent_extraction_grocery():
    raw_prompt = "Buy groceries for my family every week, up to 3000"
    intent = IntentExtractionService.extract_intent(raw_prompt, total_limit=12000.0)

    assert intent["purpose"] == raw_prompt
    assert "grocery" in intent["allowed_categories"]
    assert intent["expected_frequency"] == "weekly"
    assert len(intent["expected_amount_range"]) == 2
    assert intent["expected_amount_range"][1] <= 12000.0


def test_heuristic_intent_extraction_food():
    raw_prompt = "Order food from Swiggy on weekends up to 1000"
    intent = IntentExtractionService.extract_intent(raw_prompt, total_limit=5000.0)

    assert "food_delivery" in intent["allowed_categories"]
    assert intent["expected_frequency"] in ["weekly", "monthly"]
