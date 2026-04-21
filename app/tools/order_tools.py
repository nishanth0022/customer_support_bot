"""
app/tools/order_tools.py — Mock order lookup and shipping status tools.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DATA_FILE = Path(__file__).parent.parent / "data" / "mock_orders.json"
_DB: dict[str, Any] | None = None


def _load_db() -> dict[str, Any]:
    global _DB
    if _DB is None:
        _DB = json.loads(_DATA_FILE.read_text(encoding="utf-8"))
    return _DB


def lookup_order(order_id: str, customer_id: str) -> dict[str, Any]:
    """
    Return order details for a given order_id.
    Enforces that the order belongs to the requesting customer.
    """
    db = _load_db()
    for order in db["orders"]:
        if order["order_id"] == order_id:
            if order["customer_id"] != customer_id:
                return {
                    "success": False,
                    "error": "access_denied",
                    "message": "This order does not belong to your account.",
                }
            return {"success": True, "order": order}
    return {
        "success": False,
        "error": "not_found",
        "message": f"Order {order_id} was not found.",
    }


def get_shipping_status(order_id: str, customer_id: str) -> dict[str, Any]:
    """Return live-ish shipping status for an order."""
    result = lookup_order(order_id, customer_id)
    if not result["success"]:
        return result

    order = result["order"]
    status = order["status"]
    tracking = order.get("tracking_number")
    carrier = order.get("carrier")

    if status == "processing":
        message = "Your order is being prepared. A tracking number will be assigned soon."
    elif status == "shipped":
        eta = order.get("estimated_delivery", "soon")
        message = (
            f"Your order shipped with {carrier}. "
            f"Tracking: {tracking}. Estimated delivery: {eta}."
        )
    elif status == "delivered":
        delivered_at = order.get("delivered_at", "recently")
        message = f"Your order was delivered on {delivered_at}."
    elif status == "cancelled":
        message = f"This order was cancelled. Reason: {order.get('cancel_reason', 'N/A')}."
    elif status == "return_requested":
        message = "A return has been initiated for this order. We will process it shortly."
    else:
        message = f"Current order status: {status}."

    return {
        "success": True,
        "order_id": order_id,
        "status": status,
        "carrier": carrier,
        "tracking_number": tracking,
        "message": message,
    }


def resolve_customer_id(token: str) -> str | None:
    """Resolve a customer auth token to a customer_id. Returns None if invalid."""
    db = _load_db()
    return db["customer_tokens"].get(token)


def get_customer_orders(customer_id: str) -> dict[str, Any]:
    """Return all orders for a customer."""
    db = _load_db()
    orders = [o for o in db["orders"] if o["customer_id"] == customer_id]
    return {"success": True, "orders": orders, "count": len(orders)}
