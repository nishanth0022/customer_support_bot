"""
app/models/responses.py — Pydantic response models for the API layer.
"""
from __future__ import annotations

from typing import Any, Optional
from pydantic import BaseModel, Field


class ChatResponse(BaseModel):
    session_id: str
    response: str
    agent_used: str
    intent: str
    confidence: float
    escalated: bool = False
    pending_approval: Optional[dict[str, Any]] = None
    guardrail_violations: list[str] = Field(default_factory=list)


class SessionResponse(BaseModel):
    session_id: str
    user_id: Optional[str]
    authenticated: bool
    messages: list[dict[str, Any]]
    intent_history: list[str]
    tool_calls: list[dict[str, Any]]
    escalated: bool
    retry_count: int
    guardrail_violations: list[str]


class ApprovalResponse(BaseModel):
    session_id: str
    approval_id: str
    status: str  # "approved" | "rejected"
    message: str


class HealthResponse(BaseModel):
    status: str
    version: str
    active_sessions: int
    log_event_count: int
