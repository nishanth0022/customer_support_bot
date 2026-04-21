"""
app/main.py — FastAPI application entry point.
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.chat import router as chat_router
from app.api.session import router as session_router
from app.api.logs import router as logs_router
from app.api.approval import router as approval_router
from app.api.health import router as health_router

# ── App factory ────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Agentic AI Customer Support System",
    description=(
        "Production-ready multi-agent customer support backend. "
        "Routes queries to specialised agents for order tracking, refund processing, "
        "FAQ resolution, and human escalation — with full guardrails and observability."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# ── CORS (configure for your frontend origin in production) ────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routers ────────────────────────────────────────────────────────────────────
app.include_router(health_router)
app.include_router(chat_router)
app.include_router(session_router)
app.include_router(logs_router)
app.include_router(approval_router)


@app.get("/", tags=["Root"])
async def root() -> dict:
    return {
        "service": "Agentic AI Customer Support System",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
    }
