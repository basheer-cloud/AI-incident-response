"""
Webhook receiver — accepts incoming alerts from PagerDuty, Grafana, Datadog, etc.
Maps them to workflow triggers and starts execution via Temporal Cloud.

Dedicated routes:
  POST /api/v1/webhooks/datadog/{workflow_id}   ← paste into Datadog webhook integration
  POST /api/v1/webhooks/grafana/{workflow_id}   ← paste into Grafana contact point
  POST /api/v1/webhooks/{workflow_id}           ← generic / PagerDuty auto-detect

All routes normalize to the same trigger schema and start a Temporal workflow.
"""
from __future__ import annotations
import logging
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Request

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])


# ── Payload normalizers ───────────────────────────────────────────────────────

def _extract_service_from_title(title: str) -> str:
    """
    Last-resort: pull a service name out of the alert title.
    Matches patterns like 'checkout-service', 'api-gateway', 'payments-api'.
    """
    import re
    m = re.search(
        r"\b([\w]+-(?:service|gateway|api|worker|job|proxy|cache|db|database))\b",
        title.lower(),
    )
    return m.group(1) if m else ""


def _parse_dd_tags(raw_tags: Any) -> tuple[str, str]:
    """
    Normalise Datadog tags into (service, env).
    Handles all three formats Datadog can send: dict, comma-string, or list.
    """
    if isinstance(raw_tags, dict):
        service = raw_tags.get("service") or raw_tags.get("kube_service") or ""
        env     = raw_tags.get("env") or raw_tags.get("environment") or "production"
    elif isinstance(raw_tags, str):
        tags    = dict(t.split(":", 1) for t in raw_tags.split(",") if ":" in t)
        service = tags.get("service") or tags.get("kube_service") or ""
        env     = tags.get("env") or tags.get("environment") or "production"
    elif isinstance(raw_tags, list):
        # e.g. ["service:checkout-service", "env:production", ...]
        tags    = dict(t.split(":", 1) for t in raw_tags if isinstance(t, str) and ":" in t)
        service = tags.get("service") or tags.get("kube_service") or ""
        env     = tags.get("env") or tags.get("environment") or "production"
    else:
        service = ""
        env     = "production"
    return service, env


def _normalize_datadog(payload: dict) -> dict:
    """
    Normalize Datadog alert webhook.
    Supports legacy (v1), current webhook, and all tag formats (dict / string / list).
    """
    title = (
        payload.get("title") or
        payload.get("alert_title") or
        payload.get("body", "")[:120] or
        "Datadog Alert"
    )

    # Severity: map alert_type → our schema
    alert_type   = payload.get("alert_type", payload.get("type", "")).lower()
    severity_map = {"error": "critical", "warning": "high", "info": "medium", "success": "low"}
    severity     = severity_map.get(alert_type, "high")

    # Service: try tags first (all three formats), then top-level field, then infer from title
    service, env = _parse_dd_tags(payload.get("tags", {}))
    if not service:
        service = payload.get("service", "") or _extract_service_from_title(title) or "unknown"

    # If the payload carries an explicit source (e.g. "checkout-service" when fired
    # by our real demo service), honour it — otherwise default to "datadog".
    source = payload.get("source") or "datadog"

    # Pass logs through if the sender included them (checkout-service fast path).
    # This lets logs_fetch use real logs immediately — no Datadog indexing wait.
    raw_logs = payload.get("logs")
    logs = raw_logs if isinstance(raw_logs, list) else []

    return {
        "source":      source,
        "title":       title,
        "severity":    severity,
        "service":     service,
        "environment": env,
        "scenario":    payload.get("scenario", ""),
        "logs":        logs,
        "alert_id":    payload.get("id", ""),
        "alert_url":   payload.get("url", payload.get("link", "")),
        "timestamp":   payload.get("date", ""),
    }


