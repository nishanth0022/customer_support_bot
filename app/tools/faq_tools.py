"""
app/tools/faq_tools.py — Knowledge base search tool.

Only returns answers from the approved FAQ knowledge base.
Never fabricates or infers answers beyond what's in the KB.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_KB_FILE = Path(__file__).parent.parent / "data" / "faq_knowledge_base.json"
_KB: list[dict[str, Any]] | None = None


def _load_kb() -> list[dict[str, Any]]:
    global _KB
    if _KB is None:
        data = json.loads(_KB_FILE.read_text(encoding="utf-8"))
        _KB = data["faqs"]
    return _KB


def _score(query_lower: str, faq: dict[str, Any]) -> float:
    """Simple keyword overlap score between query and FAQ entry."""
    score = 0.0
    keywords: list[str] = faq.get("keywords", [])
    question: str = faq.get("question", "").lower()
    answer: str = faq.get("answer", "").lower()

    for kw in keywords:
        if kw.lower() in query_lower:
            score += 2.0  # keyword match = strong signal

    # Direct word overlap with question
    q_words = set(question.split())
    query_words = set(query_lower.split())
    overlap = q_words & query_words
    score += len(overlap) * 0.5

    return score


def search_knowledge_base(query: str, top_k: int = 3) -> dict[str, Any]:
    """
    Search the approved FAQ knowledge base for the best matching answer.
    Returns the top match (if score > threshold) plus confidence.
    """
    faqs = _load_kb()
    query_lower = query.lower()

    scored = [(faq, _score(query_lower, faq)) for faq in faqs]
    scored.sort(key=lambda x: x[1], reverse=True)

    top = scored[:top_k]
    best_faq, best_score = top[0]

    # Normalise score to a 0-1 confidence range
    max_possible = 10.0
    confidence = min(best_score / max_possible, 1.0)

    if best_score == 0.0:
        return {
            "success": True,
            "found": False,
            "confidence": 0.0,
            "message": "No relevant FAQ found for this query.",
            "answer": None,
        }

    return {
        "success": True,
        "found": True,
        "faq_id": best_faq["id"],
        "category": best_faq["category"],
        "question": best_faq["question"],
        "answer": best_faq["answer"],
        "confidence": round(confidence, 3),
        "alternatives": [
            {"faq_id": f["id"], "question": f["question"], "score": s}
            for f, s in top[1:]
            if s > 0
        ],
    }
