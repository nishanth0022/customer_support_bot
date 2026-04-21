"""
tests/test_escalation.py — Unit tests for all escalation paths.

Covers:
  1. Low confidence → escalation
  2. Max retry count → escalation
  3. Refund above threshold → escalation + pending approval
  4. FAQ no answer → escalation
  5. Session loop → escalation
  6. Manual escalation request
  7. Clarification exceeded → escalation
"""
import pytest

from app.orchestrator.classifier import classify
from app.orchestrator.state import initial_state
from app.guardrails import (
    check_low_confidence,
    check_max_retry_count,
    check_max_clarification_turns,
    check_refund_amount_limit,
    check_loop_detection,
)
from app.config import settings
from app.agents.human_escalation import HumanEscalationAgent
from app.agents.refund_processing import RefundProcessingAgent
from app.agents.faq_resolution import FAQResolutionAgent


def make_state(**overrides):
    s = initial_state("sess-esc-test", "CUST-100", True)
    s.update(overrides)
    return s


class TestEscalationPaths:

    # ── 1. Low confidence ─────────────────────────────────────────────────
    def test_low_confidence_triggers_escalation_guardrail(self):
        state = make_state(confidence=0.2, intent="unknown")
        result = check_low_confidence(state)
        assert not result.passed
        assert result.action == "escalate"

    def test_vague_message_produces_low_confidence(self):
        result = classify("ugh!!!")
        assert result.confidence < settings.low_confidence_threshold

    # ── 2. Max retry exceeded ──────────────────────────────────────────────
    def test_max_retry_triggers_escalation_guardrail(self):
        state = make_state(retry_count=settings.max_retry_count)
        result = check_max_retry_count(state)
        assert not result.passed
        assert result.action == "escalate"
        assert "escalating" in result.message.lower()

    # ── 3. Refund above threshold ──────────────────────────────────────────
    def test_large_refund_triggers_approval_guardrail(self):
        state = make_state(intent="refund")
        amount = settings.refund_auto_approve_limit + 1.0
        result = check_refund_amount_limit(state, amount)
        assert not result.passed
        assert result.action == "escalate"

    def test_refund_agent_creates_pending_approval_for_large_order(self):
        """ORD-003 has total $1249, well above threshold."""
        state = make_state(
            user_id="CUST-101",
            intent="refund",
            entities={"order_id": "ORD-003"},
            current_message="I want a refund for ORD-003",
        )
        agent = RefundProcessingAgent()
        result = agent.run(state)
        # Should return pending_approval, not a refund_id
        assert result.get("pending_approval") is not None
        assert "human approval" in result["response"].lower() or "approval" in result["response"].lower()

    def test_refund_agent_auto_approve_small_order(self):
        """ORD-009 has total $45, below threshold."""
        state = make_state(
            user_id="CUST-106",
            intent="refund",
            entities={"order_id": "ORD-009"},
            current_message="I want a refund for ORD-009",
        )
        agent = RefundProcessingAgent()
        result = agent.run(state)
        # Should have approved automatically
        assert "approved" in result["response"].lower()
        assert result.get("pending_approval") is None

    # ── 4. FAQ no answer ───────────────────────────────────────────────────
    def test_faq_agent_escalates_when_no_kb_match(self):
        state = make_state(
            intent="faq",
            current_message="xyzzy mumbo jumbo undefined query",
        )
        agent = FAQResolutionAgent()
        result = agent.run(state)
        # Should escalate
        assert result.get("escalated") is True

    def test_faq_agent_answers_known_policy(self):
        state = make_state(
            intent="faq",
            current_message="What is your return policy?",
        )
        agent = FAQResolutionAgent()
        result = agent.run(state)
        assert result.get("escalated") is not True
        assert "30" in result["response"]  # 30 days in the answer

    # ── 5. Loop detection ──────────────────────────────────────────────────
    def test_loop_detection_triggers_escalation(self):
        window = settings.max_loop_detection_window
        state = make_state(intent_history=["order_tracking"] * window)
        result = check_loop_detection(state)
        assert not result.passed
        assert result.action == "escalate"

    # ── 6. Manual escalation ───────────────────────────────────────────────
    def test_manual_escalation_intent(self):
        result = classify("I want to talk to a real human agent please")
        assert result.intent == "escalation"

    def test_escalation_agent_creates_ticket(self):
        state = make_state(
            intent="escalation",
            escalation_reason="manual",
            messages=[
                {"role": "user", "content": "speak to a human"},
                {"role": "assistant", "content": "Escalating..."},
            ],
        )
        agent = HumanEscalationAgent()
        result = agent.run(state)
        assert "TKT-" in result["response"]
        assert result.get("escalated") is True

    # ── 7. Clarification exceeded ──────────────────────────────────────────
    def test_clarification_limit_triggers_escalation(self):
        state = make_state(clarification_turns=settings.max_clarification_turns)
        from app.guardrails import check_max_clarification_turns
        result = check_max_clarification_turns(state)
        assert not result.passed
        assert result.action == "escalate"