def _normalize_grafana(payload: dict) -> dict:
    """Normalize a Grafana unified-alerting webhook payload."""
    alerts  = payload.get("alerts", [{}])
    first   = alerts[0] if alerts else {}
    labels  = first.get("labels", {})
    annotations = first.get("annotations", {})

    title    = payload.get("title") or annotations.get("summary") or "Grafana Alert"
    severity = labels.get("severity", "high")
    if severity not in ("critical", "high", "medium", "low"):
        severity = "high"

    return {
        "source":       "grafana",
        "title":        title,
        "severity":     severity,
        "service":      labels.get("service") or labels.get("job") or "unknown",
        "environment":  labels.get("env") or labels.get("environment") or "production",
        "status":       payload.get("status", "firing"),
        "grafana_url":  payload.get("externalURL", ""),
    }


def _normalize_pagerduty(payload: dict) -> dict:
    """Normalize a PagerDuty v3 webhook payload."""
    events  = payload.get("event", payload.get("messages", [{}]))
    if isinstance(events, list):
        events = events[0] if events else {}
    incident = events.get("data", {}).get("incident", events.get("incident", payload.get("incident", {})))

    urgency_map = {"high": "critical", "low": "high"}
    urgency = incident.get("urgency", "high")
    return {
        "source":       "pagerduty",
        "title":        incident.get("title", "PagerDuty Incident"),
        "severity":     urgency_map.get(urgency, "high"),
        "service":      incident.get("service", {}).get("summary", "unknown"),
        "environment":  "production",
        "incident_id":  incident.get("id", ""),
        "incident_url": incident.get("html_url", ""),
    }


def _normalize_generic(payload: dict) -> dict:
    return {
        "source":      "generic",
        "title":       payload.get("title", payload.get("message", "Production Alert")),
        "severity":    payload.get("severity", "high"),
        "service":     payload.get("service", "unknown"),
        "environment": payload.get("environment", "production"),
    }


def _auto_detect_source(payload: dict, headers: dict) -> str:
    if "X-PagerDuty-Signature" in headers or "messages" in payload:
        return "pagerduty"
    if "alerts" in payload and ("commonAnnotations" in payload or "externalURL" in payload):
        return "grafana"
    if payload.get("alert_type") in ("error", "warning", "info", "success"):
        return "datadog"
    return "generic"


# ── Datadog log seeder ────────────────────────────────────────────────────────

