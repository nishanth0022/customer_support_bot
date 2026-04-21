"""
app/config.py — Application-wide settings loaded from environment / .env file.
"""
from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── Refund guardrail ───────────────────────────────────────────────────────
    refund_auto_approve_limit: float = 100.0  # USD

    # ── Retry / loop protection ────────────────────────────────────────────────
    max_retry_count: int = 3
    max_clarification_turns: int = 3
    max_loop_detection_window: int = 5  # identical consecutive intents

    # ── Confidence escalation ──────────────────────────────────────────────────
    low_confidence_threshold: float = 0.60

    # ── Session ────────────────────────────────────────────────────────────────
    session_ttl_seconds: int = 3_600

    # ── Logging ───────────────────────────────────────────────────────────────
    log_level: str = "INFO"
    log_file: str = "logs/events.jsonl"

    # ── LLM Configuration (Groq) ──────────────────────────────────────────────
    groq_api_key: str = ""
    llm_model: str = "llama-3.1-70b-versatile"
    llm_temperature: float = 0.1

    # ── Tool allowlists per agent ──────────────────────────────────────────────
    # These are enforced by BaseAgent; any tool NOT in the list raises an error.
    order_agent_tools: list[str] = [
        "lookup_order",
        "get_shipping_status",
    ]
    refund_agent_tools: list[str] = [
        "check_refund_eligibility",
        "calculate_refund_amount",
        "submit_refund_auto",
        "request_human_approval",
    ]
    faq_agent_tools: list[str] = [
        "search_knowledge_base",
    ]
    escalation_agent_tools: list[str] = [
        "create_ticket",
        "add_to_queue",
    ]


# Singleton exposed across the app
settings = Settings()
