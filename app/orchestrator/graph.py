"""
app/orchestrator/graph.py — LangGraph StateGraph: the orchestration core.

Node sequence per turn:
  pre_guardrail_check → classify_intent → route_agent →
  run_agent → post_guardrail_check → format_response

Conditional edges:
  - After pre_guardrail_check: if blocked → human_escalation_node, else → classify
  - After classify: if confidence_low → human_escalation_node, else → route
  - After route: branch to correct agent node
  - After agent: → post_guardrail_check
  - After post_guardrail_check: if escalated → human_escalation_node, else → END
"""
from __future__ import annotations

from typing import Any, Literal

from langgraph.graph import StateGraph, END

from app.agents.order_tracking import OrderTrackingAgent
from app.agents.refund_processing import RefundProcessingAgent
from app.agents.faq_resolution import FAQResolutionAgent
from app.agents.human_escalation import HumanEscalationAgent
from app.guardrails import (
    check_authentication_required,
    check_loop_detection,
    check_max_retry_count,
    check_max_clarification_turns,
    check_low_confidence,
)
from app.monitoring.logger import log_event
from app.models.events import AgentDecisionEvent
from app.orchestrator.classifier import classify
from app.orchestrator.router import route_to_agent, INTENT_TO_AGENT
from app.orchestrator.state import ConversationState

# ── Instantiate agents (singletons) ───────────────────────────────────────────
_order_agent = OrderTrackingAgent()
_refund_agent = RefundProcessingAgent()
_faq_agent = FAQResolutionAgent()
_escalation_agent = HumanEscalationAgent()

_AGENT_MAP = {
    "order_tracking": _order_agent,
    "refund_processing": _refund_agent,
    "faq_resolution": _faq_agent,
    "human_escalation": _escalation_agent,
}


# ═════════════════════════════════════════════════════════════════════════════
# NODE FUNCTIONS
# Each node receives the full state dict and returns a partial dict
# that LangGraph merges back into the state.
# ═════════════════════════════════════════════════════════════════════════════

def node_pre_guardrail_check(state: ConversationState) -> dict[str, Any]:
    """
    Pre-action guardrails:
      - max_retry_count
      - max_clarification_turns
      - loop_detection
      - authentication_required (intent-aware, set after classify but checked here
        once intent is available from a prior turn)
    
    If any guardrail fires, set escalated=True so the router will pick human_escalation.
    """
    violations = list(state.get("guardrail_violations", []))

    # Only run retry/clarification/loop checks after the first turn
    checks = [
        check_max_retry_count(state),
        check_max_clarification_turns(state),
        check_loop_detection(state),
    ]

    for result in checks:
        if not result.passed:
            violations.append(result.guardrail_name)
            return {
                "guardrail_violations": violations,
                "escalated": True,
                "escalation_reason": result.guardrail_name,
                "response": result.message,
            }

    return {"guardrail_violations": violations}


def node_classify_intent(state: ConversationState) -> dict[str, Any]:
    """Classify the current message and update intent/confidence/entities."""
    message = state.get("current_message", "")
    result = classify(message)

    intent_history = list(state.get("intent_history", []))
    intent_history.append(result.intent)

    return {
        "intent": result.intent,
        "confidence": result.confidence,
        "entities": result.entities,
        "intent_history": intent_history,
    }


def node_auth_and_confidence_check(state: ConversationState) -> dict[str, Any]:
    """
    Post-classification guardrails:
      - authentication_required (now that we know the intent)
      - low_confidence_escalation
    """
    violations = list(state.get("guardrail_violations", []))

    auth_check = check_authentication_required(state)
    if not auth_check.passed:
        violations.append(auth_check.guardrail_name)
        return {
            "guardrail_violations": violations,
            "escalated": False,  # auth block returns a message, doesn't escalate
            "response": auth_check.message,
            # Mark with a sentinel so the router returns immediately
            "agent": "__auth_blocked__",
        }

    confidence_check = check_low_confidence(state)
    if not confidence_check.passed:
        violations.append(confidence_check.guardrail_name)
        return {
            "guardrail_violations": violations,
            "escalated": True,
            "escalation_reason": "low_confidence",
            "response": confidence_check.message,
        }

    return {"guardrail_violations": violations}


def node_route_agent(state: ConversationState) -> dict[str, Any]:
    """Determine which agent to use and log the routing decision."""
    agent_name = route_to_agent(state)

    # Map agent_name to the internal agent key
    agent_key = agent_name  # already matches _AGENT_MAP keys after route_to_agent()

    log_event(AgentDecisionEvent(
        session_id=state["session_id"],
        user_id=state.get("user_id"),
        intent=state.get("intent", "unknown"),
        confidence=state.get("confidence", 0.0),
        agent_selected=agent_name,
        message_snippet=state.get("current_message", "")[:120],
    ))

    return {"agent": agent_name}


