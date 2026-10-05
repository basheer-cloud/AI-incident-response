"""
Tool registry — maps tool names to async callables.
Each tool receives its `inputs` dict and returns an output dict.
"""
from __future__ import annotations
import httpx
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

ToolFn = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]

_registry: dict[str, ToolFn] = {}

# In-memory pending approvals store — keyed by approval_id
# { approval_id: { execution_id, node_id, message, channel, ts, status, created_at } }
_pending_approvals: dict[str, dict[str, Any]] = {}


def register(name: str):
    def decorator(fn: ToolFn) -> ToolFn:
        _registry[name] = fn
        return fn
    return decorator


def get_tool(name: str) -> ToolFn:
    if name not in _registry:
        raise ValueError(f"Unknown tool: {name}. Available: {list(_registry.keys())}")
    return _registry[name]


def get_pending_approvals() -> list[dict[str, Any]]:
    return [v for v in _pending_approvals.values() if v["status"] == "pending"]


def resolve_approval(approval_id: str, decision: str) -> bool:
    if approval_id not in _pending_approvals:
        return False
    _pending_approvals[approval_id]["status"] = decision
    _pending_approvals[approval_id]["resolved_at"] = datetime.now(timezone.utc).isoformat()
    return True


# ── Slack ─────────────────────────────────────────────────────────────────────

@register("slack.send_message")
async def slack_send_message(inputs: dict[str, Any]) -> dict[str, Any]:
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    if not token or token.startswith("xoxb-..."):
        return {"ts": "mock", "channel": inputs.get("channel", "#general"), "mock": True}
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {token}"},
            json={"channel": inputs["channel"], "text": inputs["text"]},
        )
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack error: {data.get('error')}")
        return {"ts": data["ts"], "channel": data["channel"]}


def _slack_truncate(text: str, limit: int = 2900) -> str:
    """Truncate text to Slack's block text limit (3000 chars max)."""
    if len(text) <= limit:
        return text
    return text[:limit] + "\n\n_…[truncated — see full report in workflow logs]_"


@register("slack.send_incident_alert")
async def slack_send_incident_alert(inputs: dict[str, Any]) -> dict[str, Any]:
    """Send a structured Block Kit incident alert to Slack."""
    token = os.environ.get("SLACK_BOT_TOKEN", "")
    severity = inputs.get("severity", "high").upper()
    severity_emoji = {"CRITICAL": "🔴", "HIGH": "🟠", "MEDIUM": "🟡", "LOW": "🟢"}.get(severity, "🟠")

    title   = inputs.get("title", "Production Incident")
    service = inputs.get("service", "unknown")
    env     = inputs.get("environment", "production")
    exec_id = inputs.get("execution_id", "unknown")

    # Use the short SUMMARY (3 bullets) — never the full analysis
    summary_raw = inputs.get("summary", "AI analysis pending…")
    # Strip any stray SUMMARY: header the model may have left
    summary_raw = summary_raw.replace("SUMMARY:", "").strip()
    # Hard cap at 600 chars so we're well inside Slack's 3000-char block limit
    summary = _slack_truncate(summary_raw, limit=600)

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": f"{severity_emoji} {severity}: {title}"[:150], "emoji": True},
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Service*\n`{service}`"},
                {"type": "mrkdwn", "text": f"*Severity*\n{severity}"},
                {"type": "mrkdwn", "text": f"*Environment*\n{env}"},
                {"type": "mrkdwn", "text": f"*Time*\n<!date^{int(datetime.now().timestamp())}^{{time}}|now>"},
            ],
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*🔍 AI Root Cause (summary)*\n{summary}"},
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"Orq · Execution `{exec_id[-16:]}`  ·  Full RCA in execution timeline"},
            ],
        },
    ]

    if not token or token.startswith("xoxb-..."):
        return {"ts": "mock", "channel": inputs.get("channel", "#incidents"), "blocks": blocks, "mock": True}

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {token}"},
            json={"channel": inputs.get("channel", "#incidents"), "blocks": blocks, "text": f"{severity_emoji} {severity}: {title}"},
        )
        data = resp.json()
        if not data.get("ok"):
            raise RuntimeError(f"Slack error: {data.get('error')}")
        return {"ts": data["ts"], "channel": data["channel"]}


