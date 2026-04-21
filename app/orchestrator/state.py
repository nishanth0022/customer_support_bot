"""
app/orchestrator/state.py — Typed conversation state for the LangGraph StateGraph.
"""
from __future__ import annotations

from typing import Any, Optional
from typing_extensions import TypedDict


class ToolCallRecord(TypedDict):
    tool_name: str
    agent: str
    inputs: dict[str, Any]
    outputs: Optional[dict[str, Any]]
    success: bool
    error: Optional[str]


class PendingApproval(TypedDict):
    approval_id: str
    action_description: str
    amount: Optional[float]
    order_id: Optional[str]


class ConversationState(TypedDict):
    # ── Identity ──────────────────────────────────────────────────────────────
    session_id: str
    user_id: Optional[str]          # customer_id resolved from auth token
    authenticated: bool

    # ── Current turn ──────────────────────────────────────────────────────────
    current_message: str            # the user's raw message this turn
    intent: str                     # classified intent
    confidence: float               # 0.0–1.0
    entities: dict[str, Any]        # extracted entities (order_id, amount, etc.)

    # ── Routing ───────────────────────────────────────────────────────────────
    agent: str                      # name of agent selected for this turn

    # ── History ───────────────────────────────────────────────────────────────
    messages: list[dict[str, str]]  # {"role": "user"|"assistant", "content": "..."}
    intent_history: list[str]       # intent per turn for loop detection
    tool_calls: list[ToolCallRecord]

    # ── State counters ────────────────────────────────────────────────────────
    retry_count: int
    clarification_turns: int

    # ── Escalation / approval ─────────────────────────────────────────────────
    escalated: bool
    escalation_reason: Optional[str]
    pending_approval: Optional[PendingApproval]

    # ── Guardrails ────────────────────────────────────────────────────────────
    guardrail_violations: list[str]

    # ── Final response ────────────────────────────────────────────────────────
    response: str


def initial_state(session_id: str, user_id: Optional[str], authenticated: bool) -> ConversationState:
    return ConversationState(
        session_id=session_id,
        user_id=user_id,
        authenticated=authenticated,
        current_message="",
        intent="unknown",
        confidence=0.0,
        entities={},
        agent="",
        messages=[],
        intent_history=[],
        tool_calls=[],
        retry_count=0,
        clarification_turns=0,
        escalated=False,
        escalation_reason=None,
        pending_approval=None,
        guardrail_violations=[],
        response="",
    )
