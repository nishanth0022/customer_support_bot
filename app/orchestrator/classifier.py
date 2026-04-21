"""
app/orchestrator/classifier.py — Rule-based intent classifier.

Classifies customer messages into one of 5 intents and extracts entities.
No LLM required — works fully offline and deterministically.

Intents:
  order_tracking  — asking about order status, shipping, delivery
  refund          — requesting a refund or return
  faq             — policy/general questions answerable from knowledge base
  escalation      — explicit escalation request ("speak to human", etc.)
  unknown         — cannot be classified with sufficient confidence
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ClassificationResult:
    intent: str
    confidence: float
    entities: dict[str, Any] = field(default_factory=dict)


# ── Entity extraction ─────────────────────────────────────────────────────────

_ORDER_ID_PATTERN = re.compile(r"\b(ORD-\d+)\b", re.IGNORECASE)
_AMOUNT_PATTERN = re.compile(r"\$\s*(\d+(?:\.\d{1,2})?)")


def _extract_entities(text: str) -> dict[str, Any]:
    entities: dict[str, Any] = {}

    order_ids = _ORDER_ID_PATTERN.findall(text)
    if order_ids:
        entities["order_id"] = order_ids[0].upper()
        entities["all_order_ids"] = [o.upper() for o in order_ids]

    amounts = _AMOUNT_PATTERN.findall(text)
    if amounts:
        entities["amount"] = float(amounts[0])

    return entities


# ── Scoring ───────────────────────────────────────────────────────────────────

# ── LLM Semantic Classifier ──────────────────────────────────────────────────

_CLASSIFICATION_PROMPT = """
You are an expert customer support intent classifier for an e-commerce company.
Your goal is to classify the user's message into EXACTLY ONE of the following 5 intents:

- order_tracking: Questions about status, delivery dates, or shipping of existing orders.
- refund: Requests for refunds, returns, money back, or reporting damaged/wrong items for return.
- faq: General policy questions (shipping times, free shipping criteria, store hours, accepted payments) that don't involve a specific order action.
- escalation: Explicit requests for a human, a manager, or expressions of extreme frustration/anger.
- unknown: Messages that are gibberish, irrelevant, or too vague to classify.

RULES:
1. Return ONLY the JSON object with two fields: "intent" and "confidence".
2. If the user asks for "return policy", that is 'faq'. If they say "I want to return this", that is 'refund'.
3. Always extract the order ID if present.

EXAMPLES:
- "Where is ORD-123?" -> {"intent": "order_tracking", "confidence": 0.98}
- "I need a refund for my broken camera" -> {"intent": "refund", "confidence": 0.95}
- "Do you ship to Canada?" -> {"intent": "faq", "confidence": 0.99}
- "Speak to a human now!" -> {"intent": "escalation", "confidence": 0.99}
- "hello" -> {"intent": "unknown", "confidence": 0.8}

Message: "{message}"
"""

def _classify_with_llm(message: str) -> ClassificationResult | None:
    """Attempt semantic classification using Groq LLM."""
    try:
        from app.orchestrator.llm import get_shared_llm
        import json
        
        llm = get_shared_llm()
        prompt = _CLASSIFICATION_PROMPT.replace("{message}", message)
        
        # Use simple invoke for now
        response = llm.invoke(prompt)
        text = response.content.strip()
        
        # Clean up JSON if LLM included prose
        if "{" in text and "}" in text:
            text = text[text.find("{"):text.rfind("}")+1]
            
        data = json.loads(text)
        
        # Explicit print for user verification in console
        print(f"\n[AI] LLM classified intent as: {data.get('intent')} (confidence: {data.get('confidence')})")
        
        return ClassificationResult(
            intent=data.get("intent", "unknown"),
            confidence=float(data.get("confidence", 0.6)),
            entities=_extract_entities(message)
        )
    except Exception as e:
        print(f"[AI] LLM Classification Error: {str(e)}")
        return None

def classify(message: str) -> ClassificationResult:
    """
    Classify a customer message into one of 5 intents.
    Relies entirely on the LLM for semantic classification.
    """
    text = message.strip()
    entities = _extract_entities(text)

    # 1. Ask LLM to classify
    llm_result = _classify_with_llm(text)
    
    if llm_result:
        # Merge entities just in case LLM missed them (rules are very good at regex)
        llm_result.entities.update(entities) 
        return llm_result

    # 2. If LLM fails (e.g. connection error), fail gracefully to unknown
    return ClassificationResult(intent="unknown", confidence=0.0, entities=entities)