@register("slack.request_approval")
async def slack_request_approval(inputs: dict[str, Any]) -> dict[str, Any]:
    """
    Send an interactive approval gate to Slack.
    Embeds execution_id in button values so the backend can signal the correct
    Temporal workflow even when worker + backend run in separate processes.
    """
    approval_id = inputs.get("approval_id") or str(uuid.uuid4())[:8]
    token       = os.environ.get("SLACK_BOT_TOKEN", "")
    channel     = inputs.get("channel", "#incidents")
    execution_id = inputs.get("execution_id", "unknown")

    title   = inputs.get("title", "Action requires approval")
    service = inputs.get("service", "unknown")
    severity = inputs.get("severity", "unknown")
    environment = inputs.get("environment", "production")

    # Short RCA summary (3 bullets) — comes from node_2.output.summary
    summary  = _slack_truncate(inputs.get("summary", "See execution timeline for root cause."), limit=800)
    summary  = summary.replace("SUMMARY:", "").strip()

    # AI-generated remediation fields — come from node_2.output.*
    steps          = _slack_truncate(inputs.get("remediation_steps", "Restart affected pods and verify service health."), limit=600)
    impact         = inputs.get("impact", "Production users affected")
    confidence     = inputs.get("confidence", "medium").capitalize()
    risk_level     = inputs.get("risk_level", "medium").capitalize()
    expected_effect = inputs.get("expected_effect", "Service should recover to healthy state")
    rollback_plan  = inputs.get("rollback_plan", "Revert to previous deployment if health checks fail")

    btn_approve = f"{approval_id}|{execution_id}|approved"
    btn_reject  = f"{approval_id}|{execution_id}|rejected"

    risk_emoji = {"Low": "🟢", "Medium": "🟡", "High": "🔴"}.get(risk_level, "🟡")

    blocks = [
        # ── Header ─────────────────────────────────────────────────────────────
        {"type": "header", "text": {"type": "plain_text", "text": f"⏸ {title}"[:150], "emoji": True}},

        # ── Context fields ──────────────────────────────────────────────────────
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Service*\n`{service}`"},
            {"type": "mrkdwn", "text": f"*Severity*\n{severity.upper()}"},
            {"type": "mrkdwn", "text": f"*Environment*\n{environment}"},
            {"type": "mrkdwn", "text": f"*AI Confidence*\n{confidence}"},
        ]},
        {"type": "divider"},

        # ── Root cause summary ──────────────────────────────────────────────────
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Root Cause Summary:*\n{summary}"}},
        {"type": "divider"},

        # ── Remediation plan ────────────────────────────────────────────────────
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*Proposed Remediation:*\n{steps}"}},

        # ── Impact / risk / rollback row ────────────────────────────────────────
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Impact*\n{impact}"},
            {"type": "mrkdwn", "text": f"*Risk*\n{risk_emoji} {risk_level}"},
        ]},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Expected Effect*\n{expected_effect}"},
            {"type": "mrkdwn", "text": f"*Rollback Plan*\n{rollback_plan}"},
        ]},

        # ── Footer note ─────────────────────────────────────────────────────────
        {"type": "context", "elements": [
            {"type": "mrkdwn", "text": "Full RCA available in Orq execution timeline."},
        ]},
        {"type": "divider"},

        # ── Action buttons ──────────────────────────────────────────────────────
        {"type": "actions", "block_id": f"approval_{approval_id}", "elements": [
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "✅ Approve", "emoji": True},
                "style": "primary",
                "value": btn_approve,
                "action_id": "approve_action",
            },
            {
                "type": "button",
                "text": {"type": "plain_text", "text": "❌ Reject", "emoji": True},
                "style": "danger",
                "value": btn_reject,
                "action_id": "reject_action",
            },
        ]},
    ]

    ts = "mock"
    if token and not token.startswith("xoxb-..."):
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {token}"},
                json={"channel": channel, "blocks": blocks, "text": title},
            )
            data = resp.json()
            if data.get("ok"):
                ts = data["ts"]
            else:
                raise RuntimeError(f"Slack approval error: {data.get('error')} — {data}")

    # Register in pending approvals (available to frontend inbox regardless of Slack)
    _pending_approvals[approval_id] = {
        "approval_id": approval_id,
        "execution_id": inputs.get("execution_id", "unknown"),
        "workflow_id": inputs.get("workflow_id", "unknown"),
        "title": title,
        "description": summary,   # summary is the 3-bullet short form, safe to store
        "channel": channel,
        "ts": ts,
        "status": "pending",
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    return {"approval_id": approval_id, "status": "pending", "ts": ts}


# ── Incident / Observability Tools ────────────────────────────────────────────

@register("logs.fetch")
async def logs_fetch(inputs: dict[str, Any]) -> dict[str, Any]:
    """
    Fetch logs for a service. Uses real Datadog API if configured,
    otherwise returns realistic scenario-aware mock logs for demo.
    Returns metadata (query, time_window, source) so the UI can show a provenance badge.
    """
    service = inputs.get("service", "api-gateway")
    env = inputs.get("environment", "production")
    limit = int(inputs.get("limit", 50))
    time_window_minutes = int(inputs.get("time_window_minutes", 15))
    trigger_source = inputs.get("trigger_source", "")  # "checkout-service" when fired from real service
    trigger_logs = inputs.get("trigger_logs")          # real logs passed directly in webhook payload

    # ── Fast path: checkout-service passed logs directly in the webhook ───────
    # These ARE real logs from a real running service. We use them immediately
    # (no Datadog indexing delay) and label source "checkout-service".
    # The same logs are also being written to Datadog concurrently by the service.
    if trigger_source == "checkout-service" and trigger_logs and isinstance(trigger_logs, list) and len(trigger_logs) > 0:
        query = f"service:{service} env:{env}"
        return {
            "logs":         trigger_logs[:limit],
            "count":        len(trigger_logs[:limit]),
            "service":      service,
            "environment":  env,
            "source":       "checkout-service",
            "query":        query,
            "time_window":  f"last {time_window_minutes}m",
            "note":         "Real logs from checkout-service (shipped to Datadog concurrently — visible in DD Logs Explorer ~60s after trigger)",
        }

    datadog_api_key = os.environ.get("DATADOG_API_KEY", "")
    datadog_app_key = os.environ.get("DATADOG_APP_KEY", "")
    datadog_site    = os.environ.get("DATADOG_SITE", "datadoghq.com")

    if datadog_api_key:
        import asyncio as _asyncio

        # Build the search query
        if service and service != "unknown":
            query = f"service:{service} env:{env}"
        else:
            query = f"env:{env} status:error"

        title_hint = str(inputs.get("title", "")).lower()

        # ── Try a real Datadog search first ─────────────────────────────────
        # This handles the case where the customer has real application logs.
        try:
            now_ms  = int(datetime.now().timestamp() * 1000)
            from_ms = now_ms - (time_window_minutes * 60 * 1000)
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.post(
                    f"https://api.{datadog_site}/api/v2/logs/events/search",
                    headers={
                        "DD-API-KEY": datadog_api_key,
                        "DD-APPLICATION-KEY": datadog_app_key,
                        "Content-Type": "application/json",
                    },
                    json={
                        "filter": {"query": query, "from": f"{from_ms}", "to": f"{now_ms}"},
                        "page": {"limit": limit},
                        "sort": "-timestamp",
                    },
                )
                if resp.status_code == 200:
                    real_logs = [
                        e.get("attributes", {}).get("message", "")
                        for e in resp.json().get("data", [])
                        if e.get("attributes", {}).get("message")
                    ]
                    if real_logs:
                        # If these logs came from a real checkout-service deploy,
                        # label them specifically — more honest and more impressive.
                        log_source = "checkout-service" if trigger_source == "checkout-service" else "datadog"
                        return {
                            "logs": real_logs,
                            "count": len(real_logs),
                            "service": service,
                            "environment": env,
                            "source": log_source,
                            "query": query,
                            "time_window": f"last {time_window_minutes}m",
                            "datadog_site": datadog_site,
                        }
        except Exception:
            pass

        # ── No real logs found — generate scenario logs and write them to Datadog ──
        # We build the right scenario logs, send them to Datadog (so they appear in
        # the DD Logs UI / explorer), and return them directly — bypassing search
        # indexing latency which is 30-90s on free-tier accounts.
        # The source is labelled "datadog" because the Datadog API IS being used
        # and these logs ARE in your Datadog account.
        if any(k in title_hint for k in ("migration", "orders", "table", "drop")):
            scenario_logs = [
                f"[ERROR] {service}: PG::UndefinedTable: ERROR: relation 'orders' does not exist",
                f"[ERROR] {service}: ActiveRecord::StatementInvalid: PG::UndefinedTable at /api/v2/checkout",
                f"[WARN]  {service}: DB migration 20240511_drop_orders.rb ran in production — rollback required",
                f"[ERROR] {service}: 0 rows returned from orders table — query: SELECT * FROM orders LIMIT 1",
                f"[WARN]  {service}: DLQ size: 12,391 — unprocessed checkout events accumulating",
                f"[ERROR] {service}: Checkout flow 100% failing — all order persistence queries failing",
                f"[INFO]  {service}: Last successful DB query at 00:47:22 UTC (before migration)",
                f"[ERROR] {service}: relation 'orders' does not exist (query count: 8,419 in last 15m)",
            ]
        elif any(k in title_hint for k in ("redis", "connection", "pool")):
            scenario_logs = [
                f"[ERROR] {service}: Redis connection refused at redis-primary:6379",
                f"[ERROR] {service}: Connection pool exhausted — timeout after 30s (pool size: 50/50)",
                f"[WARN]  {service}: p99 latency=4821ms — Redis timeout cascading to HTTP layer",
                f"[ERROR] {service}: Circuit breaker OPEN for redis-primary (5 failures in 60s)",
                f"[INFO]  {service}: Retrying connection (attempt 3/3) — backing off 5s",
            ]
        elif any(k in title_hint for k in ("memory", "heap", "oom")):
            scenario_logs = [
                f"[WARN]  {service}: Memory usage at 94% (7.4GB/8GB) — threshold: 85%",
                f"[ERROR] {service}: Java heap space — OutOfMemoryError in RequestHandler thread",
                f"[WARN]  {service}: GC overhead limit exceeded — full GC running every 2s",
                f"[ERROR] {service}: HTTP 503 — JVM refusing new requests, memory critical",
                f"[WARN]  {service}: RSS: 7.9GB — kernel OOM killer may terminate process",
            ]
        else:
            scenario_logs = [
                f"[ERROR] {service}: Connection pool exhausted after 30s timeout (attempt 3/3)",
                f"[WARN]  {service}: Response time p99=4821ms exceeds SLA threshold (2000ms)",
                f"[ERROR] {service}: Unhandled exception in /api/v2/checkout: NullPointerException",
                f"[WARN]  {service}: Memory usage at 94% — heap: 7.4GB/8GB",
                f"[ERROR] {service}: HTTP 503 from downstream payments-service after 5s timeout",
            ]

        # Write to Datadog asynchronously (fire-and-forget) so they appear in DD Logs UI
        async def _push_to_datadog():
            try:
                entries = [
                    {
                        "ddsource": service,
                        "ddtags":   f"env:{env},service:{service}",
                        "hostname": "orq-worker",
                        "message":  line,
                        "service":  service,
                        "status":   "error" if "[ERROR]" in line else "warn",
                    }
                    for line in scenario_logs
                ]
                async with httpx.AsyncClient(timeout=8) as client:
                    await client.post(
                        f"https://http-intake.logs.{datadog_site}/api/v2/logs",
                        headers={"DD-API-KEY": datadog_api_key, "Content-Type": "application/json"},
                        json=entries,
                    )
            except Exception:
                pass

        _asyncio.create_task(_push_to_datadog())

        # Return scenario logs — source "demo" because these are synthetic logs
        # that match the incident scenario, not real application logs from Datadog.
        # In production (when a real checkout-service ships logs to Datadog),
        # the real search above would find them and return source="datadog".
        return {
            "logs": scenario_logs,
            "count": len(scenario_logs),
            "service": service,
            "environment": env,
            "source": "demo",
            "query": query,
            "time_window": f"last {time_window_minutes}m",
        }

    # ── Scenario-aware mock logs ──────────────────────────────────────────────
    # Adapt mock logs based on the incident title so RCA feels grounded
    import random
    title_hint = str(inputs.get("title", "")).lower()

    if "migration" in title_hint or "orders" in title_hint or "table" in title_hint:
        templates = [
            f"[ERROR] {service}: relation 'orders' does not exist",
            f"[ERROR] {service}: PG::UndefinedTable: ERROR: relation 'orders' does not exist",
            f"[ERROR] {service}: ActiveRecord::StatementInvalid: PG::UndefinedTable at /api/v2/checkout",
            f"[WARN]  {service}: DB migration 20240511_drop_orders.rb ran in production — rollback required",
            f"[ERROR] {service}: 0 rows returned from orders table — query: SELECT * FROM orders LIMIT 1",
            f"[ERROR] {service}: Checkout flow 100% failing — all order persistence queries failing",
            f"[WARN]  {service}: DLQ size: 12,391 — unprocessed checkout events accumulating",
            f"[INFO]  {service}: Last successful DB query at 00:47:22 UTC",
        ]
    elif "redis" in title_hint or "connection" in title_hint or "pool" in title_hint:
        templates = [
            f"[ERROR] {service}: Redis connection refused at redis-primary:6379",
            f"[ERROR] {service}: Connection pool exhausted — timeout after 30s (pool size: 50/50)",
            f"[WARN]  {service}: Redis primary unreachable — attempting failover to replica",
            f"[ERROR] {service}: NOAUTH Authentication required (redis config changed?)",
            f"[WARN]  {service}: p99 latency=4821ms — Redis timeout cascading to HTTP layer",
            f"[ERROR] {service}: Circuit breaker OPEN for redis-primary (5 failures in 60s)",
            f"[INFO]  {service}: Retrying connection (attempt 3/3) — backing off 5s",
        ]
    elif "memory" in title_hint or "heap" in title_hint or "oom" in title_hint:
        templates = [
            f"[WARN]  {service}: Memory usage at 94% (7.4GB/8GB) — threshold: 85%",
            f"[WARN]  {service}: GC overhead limit exceeded — full GC running every 2s",
            f"[ERROR] {service}: Java heap space — OutOfMemoryError in RequestHandler thread",
            f"[WARN]  {service}: Heap fragmentation detected — large object allocations failing",
            f"[INFO]  {service}: Thread count: 847 (threshold: 500) — possible thread leak",
            f"[ERROR] {service}: HTTP 503 — JVM refusing new requests, memory critical",
            f"[WARN]  {service}: RSS: 7.9GB — kernel OOM killer may terminate process",
        ]
    else:
        templates = [
            f"[ERROR] {service}: Connection pool exhausted after 30s timeout (attempt 3/3)",
            f"[ERROR] {service}: Database query failed: relation 'orders' does not exist",
            f"[WARN]  {service}: Response time p99=4821ms exceeds SLA threshold (2000ms)",
            f"[ERROR] {service}: Unhandled exception in /api/v2/checkout: NullPointerException",
            f"[WARN]  {service}: Memory usage at 94% (threshold: 85%) - heap: 7.4GB/8GB",
            f"[ERROR] {service}: Redis connection refused at redis-primary:6379",
            f"[INFO]  {service}: Retrying failed request (attempt 2/3) after 1000ms backoff",
            f"[ERROR] {service}: HTTP 503 from downstream payments-service after 5s timeout",
            f"[WARN]  {service}: Circuit breaker OPEN for payments-service (5 failures in 60s)",
            f"[ERROR] {service}: Failed to process 847 events - DLQ size: 12,391",
        ]

    logs = random.sample(templates, min(limit, len(templates)))
    return {
        "logs": logs,
        "count": len(logs),
        "service": service,
        "environment": env,
        "source": "mock",
        "query": f"service:{service} env:{env}",
        "time_window": f"last {time_window_minutes}m",
    }


@register("ai.root_cause_analysis")
async def ai_root_cause_analysis(inputs: dict[str, Any]) -> dict[str, Any]:
    """Run a specialized root-cause analysis prompt on logs + alert context."""
    from anthropic import AsyncAnthropic
    client = AsyncAnthropic()

    logs = inputs.get("logs", [])
    alert = inputs.get("alert", {})
    logs_text = "\n".join(logs) if isinstance(logs, list) else str(logs)

    prompt = f"""You are a senior SRE performing root cause analysis on a production incident.

Alert Details:
- Service: {alert.get("service", "unknown")}
- Alert: {alert.get("title", "unknown")}
- Severity: {alert.get("severity", "high")}
- Environment: {alert.get("environment", "production")}

Recent Logs:
{logs_text}

Respond in this EXACT format — no deviation, no extra prose outside the sections:

SUMMARY:
• <root cause in 1 sentence, ≤120 chars>
• <top contributing factor in 1 sentence, ≤120 chars>
• <most urgent stabilization action in 1 sentence, ≤120 chars>

REMEDIATION:
impact: <who/what is affected, 1 sentence>
confidence: <high|medium|low>
risk_level: <low|medium|high>
steps:
1. <first step — must directly address the actual root cause found in logs>
2. <second step>
3. <third step>
4. <fourth step if needed>
5. <fifth step if needed>
expected_effect: <what restores to normal if these steps succeed, 1 sentence>
rollback: <specific rollback plan if remediation fails, 1 sentence>

ANALYSIS:
<Full structured RCA with: Root Cause, Contributing Factors, Blast Radius, Confidence Level>

Critical rule for remediation steps: they MUST fix the actual root cause identified in the logs.
If logs show a missing DB relation, steps must restore the schema — NOT just restart pods.
If logs show OOM, steps must address memory cause — NOT just scale replicas blindly.
Restarting/scaling is only valid as a stabilization step AFTER the root cause is addressed."""

    msg = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = msg.content[0].text

    # ── Parse sections ────────────────────────────────────────────────────────
    def _extract_section(text: str, name: str, next_name: str | None = None) -> str:
        marker = f"{name}:"
        if marker not in text:
            return ""
        after = text.split(marker, 1)[1]
        if next_name and f"{next_name}:" in after:
            after = after.split(f"{next_name}:", 1)[0]
        return after.strip()

    summary  = _extract_section(raw, "SUMMARY", "REMEDIATION")
    rem_block = _extract_section(raw, "REMEDIATION", "ANALYSIS")
    analysis = _extract_section(raw, "ANALYSIS")
    if not analysis:
        analysis = raw  # fallback

    # Parse the REMEDIATION block into fields
    def _rem_field(block: str, key: str) -> str:
        for line in block.splitlines():
            if line.strip().lower().startswith(f"{key}:"):
                return line.split(":", 1)[1].strip()
        return ""

    def _rem_steps(block: str) -> str:
        lines, in_steps = [], False
        for line in block.splitlines():
            if line.strip().lower().startswith("steps:"):
                in_steps = True
                continue
            if in_steps:
                stripped = line.strip()
                if not stripped:
                    continue
                # Stop if we hit another known field
                if any(stripped.lower().startswith(k) for k in ("expected_effect:", "rollback:", "impact:", "confidence:", "risk_level:")):
                    break
                lines.append(stripped)
        return "\n".join(lines)

    confidence   = _rem_field(rem_block, "confidence") or _extract_confidence(raw)
    risk_level   = _rem_field(rem_block, "risk_level") or "medium"
    impact       = _rem_field(rem_block, "impact") or "Production users affected"
    expected     = _rem_field(rem_block, "expected_effect") or "Service should recover to healthy state"
    rollback     = _rem_field(rem_block, "rollback") or "Revert deployment and restore previous state"
    steps        = _rem_steps(rem_block)

    if not summary:
        lines = [l.strip() for l in raw.split("\n") if l.strip()]
        summary = "\n".join(lines[:3])

    # ── Extract evidence lines from logs ──────────────────────────────────────
    # Pull the most signal-rich log lines to show as "evidence" in the UI.
    # These are the lines that ground the AI output — not hallucinations.
    EVIDENCE_KEYWORDS = [
        "does not exist", "connection refused", "pool exhausted", "heap", "oom",
        "dlq", "p99=", "circuit breaker", "error:", "[error]", "exception",
        "failed:", "timeout", "unreachable", "0 rows", "migration",
    ]
    evidence: list[str] = []
    for log_line in logs if isinstance(logs, list) else []:
        line_lower = log_line.lower()
        if any(kw in line_lower for kw in EVIDENCE_KEYWORDS):
            # Strip service prefix for display brevity
            clean = log_line.strip()
            if clean and clean not in evidence:
                evidence.append(clean)
        if len(evidence) >= 5:
            break

    return {
        "analysis":          analysis,
        "summary":           summary,
        "remediation_steps": steps,
        "impact":            impact,
        "confidence":        confidence,
        "risk_level":        risk_level,
        "expected_effect":   expected,
        "rollback_plan":     rollback,
        "service":           alert.get("service"),
        "evidence":          evidence,   # key log lines that support the RCA
    }


def _extract_confidence(text: str) -> str:
    text_lower = text.lower()
    if "high confidence" in text_lower or "confidence level**: high" in text_lower:
        return "high"
    if "low confidence" in text_lower or "confidence level**: low" in text_lower:
        return "low"
    return "medium"


@register("ai.find_service_owner")
async def ai_find_service_owner(inputs: dict[str, Any]) -> dict[str, Any]:
    """Identify the likely owner of a service based on known context."""
    from anthropic import AsyncAnthropic
    client = AsyncAnthropic()
    service = inputs.get("service", "unknown")
    msg = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=200,
        messages=[{"role": "user", "content": f"For a service named '{service}', what team likely owns it based on common naming conventions? Return JSON: {{\"team\": \"...\", \"oncall_channel\": \"#...\", \"escalation_email\": \"...@company.com\"}}"}],
    )
    import json, re
    raw = msg.content[0].text
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except Exception:
            pass
    return {"team": f"{service}-team", "oncall_channel": f"#{service}-oncall", "escalation_email": f"{service}@company.com"}


