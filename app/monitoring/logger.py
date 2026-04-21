"""
app/monitoring/logger.py — Structured JSON event logger.

All system events (agent decisions, tool calls, guardrail violations,
escalations) are written here. Events are:
  1. Printed to stdout as JSON lines (for log aggregators / Docker).
  2. Appended to LOG_FILE on disk (for local inspection / testing).

The module also holds an in-memory ring buffer (last 10 000 events) used
by the GET /logs endpoint so the system works without a database.
"""
from __future__ import annotations

import json
import os
import threading
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.models.events import BaseEvent

# ── In-memory ring buffer (thread-safe) ───────────────────────────────────────
_BUFFER_MAX = 10_000
_buffer: deque[dict[str, Any]] = deque(maxlen=_BUFFER_MAX)
_lock = threading.Lock()

# ── Log file setup ─────────────────────────────────────────────────────────────
_log_path = Path(settings.log_file)
_log_path.parent.mkdir(parents=True, exist_ok=True)


def _serialize(event: BaseEvent) -> dict[str, Any]:
    """Convert a Pydantic event to a plain dict suitable for JSON serialisation."""
    return json.loads(event.model_dump_json())


def log_event(event: BaseEvent) -> None:
    """Primary entry point — call this for every system event."""
    payload = _serialize(event)

    # 1. Append to ring buffer
    with _lock:
        _buffer.append(payload)

    # 2. Write to log file (append mode, one JSON line per event)
    try:
        with open(_log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, default=str) + "\n")
    except OSError:
        pass  # Never crash the main flow due to logging

    # 3. Print to stdout for container log aggregators
    level = _resolve_level(payload.get("event_type", ""))
    print(f"[{level}] {json.dumps(payload, default=str)}", flush=True)


def _resolve_level(event_type: str) -> str:
    if "VIOLATION" in event_type or "BLOCK" in event_type:
        return "WARNING"
    if event_type in ("ESCALATION", "HUMAN_APPROVAL"):
        return "INFO"
    return "DEBUG"


# ── Query helpers used by GET /logs ───────────────────────────────────────────

def get_all_events(
    session_id: str | None = None,
    event_type: str | None = None,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Return recent events from the ring buffer, newest-first."""
    with _lock:
        events = list(_buffer)

    if session_id:
        events = [e for e in events if e.get("session_id") == session_id]
    if event_type:
        events = [e for e in events if e.get("event_type") == event_type]

    return list(reversed(events))[:limit]


def event_count() -> int:
    with _lock:
        return len(_buffer)
