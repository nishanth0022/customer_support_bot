"""
tests/test_guardrails.py — Unit tests for all 10 guardrails.
"""
import pytest

from app.guardrails import (
    check_refund_amount_limit,
    check_authentication_required,
    check_session_data_isolation,
    check_max_retry_count,
    check_max_clarification_turns,
    check_low_confidence,
    check_tool_allowlist,
    check_loop_detection,
    check_policy_violation,
    check_sensitive_data_isolation,
    BLOCKED_ACTIONS,
)
from app.orchestrator.state import initial_state
from app.config import settings


def make_state(**overrides):
    s = initial_state("sess-guard", "CUST-100", True)
    s.update(overrides)
    return s


# ── 1. Refund Amount Limit ────────────────────────────────────────────────────

class TestRefundAmountLimit:
    def test_under_limit_passes(self):
        state = make_state()
        result = check_refund_amount_limit(state, settings.refund_auto_approve_limit - 0.01)
        assert result.passed
        assert result.action == "pass"

    def test_at_limit_passes(self):
        state = make_state()
        result = check_refund_amount_limit(state, settings.refund_auto_approve_limit)
        assert result.passed

    def test_over_limit_fails(self):
        state = make_state()
        result = check_refund_amount_limit(state, settings.refund_auto_approve_limit + 0.01)
        assert not result.passed
        assert result.action == "escalate"
        assert "human approval" in result.message.lower()

    def test_large_amount_fails(self):
        state = make_state()
        result = check_refund_amount_limit(state, 9999.99)
        assert not result.passed
        assert result.metadata["amount"] == 9999.99


# ── 2. Authentication Required ────────────────────────────────────────────────

class TestAuthenticationRequired:
    def test_authenticated_order_intent_passes(self):
        state = make_state(intent="order_tracking", authenticated=True)
        result = check_authentication_required(state)
        assert result.passed

    def test_unauthenticated_order_intent_fails(self):
        state = make_state(intent="order_tracking", authenticated=False, user_id=None)
        result = check_authentication_required(state)
        assert not result.passed
        assert result.action == "block"

    def test_unauthenticated_refund_fails(self):
        state = make_state(intent="refund", authenticated=False, user_id=None)
        result = check_authentication_required(state)
        assert not result.passed

    def test_unauthenticated_faq_passes(self):
        state = make_state(intent="faq", authenticated=False, user_id=None)
        result = check_authentication_required(state)
        assert result.passed  # FAQ doesn't need auth


# ── 3. Session Data Isolation ─────────────────────────────────────────────────

class TestSessionDataIsolation:
    def test_same_customer_passes(self):
        state = make_state(user_id="CUST-100")
        result = check_session_data_isolation(state, "CUST-100")
        assert result.passed

    def test_different_customer_fails(self):
        state = make_state(user_id="CUST-100")
        result = check_session_data_isolation(state, "CUST-999")
        assert not result.passed
        assert result.action == "block"

    def test_no_session_user_passes(self):
        state = make_state(user_id=None)
        result = check_session_data_isolation(state, "CUST-100")
        assert result.passed  # no user_id in session — can't verify, pass


# ── 4. Max Retry Count ────────────────────────────────────────────────────────

class TestMaxRetryCount:
    def test_zero_retries_passes(self):
        state = make_state(retry_count=0)
        assert check_max_retry_count(state).passed

    def test_below_limit_passes(self):
        state = make_state(retry_count=settings.max_retry_count - 1)
        assert check_max_retry_count(state).passed

    def test_at_limit_fails(self):
        state = make_state(retry_count=settings.max_retry_count)
        result = check_max_retry_count(state)
        assert not result.passed
        assert result.action == "escalate"

    def test_above_limit_fails(self):
        state = make_state(retry_count=settings.max_retry_count + 5)
        assert not check_max_retry_count(state).passed


# ── 5. Max Clarification Turns ────────────────────────────────────────────────

class TestMaxClarificationTurns:
    def test_zero_turns_passes(self):
        state = make_state(clarification_turns=0)
        assert check_max_clarification_turns(state).passed

    def test_at_limit_fails(self):
        state = make_state(clarification_turns=settings.max_clarification_turns)
        result = check_max_clarification_turns(state)
        assert not result.passed
        assert result.action == "escalate"


