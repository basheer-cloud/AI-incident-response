"""
Approval management — list pending approvals, approve/reject them.
Works both from the frontend inbox and from Slack interactive messages.
"""
from __future__ import annotations
import json
import os
from urllib.parse import unquote_plus

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ...tools.registry import get_pending_approvals, resolve_approval

router = APIRouter(prefix="/approvals", tags=["approvals"])


@router.get("/")
async def list_approvals() -> list[dict]:
    return get_pending_approvals()


class ApprovalDecision(BaseModel):
    decision: str  # "approved" | "rejected"
    approver: str = "user"


@router.post("/{approval_id}/respond")
async def respond_to_approval(approval_id: str, body: ApprovalDecision) -> dict:
    if body.decision not in ("approved", "rejected"):
        raise HTTPException(400, "decision must be 'approved' or 'rejected'")

    resolved = resolve_approval(approval_id, body.decision)
    if not resolved:
        raise HTTPException(404, f"Approval {approval_id} not found or already resolved")

    # If Temporal is running, send the signal to the waiting workflow
    from ...tools.registry import _pending_approvals
    approval = _pending_approvals.get(approval_id, {})
    execution_id = approval.get("execution_id", "")

    if execution_id and execution_id != "unknown":
        try:
            from temporalio.client import Client
            client = await Client.connect(TEMPORAL_HOST)
            handle = client.get_workflow_handle(execution_id)
            await handle.signal("approval_signal", body.decision)
        except Exception:
            pass  # Temporal not running — approval still recorded in memory

    return {"approval_id": approval_id, "decision": body.decision, "status": "resolved"}


# ── Slack Interactive Webhook ─────────────────────────────────────────────────

@router.post("/slack/interactive")
async def slack_interactive(request: Request) -> dict:
    """
    Slack sends a URL-encoded payload when a user clicks an interactive button.
    We parse the action value, resolve the approval, and signal Temporal.
    """
    body = await request.body()
    # Slack sends: payload=<url-encoded-json>
    decoded = unquote_plus(body.decode("utf-8"))
    if decoded.startswith("payload="):
        decoded = decoded[len("payload="):]

    try:
        payload = json.loads(decoded)
    except Exception:
        raise HTTPException(400, "Invalid Slack payload")

    actions = payload.get("actions", [])
    if not actions:
        return {"ok": True}

    action_value = actions[0].get("value", "")

    # New format: "{approval_id}|{execution_id}|{decision}"
    # Legacy format: "{approval_id}:{decision}"
    if "|" in action_value:
        parts = action_value.split("|", 2)
        approval_id, execution_id, decision = parts[0], parts[1], parts[2]
    elif ":" in action_value:
        approval_id, decision = action_value.split(":", 1)
        execution_id = ""
    else:
        return {"ok": True}

    # Mark resolved in local memory (best-effort — may be empty for Temporal runs)
    resolve_approval(approval_id, decision)

    # Always signal Temporal directly using the execution_id from the button value.
    # This works even when worker and backend are separate processes.
    if execution_id and execution_id != "unknown":
        try:
            from ...temporal.client import get_temporal_client
            client = await get_temporal_client()
            handle = client.get_workflow_handle(execution_id)
            await handle.signal("approval_signal", decision)
        except Exception:
            pass

    return {"ok": True}
