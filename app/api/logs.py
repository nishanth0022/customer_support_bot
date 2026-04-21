"""
app/api/logs.py — GET /logs endpoint.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Query

from app.monitoring.logger import get_all_events

router = APIRouter()


@router.get("/logs", tags=["Monitoring"])
async def get_logs(
    session_id: Optional[str] = Query(None, description="Filter by session ID"),
    event_type: Optional[str] = Query(None, description="Filter by event type (e.g. TOOL_CALL, ESCALATION)"),
    limit: int = Query(100, ge=1, le=1000, description="Max events to return"),
) -> dict:
    """
    Retrieve structured event logs from the in-memory ring buffer.

    Supports filtering by session_id and/or event_type.
    Returns events in reverse-chronological order (newest first).
    """
    events = get_all_events(
        session_id=session_id,
        event_type=event_type,
        limit=limit,
    )
    return {
        "count": len(events),
        "filters": {
            "session_id": session_id,
            "event_type": event_type,
            "limit": limit,
        },
        "events": events,
    }
