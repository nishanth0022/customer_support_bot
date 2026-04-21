# Agentic AI Customer Support System

A production-ready, orchestrator-based multi-agent customer support backend for a large e-commerce company. Powered by **LLM-based Semantic Intelligence** using **Groq (Llama 3.1)** and orchestrated with **LangGraph**.

---

## Architecture

```
Customer Query (POST /chat)
         │
         ▼
   Session Manager ──► creates/resumes ConversationState
         │
         ▼
   LangGraph Orchestrator (StateGraph)
         │
    ┌─────┴──────────────────────────────────────┐
    │ 1. pre_guardrail    ← retry, loop, clari.  │
    │ 2. classify_intent  ← semantic LLM (Groq)  │
    │ 3. auth_confidence  ← auth + confidence    │
    │ 4. route_agent      ← intent → agent       │
    │ 5. run_agent        ← execute agent (LLM)  │
    │ 6. post_guardrail   ← final checks         │
    └─────┬──────────────────────────────────────┘
         │
   ┌─────┴──── Specialized Agents ─────────────┐
   │  OrderTrackingAgent    (order_tracking)    │
   │  RefundProcessingAgent (refund_processing) │
   │  FAQResolutionAgent    (faq_resolution)    │
   │  HumanEscalationAgent  (human_escalation)  │
   └────────────────────────────────────────────┘
         │
         ▼
   Structured JSON Response → /chat
```

### Key Design Decisions
- **LangGraph `StateGraph`**: Makes every routing decision explicit as a node/edge — easy to read, debug, and extend.
- **LLM-Powered Semantic Intelligence**: Uses Groq (Llama 3.1) for high-accuracy intent classification and natural language generation.
- **Pure LLM Classifier**: Relies entirely on Groq to understand the *meaning* of the message, replacing fragile keyword heuristics.
- **Conversational Synthesis**: Agents don't just return raw tool data; they use the LLM to synthesize friendly, context-aware responses.
- **10 Production Guardrails**: Enforced at both pre- and post-action stages to ensure safety and policy compliance.

---

## Folder Structure

```
customer_support_bot/
├── app/
│   ├── main.py                     # FastAPI entry point
│   ├── config.py                   # Settings (env vars + thresholds)
│   ├── orchestrator/
│   │   ├── graph.py                # LangGraph StateGraph
│   │   ├── classifier.py           # Rule-based intent classifier
│   │   ├── router.py               # Intent → agent routing
│   │   └── state.py                # ConversationState TypedDict
│   ├── agents/
│   │   ├── base.py                 # BaseAgent ABC + tool enforcement
│   │   ├── order_tracking.py
│   │   ├── refund_processing.py
│   │   ├── faq_resolution.py
│   │   └── human_escalation.py
│   ├── tools/                      # Mock external services
│   │   ├── order_tools.py
│   │   ├── refund_tools.py
│   │   ├── faq_tools.py
│   │   └── escalation_tools.py
│   ├── guardrails/
│   │   └── guardrails.py           # All 10 guardrails
│   ├── monitoring/
│   │   └── logger.py               # Structured JSON event logger
│   ├── models/
│   │   ├── requests.py             # Pydantic request models
│   │   ├── responses.py            # Pydantic response models
│   │   └── events.py               # Typed event schemas
│   ├── api/
│   │   ├── chat.py                 # POST /chat
│   │   ├── session.py              # GET /session/{id}
│   │   ├── logs.py                 # GET /logs
│   │   ├── approval.py             # POST /human-approval
│   │   ├── health.py               # GET /health
│   │   └── session_store.py        # In-memory session store
│   └── data/
│       ├── mock_orders.json         # 10 sample orders
│       └── faq_knowledge_base.json  # 20 approved FAQs
├── tests/
│   ├── test_routing.py
│   ├── test_guardrails.py
│   ├── test_escalation.py
│   ├── test_agents.py
│   └── test_api.py
├── logs/                            # Runtime log output (auto-created)
├── requirements.txt
├── .env.example
├── pytest.ini
└── README.md
```

---

## How Routing Works

1. **Classify**: The `classifier.py` module uses **Groq (Llama 3.1)** to semantically analyze the customer message and map it to an intent (e.g., "Where's my stuff?" -> `order_tracking`). If the LLM throws an error or fails, it natively falls back to an `unknown` state to trigger safety mechanisms.

2. **Route**: `router.py` maps the detected `intent → agent name`. The `escalated` flag (triggered by guardrails or explicit user request) always overrides to `human_escalation`.

