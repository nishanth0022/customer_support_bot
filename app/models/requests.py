"""
app/models/requests.py — Pydantic request models for the API layer.
"""
from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=4000, description="Customer message")
    session_id: Optional[str] = Field(None, description="Existing session ID; omit to start a new session")
    customer_token: Optional[str] = Field(None, description="Auth token (alternative to X-Customer-Token header)")


class HumanApprovalRequest(BaseModel):
    session_id: str = Field(..., description="Session awaiting approval")
    approval_id: str = Field(..., description="Unique ID of the pending approval item")
    approved: bool = Field(..., description="True = approve the action, False = reject it")
    reviewer_note: Optional[str] = Field(None, max_length=1000, description="Optional note from reviewer")
