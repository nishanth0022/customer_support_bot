"""
app/agents/refund_processing.py — Refund Processing Agent.

Handles: refund eligibility checks, refund calculation, auto-approval (≤ limit),
         and human approval requests (> limit).

Tools:   check_refund_eligibility, calculate_refund_amount,
         submit_refund_auto, request_human_approval

Guardrail: refund_amount_limit is checked here before any submission.
"""
from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent
from app.config import settings
from app.guardrails import check_refund_amount_limit
from app.orchestrator.state import ConversationState, PendingApproval
from app.tools.refund_tools import (
    check_refund_eligibility,
    calculate_refund_amount,
    submit_refund_auto,
    request_human_approval,
)


class RefundProcessingAgent(BaseAgent):
    name = "refund_processing"
    tool_allowlist = settings.refund_agent_tools

    def run(self, state: ConversationState) -> dict[str, Any]:
        entities = state.get("entities", {})
        customer_id = state.get("user_id")
        session_id = state["session_id"]
        tool_calls = list(state.get("tool_calls", []))
        order_id = entities.get("order_id")

        if not order_id:
            return {
                "response": (
                    "I'd be glad to help with a refund! "
                    "Please provide your order number (e.g., ORD-002) "
                    "and a brief reason for the refund."
                ),
                "clarification_turns": state.get("clarification_turns", 0) + 1,
                "tool_calls": tool_calls,
            }

        # ── Step 1: Eligibility ────────────────────────────────────────────
        elig_result = self.call_tool(
            state,
            "check_refund_eligibility",
            check_refund_eligibility,
            order_id=order_id,
            customer_id=customer_id,
        )
        tool_calls.append(self._record_tool_call(
            state, "check_refund_eligibility",
            {"order_id": order_id, "customer_id": customer_id}, elig_result,
        ))

        if not elig_result.get("eligible", False):
            response = (
                f"❌ **Refund Not Eligible**\n\n"
                f"{elig_result.get('reason', 'This order is not eligible for a refund.')}\n\n"
                "If you believe this is an error, type **'speak to an agent'** to escalate."
            )
            return {"response": response, "tool_calls": tool_calls}

        # ── Step 2: Calculate refund amount ────────────────────────────────
        reason = "customer_request"
        calc_result = self.call_tool(
            state,
            "calculate_refund_amount",
            calculate_refund_amount,
            order_id=order_id,
            customer_id=customer_id,
            reason=reason,
        )
        tool_calls.append(self._record_tool_call(
            state, "calculate_refund_amount",
            {"order_id": order_id, "customer_id": customer_id, "reason": reason}, calc_result,
        ))

        if not calc_result.get("success"):
            return {
                "response": f"I couldn't calculate the refund amount: {calc_result.get('reason', 'unknown error')}",
                "tool_calls": tool_calls,
                "retry_count": state.get("retry_count", 0) + 1,
            }

        refund_amount = calc_result["refund_amount"]

        # ── Step 3: Guardrail — refund amount limit ────────────────────────
        guard = check_refund_amount_limit(state, refund_amount)

        if not guard.passed:
            # Above threshold → need human approval
            approval_result = self.call_tool(
                state,
                "request_human_approval",
                request_human_approval,
                order_id=order_id,
                customer_id=customer_id,
                amount=refund_amount,
                reason=reason,
                session_id=session_id,
            )
            tool_calls.append(self._record_tool_call(
                state, "request_human_approval",
                {"order_id": order_id, "amount": refund_amount}, approval_result,
            ))

            approval_id = approval_result.get("approval_id", "")
            pending: PendingApproval = {
                "approval_id": approval_id,
                "action_description": f"Refund of ${refund_amount:.2f} for order {order_id}",
                "amount": refund_amount,
                "order_id": order_id,
            }

            response = (
                f"⚠️ **Human Approval Required**\n\n"
                f"Your refund of **${refund_amount:.2f}** for order **{order_id}** exceeds "
                f"our automatic approval limit of **${settings.refund_auto_approve_limit:.2f}**.\n\n"
                f"{approval_result.get('message', '')}\n\n"
                f"**Approval ID:** `{approval_id}`"
            )
            return {
                "response": response,
                "tool_calls": tool_calls,
                "pending_approval": pending,
                "guardrail_violations": state.get("guardrail_violations", []) + [guard.guardrail_name],
            }

        # ── Step 4: Auto-approve (within threshold) ────────────────────────
        submit_result = self.call_tool(
            state,
            "submit_refund_auto",
            submit_refund_auto,
            order_id=order_id,
            customer_id=customer_id,
            amount=refund_amount,
            reason=reason,
        )
        tool_calls.append(self._record_tool_call(
            state, "submit_refund_auto",
            {"order_id": order_id, "amount": refund_amount}, submit_result,
        ))

        response = (
            f"✅ **Refund Approved!**\n\n"
            f"A refund of **${refund_amount:.2f}** for order **{order_id}** has been processed.\n\n"
            f"Refund ID: `{submit_result.get('refund_id', 'N/A')}`\n"
            f"{submit_result.get('message', 'Your refund will appear in 3–5 business days.')}"
        )
        return {"response": response, "tool_calls": tool_calls}
