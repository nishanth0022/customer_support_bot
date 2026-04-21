"""
app/agents/faq_resolution.py — FAQ Resolution Agent.

Handles: policy questions, general support questions.
Tools:   search_knowledge_base

Strict policy: ONLY answers from the approved knowledge base.
Low-confidence KB matches are escalated to human rather than hallucinated.
"""
from __future__ import annotations

from typing import Any

from app.agents.base import BaseAgent
from app.config import settings
from app.orchestrator.state import ConversationState
from app.tools.faq_tools import search_knowledge_base


class FAQResolutionAgent(BaseAgent):
    name = "faq_resolution"
    tool_allowlist = settings.faq_agent_tools

    # Minimum KB confidence to return an answer (below this → escalate)
    MIN_ANSWER_CONFIDENCE = 0.25

    def _synthesize_answer(self, user_query: str, kb_answer: str, category: str) -> str | None:
        """Use LLM to rephrase the KB answer into a natural response."""
        try:
            from app.orchestrator.llm import get_shared_llm
            llm = get_shared_llm()
            
            prompt = (
                "You are a helpful customer support agent. "
                "Answer the user's question based ONLY on the provided knowledge base entry. "
                "Maintain a professional and friendly tone. "
                "If the information is not in the entry, do not make it up.\n\n"
                f"Knowledge Base Category: {category}\n"
                f"Knowledge Base Entry: {kb_answer}\n\n"
                f"User Question: {user_query}\n\n"
                "Helpful Response:"
            )
            
            response = llm.invoke(prompt)
            return response.content.strip()
        except Exception as e:
            print(f"[AI] FAQ Synthesis Error: {str(e)}")
            return None

    def run(self, state: ConversationState) -> dict[str, Any]:
        message = state.get("current_message", "")
        tool_calls = list(state.get("tool_calls", []))

        result = self.call_tool(
            state,
            "search_knowledge_base",
            search_knowledge_base,
            query=message,
        )
        tool_calls.append(self._record_tool_call(
            state, "search_knowledge_base", {"query": message}, result,
        ))

        if not result.get("found") or result.get("confidence", 0) < self.MIN_ANSWER_CONFIDENCE:
            # Cannot confidently answer → escalate to human
            response = (
                "I wasn't able to find a confident answer in our knowledge base for your question.\n\n"
                "Let me connect you with a human support agent who can give you an accurate answer."
            )
            return {
                "response": response,
                "tool_calls": tool_calls,
                "escalated": True,
                "escalation_reason": "faq_no_answer",
            }

        confidence = result.get("confidence", 0)
        answer = result.get("answer", "")
        category = result.get("category", "general").title()

        # Use LLM synthesis exclusively for response generation
        print(f"\n[AI] FAQ Agent using Groq to synthesize response for: '{message}'")
        synthesized = self._synthesize_answer(message, answer, category)
        
        response = synthesized or "I'm currently experiencing an AI processing issue. Please try again in a moment."

        return {
            "response": response,
            "tool_calls": tool_calls,
            "confidence": confidence,
        }
