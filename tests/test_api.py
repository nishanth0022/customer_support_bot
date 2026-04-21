"""
tests/test_api.py — Integration tests for all 5 API endpoints.

Uses FastAPI's TestClient (synchronous) to exercise the full pipeline.
"""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


# ── Health ─────────────────────────────────────────────────────────────────────

class TestHealthEndpoint:
    def test_health_returns_200(self):
        r = client.get("/health")
        assert r.status_code == 200

    def test_health_response_schema(self):
        r = client.get("/health")
        data = r.json()
        assert data["status"] == "healthy"
        assert "version" in data
        assert "active_sessions" in data
        assert "log_event_count" in data


# ── Chat ───────────────────────────────────────────────────────────────────────

class TestChatEndpoint:

    # ── Scenario 1: Normal order tracking ──────────────────────────────────
    def test_order_tracking_authenticated(self):
        r = client.post(
            "/chat",
            json={"message": "Where is my order ORD-001?"},
            headers={"X-Customer-Token": "tok-cust-100"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["intent"] == "order_tracking"
        assert data["agent_used"] == "order_tracking"
        assert "ORD-001" in data["response"]
        assert data["escalated"] is False

    # ── Scenario 2: Eligible refund under threshold ─────────────────────
    def test_refund_under_threshold(self):
        r = client.post(
            "/chat",
            json={"message": "I want a refund for ORD-009"},
            headers={"X-Customer-Token": "tok-cust-106"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["intent"] == "refund"
        assert "approved" in data["response"].lower()
        assert data["pending_approval"] is None

    # ── Scenario 3: Refund over threshold → human approval ──────────────
    def test_refund_over_threshold_requires_approval(self):
        r = client.post(
            "/chat",
            json={"message": "I need a refund for order ORD-003"},
            headers={"X-Customer-Token": "tok-cust-101"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["pending_approval"] is not None
        assert "APR-" in data["response"]
        assert "refund_amount_limit" in data["guardrail_violations"]

    # ── Scenario 4: FAQ question answered from knowledge base ────────────
    def test_faq_return_policy(self):
        r = client.post(
            "/chat",
            json={"message": "What is your return policy?"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["intent"] == "faq"
        assert data["agent_used"] == "faq_resolution"
        assert "30" in data["response"]
        assert data["escalated"] is False

    # ── Scenario 5: Sensitive request blocked without auth ───────────────
    def test_order_tracking_no_auth_blocked(self):
        r = client.post(
            "/chat",
            json={"message": "Where is my order ORD-001? I need to track it."},
            # No X-Customer-Token header
        )
        assert r.status_code == 200
        data = r.json()
        # Should be blocked by authentication guardrail
        assert "authentication_required" in data["guardrail_violations"]
        assert "token" in data["response"].lower() or "verify" in data["response"].lower()

    # ── Scenario 6: Low-confidence query escalates to human ─────────────
    def test_low_confidence_escalates(self):
        r = client.post(
            "/chat",
            json={"message": "ugh!!!"},
        )
        assert r.status_code == 200
        data = r.json()
        # Very low confidence → escalation
        assert data["escalated"] is True or data["confidence"] < 0.6

    # ── Scenario 7: Explicit escalation request ──────────────────────────
    def test_explicit_escalation_request(self):
        r = client.post(
            "/chat",
            json={"message": "I want to speak to a human agent"},
        )
        assert r.status_code == 200
        data = r.json()
        assert data["intent"] == "escalation"
        assert data["escalated"] is True
        assert "TKT-" in data["response"]

    # ── Session continuity ────────────────────────────────────────────────
    def test_session_continuity(self):
        """Second message using the same session_id should work."""
        r1 = client.post(
            "/chat",
            json={"message": "What is your return policy?"},
        )
        session_id = r1.json()["session_id"]

        r2 = client.post(
            "/chat",
            json={"message": "What payment methods do you accept?", "session_id": session_id},
        )
        assert r2.status_code == 200
        assert r2.json()["session_id"] == session_id

    # ── Invalid session ───────────────────────────────────────────────────
    def test_invalid_session_returns_404(self):
        r = client.post(
            "/chat",
            json={"message": "Hello", "session_id": "nonexistent-session-id"},
        )
        assert r.status_code == 404


# ── Session endpoint ───────────────────────────────────────────────────────────

class TestSessionEndpoint:
    def test_session_details_returned(self):
        # Create a session via chat
        r1 = client.post("/chat", json={"message": "What is your return policy?"})
        session_id = r1.json()["session_id"]

        r2 = client.get(f"/session/{session_id}")
        assert r2.status_code == 200
        data = r2.json()
        assert data["session_id"] == session_id
        assert len(data["messages"]) >= 2  # user + assistant

    def test_unknown_session_returns_404(self):
        r = client.get("/session/totally-fake-id")
        assert r.status_code == 404


# ── Logs endpoint ─────────────────────────────────────────────────────────────

class TestLogsEndpoint:
    def test_logs_returns_events(self):
        # Make some traffic first
        client.post("/chat", json={"message": "What is your return policy?"})
        r = client.get("/logs")
        assert r.status_code == 200
        data = r.json()
        assert "events" in data
        assert data["count"] >= 0

    def test_logs_filter_by_event_type(self):
        r = client.get("/logs?event_type=AGENT_DECISION&limit=10")
        assert r.status_code == 200
        data = r.json()
        for event in data["events"]:
            assert event["event_type"] == "AGENT_DECISION"

    def test_logs_limit_respected(self):
        r = client.get("/logs?limit=5")
        assert r.status_code == 200
        assert len(r.json()["events"]) <= 5


# ── Human Approval endpoint ───────────────────────────────────────────────────

class TestHumanApprovalEndpoint:
    def test_approve_large_refund(self):
        # First, create a large refund request
        r1 = client.post(
            "/chat",
            json={"message": "I need a refund for order ORD-003"},
            headers={"X-Customer-Token": "tok-cust-101"},
        )
        data = r1.json()
        assert data["pending_approval"] is not None

        approval_id = data["pending_approval"]["approval_id"]
        session_id = data["session_id"]

        # Now approve it
        r2 = client.post(
            "/human-approval",
            json={
                "session_id": session_id,
                "approval_id": approval_id,
                "approved": True,
                "reviewer_note": "Approved by senior agent",
            },
        )
        assert r2.status_code == 200
        result = r2.json()
        assert result["status"] == "approved"
        assert "processed" in result["message"].lower()

    def test_reject_large_refund(self):
        r1 = client.post(
            "/chat",
            json={"message": "Refund ORD-003 please"},
            headers={"X-Customer-Token": "tok-cust-101"},
        )
        data = r1.json()

        if data.get("pending_approval"):
            approval_id = data["pending_approval"]["approval_id"]
            session_id = data["session_id"]

            r2 = client.post(
                "/human-approval",
                json={
                    "session_id": session_id,
                    "approval_id": approval_id,
                    "approved": False,
                    "reviewer_note": "Policy violation",
                },
            )
            assert r2.status_code == 200
            assert r2.json()["status"] == "rejected"

    def test_wrong_session_returns_403(self):
        # Create an approval from CUST-101's session
        r1 = client.post(
            "/chat",
            json={"message": "Refund ORD-003"},
            headers={"X-Customer-Token": "tok-cust-101"},
        )
        data = r1.json()
        if data.get("pending_approval"):
            approval_id = data["pending_approval"]["approval_id"]
            r2 = client.post(
                "/human-approval",
                json={
                    "session_id": "wrong-session-id",
                    "approval_id": approval_id,
                    "approved": True,
                },
            )
            assert r2.status_code == 403

    def test_invalid_approval_id_returns_404(self):
        r = client.post(
            "/human-approval",
            json={
                "session_id": "any-session",
                "approval_id": "APR-DOESNOTEXIST",
                "approved": True,
            },
        )
        assert r.status_code == 404