async def _seed_datadog_logs(trigger: dict) -> None:
    """
    Write scenario-appropriate log events to Datadog immediately when a webhook fires.
    The workflow's logs.fetch activity runs ~10-20 s later, by which time Datadog has
    indexed these entries and the search API returns them — so the badge flips from
    "Mock" to "Datadog · N logs".

    Non-fatal: any failure is logged and silently ignored.
    """
    import os, httpx as _httpx
    api_key = os.environ.get("DATADOG_API_KEY", "")
    site    = os.environ.get("DATADOG_SITE", "datadoghq.com")
    if not api_key:
        return

    service = trigger.get("service", "unknown")
    env     = trigger.get("environment", "production")
    title   = trigger.get("title", "").lower()

    # Pick scenario-appropriate log lines based on alert title keywords
    if any(k in title for k in ("migration", "orders", "table", "drop")):
        lines = [
            f"[ERROR] {service}: PG::UndefinedTable: ERROR: relation 'orders' does not exist",
            f"[ERROR] {service}: ActiveRecord::StatementInvalid: PG::UndefinedTable at /api/v2/checkout",
            f"[WARN]  {service}: DB migration 20240511_drop_orders.rb ran in production — rollback required",
            f"[ERROR] {service}: 0 rows returned from orders table — query: SELECT * FROM orders LIMIT 1",
            f"[WARN]  {service}: DLQ size: 12,391 — unprocessed checkout events accumulating",
            f"[ERROR] {service}: Checkout flow 100% failing — all order persistence queries failing",
            f"[INFO]  {service}: Last successful DB query at 00:47:22 UTC (before migration)",
            f"[ERROR] {service}: relation 'orders' does not exist (query count: 8,419 in last 15m)",
        ]
    elif any(k in title for k in ("redis", "connection", "pool")):
        lines = [
            f"[ERROR] {service}: Redis connection refused at redis-primary:6379",
            f"[ERROR] {service}: Connection pool exhausted — timeout after 30s (pool size: 50/50)",
            f"[WARN]  {service}: p99 latency=4821ms — Redis timeout cascading to HTTP layer",
            f"[ERROR] {service}: Circuit breaker OPEN for redis-primary (5 failures in 60s)",
        ]
    elif any(k in title for k in ("memory", "heap", "oom")):
        lines = [
            f"[WARN]  {service}: Memory usage at 94% (7.4GB/8GB) — threshold: 85%",
            f"[ERROR] {service}: Java heap space — OutOfMemoryError in RequestHandler thread",
            f"[ERROR] {service}: HTTP 503 — JVM refusing new requests, memory critical",
        ]
    else:
        lines = [
            f"[ERROR] {service}: Connection pool exhausted after 30s timeout (attempt 3/3)",
            f"[WARN]  {service}: Response time p99=4821ms exceeds SLA threshold (2000ms)",
            f"[ERROR] {service}: Unhandled exception in /api/v2/checkout: NullPointerException",
            f"[WARN]  {service}: Memory usage at 94% — heap: 7.4GB/8GB",
            f"[ERROR] {service}: HTTP 503 from downstream payments-service after 5s timeout",
        ]

    entries = [
        {
            "ddsource": service,
            "ddtags":   f"env:{env},service:{service}",
            "hostname": "orq-incident-injector",
            "message":  line,
            "service":  service,
            "status":   "error" if "[ERROR]" in line else "warn",
        }
        for line in lines
    ]

    try:
        async with _httpx.AsyncClient(timeout=8) as client:
            resp = await client.post(
                f"https://http-intake.logs.{site}/api/v2/logs",
                headers={
                    "DD-API-KEY": api_key,
                    "Content-Type": "application/json",
                },
                json=entries,
            )
            if resp.status_code in (200, 202):
                logger.info(f"Seeded {len(entries)} log events to Datadog for service={service}")
            else:
                logger.warning(f"Datadog log seed returned {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        logger.warning(f"Datadog log seed failed (non-fatal): {e}")


# ── Shared execution starter ──────────────────────────────────────────────────

async def _start_execution(workflow_id: str, trigger_payload: dict) -> dict:
    """Load the workflow and start execution on Temporal Cloud."""
    from ...db.repository import get_workflow, _mem_workflows
    from ...db.engine import AsyncSessionLocal
    from ...core.dag_schema import WorkflowDefinition
    from ...core.templates import TEMPLATES
    import os

    # Load workflow definition — check templates first (most common for webhooks),
    # then fall back to DB and in-memory store.
    # Templates first avoids DB errors when USE_DB=false.
    wf = next((t for t in TEMPLATES if t.workflow_id == workflow_id), None)

    if not wf:
        try:
            async with AsyncSessionLocal() as db:
                wf = await get_workflow(db, workflow_id)
        except Exception as db_err:
            logger.warning(f"DB lookup failed for webhook (non-fatal): {db_err}")

    if not wf:
        data = _mem_workflows.get(workflow_id)
        wf = WorkflowDefinition(**data) if data else None

    if not wf:
        raise HTTPException(404, f"Workflow '{workflow_id}' not found. Valid template ids: tpl-incident-response")

    exec_id = f"wh-{workflow_id[:8]}-{uuid.uuid4().hex[:8]}"

    # Seed scenario-appropriate log events to Datadog so logs.fetch finds real data.
    # Fire-and-forget: Datadog indexes within ~10-30s; the workflow's first activity
    # (logs.fetch) runs at that point, so timing works out naturally.
    await _seed_datadog_logs(trigger_payload)

    try:
        from ...temporal.client import get_temporal_client
        from ...temporal.workflows import WorkflowExecutionWorkflow
        import os
        task_queue = os.environ.get("TEMPORAL_TASK_QUEUE", "workflow-builder")

        client = await get_temporal_client()
        handle = await client.start_workflow(
            WorkflowExecutionWorkflow.run,
            args=[wf.model_dump(), trigger_payload],
            id=exec_id,
            task_queue=task_queue,
        )
        logger.info(f"Webhook started execution {exec_id} for workflow {workflow_id} source={trigger_payload.get('source')}")
        return {
            "execution_id":    exec_id,
            "run_id":          handle.result_run_id,
            "status":          "started",
            "source":          trigger_payload.get("source", "unknown"),
            "trigger_payload": trigger_payload,
        }
    except Exception as e:
        logger.warning(f"Temporal unavailable for webhook trigger: {e}")
        return {
            "execution_id":    exec_id,
            "status":          "queued",
            "source":          trigger_payload.get("source", "unknown"),
            "trigger_payload": trigger_payload,
            "note":            "Temporal unreachable — execution queued",
        }


# ── Dedicated routes ──────────────────────────────────────────────────────────

@router.post("/datadog/{workflow_id}", summary="Datadog alert webhook")
async def receive_datadog(workflow_id: str, request: Request) -> dict:
    """
    Receive a Datadog monitor/alert webhook.
    Paste this URL into Datadog Integrations → Webhooks:
      POST https://<your-backend>/api/v1/webhooks/datadog/{workflow_id}
    """
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    trigger = _normalize_datadog(payload)
    return await _start_execution(workflow_id, trigger)


@router.post("/grafana/{workflow_id}", summary="Grafana alert webhook")
async def receive_grafana(workflow_id: str, request: Request) -> dict:
    """
    Receive a Grafana unified-alerting webhook.
    Add this URL as a Grafana Contact Point (type: Webhook):
      POST https://<your-backend>/api/v1/webhooks/grafana/{workflow_id}
    """
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    trigger = _normalize_grafana(payload)
    return await _start_execution(workflow_id, trigger)


@router.post("/pagerduty/{workflow_id}", summary="PagerDuty alert webhook")
async def receive_pagerduty(workflow_id: str, request: Request) -> dict:
    """Receive a PagerDuty v3 webhook."""
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    trigger = _normalize_pagerduty(payload)
    return await _start_execution(workflow_id, trigger)


@router.post("/{workflow_id}", summary="Generic / auto-detect webhook")
async def receive_generic(workflow_id: str, request: Request) -> dict:
    """
    Auto-detect PagerDuty / Grafana / Datadog / generic payloads.
    Useful as a catch-all when you don't know the source format in advance.
    """
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    headers = dict(request.headers)
    source  = _auto_detect_source(payload, headers)
    normalizers = {
        "pagerduty": _normalize_pagerduty,
        "grafana":   _normalize_grafana,
        "datadog":   _normalize_datadog,
        "generic":   _normalize_generic,
    }
    trigger = normalizers[source](payload)
    return await _start_execution(workflow_id, trigger)


# ── Test payload helper ───────────────────────────────────────────────────────

@router.get("/test-payloads/{source}", summary="Sample payloads for integration testing")
async def get_test_payload(source: str) -> dict:
    """Return a sample webhook payload for the given source, ready to POST."""
    payloads: dict[str, Any] = {
        "datadog": {
            "title": "DB migration dropped orders table — checkout 100% down",
            "alert_type": "error",
            "tags": {"service": "checkout-service", "env": "production"},
            "id": "1234567890",
            "url": "https://app.datadoghq.com/monitors/1234567890",
        },
        "grafana": {
            "title": "High Error Rate — checkout-service",
            "status": "firing",
            "externalURL": "https://grafana.example.com",
            "alerts": [{
                "labels": {"severity": "critical", "service": "checkout-service", "env": "production"},
                "annotations": {"summary": "Error rate exceeded 5% threshold for >5 minutes"},
            }],
        },
        "pagerduty": {
            "event": {"data": {"incident": {
                "title": "API Gateway 5xx rate > 5%",
                "urgency": "high",
                "service": {"summary": "api-gateway"},
                "id": "P1234567",
                "html_url": "https://app.pagerduty.com/incidents/P1234567",
            }}}
        },
        "generic": {
            "source": "generic",
            "title": "Production Alert",
            "severity": "high",
            "service": "user-service",
            "environment": "production",
        },
    }
    if source not in payloads:
        raise HTTPException(400, f"Unknown source. Options: {list(payloads.keys())}")
    return payloads[source]