def node_run_agent(state: ConversationState) -> dict[str, Any]:
    """Execute the selected agent and merge its output."""
    agent_name = state.get("agent", "human_escalation")

    # If auth was blocked, skip agent execution (response already set)
    if agent_name == "__auth_blocked__":
        return {}

    agent = _AGENT_MAP.get(agent_name, _escalation_agent)
    result = agent.run(state)

    # Merge messages
    messages = list(state.get("messages", []))
    if result.get("response"):
        messages.append({"role": "assistant", "content": result["response"]})

    update = {**result, "messages": messages}
    return update


def node_post_guardrail_check(state: ConversationState) -> dict[str, Any]:
    """
    Post-action checks:
    - If the agent set escalated=True (e.g., faq_no_answer) → route to escalation
    - Otherwise do nothing (refund guardrail is enforced inside the refund agent)
    """
    # If the agent itself decided to escalate (e.g. faq agent), trigger escalation
    # next turn handling is done by the graph conditional edge
    return {}


# ═════════════════════════════════════════════════════════════════════════════
# CONDITIONAL EDGE FUNCTIONS
# These return the name of the next node to route to.
# ═════════════════════════════════════════════════════════════════════════════

def edge_after_pre_guardrail(
    state: ConversationState,
) -> Literal["classify_intent", "run_escalation"]:
    if state.get("escalated"):
        return "run_escalation"
    return "classify_intent"


def edge_after_auth_confidence(
    state: ConversationState,
) -> Literal["route_agent", "run_escalation", "end_auth_block"]:
    if state.get("agent") == "__auth_blocked__":
        return "end_auth_block"
    if state.get("escalated"):
        return "run_escalation"
    return "route_agent"


def edge_after_route(
    state: ConversationState,
) -> Literal["run_order", "run_refund", "run_faq", "run_escalation"]:
    agent = state.get("agent", "human_escalation")
    mapping = {
        "order_tracking": "run_order",
        "refund_processing": "run_refund",
        "faq_resolution": "run_faq",
        "human_escalation": "run_escalation",
    }
    return mapping.get(agent, "run_escalation")


def edge_after_agent(
    state: ConversationState,
) -> Literal["run_escalation", "post_guardrail"]:
    # If agent marked escalation (e.g. faq couldn't answer) → escalate now
    if state.get("escalated") and state.get("agent") != "human_escalation":
        return "run_escalation"
    return "post_guardrail"


# ═════════════════════════════════════════════════════════════════════════════
# GRAPH ASSEMBLY
# ═════════════════════════════════════════════════════════════════════════════

def build_graph() -> StateGraph:
    graph = StateGraph(ConversationState)

    # ── Nodes ──────────────────────────────────────────────────────────────
    graph.add_node("pre_guardrail", node_pre_guardrail_check)
    graph.add_node("classify_intent", node_classify_intent)
    graph.add_node("auth_confidence_check", node_auth_and_confidence_check)
    graph.add_node("route_agent", node_route_agent)

    # Dedicated node per agent (readable, explicit, easy to extend)
    graph.add_node("run_order", lambda s: node_run_agent({**s, "agent": "order_tracking"}))
    graph.add_node("run_refund", lambda s: node_run_agent({**s, "agent": "refund_processing"}))
    graph.add_node("run_faq", lambda s: node_run_agent({**s, "agent": "faq_resolution"}))
    graph.add_node("run_escalation", lambda s: node_run_agent({**s, "agent": "human_escalation"}))

    # Auth-blocked end node (just pass-through with response already set)
    graph.add_node("end_auth_block", lambda s: {})

    graph.add_node("post_guardrail", node_post_guardrail_check)

    # ── Entry ───────────────────────────────────────────────────────────────
    graph.set_entry_point("pre_guardrail")

    # ── Edges ───────────────────────────────────────────────────────────────
    graph.add_conditional_edges(
        "pre_guardrail",
        edge_after_pre_guardrail,
        {"classify_intent": "classify_intent", "run_escalation": "run_escalation"},
    )

    graph.add_edge("classify_intent", "auth_confidence_check")

    graph.add_conditional_edges(
        "auth_confidence_check",
        edge_after_auth_confidence,
        {
            "route_agent": "route_agent",
            "run_escalation": "run_escalation",
            "end_auth_block": "end_auth_block",
        },
    )

    graph.add_conditional_edges(
        "route_agent",
        edge_after_route,
        {
            "run_order": "run_order",
            "run_refund": "run_refund",
            "run_faq": "run_faq",
            "run_escalation": "run_escalation",
        },
    )

    # After each agent node → check if we need escalation
    for agent_node in ("run_order", "run_refund", "run_faq"):
        graph.add_conditional_edges(
            agent_node,
            edge_after_agent,
            {"run_escalation": "run_escalation", "post_guardrail": "post_guardrail"},
        )

    graph.add_edge("run_escalation", "post_guardrail")
    graph.add_edge("end_auth_block", END)
    graph.add_edge("post_guardrail", END)

    return graph


# Compile once at import time
compiled_graph = build_graph().compile()
