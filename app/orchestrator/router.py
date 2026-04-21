"""
app/orchestrator/router.py — Agent routing logic.

Maps classified intents to the correct agent + handles pre-routing guardrail checks.
"""
from __future__ import annotations

from app.orchestrator.state import ConversationState

# Intent → agent name
INTENT_TO_AGENT: dict[str, str] = {
    "order_tracking": "order_tracking",
    "refund": "refund_processing",
    "faq": "faq_resolution",
    "escalation": "human_escalation",
    "unknown": "human_escalation",
}


def route_to_agent(state: ConversationState) -> str:
    """
    Return the name of the agent to use for the current intent.
    If already escalated, always go to human_escalation.
    """
    if state.get("escalated"):
        return "human_escalation"
    intent = state.get("intent", "unknown")
    return INTENT_TO_AGENT.get(intent, "human_escalation")