3. **Guard**: Before and after routing, 10 guardrails are evaluated. Any violation either blocks the action, escalates it, or logs a warning.

---

## How Guardrails Work

| # | Name | Trigger | Action |
|---|------|---------|--------|
| 1 | `refund_amount_limit` | Refund > $100 | Escalate, require human approval |
| 2 | `authentication_required` | Order/refund intent without auth token | Block, return auth prompt |
| 3 | `session_data_isolation` | Access to another user's data | Block |
| 4 | `max_retry_count` | ≥ 3 tool failures | Escalate to human |
| 5 | `max_clarification_turns` | ≥ 3 clarification rounds | Escalate to human |
| 6 | `low_confidence_escalation` | Confidence < 0.6 | Escalate to human |
| 7 | `tool_allowlist` | Agent calls unlisted tool | Block (`ToolNotAllowedError`) |
| 8 | `loop_detection` | Same intent 5× in a row | Escalate to human |
| 9 | `policy_violation_blocking` | Categorically disallowed action | Block |
| 10 | `sensitive_data_isolation` | PII in output text | Scrub + warn |

---

## How to Run Locally

### Prerequisites
- Python 3.10+
- Groq API Key (Place in `.env` as `GROQ_API_KEY`)
- pip

### 1. Clone & enter directory
```bash
cd customer_support_bot
```

### 2. Create virtual environment
```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS/Linux
source venv/bin/activate
```

### 3. Install dependencies
```bash
pip install -r requirements.txt
```

### 4. Configure environment (optional)
```bash
cp .env.example .env
# Edit .env to change thresholds, log path, etc.
```

### 5. Start the server
```bash
uvicorn app.main:app --reload --port 8000
```

### 6. Open API docs
- Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
- ReDoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)

---

## How to Run Tests

```bash
# Run all tests
pytest tests/ -v

# Run a specific test file
pytest tests/test_guardrails.py -v

# Run with output for debugging
pytest tests/ -v -s

# Coverage report (install pytest-cov first)
pip install pytest-cov
pytest tests/ --cov=app --cov-report=term-missing
```

---

## Example API Requests

### 1. Normal order tracking (authenticated)
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-Customer-Token: tok-cust-100" \
  -d '{"message": "Where is my order ORD-001?"}'
```

### 2. Eligible refund under threshold ($45 order)
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-Customer-Token: tok-cust-106" \
  -d '{"message": "I want a refund for order ORD-009"}'
```

### 3. Refund over threshold → human approval required ($1249 order)
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -H "X-Customer-Token: tok-cust-101" \
  -d '{"message": "I need to return my order ORD-003 and get a refund"}'
```

### 4. Approve a pending refund (as human reviewer)
```bash
curl -X POST http://localhost:8000/human-approval \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "<session_id_from_above>",
    "approval_id": "<APR-XXXXXXXX_from_above>",
    "approved": true,
    "reviewer_note": "Verified: laptop was defective"
  }'
```

### 5. FAQ question (no auth required)
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "What is your return policy?"}'
```

### 6. Blocked without authentication
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Where is my order ORD-001 and what is the tracking number?"}'
  # No X-Customer-Token → blocked
```

### 7. Low confidence → escalation
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "ugh this is so bad!!!"}'
```

### 8. View session state
```bash
curl http://localhost:8000/session/<session_id>
```

### 9. View all logs
```bash
curl "http://localhost:8000/logs?limit=50"

# Filter by event type
curl "http://localhost:8000/logs?event_type=GUARDRAIL_VIOLATION"

# Filter by session
curl "http://localhost:8000/logs?session_id=<session_id>"
```

### 10. Health check
```bash
curl http://localhost:8000/health
```

---

## Mock Customer Tokens

| Token | Customer ID | Orders |
|-------|-------------|--------|
| `tok-cust-100` | CUST-100 | ORD-001 (shipped), ORD-002 (delivered), ORD-005 (cancelled) |
| `tok-cust-101` | CUST-101 | ORD-003 (delivered, $1249) |
| `tok-cust-102` | CUST-102 | ORD-004 (processing) |
| `tok-cust-103` | CUST-103 | ORD-006 (shipped, $299) |
| `tok-cust-104` | CUST-104 | ORD-007 (delivered) |
| `tok-cust-105` | CUST-105 | ORD-008 (return_requested) |
| `tok-cust-106` | CUST-106 | ORD-009 (delivered, **$45** — under refund limit) |
| `tok-cust-107` | CUST-107 | ORD-010 (shipped, $899) |

---

## Monitoring / Observability