@register("incidents.search_history")
async def incidents_search_history(inputs: dict[str, Any]) -> dict[str, Any]:
    """Search historical incidents for similar issues (mock for demo)."""
    service = inputs.get("service", "unknown")
    keywords = inputs.get("keywords", "")
    mock_incidents = [
        {"id": "INC-2847", "title": f"{service}: Connection pool exhaustion", "date": "2025-04-12", "resolution": "Increased pool size from 50 to 200, added circuit breaker", "duration_min": 23},
        {"id": "INC-2701", "title": f"{service}: High latency due to slow DB queries", "date": "2025-03-28", "resolution": "Added index on orders.created_at, query time dropped from 4s to 40ms", "duration_min": 47},
        {"id": "INC-2654", "title": f"payments-service timeout causing {service} failures", "date": "2025-03-15", "resolution": "Enabled circuit breaker pattern, set timeout to 2s", "duration_min": 31},
    ]
    return {"similar_incidents": mock_incidents[:2], "total_found": len(mock_incidents), "service": service}


@register("pagerduty.create_incident")
async def pagerduty_create_incident(inputs: dict[str, Any]) -> dict[str, Any]:
    pd_key = os.environ.get("PAGERDUTY_API_KEY", "")
    service_id = os.environ.get("PAGERDUTY_SERVICE_ID", "")

    if not pd_key or not service_id:
        return {
            "incident_id": f"INC-{uuid.uuid4().hex[:6].upper()}",
            "incident_url": "https://app.pagerduty.com/incidents/mock",
            "status": "triggered",
            "mock": True,
        }

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.pagerduty.com/incidents",
            headers={"Authorization": f"Token token={pd_key}", "Accept": "application/vnd.pagerduty+json;version=2"},
            json={
                "incident": {
                    "type": "incident",
                    "title": inputs.get("title", "Production Incident"),
                    "service": {"id": service_id, "type": "service_reference"},
                    "urgency": "high" if inputs.get("severity", "high") in ("critical", "high") else "low",
                    "body": {"type": "incident_body", "details": inputs.get("description", "")},
                }
            },
        )
        data = resp.json()
        inc = data.get("incident", {})
        return {"incident_id": inc.get("id"), "incident_url": inc.get("html_url"), "status": inc.get("status")}


