"""
app/guardrails/guardrails.py — All 10 production guardrails.

Each guardrail is a standalone function that takes the current ConversationState
and optional extra args, then returns a GuardrailResult.

Guardrails:
  1.  refund_amount_limit
  2.  authentication_required
  3.  session_data_isolation
  4.  max_retry_count
  5.  max_clarification_turns
  6.  low_confidence_escalation
  7.  tool_allowlist
  8.  loop_detection
  9.  policy_violation_blocking
  10. sensitive_data_isolation
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.config import settings
from app.monitoring.logger import log_event
from app.models.events import GuardrailViolationEvent, GuardrailPassEvent, GuardrailStatus

if TYPE_CHECKING:
    from app.orchestrator.state import ConversationState


# ── Result type ───────────────────────────────────────────────────────────────

@dataclass
class GuardrailResult:
    passed: bool
    guardrail_name: str
    action: str = "pass"          # "pass" | "block" | "escalate" | "warn"
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


# ── Logging helpers ────────────────────────────────────────────────────────────

def _log_pass(state: "ConversationState", name: str) -> None:
    log_event(GuardrailPassEvent(
        session_id=state["session_id"],
        user_id=state.get("user_id"),
        guardrail_name=name,
    ))


def _log_violation(
    state: "ConversationState",
    name: str,
    details: str,
    action: str,
) -> None:
    log_event(GuardrailViolationEvent(
        session_id=state["session_id"],
        user_id=state.get("user_id"),
        guardrail_name=name,
        details=details,
        action_taken=action,
    ))


# ── Guardrail 1: Refund Amount Limit ─────────────────────────────────────────

def check_refund_amount_limit(state: "ConversationState", refund_amount: float) -> GuardrailResult:
    """Block auto-approval of refunds above the configured threshold."""
    limit = settings.refund_auto_approve_limit
    name = "refund_amount_limit"

    if refund_amount > limit:
        _log_violation(
            state, name,
            f"Refund amount ${refund_amount:.2f} exceeds auto-approve limit ${limit:.2f}",
            "escalated",
        )
        return GuardrailResult(
            passed=False,
            guardrail_name=name,
            action="escalate",
            message=(
                f"Refund of ${refund_amount:.2f} exceeds the automatic approval limit "
                f"of ${limit:.2f}. Human approval is required."
            ),
            metadata={"amount": refund_amount, "limit": limit},
        )

    _log_pass(state, name)
    return GuardrailResult(passed=True, guardrail_name=name, action="pass")


# ── Guardrail 2: Authentication Required ─────────────────────────────────────

SENSITIVE_INTENTS = {"order_tracking", "refund"}

def check_authentication_required(state: "ConversationState") -> GuardrailResult:
    """Block sensitive operations if the user is not authenticated."""
    name = "authentication_required"
    intent = state.get("intent", "")

    if intent in SENSITIVE_INTENTS and not state.get("authenticated", False):
        _log_violation(
            state, name,
            f"Unauthenticated access attempt for intent '{intent}'",
            "blocked",
        )
        return GuardrailResult(
            passed=False,
            guardrail_name=name,
            action="block",
            message=(
                "To access order and refund information, we need to verify your identity. "
                "Please include your Customer Token in the X-Customer-Token header."
            ),
        )

    _log_pass(state, name)
    return GuardrailResult(passed=True, guardrail_name=name, action="pass")


# ── Guardrail 3: Session Data Isolation ──────────────────────────────────────

def check_session_data_isolation(
    state: "ConversationState",
    requested_customer_id: str,
) -> GuardrailResult:
    """Prevent a user from accessing another user's data."""
    name = "session_data_isolation"
    session_customer_id = state.get("user_id")

    if session_customer_id and requested_customer_id != session_customer_id:
        _log_violation(
            state, name,
            f"Session user '{session_customer_id}' tried to access data for '{requested_customer_id}'",
            "blocked",
        )
        return GuardrailResult(
            passed=False,
            guardrail_name=name,
            action="block",
            message="Access denied: you can only access your own account data.",
        )

    _log_pass(state, name)
    return GuardrailResult(passed=True, guardrail_name=name, action="pass")


# ── Guardrail 4: Max Retry Count ─────────────────────────────────────────────

def check_max_retry_count(state: "ConversationState") -> GuardrailResult:
    """Escalate if a tool/agent has failed too many times in this session."""
    name = "max_retry_count"
    retries = state.get("retry_count", 0)
    limit = settings.max_retry_count

    if retries >= limit:
        _log_violation(
            state, name,
            f"Retry count {retries} reached limit {limit}",
            "escalated",
        )
        return GuardrailResult(
            passed=False,
            guardrail_name=name,
            action="escalate",
            message=(
                f"We've tried to resolve your request {retries} times without success. "
                "Escalating to a human agent."
            ),
            metadata={"retry_count": retries, "limit": limit},
        )

    _log_pass(state, name)
    return GuardrailResult(passed=True, guardrail_name=name, action="pass")


# ── Guardrail 5: Max Clarification Turns ─────────────────────────────────────

def check_max_clarification_turns(state: "ConversationState") -> GuardrailResult:
    """Escalate if clarification has been requested too many consecutive times."""
    name = "max_clarification_turns"
    turns = state.get("clarification_turns", 0)
    limit = settings.max_clarification_turns

    if turns >= limit:
        _log_violation(
            state, name,
            f"Clarification turns {turns} reached limit {limit}",
            "escalated",
        )
        return GuardrailResult(
            passed=False,
            guardrail_name=name,
            action="escalate",
            message=(
                "It seems I'm having trouble understanding your request. "
                "Let me connect you with a human agent."
            ),
            metadata={"clarification_turns": turns, "limit": limit},
        )

    _log_pass(state, name)
    return GuardrailResult(passed=True, guardrail_name=name, action="pass")


