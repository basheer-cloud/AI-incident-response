from __future__ import annotations
import asyncio
import logging
import os
import uuid
from typing import Any, AsyncGenerator

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.dag_schema import WorkflowDefinition
from ...core.nl_parser import parse_workflow, check_ambiguity
from ...core.validator import validate_workflow
from ...db.repository import (
    save_workflow, get_workflow, list_workflows,
    update_workflow, delete_workflow, save_execution,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/workflows", tags=["workflows"])

TEMPORAL_HOST = os.environ.get("TEMPORAL_HOST", "localhost:7233")
TASK_QUEUE = os.environ.get("TEMPORAL_TASK_QUEUE", "workflow-builder")
USE_DB = os.environ.get("USE_DB", "false").lower() == "true"

# In-memory store for background mock execution results
_mock_results: dict[str, dict] = {}


async def _get_db() -> AsyncGenerator[AsyncSession | None, None]:
    if not USE_DB:
        yield None
        return
    from ...db.engine import AsyncSessionLocal
    async with AsyncSessionLocal() as session:
        yield session


# ── Parse NL → Workflow ───────────────────────────────────────────────────────

class ParseRequest(BaseModel):
    description: str
    force: bool = False


@router.post("/parse")
async def parse(req: ParseRequest, db: AsyncSession | None = Depends(_get_db)) -> dict:
    if not req.force:
        ambiguity = check_ambiguity(req.description)
        if ambiguity.get("needs_clarification"):
            return {"needs_clarification": True, "question": ambiguity["question"]}

    workflow = parse_workflow(req.description)

    errors = validate_workflow(workflow)
    if errors:
        logger.warning(f"Workflow validation warnings: {errors}")

    await save_workflow(db, workflow)
    return {"needs_clarification": False, "workflow": workflow.model_dump(), "warnings": errors}


# ── Templates ─────────────────────────────────────────────────────────────────

@router.get("/templates")
async def get_templates() -> list[dict]:
    from ...core.templates import TEMPLATES
    return [t.model_dump() for t in TEMPLATES]


@router.post("/templates/{template_id}/import")
async def import_template(template_id: str, db: AsyncSession | None = Depends(_get_db)) -> dict:
    from ...core.templates import TEMPLATES
    template = next((t for t in TEMPLATES if t.workflow_id == template_id), None)
    if not template:
        raise HTTPException(404, "Template not found")
    # Give it a fresh ID so it becomes the user's own workflow
    import copy
    wf = copy.deepcopy(template)
    wf.workflow_id = str(uuid.uuid4())
    await save_workflow(db, wf)
    return wf.model_dump()


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.get("/")
async def list_wf(db: AsyncSession | None = Depends(_get_db)) -> list[dict]:
    wfs = await list_workflows(db)
    return [w.model_dump() for w in wfs]


@router.get("/mock-status/{exec_id}")
async def get_mock_status_early(exec_id: str) -> dict:
    result = _mock_results.get(exec_id)
    if not result:
        return {"execution_id": exec_id, "status": "running", "node_statuses": {}, "mock": True}
    return result


@router.get("/{workflow_id}")
async def get_wf(workflow_id: str, db: AsyncSession | None = Depends(_get_db)) -> dict:
    wf = await get_workflow(db, workflow_id)
    if not wf:
        raise HTTPException(404, "Workflow not found")
    return wf.model_dump()


@router.put("/{workflow_id}")
async def update_wf(workflow_id: str, wf: WorkflowDefinition,
                    db: AsyncSession | None = Depends(_get_db)) -> dict:
    existing = await get_workflow(db, workflow_id)
    if not existing:
        raise HTTPException(404, "Workflow not found")
    wf.workflow_id = workflow_id
    updated = await update_workflow(db, wf)
    return updated.model_dump()


@router.delete("/{workflow_id}")
async def delete_wf(workflow_id: str, db: AsyncSession | None = Depends(_get_db)) -> dict:
    existing = await get_workflow(db, workflow_id)
    if not existing:
        raise HTTPException(404, "Workflow not found")
    await delete_workflow(db, workflow_id)
    return {"deleted": workflow_id}


# ── Execute ───────────────────────────────────────────────────────────────────

_DEMO_PAYLOAD: dict[str, Any] = {
    "service": "checkout-service",
    "environment": "production",
    "severity": "critical",
    "title": "DB migration dropped orders table — checkout 100% down",
}

class ExecuteRequest(BaseModel):
    trigger_payload: dict[str, Any] = {}
    mock: bool = False        # simulate execution without Temporal
    demo_preset: bool = False  # use hardcoded checkout-service incident for demo


async def _mock_execute(wf, exec_id: str, trigger_payload: dict) -> dict:
    """Simulate workflow execution locally — useful for demos without Temporal."""
    import random
    from ...tools.registry import get_tool, _pending_approvals

    node_statuses: dict[str, str] = {}
    node_outputs: dict[str, Any] = {}

    # BFS from trigger
    adjacency: dict[str, list[str]] = {}
    for edge in wf.edges:
        src = edge.from_node
        adjacency.setdefault(src, []).append(edge.to_node)

    node_map = {n.id: n for n in wf.nodes}
    queue = list(adjacency.get("trigger", []))
    visited: set[str] = set()

    while queue:
        node_id = queue.pop(0)
        if node_id in visited:
            continue
        visited.add(node_id)
        node = node_map.get(node_id)

        await asyncio.sleep(0.3)  # simulate network latency

        # Approval nodes: call the real tool so the frontend inbox lights up,
        # then wait (up to 5 min) for the user to approve/reject.
        if node and node.tool == "slack.request_approval":
            approval_id = uuid.uuid4().hex[:8]
            approval_inputs = {
                **node.inputs,
                "approval_id": approval_id,
                "execution_id": exec_id,
                "workflow_id": wf.workflow_id,
            }
            try:
                tool_fn = get_tool("slack.request_approval")
                await tool_fn(approval_inputs)
            except Exception:
                pass  # still register — tool may have already written to _pending_approvals

            # Poll until user decides (max 5 minutes, check every second)
            deadline = 300
            elapsed = 0
            decision = None
            while elapsed < deadline:
                await asyncio.sleep(1)
                elapsed += 1
                entry = _pending_approvals.get(approval_id, {})
                if entry.get("status") not in (None, "pending"):
                    decision = entry["status"]
                    break

            if decision == "approved":
                node_statuses[node_id] = "success"
                node_outputs[node_id] = {"approval_id": approval_id, "decision": "approved"}
                queue.extend(adjacency.get(node_id, []))
            else:
                node_statuses[node_id] = "failed"
                node_outputs[node_id] = {"approval_id": approval_id, "decision": decision or "timeout"}
            continue

        # 90% success rate for all other nodes
        status = "success" if random.random() > 0.1 else "failed"
        node_statuses[node_id] = status
        node_outputs[node_id] = {"mock": True, "status": status}

        if status == "success":
            queue.extend(adjacency.get(node_id, []))

    overall = "failed" if "failed" in node_statuses.values() else "success"
    result = {
        "execution_id": exec_id,
        "status": overall,
        "node_statuses": node_statuses,
        "node_outputs": node_outputs,
        "mock": True,
    }
    _mock_results[exec_id] = result
    return result


@router.post("/{workflow_id}/execute")
async def execute_workflow(workflow_id: str, req: ExecuteRequest,
                           db: AsyncSession | None = Depends(_get_db)) -> dict:
    wf = await get_workflow(db, workflow_id)
    if not wf:
        from ...core.templates import TEMPLATES
        wf = next((t for t in TEMPLATES if t.workflow_id == workflow_id), None)
    if not wf:
        raise HTTPException(404, "Workflow not found")

    # Use demo preset when explicitly requested OR when payload arrives empty
    # (empty payload means old browser cache — inject demo so the run always looks right)
    payload_empty = not req.trigger_payload
    trigger_payload = _DEMO_PAYLOAD if (req.demo_preset or payload_empty) else req.trigger_payload
    logger.info(
        "execute_workflow: workflow_id=%s mock=%s demo_preset=%s payload_empty=%s trigger_payload=%s",
        workflow_id, req.mock, req.demo_preset, payload_empty, trigger_payload,
    )

    exec_id = f"exec-{wf.workflow_id[:8]}-{uuid.uuid4().hex[:8]}"

    if req.mock:
        # Run in background so approval gate can be interactive
        asyncio.create_task(_mock_execute(wf, exec_id, trigger_payload))
        return {"execution_id": exec_id, "status": "running", "node_statuses": {}, "mock": True}

    try:
        from ...temporal.client import get_temporal_client
        from ...temporal.workflows import WorkflowExecutionWorkflow

        client = await get_temporal_client()
        handle = await client.start_workflow(
            WorkflowExecutionWorkflow.run,
            args=[wf.model_dump(), trigger_payload],
            id=exec_id,
            task_queue=TASK_QUEUE,
        )
        await save_execution(db, exec_id, workflow_id, handle.result_run_id or "", trigger_payload)
        return {"execution_id": exec_id, "run_id": handle.result_run_id, "status": "started"}
    except Exception as e:
        raise HTTPException(500, f"Failed to start workflow: {e}")


@router.get("/metrics/summary")
async def get_metrics_summary() -> dict:
    """
    Aggregate execution metrics across all WorkflowExecution runs on Temporal.
    Used to power the MTTR / auto-resolve metrics bar in the frontend.
    Returns lightweight numbers — no event-history scan, just execution list metadata.
    """
    try:
        from ...temporal.client import get_temporal_client
        from temporalio.client import WorkflowExecutionStatus

        client = await get_temporal_client()

        total = 0
        completed = 0
        failed = 0
        running = 0
        mttr_ms: list[float] = []

        async for wf_exec in client.list_workflows(
            query="WorkflowType='WorkflowExecution'",
            page_size=100,
        ):
            total += 1
            st = wf_exec.status
            if st == WorkflowExecutionStatus.COMPLETED:
                completed += 1
                if wf_exec.close_time and wf_exec.start_time:
                    dt = (wf_exec.close_time - wf_exec.start_time).total_seconds() * 1000
                    if dt > 0:
                        mttr_ms.append(dt)
            elif st in (
                WorkflowExecutionStatus.FAILED,
                WorkflowExecutionStatus.CANCELED,
                WorkflowExecutionStatus.TERMINATED,
                WorkflowExecutionStatus.TIMED_OUT,
            ):
                failed += 1
            elif st == WorkflowExecutionStatus.RUNNING:
                running += 1

        resolved = completed + failed
        auto_resolved_pct = round(completed / resolved * 100) if resolved > 0 else None

        avg_mttr_s: float | None = None
        p95_mttr_s: float | None = None
        if mttr_ms:
            avg_mttr_s = round(sum(mttr_ms) / len(mttr_ms) / 1000, 1)
            sorted_ms = sorted(mttr_ms)
            p95_idx = max(0, int(len(sorted_ms) * 0.95) - 1)
            p95_mttr_s = round(sorted_ms[p95_idx] / 1000, 1)

        return {
            "total_incidents": total,
            "completed": completed,
            "failed": failed,
            "running": running,
            "auto_resolved_pct": auto_resolved_pct,
            "avg_mttr_seconds": avg_mttr_s,
            "p95_mttr_seconds": p95_mttr_s,
            "sample_size": len(mttr_ms),
        }
    except Exception as e:
        logger.warning(f"Metrics summary failed: {e}")
        # Return zeros rather than 500 — metrics are non-critical
        return {
            "total_incidents": 0,
            "completed": 0,
            "failed": 0,
            "running": 0,
            "auto_resolved_pct": None,
            "avg_mttr_seconds": None,
            "p95_mttr_seconds": None,
            "sample_size": 0,
            "error": str(e),
        }


@router.get("/{workflow_id}/executions/{execution_id}/timeline")
async def get_execution_timeline(workflow_id: str, execution_id: str,
                                  db: AsyncSession | None = Depends(_get_db)) -> dict:
    """
    Parse Temporal event history → per-node status + approval gate state.
    Powers the live execution timeline in the UI. Polls every 3s from the frontend.
    """
    import json as _json
    from datetime import timezone

    wf = await get_workflow(db, workflow_id)
    if not wf:
        # Also check built-in templates (used by webhook-triggered runs)
        from ...core.templates import TEMPLATES
        wf = next((t for t in TEMPLATES if t.workflow_id == workflow_id), None)
    if not wf:
        raise HTTPException(404, "Workflow not found")

    try:
        from ...temporal.client import get_temporal_client
        from temporalio.client import WorkflowExecutionStatus
        from temporalio.api.enums.v1 import EventType

        client = await get_temporal_client()
        handle = client.get_workflow_handle(execution_id)
        desc = await handle.describe()
        history = await handle.fetch_history()

        # ── Parse event history ────────────────────────────────────────────────
        # activity_id → {node_id, name, tool, status, times, error}
        activity_map: dict[str, dict] = {}
        # scheduled event_id → activity_id  (for linking started/completed events)
        seid_to_aid: dict[int, str] = {}

        timer_active = False
        timer_since: str | None = None
        approval_decision: str | None = None
        approval_aid: str | None = None  # activity_id of the approval node
        trigger_source: str = "temporal"  # "datadog" | "grafana" | "pagerduty" | "demo" | "mock" | "temporal"

        def _ts(ts) -> str:
            try:
                return ts.ToDatetime(tzinfo=timezone.utc).isoformat()
            except Exception:
                try:
                    return ts.isoformat()
                except Exception:
                    return ""

        for event in history.events:
            et = event.event_type

            # ── Workflow started — extract trigger source ──────────────────────
            if et == EventType.EVENT_TYPE_WORKFLOW_EXECUTION_STARTED:
                try:
                    attrs = event.workflow_execution_started_event_attributes
                    # The workflow is called with (workflow_def, trigger_payload)
                    # trigger_payload is the second argument (index 1)
                    raw_tp = attrs.input.payloads[1].data
                    tp = _json.loads(raw_tp)
                    src = tp.get("source", "")
                    if src in ("datadog", "grafana", "pagerduty", "generic", "checkout-service"):
                        trigger_source = src
                    elif tp.get("mock"):
                        trigger_source = "mock"
                    elif not src:
                        trigger_source = "demo"
                except Exception:
                    pass

            # ── Activity scheduled ────────────────────────────────────────────
            if et == EventType.EVENT_TYPE_ACTIVITY_TASK_SCHEDULED:
                attrs = event.activity_task_scheduled_event_attributes
                aid = attrs.activity_id
                seid_to_aid[event.event_id] = aid
                try:
                    raw = attrs.input.payloads[0].data
                    node_data = _json.loads(raw)
                    # Only create entry once (first attempt); retries reuse activity_id
                    if aid not in activity_map:
                        activity_map[aid] = {
                            "node_id": node_data.get("id", f"act_{aid}"),
                            "name": node_data.get("name", f"Activity {aid}"),
                            "tool": node_data.get("tool", "unknown"),
                            "status": "running",
                            "scheduled_at": _ts(event.event_time),
                            "started_at": None,
                            "completed_at": None,
                            "error": None,
                        }
                        if node_data.get("tool") == "slack.request_approval":
                            approval_aid = aid
                    else:
                        # Retry — update seid mapping but keep existing entry
                        seid_to_aid[event.event_id] = aid
                except Exception:
                    pass

            # ── Activity started ──────────────────────────────────────────────
            elif et == EventType.EVENT_TYPE_ACTIVITY_TASK_STARTED:
                attrs = event.activity_task_started_event_attributes
                aid = seid_to_aid.get(attrs.scheduled_event_id)
                if aid and aid in activity_map and not activity_map[aid]["started_at"]:
                    activity_map[aid]["started_at"] = _ts(event.event_time)

            # ── Activity completed ────────────────────────────────────────────
            elif et == EventType.EVENT_TYPE_ACTIVITY_TASK_COMPLETED:
                attrs = event.activity_task_completed_event_attributes
                aid = seid_to_aid.get(attrs.scheduled_event_id)
                if aid and aid in activity_map:
                    activity_map[aid]["status"] = "success"
                    activity_map[aid]["completed_at"] = _ts(event.event_time)
                    # Extract logs metadata so the frontend can show a provenance badge
                    if activity_map[aid].get("tool") == "logs.fetch":
                        try:
                            out = _json.loads(attrs.result.payloads[0].data)
                            activity_map[aid]["logs_source"]      = out.get("source", "mock")
                            activity_map[aid]["logs_count"]       = out.get("count", 0)
                            activity_map[aid]["logs_time_window"] = out.get("time_window", "")
                            activity_map[aid]["logs_query"]       = out.get("query", "")
                        except Exception:
                            pass

                    # Flag simulated integrations (no real API key configured)
                    _mock_tools = {"pagerduty.create_incident", "jira.create_incident_ticket",
                                   "jira.create_ticket", "email.send"}
                    if activity_map[aid].get("tool") in _mock_tools:
                        try:
                            out = _json.loads(attrs.result.payloads[0].data)
                            if out.get("mock"):
                                activity_map[aid]["is_simulated"] = True
                        except Exception:
                            pass

                    # Extract RCA output so the frontend can show full analysis inline
                    if activity_map[aid].get("tool") == "ai.root_cause_analysis":
                        try:
                            out = _json.loads(attrs.result.payloads[0].data)
                            activity_map[aid]["rca_analysis"] = out.get("analysis")
                            activity_map[aid]["rca_service"]  = out.get("service")
                            activity_map[aid]["rca_evidence"] = out.get("evidence", [])
                        except Exception:
                            pass

            # ── Activity failed ───────────────────────────────────────────────
            elif et == EventType.EVENT_TYPE_ACTIVITY_TASK_FAILED:
                attrs = event.activity_task_failed_event_attributes
                aid = seid_to_aid.get(attrs.scheduled_event_id)
                if aid and aid in activity_map:
                    # Only mark permanently failed when no retries remain
                    if int(attrs.retry_state) == 4:  # MAXIMUM_ATTEMPTS_REACHED
                        activity_map[aid]["status"] = "failed"
                        activity_map[aid]["completed_at"] = _ts(event.event_time)
                        try:
                            activity_map[aid]["error"] = attrs.failure.message
                        except Exception:
                            pass

            # ── Timer started (approval gate) ─────────────────────────────────
            elif et == EventType.EVENT_TYPE_TIMER_STARTED:
                attrs = event.timer_started_event_attributes
                try:
                    timeout_s = attrs.start_to_fire_timeout.seconds
                except Exception:
                    timeout_s = 0
                if timeout_s > 3600:  # Only multi-hour approval timers
                    timer_active = True
                    timer_since = _ts(event.event_time)

            # ── Approval signal received ──────────────────────────────────────
            elif et == EventType.EVENT_TYPE_WORKFLOW_EXECUTION_SIGNALED:
                attrs = event.workflow_execution_signaled_event_attributes
                if attrs.signal_name == "approval_signal":
                    try:
                        raw_decision = _json.loads(attrs.input.payloads[0].data)
                        approval_decision = raw_decision if isinstance(raw_decision, str) else "approved"
                    except Exception:
                        approval_decision = "approved"
                    timer_active = False

            # ── Timer canceled (after signal) ─────────────────────────────────
            elif et == EventType.EVENT_TYPE_TIMER_CANCELED:
                timer_active = False

        # ── Post-process approval node status ─────────────────────────────────
        if approval_aid and approval_aid in activity_map:
            entry = activity_map[approval_aid]
            if timer_active:
                entry["status"] = "waiting_approval"
                entry["waiting_since"] = timer_since
            elif approval_decision and entry["status"] in ("success", "waiting_approval"):
                entry["status"] = "approved" if approval_decision == "approved" else "rejected"
                entry["decision"] = approval_decision

        # ── Build ordered node list from workflow definition ───────────────────
        node_id_to_activity = {a["node_id"]: a for a in activity_map.values()}
        nodes_out = []
        for node in wf.nodes:
            match = node_id_to_activity.get(node.id)
            if match:
                nodes_out.append(match)
            else:
                nodes_out.append({
                    "node_id": node.id,
                    "name": node.name,
                    "tool": node.tool,
                    "status": "pending",
                    "scheduled_at": None,
                    "started_at": None,
                    "completed_at": None,
                    "error": None,
                })

        # ── Overall status ────────────────────────────────────────────────────
        _STATUS_MAP = {
            WorkflowExecutionStatus.RUNNING: "running",
            WorkflowExecutionStatus.COMPLETED: "completed",
            WorkflowExecutionStatus.FAILED: "failed",
            WorkflowExecutionStatus.CANCELED: "failed",
            WorkflowExecutionStatus.TERMINATED: "failed",
            WorkflowExecutionStatus.TIMED_OUT: "failed",
            WorkflowExecutionStatus.CONTINUED_AS_NEW: "running",
        }
        overall = _STATUS_MAP.get(desc.status, "running")

        # Surface RCA output at the top level so the frontend can render it
        rca_activity = next(
            (a for a in activity_map.values() if a.get("tool") == "ai.root_cause_analysis"),
            None,
        )

        return {
            "execution_id":     execution_id,
            "status":           overall,
            "nodes":            nodes_out,
            "approval_waiting": timer_active,
            "approval_since":   timer_since if timer_active else None,
            "approval_decision": approval_decision,
            "trigger_source":   trigger_source,
            "rca_analysis":     rca_activity.get("rca_analysis") if rca_activity else None,
            "rca_service":      rca_activity.get("rca_service") if rca_activity else None,
            "rca_evidence":     rca_activity.get("rca_evidence", []) if rca_activity else [],
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Timeline error")
        raise HTTPException(500, f"Timeline error: {e}")


@router.get("/{workflow_id}/executions/{execution_id}")
async def get_execution(workflow_id: str, execution_id: str) -> dict:
    try:
        from ...temporal.client import get_temporal_client
        from temporalio.client import WorkflowExecutionStatus
        client = await get_temporal_client()
        handle = client.get_workflow_handle(execution_id)
        desc = await handle.describe()

        # Map Temporal's IntEnum to a plain string the frontend understands.
        # In Python 3.11+ str(IntEnum) returns just the integer; use .name instead.
        _STATUS_MAP = {
            WorkflowExecutionStatus.RUNNING: "running",
            WorkflowExecutionStatus.COMPLETED: "completed",
            WorkflowExecutionStatus.FAILED: "failed",
            WorkflowExecutionStatus.CANCELED: "failed",
            WorkflowExecutionStatus.TERMINATED: "failed",
            WorkflowExecutionStatus.TIMED_OUT: "failed",
            WorkflowExecutionStatus.CONTINUED_AS_NEW: "running",
        }
        status = _STATUS_MAP.get(desc.status, desc.status.name.lower() if hasattr(desc.status, "name") else str(desc.status))
        return {"execution_id": execution_id, "status": status, "start_time": str(desc.start_time)}
    except Exception as e:
        raise HTTPException(500, f"Could not fetch execution: {e}")