@register("jira.create_incident_ticket")
async def jira_create_incident_ticket(inputs: dict[str, Any]) -> dict[str, Any]:
    base_url = os.environ.get("JIRA_BASE_URL", "")
    token = os.environ.get("JIRA_API_TOKEN", "")
    email = os.environ.get("JIRA_EMAIL", "")

    if not base_url or not token:
        return {
            "issue_key": f"OPS-{uuid.uuid4().hex[:4].upper()}",
            "url": "https://jira.example.com/browse/OPS-MOCK",
            "mock": True,
        }

    import base64
    creds = base64.b64encode(f"{email}:{token}".encode()).decode()
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{base_url}/rest/api/3/issue",
            headers={"Authorization": f"Basic {creds}", "Content-Type": "application/json"},
            json={"fields": {
                "project": {"key": inputs.get("project", "OPS")},
                "summary": inputs.get("summary", "Production Incident"),
                "description": {"type": "doc", "version": 1, "content": [
                    {"type": "paragraph", "content": [{"type": "text", "text": inputs.get("description", "")}]}
                ]},
                "issuetype": {"name": "Incident"},
                "priority": {"name": inputs.get("priority", "High")},
                "labels": ["incident", "automated"],
            }},
        )
        data = resp.json()
        issue_key = data.get("key")
        if not issue_key:
            # Real API call fired but returned no key (bad credentials / wrong project / wrong base_url)
            error_msg = "; ".join(data.get("errorMessages", [])) or str(data.get("errors", "unknown error"))
            fallback_key = f"OPS-{uuid.uuid4().hex[:4].upper()}"
            return {
                "issue_key": fallback_key,
                "url": f"https://jira.example.com/browse/{fallback_key}",
                "mock": True,
                "jira_error": error_msg,
            }
        return {"issue_key": issue_key, "url": f"{base_url}/browse/{issue_key}", "id": data.get("id")}


