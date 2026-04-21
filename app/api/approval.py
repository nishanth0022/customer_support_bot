"""
app/api/approval.py — POST /human-approval endpoint.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.api.session_store import get_session, save_state
from app.models.requests import HumanApprovalRequest
from app.models.responses import ApprovalResponse
from app.monitoring.logger import log_event
from app.models.events import HumanApprovalEvent
from app.tools.refund_tools import get_pending_approval, resolve_approval

router = APIRouter()


@router.post("/human-approval", response_model=ApprovalResponse, tags=["Approvals"])
async def handle_human_approval(body: HumanApprovalRequest) -> ApprovalResponse:
    """
    Approve or reject a pending human-approval action (e.g. large refund).

    - Looks up the pending approval by approval_id.
    - Validates the session owns this approval.
    - Processes the approval/rejection and logs the event.
    """
    approval = get_pending_approval(body.approval_id)
    if not approval:
        raise HTTPException(
            status_code=404,
            detail=f"Approval '{body.approval_id}' not found or already resolved.",
        )

    if approval.get("status") != "pending":
        raise HTTPException(
            status_code=409,
            detail=f"Approval '{body.approval_id}' is already in status '{approval['status']}'.",
        )

    if approval.get("session_id") != body.session_id:
        raise HTTPException(
            status_code=403,
            detail="This approval does not belong to the specified session.",
        )

    # ── Process the approval ───────────────────────────────────────────────
    result = resolve_approval(
        body.approval_id,
        approved=body.approved,
        reviewer_note=body.reviewer_note,
    )

    # ── Log the event ──────────────────────────────────────────────────────
    log_event(HumanApprovalEvent(
        session_id=body.session_id,
        approval_id=body.approval_id,
        approved=body.approved,
        reviewer_note=body.reviewer_note,
        action_description=f"Refund of ${approval.get('amount', 0):.2f} for order {approval.get('order_id', 'N/A')}",
    ))

    # ── Update session pending_approval ────────────────────────────────────
    state = get_session(body.session_id)
    if state:
        state["pending_approval"] = None
        save_state(state)

    if body.approved:
        refund = result.get("refund", {})
        message = (
            f"Refund approved and processed. "
            f"Refund ID: {refund.get('refund_id', 'N/A')}. "
            f"Amount: ${refund.get('amount', 0):.2f}. "
            "Customer will receive credit in 3–5 business days."
        )
        status = "approved"
    else:
        message = f"Refund request has been rejected. Reviewer note: {body.reviewer_note or 'None'}"
        status = "rejected"

    return ApprovalResponse(
        session_id=body.session_id,
        approval_id=body.approval_id,
        status=status,
        message=message,
    )
