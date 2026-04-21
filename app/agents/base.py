"""
app/agents/base.py — BaseAgent ABC.

Provides:
- Tool allowlist enforcement (raises ToolNotAllowedError on violation)
- Instrumented tool call wrapper that logs ToolCallEvent + measures duration
- Retry counting passed back to state
"""
from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any, Callable

from app.config import settings
from app.guardrails import check_tool_allowlist
from app.monitoring.logger import log_event
from app.models.events import ToolCallEvent, GuardrailStatus
from app.orchestrator.state import ConversationState, ToolCallRecord


class ToolNotAllowedError(RuntimeError):
    """Raised when an agent attempts to call a tool outside its allowlist."""


class BaseAgent(ABC):
    name: str  # must be set by subclass
    tool_allowlist: list[str]  # must be set by subclass

    @abstractmethod
    def run(self, state: ConversationState) -> dict[str, Any]:
        """
        Execute agent logic. Returns a partial state dict to merge into
        the main ConversationState.
        """

    def call_tool(
        self,
        state: ConversationState,
        tool_name: str,
        tool_fn: Callable[..., Any],
        **kwargs: Any,
    ) -> dict[str, Any]:
        """
        Execute a tool call with:
          1) Allowlist check (via guardrail)
          2) Structured event logging
          3) Duration measurement
          4) Error handling
        """
        # ── Guardrail: tool allowlist ──────────────────────────────────────
        guard = check_tool_allowlist(state, self.name, tool_name)
        if not guard.passed:
            raise ToolNotAllowedError(guard.message)

        # ── Execute tool ───────────────────────────────────────────────────
        t0 = time.monotonic()
        outputs: dict[str, Any] | None = None
        error_msg: str | None = None
        success = True

        try:
            outputs = tool_fn(**kwargs)
        except Exception as exc:
            success = False
            error_msg = str(exc)
            outputs = None

        duration_ms = int((time.monotonic() - t0) * 1000)

        # ── Log the tool call ──────────────────────────────────────────────
        log_event(ToolCallEvent(
            session_id=state["session_id"],
            user_id=state.get("user_id"),
            agent=self.name,
            tool_name=tool_name,
            inputs=kwargs,
            outputs=outputs,
            success=success,
            error_message=error_msg,
            duration_ms=duration_ms,
            guardrail_status=GuardrailStatus.PASS,
        ))

        if not success:
            return {"success": False, "error": error_msg}
        return outputs or {}

    def _record_tool_call(
        self,
        state: ConversationState,
        tool_name: str,
        inputs: dict[str, Any],
        result: dict[str, Any],
    ) -> ToolCallRecord:
        return ToolCallRecord(
            tool_name=tool_name,
            agent=self.name,
            inputs=inputs,
            outputs=result,
            success=result.get("success", True),
            error=result.get("error"),
        )