# ── 6. Low Confidence Escalation ─────────────────────────────────────────────

class TestLowConfidence:
    def test_high_confidence_passes(self):
        state = make_state(confidence=0.9)
        assert check_low_confidence(state).passed

    def test_at_threshold_passes(self):
        state = make_state(confidence=settings.low_confidence_threshold)
        assert check_low_confidence(state).passed

    def test_below_threshold_fails(self):
        state = make_state(confidence=settings.low_confidence_threshold - 0.01)
        result = check_low_confidence(state)
        assert not result.passed
        assert result.action == "escalate"

    def test_zero_confidence_fails(self):
        state = make_state(confidence=0.0)
        assert not check_low_confidence(state).passed


# ── 7. Tool Allowlist ─────────────────────────────────────────────────────────

class TestToolAllowlist:
    def test_allowed_tool_passes(self):
        state = make_state()
        result = check_tool_allowlist(state, "order_tracking", "lookup_order")
        assert result.passed

    def test_allowed_refund_tool_passes(self):
        state = make_state()
        result = check_tool_allowlist(state, "refund_processing", "submit_refund_auto")
        assert result.passed

    def test_disallowed_tool_fails(self):
        state = make_state()
        result = check_tool_allowlist(state, "order_tracking", "submit_refund_auto")
        assert not result.passed
        assert result.action == "block"

    def test_faq_agent_cannot_call_order_tool(self):
        state = make_state()
        result = check_tool_allowlist(state, "faq_resolution", "lookup_order")
        assert not result.passed

    def test_escalation_agent_cannot_call_refund_tool(self):
        state = make_state()
        result = check_tool_allowlist(state, "human_escalation", "submit_refund_auto")
        assert not result.passed


# ── 8. Loop Detection ─────────────────────────────────────────────────────────

class TestLoopDetection:
    def test_no_loop_passes(self):
        state = make_state(intent_history=["order_tracking", "faq", "refund"])
        assert check_loop_detection(state).passed

    def test_short_history_passes(self):
        state = make_state(intent_history=["refund", "refund"])
        assert check_loop_detection(state).passed  # window not reached

    def test_loop_detected_fails(self):
        window = settings.max_loop_detection_window
        state = make_state(intent_history=["refund"] * window)
        result = check_loop_detection(state)
        assert not result.passed
        assert result.action == "escalate"

    def test_mixed_history_no_loop(self):
        window = settings.max_loop_detection_window
        history = (["refund"] * (window - 1)) + ["order_tracking"]
        state = make_state(intent_history=history)
        assert check_loop_detection(state).passed


# ── 9. Policy Violation Blocking ─────────────────────────────────────────────

class TestPolicyViolation:
    def test_normal_action_passes(self):
        state = make_state()
        result = check_policy_violation(state, "process_refund")
        assert result.passed

    def test_blocked_actions_fail(self):
        state = make_state()
        for action in BLOCKED_ACTIONS:
            result = check_policy_violation(state, action)
            assert not result.passed, f"Expected '{action}' to be blocked"
            assert result.action == "block"


# ── 10. Sensitive Data Isolation (PII scrubbing) ──────────────────────────────

class TestSensitiveDataIsolation:
    def test_clean_text_passes(self):
        state = make_state()
        result = check_sensitive_data_isolation(state, "Your order has shipped!")
        assert result.passed
        assert result.action == "pass"

    def test_credit_card_detected(self):
        state = make_state()
        result = check_sensitive_data_isolation(state, "Card: 4111-1111-1111-1111")
        assert result.passed  # pass but with warn action
        assert result.action == "warn"

    def test_ssn_detected(self):
        state = make_state()
        result = check_sensitive_data_isolation(state, "My SSN is 123-45-6789")
        assert result.action == "warn"

    def test_email_detected(self):
        state = make_state()
        result = check_sensitive_data_isolation(state, "Email me at user@example.com")
        assert result.action == "warn"
