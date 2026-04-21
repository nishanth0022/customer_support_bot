"""
tests/test_routing.py — Unit tests for intent classification and agent routing.

Covers all 5 intents and verifies routing produces the correct agent.
"""
import pytest

from app.orchestrator.classifier import classify
from app.orchestrator.router import route_to_agent, INTENT_TO_AGENT
from app.orchestrator.state import initial_state


# ── Classifier tests ──────────────────────────────────────────────────────────

class TestClassifier:
    def test_order_tracking_with_order_id(self):
        result = classify("Where is my order ORD-001? Has it shipped?")
        assert result.intent == "order_tracking"
        assert result.confidence >= 0.5
        assert result.entities.get("order_id") == "ORD-001"

    def test_order_tracking_generic(self):
        result = classify("What is the delivery status of my package?")
        assert result.intent == "order_tracking"

    def test_refund_intent(self):
        result = classify("I want a refund for my order ORD-002, it arrived damaged.")
        assert result.intent == "refund"
        assert result.entities.get("order_id") == "ORD-002"

    def test_refund_with_amount(self):
        result = classify("I need to return my $500 camera and get my money back.")
        assert result.intent == "refund"
        assert result.entities.get("amount") == 500.0

    def test_faq_return_policy(self):
        result = classify("What is your return policy?")
        assert result.intent == "faq"

    def test_faq_shipping_time(self):
        result = classify("How long does standard shipping take?")
        assert result.intent == "faq"

    def test_escalation_explicit(self):
        result = classify("I want to speak to a human agent right now.")
        assert result.intent == "escalation"
        assert result.confidence >= 0.9

    def test_escalation_frustrated(self):
        result = classify("This is terrible! I want a supervisor!")
        assert result.intent == "escalation"

    def test_unknown_intent_low_confidence(self):
        result = classify("ugh!!!")
        assert result.confidence < 0.6

    def test_entity_extraction_order_id(self):
        result = classify("Show me ORD-007 and ORD-008 please")
        assert result.entities.get("order_id") in ("ORD-007", "ORD-008")
        assert len(result.entities.get("all_order_ids", [])) == 2

    def test_confidence_range(self):
        for msg in [
            "track my order ORD-001",
            "refund please",
            "what is return policy",
            "speak to human",
        ]:
            result = classify(msg)
            assert 0.0 <= result.confidence <= 1.0


# ── Router tests ──────────────────────────────────────────────────────────────

class TestRouter:
    def _make_state(self, intent: str, escalated: bool = False):
        s = initial_state("sess-test", "CUST-100", True)
        s["intent"] = intent
        s["escalated"] = escalated
        return s

    def test_routes_order_tracking(self):
        state = self._make_state("order_tracking")
        assert route_to_agent(state) == "order_tracking"

    def test_routes_refund(self):
        state = self._make_state("refund")
        assert route_to_agent(state) == "refund_processing"

    def test_routes_faq(self):
        state = self._make_state("faq")
        assert route_to_agent(state) == "faq_resolution"

    def test_routes_escalation(self):
        state = self._make_state("escalation")
        assert route_to_agent(state) == "human_escalation"

    def test_routes_unknown_to_escalation(self):
        state = self._make_state("unknown")
        assert route_to_agent(state) == "human_escalation"

    def test_escalated_flag_overrides_intent(self):
        state = self._make_state("order_tracking", escalated=True)
        assert route_to_agent(state) == "human_escalation"

    def test_all_intents_covered(self):
        """Every intent in INTENT_TO_AGENT should map to a valid agent."""
        valid_agents = {"order_tracking", "refund_processing", "faq_resolution", "human_escalation"}
        for intent, agent in INTENT_TO_AGENT.items():
            assert agent in valid_agents, f"Intent '{intent}' maps to unknown agent '{agent}'"
