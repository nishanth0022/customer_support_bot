"""
app/api/session_store.py — In-memory session store.

Maintains ConversationState for each active session.
Thread-safe. Can be replaced with Redis in production.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timezone

from app.orchestrator.state import ConversationState, initial_state
from app.tools.order_tools import resolve_customer_id

_store: dict[str, ConversationState] = {}
_lock = threading.Lock()


def create_session(customer_token: str | None = None) -> ConversationState:
    """Create a new session. Resolves auth token to customer_id if provided."""
    session_id = str(uuid.uuid4())
    user_id: str | None = None
    authenticated = False

    if customer_token:
        user_id = resolve_customer_id(customer_token)
        authenticated = user_id is not None

    state = initial_state(session_id, user_id, authenticated)
    with _lock:
        _store[session_id] = state
    return state


def get_session(session_id: str) -> ConversationState | None:
    with _lock:
        return _store.get(session_id)


def update_session(session_id: str, updates: dict) -> ConversationState | None:
    with _lock:
        state = _store.get(session_id)
        if state is None:
            return None
        state.update(updates)  # type: ignore[attr-defined]
        return state


def save_state(state: ConversationState) -> None:
    with _lock:
        _store[state["session_id"]] = state


def list_sessions() -> list[str]:
    with _lock:
        return list(_store.keys())


def session_count() -> int:
    with _lock:
        return len(_store)
