"""
app/agents/order_tracking.py — Order Tracking Agent.

Handles: order status queries, shipping updates, delivery tracking.
Tools:   lookup_order, get_shipping_status
Requires authentication for any personal order data.
"""
from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent
from app.config import settings
from app.orchestrator.state import ConversationState
from app.tools.order_tools import lookup_order, get_shipping_status, get_customer_orders


class OrderTrackingAgent(BaseAgent):
    name = "order_tracking"
    tool_allowlist = settings.order_agent_tools

    def _humanize_status(self, order_id: str, status_data: dict[str, Any]) -> str | None:
        """Use LLM to format shipping status into a friendly message."""
        try:
            from app.orchestrator.llm import get_shared_llm
            llm = get_shared_llm()
            
            prompt = (
                "You are a friendly customer support agent. "
                "Humanize the following shipping status data into a concise, helpful update for the customer. "
                "Include the order ID, the carrier, and the tracking number if present. "
                "If the status is 'delivered', sound happy! If it is 'delayed', sound empathetic.\n\n"
                f"Data: {status_data}\n"
                f"Order ID: {order_id}\n\n"
                "Response:"
            )
            
            response = llm.invoke(prompt)
            return response.content.strip()
        except Exception as e:
            print(f"[AI] Order Humanization Error: {str(e)}")
            return None

    def run(self, state: ConversationState) -> dict[str, Any]:
        entities = state.get("entities", {})
        customer_id = state.get("user_id")
        tool_calls = list(state.get("tool_calls", []))
        order_id = entities.get("order_id")

        # ── Case 1: specific order lookup ──────────────────────────────────
        if order_id:
            result = self.call_tool(
                state,
                "get_shipping_status",
                get_shipping_status,
                order_id=order_id,
                customer_id=customer_id,
            )
            tool_calls.append(self._record_tool_call(
                state, "get_shipping_status",
                {"order_id": order_id, "customer_id": customer_id}, result,
            ))

            if result.get("success"):
                # Use LLM humanization exclusively
                print(f"\n[AI] Order Agent using Groq to humanize status for: {order_id}")
                humanized = self._humanize_status(order_id, result)
                response = humanized or "I'm currently experiencing an AI processing issue. Please try again in a moment."
            elif result.get("error") == "access_denied":
                response = "❌ " + result["message"]
            else:
                response = f"I couldn't find order {order_id}. Please double-check the order number and try again."
            return {"response": response, "tool_calls": tool_calls}

        # ── Case 2: list all orders ────────────────────────────────────────
        if customer_id:
            result = self.call_tool(
                state,
                "lookup_order",
                get_customer_orders,
                customer_id=customer_id,
            )
            tool_calls.append(self._record_tool_call(
                state, "lookup_order", {"customer_id": customer_id}, result,
            ))

            orders = result.get("orders", [])
            if not orders:
                response = "You don't have any orders in your account yet."
            else:
                lines = [f"🛍️ **Your Recent Orders ({len(orders)} total):**\n"]
                for o in orders[:5]:  # show up to 5
                    lines.append(
                        f"• **{o['order_id']}** — {o['status'].title()} — "
                        f"${o['total']:.2f} ({o.get('placed_at', '')[:10]})"
                    )
                if len(orders) > 5:
                    lines.append(f"...and {len(orders) - 5} more.")
                response = "\n".join(lines)
            return {"response": response, "tool_calls": tool_calls}

        # ── Case 3: unauthenticated fallback ───────────────────────────────
        response = (
            "I'd be happy to help with order tracking! "
            "Could you please provide your order number (e.g., ORD-001)?"
        )
        return {
            "response": response,
            "tool_calls": tool_calls,
            "clarification_turns": state.get("clarification_turns", 0) + 1,
        }
