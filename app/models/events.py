"""
app/models/events.py — Typed Pydantic schemas for all monitoring events.
"""
from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class EventType(str, Enum):
    AGENT_DECISION = "AGENT_DECISION"
    TOOL_CALL = "TOOL_CALL"
    ESCALATION = "ESCALATION"
    GUARDRAIL_VIOLATION = "GUARDRAIL_VIOLATION"
    GUARDRAIL_PASS = "GUARDRAIL_PASS"
    SESSION_START = "SESSION_START"
    SESSION_END = "SESSION_END"
    HUMAN_APPROVAL = "HUMAN_APPROVAL"
    POLICY_BLOCK = "POLICY_BLOCK"


class GuardrailStatus(str, Enum):
    PASS = "PASS"
    VIOLATION = "VIOLATION"
    BLOCKED = "BLOCKED"


class BaseEvent(BaseModel):
    timestamp: datetime = Field(default_factory=_utcnow)
    session_id: str
    user_id: Optional[str] = None
    event_type: EventType


class AgentDecisionEvent(BaseEvent):
    event_type: EventType = EventType.AGENT_DECISION
    intent: str
    confidence: float
    agent_selected: str
    message_snippet: str  # first 120 chars of user message


class ToolCallEvent(BaseEvent):
    event_type: EventType = EventType.TOOL_CALL
    agent: str
    tool_name: str
    inputs: dict[str, Any]
    outputs: Optional[dict[str, Any]] = None
    success: bool = True
    error_message: Optional[str] = None
    duration_ms: int = 0
    guardrail_status: GuardrailStatus = GuardrailStatus.PASS


class EscalationEvent(BaseEvent):
    event_type: EventType = EventType.ESCALATION
    reason: str
    escalation_type: str  # "low_confidence" | "retry_exceeded" | "threshold" | "policy" | "manual"
    context_summary: str
    ticket_id: Optional[str] = None


class GuardrailViolationEvent(BaseEvent):
    event_type: EventType = EventType.GUARDRAIL_VIOLATION
    guardrail_name: str
    details: str
    action_taken: str  # "blocked" | "escalated" | "warned"
    guardrail_status: GuardrailStatus = GuardrailStatus.VIOLATION


class GuardrailPassEvent(BaseEvent):
    event_type: EventType = EventType.GUARDRAIL_PASS
    guardrail_name: str


class SessionStartEvent(BaseEvent):
    event_type: EventType = EventType.SESSION_START


class SessionEndEvent(BaseEvent):
    event_type: EventType = EventType.SESSION_END
    total_turns: int
    escalated: bool


class HumanApprovalEvent(BaseEvent):
    event_type: EventType = EventType.HUMAN_APPROVAL
    approval_id: str
    approved: bool
    reviewer_note: Optional[str] = None
    action_description: str


# Union type for all events
AnyEvent = (
    AgentDecisionEvent
    | ToolCallEvent
    | EscalationEvent
    | GuardrailViolationEvent
    | GuardrailPassEvent
    | SessionStartEvent
    | SessionEndEvent
    | HumanApprovalEvent
)