All events are written to:
- **stdout** as JSON lines (structured, suitable for log aggregators like Datadog, Splunk, CloudWatch)
- **`logs/events.jsonl`** on disk (local dev inspection)
- **In-memory ring buffer** (last 10,000 events, queryable via `GET /logs`)

### Event Types

| Event Type | Emitted When |
|-----------|--------------|
| `SESSION_START` | New session created |
| `AGENT_DECISION` | Intent classified + agent selected |
| `TOOL_CALL` | Any agent calls a tool |
| `GUARDRAIL_PASS` | A guardrail check passes |
| `GUARDRAIL_VIOLATION` | A guardrail check fails |
| `ESCALATION` | Query escalated to human agent |
| `HUMAN_APPROVAL` | Approval resolved by human reviewer |
| `SESSION_END` | Session ends (not yet implemented in v1) |

### Sample Event

```json
{
  "timestamp": "2026-04-21T14:00:00.123Z",
  "session_id": "a1b2c3d4-...",
  "user_id": "CUST-100",
  "event_type": "TOOL_CALL",
  "agent": "refund_processing",
  "tool_name": "calculate_refund_amount",
  "inputs": {"order_id": "ORD-003", "reason": "customer_request"},
  "outputs": {"success": true, "refund_amount": 1249.00},
  "success": true,
  "duration_ms": 3,
  "guardrail_status": "PASS"
}
```

---

## Assumptions

1. **100% LLM Driven**: The system utilizes the `langchain-groq` library. All intents, responses, and summaries are generated dynamically by Llama 3.1 70B—static rule-based templates have been entirely removed.
2. **In-memory storage**: Sessions and pending approvals are stored in memory. A restart clears all state. Replace with Redis + PostgreSQL for production.
3. **Auth via header**: Authentication is simulated with `X-Customer-Token`. Map this to JWTs/OAuth in production.
4. **Mock external systems**: All tools (order lookup, refund submission, ticket creation) are mocked. Wire up real payment gateways and CRM APIs in production.
5. **Refund threshold**: Default `$100.00`. Change via `REFUND_AUTO_APPROVE_LIMIT` in `.env`.
6. **Return window**: 30 days from order placement (for delivered orders).

---

## Extending the System

### Adding a new agent
1. Create `app/agents/my_new_agent.py` subclassing `BaseAgent`
2. Add the agent name + allowlist to `app/config.py`
3. Add the intent keyword patterns to `app/orchestrator/classifier.py`
4. Add the intent → agent mapping in `app/orchestrator/router.py`
5. Add a node in `app/orchestrator/graph.py`
6. Add a conditional edge in `edge_after_route()`

That's it. All guardrails, monitoring, and session management are inherited automatically.

---

## Configuration Reference

| Variable | Default | Description |
|----------|---------|-------------|
| `GROQ_API_KEY` | | Your Groq API Key (Required) |
| `LLM_MODEL` | `llama-3.1-70b-versatile` | Groq model for classification/generation |
| `LLM_TEMPERATURE` | `0.1` | LLM temperature (low for deterministic logic) |
| `REFUND_AUTO_APPROVE_LIMIT` | `100.0` | Max USD for auto-refund |
| `MAX_RETRY_COUNT` | `3` | Tool failures before escalation |
| `MAX_CLARIFICATION_TURNS` | `3` | Clarification rounds before escalation |
| `MAX_LOOP_DETECTION_WINDOW` | `5` | Consecutive identical intents = loop |
| `LOW_CONFIDENCE_THRESHOLD` | `0.6` | Min confidence to avoid escalation |
| `LOG_LEVEL` | `INFO` | Logging level |
| `LOG_FILE` | `logs/events.jsonl` | Log file path |

### Environment Setup (`.env` file)
Your `.env` file should look like this (do not commit your actual key):

```bash
# ── Customer Support Bot — Environment Configuration ──────────────────────────

# Refund auto-approve threshold (USD)
REFUND_AUTO_APPROVE_LIMIT=100.0

# Retry / loop limits
MAX_RETRY_COUNT=3
MAX_CLARIFICATION_TURNS=3
MAX_LOOP_DETECTION_WINDOW=5

# Confidence below this → escalate to human
LOW_CONFIDENCE_THRESHOLD=0.6

# Session
SESSION_TTL_SECONDS=3600

# Logging
LOG_LEVEL=INFO
LOG_FILE=logs/events.jsonl

# --- Groq LLM Configuration ---
GROQ_API_KEY=
LLM_MODEL=llama-3.1-70b-versatile
LLM_TEMPERATURE=0.1
```