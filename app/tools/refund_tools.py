"""
app/tools/refund_tools.py — Mock refund eligibility, calculation, and approval tools.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.tools.order_tools import lookup_order

# In-memory store of pending approvals (keyed by approval_id)
_pending_approvals: dict[str, dict[str, Any]] = {}

RETURN_WINDOW_DAYS = 30


def check_refund_eligibility(order_id: str, customer_id: str) -> dict[str, Any]:
    """Check whether an order qualifies for a refund."""
    result = lookup_order(order_id, customer_id)
    if not result["success"]:
        return {**result, "eligible": False, "reason": result["message"]}

    order = result["order"]
    status = order["status"]
    placed_at = order.get("placed_at")

    # Non-refundable statuses
    if status in ("processing",):
        return {
            "success": True,
            "eligible": True,
            "reason": "Order has not shipped yet. Full refund available.",
            "order": order,
        }
    if status == "cancelled":
        return {
            "success": True,
            "eligible": False,
            "reason": "Order is already cancelled. Refund was auto-processed.",
            "order": order,
        }
    if status not in ("delivered", "return_requested", "shipped"):
        return {
            "success": True,
            "eligible": False,
            "reason": f"Order in status '{status}' is not eligible for a refund.",
            "order": order,
        }

    # Check 30-day return window (for delivered orders)
    if placed_at and status == "delivered":
        placed_dt = datetime.fromisoformat(placed_at.replace("Z", "+00:00"))
        days_ago = (datetime.now(timezone.utc) - placed_dt).days
        if days_ago > RETURN_WINDOW_DAYS:
            return {
                "success": True,
                "eligible": False,
                "reason": f"Return window has expired ({days_ago} days since order). Policy allows {RETURN_WINDOW_DAYS} days.",
                "order": order,
            }

    return {
        "success": True,
        "eligible": True,
        "reason": "Order is eligible for a refund within the return window.",
        "order": order,
    }


def calculate_refund_amount(order_id: str, customer_id: str, reason: str = "customer_request") -> dict[str, Any]:
    """Calculate the refund amount for an eligible order."""
    eligibility = check_refund_eligibility(order_id, customer_id)
    if not eligibility["success"] or not eligibility["eligible"]:
        return {
            "success": False,
            "amount": 0.0,
            "reason": eligibility.get("reason", "Not eligible"),
        }

    order = eligibility["order"]
    total = order["total"]

    # Simple policy: full refund for most cases
    deduction = 0.0
    if reason == "buyer_remorse" and order.get("status") == "delivered":
        deduction = 0.0  # still full for this mock

    refund_amount = round(total - deduction, 2)
    return {
        "success": True,
        "order_id": order_id,
        "order_total": total,
        "refund_amount": refund_amount,
        "deduction": deduction,
        "reason": reason,
        "currency": "USD",
    }


def submit_refund_auto(order_id: str, customer_id: str, amount: float, reason: str) -> dict[str, Any]:
    """
    Auto-approve and submit a refund (only called when amount ≤ threshold).
    In production this would call a payment gateway API.
    """
    refund_id = f"RFD-{uuid.uuid4().hex[:8].upper()}"
    return {
        "success": True,
        "refund_id": refund_id,
        "order_id": order_id,
        "amount": amount,
        "currency": "USD",
        "status": "approved",
        "message": f"Refund of ${amount:.2f} approved and submitted. Refund ID: {refund_id}. Credit in 3–5 business days.",
    }


def request_human_approval(
    order_id: str,
    customer_id: str,
    amount: float,
    reason: str,
    session_id: str,
) -> dict[str, Any]:
    """
    Create a pending approval record for refunds above the auto-approve limit.
    Returns an approval_id that the human reviewer will reference.
    """
    approval_id = f"APR-{uuid.uuid4().hex[:8].upper()}"
    record = {
        "approval_id": approval_id,
        "session_id": session_id,
        "order_id": order_id,
        "customer_id": customer_id,
        "amount": amount,
        "reason": reason,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _pending_approvals[approval_id] = record
    return {
        "success": True,
        "approval_id": approval_id,
        "status": "pending_human_approval",
        "message": (
            f"Refund of ${amount:.2f} requires human approval. "
            f"Approval ID: {approval_id}. A support agent will review within 24 hours."
        ),
    }


def get_pending_approval(approval_id: str) -> dict[str, Any] | None:
    return _pending_approvals.get(approval_id)


def resolve_approval(approval_id: str, approved: bool, reviewer_note: str | None = None) -> dict[str, Any]:
    """Mark a pending approval as approved or rejected."""
    record = _pending_approvals.get(approval_id)
    if not record:
        return {"success": False, "message": f"Approval {approval_id} not found."}

    record["status"] = "approved" if approved else "rejected"
    record["reviewer_note"] = reviewer_note
    record["resolved_at"] = datetime.now(timezone.utc).isoformat()

    if approved:
        # Process the actual refund
        refund_result = submit_refund_auto(
            record["order_id"], record["customer_id"], record["amount"], record["reason"]
        )
        record["refund_result"] = refund_result
        return {"success": True, "status": "approved", "refund": refund_result}
    else:
        return {"success": True, "status": "rejected", "message": "Refund request has been rejected."}


def get_all_pending_approvals() -> list[dict[str, Any]]:
    return [v for v in _pending_approvals.values() if v["status"] == "pending"]