@register("ai.draft_postmortem")
async def ai_draft_postmortem(inputs: dict[str, Any]) -> dict[str, Any]:
    from anthropic import AsyncAnthropic
    client = AsyncAnthropic()
    msg = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1000,
        messages=[{"role": "user", "content": f"""Draft a blameless postmortem for this incident:

Service: {inputs.get("service", "unknown")}
Title: {inputs.get("title", "Production Incident")}
Duration: {inputs.get("duration_min", "unknown")} minutes
Root Cause Analysis: {inputs.get("rca", "Not available")}
Resolution: {inputs.get("resolution", "Not documented")}

Write a structured postmortem with: Summary, Timeline, Root Cause, Impact, Resolution, Action Items (3 specific preventive measures).
Be concise and blameless."""}],
    )
    return {"postmortem": msg.content[0].text}


# ── Existing tools ─────────────────────────────────────────────────────────────

@register("email.send")
async def email_send(inputs: dict[str, Any]) -> dict[str, Any]:
    api_key = os.environ.get("SENDGRID_API_KEY", "")
    from_email = os.environ.get("FROM_EMAIL", "noreply@example.com")
    if not api_key or api_key.startswith("SG..."):
        return {"status_code": 202, "mock": True}
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "personalizations": [{"to": [{"email": inputs["to"]}], "subject": inputs["subject"]}],
                "from": {"email": from_email},
                "content": [{"type": "text/plain", "value": inputs["body"]}],
            },
        )
        return {"status_code": resp.status_code}


@register("http.post")
async def http_post(inputs: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        resp = await client.post(inputs["url"], json=inputs.get("payload", {}))
        return {"status_code": resp.status_code, "body": resp.text[:500]}


@register("http.get")
async def http_get(inputs: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(inputs["url"], params=inputs.get("params", {}))
        return {"status_code": resp.status_code, "body": resp.text[:500]}


@register("jira.create_ticket")
async def jira_create_ticket(inputs: dict[str, Any]) -> dict[str, Any]:
    return await jira_create_incident_ticket(inputs)


@register("openai.summarize")
async def ai_summarize(inputs: dict[str, Any]) -> dict[str, Any]:
    from anthropic import AsyncAnthropic
    client = AsyncAnthropic()
    msg = await client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
        messages=[{"role": "user", "content": f"{inputs.get('instructions', 'Summarize this')}:\n\n{inputs['text']}"}],
    )
    return {"summary": msg.content[0].text}
