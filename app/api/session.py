"""
app/api/session.py — GET /session/{id} endpoint.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.session_store import get_session
from app.models.responses import SessionResponse

router = APIRouter()


@router.get("/session/{session_id}", response_model=SessionResponse, tags=["Session"])
async def get_session_details(session_id: str) -> SessionResponse:
    """
    Retrieve the full state of an active session including message history,
    tool call log, intent history, and guardrail violations.
    """
    state = get_session(session_id)
    if not state:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

    return SessionResponse(
        session_id=state["session_id"],
        user_id=state.get("user_id"),
        authenticated=state.get("authenticated", False),
        messages=state.get("messages", []),
        intent_history=state.get("intent_history", []),
        tool_calls=list(state.get("tool_calls", [])),
        escalated=state.get("escalated", False),
        retry_count=state.get("retry_count", 0),
        guardrail_violations=state.get("guardrail_violations", []),
    )