# ── Guardrail 6: Low Confidence Escalation ───────────────────────────────────

def check_low_confidence(state: "ConversationState") -> GuardrailResult:
    """Escalate to human when intent classification confidence is too low."""
    name = "low_confidence_escalation"
    confidence = state.get("confidence", 1.0)
    threshold = settings.low_confidence_threshold

    if confidence < threshold:
        _log_violation(
            state, name,
            f"Confidence {confidence:.2f} below threshold {threshold:.2f}",
            "escalated",
        )
        return GuardrailResult(
            passed=False,
            guardrail_name=name,
            action="escalate",
            message=(
                "I'm not confident I fully understand your request. "
                "Connecting you with a human agent who can help."
            ),
            metadata={"confidence": confidence, "threshold": threshold},
        )

    _log_pass(state, name)
    return GuardrailResult(passed=True, guardrail_name=name, action="pass")


# ── Guardrail 7: Tool Allowlist ───────────────────────────────────────────────

_AGENT_TOOL_ALLOWLISTS: dict[str, list[str]] = {
    "order_tracking": settings.order_agent_tools,
    "refund_processing": settings.refund_agent_tools,
    "faq_resolution": settings.faq_agent_tools,
    "human_escalation": settings.escalation_agent_tools,
}

def check_tool_allowlist(state: "ConversationState", agent_name: str, tool_name: str) -> GuardrailResult:
    """Reject any tool call not in the agent's allowlist."""
    name = "tool_allowlist"
    allowlist = _AGENT_TOOL_ALLOWLISTS.get(agent_name, [])

    if tool_name not in allowlist:
        _log_violation(
            state, name,
            f"Agent '{agent_name}' attempted to call disallowed tool '{tool_name}'",
            "blocked",
        )
        return GuardrailResult(
            passed=False,
            guardrail_name=name,
            action="block",
            message=f"Tool '{tool_name}' is not permitted for agent '{agent_name}'.",
            metadata={"agent": agent_name, "tool": tool_name, "allowlist": allowlist},
        )

    _log_pass(state, name)
    return GuardrailResult(passed=True, guardrail_name=name, action="pass")


# ── Guardrail 8: Loop Detection ───────────────────────────────────────────────

def check_loop_detection(state: "ConversationState") -> GuardrailResult:
    """Detect if the same intent has fired repeatedly with no resolution."""
    name = "loop_detection"
    history: list[str] = state.get("intent_history", [])
    window = settings.max_loop_detection_window

    if len(history) >= window:
        recent = history[-window:]
        if len(set(recent)) == 1:  # all identical
            _log_violation(
                state, name,
                f"Loop detected: intent '{recent[0]}' repeated {window} times",
                "escalated",
            )
            return GuardrailResult(
                passed=False,
                guardrail_name=name,
                action="escalate",
                message=(
                    "It appears we've been going in circles. "
                    "Let me escalate this to a human agent."
                ),
                metadata={"repeated_intent": recent[0], "window": window},
            )

    _log_pass(state, name)
    return GuardrailResult(passed=True, guardrail_name=name, action="pass")


# ── Guardrail 9: Policy Violation Blocking ────────────────────────────────────

# Actions that are categorically disallowed regardless of context.
BLOCKED_ACTIONS = {
    "delete_customer_data",
    "bypass_refund_policy",
    "override_authentication",
    "access_all_customer_data",
    "mass_refund",
}

def check_policy_violation(state: "ConversationState", attempted_action: str) -> GuardrailResult:
    """Block categorically disallowed actions."""
    name = "policy_violation_blocking"

    if attempted_action in BLOCKED_ACTIONS:
        _log_violation(
            state, name,
            f"Attempted blocked action: '{attempted_action}'",
            "blocked",
        )
        return GuardrailResult(
            passed=False,
            guardrail_name=name,
            action="block",
            message=f"Action '{attempted_action}' is not permitted by company policy.",
            metadata={"blocked_action": attempted_action},
        )

    _log_pass(state, name)
    return GuardrailResult(passed=True, guardrail_name=name, action="pass")


# ── Guardrail 10: Sensitive Data Isolation ────────────────────────────────────

import re  # noqa: E402

_PII_PATTERNS = [
    (re.compile(r"\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b"), "[CARD_REDACTED]"),  # credit cards
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN_REDACTED]"),                        # SSN
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "[EMAIL_REDACTED]"),
    (re.compile(r"\b\d{10,11}\b"), "[PHONE_REDACTED]"),                               # phone
]

def scrub_pii(text: str) -> str:
    """Remove known PII patterns from a string before logging."""
    for pattern, replacement in _PII_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def check_sensitive_data_isolation(
    state: "ConversationState", text: str
) -> GuardrailResult:
    """Warn if the response text contains apparent PII that should be scrubbed."""
    name = "sensitive_data_isolation"
    scrubbed = scrub_pii(text)
    had_pii = scrubbed != text

    if had_pii:
        _log_violation(
            state, name,
            "PII detected in output — scrubbed before logging",
            "warn",
        )
        return GuardrailResult(
            passed=True,  # pass (we scrubbed it), but still record the event
            guardrail_name=name,
            action="warn",
            message="PII detected and removed from output.",
            metadata={"scrubbed_text": scrubbed},
        )

    _log_pass(state, name)
    return GuardrailResult(passed=True, guardrail_name=name, action="pass")
