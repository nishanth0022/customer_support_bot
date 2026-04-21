"""
app/api/health.py — GET /health endpoint.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.api.session_store import session_count
from app.models.responses import HealthResponse
from app.monitoring.logger import event_count

router = APIRouter()

APP_VERSION = "1.0.0"


@router.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check() -> HealthResponse:
    """Liveness + readiness health check."""
    return HealthResponse(
        status="healthy",
        version=APP_VERSION,
        active_sessions=session_count(),
        log_event_count=event_count(),
    )
