"""
app/agents/human_escalation.py — Human Escalation Agent.

Creates a support ticket, adds it to the priority queue, and returns a
structured escalation summary to the customer.

Tools: create_ticket, add_to_queue
"""
from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent
from app.config import settings
from app.monitoring.logger import log_event
from app.models.events import EscalationEvent
from app.orchestrator.state import ConversationState
from app.tools.escalation_tools import create_ticket, add_to_queue


_ESCALATION_TYPE_MAP = {
    "low_confidence": "I wasn't confident enough to resolve this automatically",
    "retry_exceeded": "We exceeded the maximum number of retry attempts",
    "refund_threshold": "A large refund requires human review",
    "policy": "Company policy requires human review for this action",
    "faq_no_answer": "No KB answer was found for your question",
    "loop": "A resolution loop was detected",
    "clarification_exceeded": "We reached the clarification limit",
    "manual": "You requested to speak with a human agent",
    "unknown_intent": "I wasn't able to determine the type of help you need",
}


class HumanEscalationAgent(BaseAgent):
    name = "human_escalation"
    tool_allowlist = settings.escalation_agent_tools

    def _generate_briefing(self, state: ConversationState, context_summary: str) -> str | None:
        """Use LLM to generate a structured briefing for the human agent."""
        try:
            from app.orchestrator.llm import get_shared_llm
            llm = get_shared_llm()
            
            prompt = (
                "You are an internal support coordinator. "
                "Summarize the following customer support conversation into a concise briefing for a human agent. "
                "Highlight: 1) The core problem, 2) The customer's tone, 3) Any order/ticket details mentioned.\n\n"
                f"Raw Context:\n{context_summary}\n\n"
                "Briefing for Human Agent:"
            )
            
            response = llm.invoke(prompt)
            return response.content.strip()
        except Exception:
            return None

    def run(self, state: ConversationState) -> dict[str, Any]:
        session_id = state.get("session_id", "UNKNOWN")
        customer_id = state.get("user_id")
        tool_calls = list(state.get("tool_calls", []))
        escalation_reason = state.get("escalation_reason") or "manual"

        # ── Build raw context summary ──────────────────────────────────────
        messages = state.get("messages", [])
        recent_messages = messages[-10:] if len(messages) > 10 else messages
        context_parts = []
        for msg in recent_messages:
            if not isinstance(msg, dict):
                continue
            role = str(msg.get("role", "?")).upper()
            content = str(msg.get("content", ""))[:300]
            context_parts.append(f"[{role}]: {content}")
        raw_context = "\n".join(context_parts) or "No conversation context available."

        intent = state.get("intent", "unknown")
        confidence = state.get("confidence", 0.0)
        if not isinstance(confidence, (int, float)):
            confidence = 0.0
            
        retry_count = state.get("retry_count", 0)
        violations = state.get("guardrail_violations", [])

        # Use LLM briefing exclusively
        briefing = self._generate_briefing(state, raw_context)
        
        briefing_text = briefing or "No LLM briefing available due to processing error."
        
        summary_text = (
            f"--- LLM GENERATED BRIEFING ---\n{briefing_text}\n\n"
            f"--- SYSTEM METADATA ---\n"
            f"Intent: {intent} ({confidence:.0%}) | Reason: {escalation_reason}\n"
            f"Retries: {retry_count} | Violations: {', '.join(violations) or 'none'}"
        )

        # Determine priority
        priority = "normal"
        if escalation_reason in ("refund_threshold", "policy"):
            priority = "high"
        elif retry_count >= settings.max_retry_count:
            priority = "high"

        # ── Step 1: Create ticket ──────────────────────────────────────────
        try:
            ticket_result = self.call_tool(
                state,
                "create_ticket",
                create_ticket,
                session_id=session_id,
                customer_id=customer_id,
                reason=_ESCALATION_TYPE_MAP.get(escalation_reason, escalation_reason),
                escalation_type=escalation_reason,
                context_summary=summary_text,
                priority=priority,
            )
        except Exception as e:
            ticket_result = {"success": False, "error": str(e)}

        tool_calls.append(self._record_tool_call(
            state, "create_ticket",
            {"session_id": session_id, "escalation_type": escalation_reason}, ticket_result,
        ))

        ticket_id = ticket_result.get("ticket_id", "TKT-PENDING")

        # ── Step 2: Add to queue ───────────────────────────────────────────
        queue_pos = "N/A"
        if ticket_result.get("success"):
            try:
                queue_result = self.call_tool(
                    state,
                    "add_to_queue",
                    add_to_queue,
                    ticket_id=ticket_id,
                    priority=priority,
                )
                queue_pos = queue_result.get("queue_position", "N/A")
            except Exception as e:
                queue_result = {"success": False, "error": str(e)}
            
            tool_calls.append(self._record_tool_call(
                state, "add_to_queue",
                {"ticket_id": ticket_id, "priority": priority}, queue_result,
            ))

        # ── Log escalation event ───────────────────────────────────────────
        log_event(EscalationEvent(
            session_id=session_id,
            user_id=customer_id,
            reason=_ESCALATION_TYPE_MAP.get(escalation_reason, escalation_reason),
            escalation_type=escalation_reason,
            context_summary=summary_text[:500],
            ticket_id=ticket_id,
        ))

        # ── Build customer-facing response ─────────────────────────────────
        reason_desc = _ESCALATION_TYPE_MAP.get(escalation_reason, "this requires human attention")

        response = (
            f"🎧 **Connecting you with a human agent**\n\n"
            f"I've escalated your request because {reason_desc}.\n\n"
            f"**Support Ticket:** `{ticket_id}`\n"
            f"**Priority:** {priority.title()}\n"
            f"**Queue Position:** #{queue_pos}\n\n"
            f"A human agent will reach out to you within 2–4 hours. "
            f"Please reference ticket **{ticket_id}** in any follow-up communications.\n\n"
            f"We apologise for any inconvenience and appreciate your patience. 🙏"
        )

        return {
            "response": response,
            "tool_calls": tool_calls,
            "escalated": True,
        }
