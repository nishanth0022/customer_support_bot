"""
app/tools/escalation_tools.py — Ticket creation and queue handoff tools.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

# In-memory ticket store
_tickets: dict[str, dict[str, Any]] = {}
_queue: list[dict[str, Any]] = []


def create_ticket(
    session_id: str,
    customer_id: str | None,
    reason: str,
    escalation_type: str,
    context_summary: str,
    priority: str = "normal",
) -> dict[str, Any]:
    """
    Create a support ticket for human review.
    escalation_type: "low_confidence" | "retry_exceeded" | "threshold" | "policy" | "manual"
    priority: "low" | "normal" | "high" | "urgent"
    """
    ticket_id = f"TKT-{uuid.uuid4().hex[:8].upper()}"
    ticket = {
        "ticket_id": ticket_id,
        "session_id": session_id,
        "customer_id": customer_id,
        "reason": reason,
        "escalation_type": escalation_type,
        "context_summary": context_summary,
        "priority": priority,
        "status": "open",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "assigned_to": None,
    }
    _tickets[ticket_id] = ticket
    return {
        "success": True,
        "ticket_id": ticket_id,
        "message": (
            f"Your request has been escalated to our support team (Ticket: {ticket_id}). "
            "A human agent will reach you within 2–4 hours. We apologise for any inconvenience."
        ),
    }


def add_to_queue(ticket_id: str, priority: str = "normal") -> dict[str, Any]:
    """Add a ticket to the human support queue."""
    ticket = _tickets.get(ticket_id)
    if not ticket:
        return {"success": False, "message": f"Ticket {ticket_id} not found."}

    priority_order = {"urgent": 0, "high": 1, "normal": 2, "low": 3}
    queue_entry = {
        "ticket_id": ticket_id,
        "priority": priority,
        "priority_order": priority_order.get(priority, 2),
        "queued_at": datetime.now(timezone.utc).isoformat(),
    }
    _queue.append(queue_entry)
    _queue.sort(key=lambda x: x["priority_order"])

    return {
        "success": True,
        "ticket_id": ticket_id,
        "queue_position": _queue.index(queue_entry) + 1,
        "message": f"Added to support queue at position {_queue.index(queue_entry) + 1}.",
    }


def get_ticket(ticket_id: str) -> dict[str, Any] | None:
    return _tickets.get(ticket_id)


def get_queue() -> list[dict[str, Any]]:
    return list(_queue)


def get_all_tickets() -> list[dict[str, Any]]:
    return list(_tickets.values())
