"""
app/api/chat.py — POST /chat endpoint.
"""
from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException
from typing import Optional

from app.api.session_store import create_session, get_session, save_state
from app.models.requests import ChatRequest
from app.models.responses import ChatResponse
from app.monitoring.logger import log_event
from app.models.events import SessionStartEvent
from app.orchestrator.graph import compiled_graph
from app.guardrails.guardrails import scrub_pii

router = APIRouter()


@router.post("/chat", response_model=ChatResponse, tags=["Chat"])
async def chat(
    body: ChatRequest,
    x_customer_token: Optional[str] = Header(None, alias="X-Customer-Token"),
) -> ChatResponse:
    """
    Process a customer support message through the multi-agent orchestrator.

    - Creates a new session if session_id is not provided.
    - Auth token can be in X-Customer-Token header or body.customer_token.
    - Runs the full LangGraph pipeline and returns the agent response.
    """
    # ── Resolve auth token from header or body ─────────────────────────────
    token = x_customer_token or body.customer_token

    # ── Get or create session ──────────────────────────────────────────────
    session_id = body.session_id
    if session_id:
        state = get_session(session_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")

        # Upgrade auth if token is now provided but wasn't before
        if token and not state.get("authenticated"):
            from app.tools.order_tools import resolve_customer_id
            user_id = resolve_customer_id(token)
            if user_id:
                state["authenticated"] = True
                state["user_id"] = user_id
    else:
        state = create_session(customer_token=token)
        log_event(SessionStartEvent(
            session_id=state["session_id"],
            user_id=state.get("user_id"),
        ))

    # ── Append the user's message to history ───────────────────────────────
    messages = list(state.get("messages", []))
    messages.append({"role": "user", "content": body.message})
    state["messages"] = messages
    state["current_message"] = body.message

    # ── Run the LangGraph orchestrator ─────────────────────────────────────
    result_state: dict = compiled_graph.invoke(state)

    # ── Merge result back into session ─────────────────────────────────────
    state.update(result_state)
    save_state(state)

    # ── Scrub PII from the response before returning ───────────────────────
    response_text = scrub_pii(state.get("response", "I'm sorry, I couldn't process your request."))

    return ChatResponse(
        session_id=state["session_id"],
        response=response_text,
        agent_used=state.get("agent", "unknown"),
        intent=state.get("intent", "unknown"),
        confidence=state.get("confidence", 0.0),
        escalated=state.get("escalated", False),
        pending_approval=state.get("pending_approval"),
        guardrail_violations=state.get("guardrail_violations", []),
    )
