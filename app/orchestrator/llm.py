"""
app/orchestrator/llm.py — LLM Service (Groq).

Initializes and provides the ChatGroq instance for semantic classification 
and conversational response generation.
"""
from __future__ import annotations

import os
from langchain_groq import ChatGroq

from app.config import settings

def get_llm() -> ChatGroq:
    """
    Initialize and return a ChatGroq instance.
    Uses the configuration defined in settings.
    """
    # Prefer explicit setting, fallback to environment variable
    api_key = settings.groq_api_key or os.getenv("GROQ_API_KEY")
    
    if not api_key:
        # If no key is available, the system will fallback to rule-based logic
        # through exception handling in the calling modules.
        raise ValueError("GROQ_API_KEY is not configured.")

    return ChatGroq(
        groq_api_key=api_key,
        model_name=settings.llm_model,
        temperature=settings.llm_temperature,
    )

# Shared instance (lazy-loaded if needed, but here we'll just expose the factory)
_llm: ChatGroq | None = None

def get_shared_llm() -> ChatGroq:
    global _llm
    if _llm is None:
        _llm = get_llm()
    return _llm
