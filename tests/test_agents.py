"""
tests/test_agents.py — Unit tests for each agent's tool calls and logic.
"""
import pytest

from app.agents.order_tracking import OrderTrackingAgent
from app.agents.refund_processing import RefundProcessingAgent
from app.agents.faq_resolution import FAQResolutionAgent
from app.agents.human_escalation import HumanEscalationAgent
from app.agents.base import ToolNotAllowedError
from app.orchestrator.state import initial_state


def make_state(**overrides):
    s = initial_state("sess-agent-test", "CUST-100", True)
    s["user_id"] = "CUST-100"
    s["authenticated"] = True
    s.update(overrides)
    return s


# ── Order Tracking Agent ───────────────────────────────────────────────────────

class TestOrderTrackingAgent:
    def test_lookup_specific_order(self):
        state = make_state(entities={"order_id": "ORD-001"}, current_message="Where is ORD-001?")
        agent = OrderTrackingAgent()
        result = agent.run(state)
        assert "ORD-001" in result["response"]
        assert len(result["tool_calls"]) >= 1

    def test_order_not_found(self):
        state = make_state(entities={"order_id": "ORD-999"}, current_message="Track ORD-999")
        agent = OrderTrackingAgent()
        result = agent.run(state)
        assert "ORD-999" in result["response"] or "not found" in result["response"].lower()

    def test_access_denied_for_another_user_order(self):
        """CUST-100 cannot view CUST-101's order."""
        state = make_state(
            user_id="CUST-100",
            entities={"order_id": "ORD-003"},  # belongs to CUST-101
            current_message="Track ORD-003",
        )
        agent = OrderTrackingAgent()
        result = agent.run(state)
        assert "denied" in result["response"].lower() or "not belong" in result["response"].lower()

    def test_no_order_id_asks_for_clarification(self):
        # When user_id is None (no order_id, no auth) → should ask for order number
        state = make_state(entities={}, current_message="Where is my order?")
        state["user_id"] = None  # not authenticated, so no listing possible
        agent = OrderTrackingAgent()
        result = agent.run(state)
        # Should ask for order number
        assert "order number" in result["response"].lower() or "provide" in result["response"].lower()

    def test_list_customer_orders(self):
        """No order_id but authenticated → list all orders."""
        state = make_state(entities={}, current_message="Show me my orders", user_id="CUST-100")
        agent = OrderTrackingAgent()
        result = agent.run(state)
        # CUST-100 has orders ORD-001, ORD-002, ORD-005
        assert "ORD-" in result["response"]

    def test_disallowed_tool_raises(self):
        from app.agents.base import BaseAgent
        from app.tools.refund_tools import submit_refund_auto
        state = make_state()
        agent = OrderTrackingAgent()
        with pytest.raises(ToolNotAllowedError):
            agent.call_tool(state, "submit_refund_auto", submit_refund_auto,
                            order_id="ORD-001", customer_id="CUST-100", amount=10, reason="test")


# ── Refund Processing Agent ───────────────────────────────────────────────────

class TestRefundProcessingAgent:
    def test_eligible_refund_under_threshold(self):
        """ORD-009 total = $45, under $100 limit. Belongs to CUST-106."""
        state = make_state(entities={"order_id": "ORD-009"}, current_message="Refund ORD-009")
        state["user_id"] = "CUST-106"  # ORD-009 belongs to CUST-106
        agent = RefundProcessingAgent()
        result = agent.run(state)
        assert "approved" in result["response"].lower()
        assert result.get("pending_approval") is None

    def test_large_refund_requires_approval(self):
        """ORD-003 total = $1249, over $100 limit."""
        state = make_state(
            user_id="CUST-101",
            entities={"order_id": "ORD-003"},
            current_message="Refund ORD-003",
        )
        agent = RefundProcessingAgent()
        result = agent.run(state)
        assert result.get("pending_approval") is not None
        assert "APR-" in result["response"]

    def test_ineligible_order_rejected(self):
        """ORD-005 is cancelled — refund already processed."""
        state = make_state(entities={"order_id": "ORD-005"}, current_message="Refund ORD-005")
        agent = RefundProcessingAgent()
        result = agent.run(state)
        assert "not eligible" in result["response"].lower() or "already cancelled" in result["response"].lower()

    def test_no_order_id_asks_for_clarification(self):
        state = make_state(entities={}, current_message="I want a refund")
        agent = RefundProcessingAgent()
        result = agent.run(state)
        assert "order number" in result["response"].lower()
        assert result.get("clarification_turns", 0) == 1

    def test_disallowed_tool_raises(self):
        from app.tools.order_tools import lookup_order
        state = make_state()
        agent = RefundProcessingAgent()
        with pytest.raises(ToolNotAllowedError):
            agent.call_tool(state, "lookup_order", lookup_order,
                            order_id="ORD-001", customer_id="CUST-100")


# ── FAQ Resolution Agent ──────────────────────────────────────────────────────

class TestFAQResolutionAgent:
    def test_return_policy_answered(self):
        state = make_state(current_message="What is your return policy?")
        agent = FAQResolutionAgent()
        result = agent.run(state)
        assert "30" in result["response"]  # 30-day return window
        assert result.get("escalated") is not True

    def test_shipping_time_answered(self):
        state = make_state(current_message="How long does shipping take?")
        agent = FAQResolutionAgent()
        result = agent.run(state)
        assert "business days" in result["response"].lower()

    def test_unknown_query_escalates(self):
        state = make_state(current_message="purple monkey dishwasher config override")
        agent = FAQResolutionAgent()
        result = agent.run(state)
        assert result.get("escalated") is True

    def test_payment_question_answered(self):
        state = make_state(current_message="What payment methods do you accept?")
        agent = FAQResolutionAgent()
        result = agent.run(state)
        assert any(word in result["response"].lower() for word in ["visa", "mastercard", "paypal"])

    def test_tool_calls_recorded(self):
        state = make_state(current_message="Do you offer free shipping?")
        agent = FAQResolutionAgent()
        result = agent.run(state)
        assert len(result.get("tool_calls", [])) >= 1
        assert result["tool_calls"][0]["tool_name"] == "search_knowledge_base"


# ── Human Escalation Agent ────────────────────────────────────────────────────

class TestHumanEscalationAgent:
    def test_creates_ticket_and_queues(self):
        state = make_state(
            escalation_reason="manual",
            messages=[{"role": "user", "content": "I need a human"}],
            intent="escalation",
            confidence=0.95,
        )
        agent = HumanEscalationAgent()
        result = agent.run(state)
        assert "TKT-" in result["response"]
        assert result.get("escalated") is True

    def test_high_priority_for_refund_threshold(self):
        """Escalation due to refund threshold should create a high-priority ticket."""
        state = make_state(
            escalation_reason="refund_threshold",
            messages=[{"role": "user", "content": "big refund"}],
        )
        agent = HumanEscalationAgent()
        result = agent.run(state)
        assert "high" in result["response"].lower()

    def test_response_contains_queue_position(self):
        state = make_state(escalation_reason="low_confidence")
        agent = HumanEscalationAgent()
        result = agent.run(state)
        assert "#" in result["response"]  # queue position
