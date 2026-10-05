"""
checkout-service — intentionally breakable demo app
====================================================
Simulates a real production checkout API that can fail in realistic ways.
Ships structured logs to Datadog (backdated 5 min so they land inside the
query window immediately after ingestion), then fires the Orq webhook.

Endpoints:
  GET  /health                  → service status
  GET  /scenarios               → list available failure scenarios
  POST /checkout                → process an order (fails when "broken")
  GET  /orders/{order_id}       → fetch order (fails if DB missing)
  POST /simulate/{scenario}     → trigger a controlled failure
  POST /reset                   → restore service to healthy state
"""
from __future__ import annotations
import os
import uuid
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Config ────────────────────────────────────────────────────────────────────

DD_API_KEY       = os.environ.get("DATADOG_API_KEY", "")
DD_SITE          = os.environ.get("DATADOG_SITE", "datadoghq.com")
ORQ_WEBHOOK_URL  = os.environ.get("ORQ_WEBHOOK_URL", "")
# e.g. https://orq-runtime-production.up.railway.app/api/v1/webhooks/datadog/tpl-incident-response

SERVICE = "checkout-service"
ENV     = "production"

# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="checkout-service",
    description="Intentionally breakable demo service for Orq incident response demos.",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory "service state" ─────────────────────────────────────────────────
# These flags simulate infra failures. Reset with POST /reset.

_state = {
    "orders_table": True,
    "redis":        True,
    "memory_ok":    True,
    "active_scenario": None,
}


# ── Scenario definitions ──────────────────────────────────────────────────────

SCENARIOS: dict[str, dict] = {
    "db-migration-failure": {
        "title":    "DB migration dropped orders table — checkout 100% down",
        "severity": "critical",
        "alert_type": "error",
        "logs": [
            "[ERROR] checkout-service: PG::UndefinedTable: ERROR: relation 'orders' does not exist",
            "[ERROR] checkout-service: ActiveRecord::StatementInvalid: PG::UndefinedTable at /api/v2/checkout",
            "[WARN]  checkout-service: DB migration 20240511_drop_orders.rb ran in production — rollback required",
            "[ERROR] checkout-service: 0 rows returned from orders table — query: SELECT * FROM orders LIMIT 1",
            "[WARN]  checkout-service: DLQ size: 12,391 — unprocessed checkout events accumulating",
            "[ERROR] checkout-service: Checkout flow 100% failing — all order persistence queries failing",
            "[INFO]  checkout-service: Last successful DB query at 00:47:22 UTC (before migration ran)",
            "[ERROR] checkout-service: relation 'orders' does not exist (8,419 failed queries in last 15m)",
            "[WARN]  checkout-service: Dead letter queue growing — 847 new events since 00:47 UTC",
            "[ERROR] checkout-service: POST /api/v2/checkout → 500 InternalServerError (DB unavailable)",
        ],
        "state_change": {"orders_table": False},
    },
    "redis-failure": {
        "title":    "Redis connection refused — checkout-service latency critical",
        "severity": "high",
        "alert_type": "error",
        "logs": [
            "[ERROR] checkout-service: Redis connection refused at redis-primary:6379",
            "[ERROR] checkout-service: Connection pool exhausted — timeout after 30s (pool size: 50/50)",
            "[WARN]  checkout-service: p99 latency=4821ms — Redis timeout cascading to HTTP layer",
            "[ERROR] checkout-service: Circuit breaker OPEN for redis-primary (5 failures in 60s)",
            "[INFO]  checkout-service: Retrying connection (attempt 3/3) — backing off 5s",
            "[WARN]  checkout-service: Session cache unavailable — falling back to DB auth (5× overhead)",
            "[ERROR] checkout-service: POST /checkout → 503 Service Unavailable (Redis down)",
            "[WARN]  checkout-service: 847 requests queued waiting for Redis slot",
        ],
        "state_change": {"redis": False},
    },
    "oom": {
        "title":    "checkout-service memory critical — heap at 94%",
        "severity": "high",
        "alert_type": "warning",
        "logs": [
            "[WARN]  checkout-service: Memory usage at 94% (7.4 GB / 8 GB) — threshold: 85%",
            "[WARN]  checkout-service: GC overhead limit exceeded — full GC running every 2s",
            "[ERROR] checkout-service: Java heap space — OutOfMemoryError in RequestHandler thread",
            "[WARN]  checkout-service: Heap fragmentation detected — large object allocations failing",
            "[INFO]  checkout-service: Thread count: 847 (threshold: 500) — possible thread leak",
            "[ERROR] checkout-service: HTTP 503 — JVM refusing new requests, memory critical",
            "[WARN]  checkout-service: RSS: 7.9 GB — kernel OOM killer may terminate process",
        ],
        "state_change": {"memory_ok": False},
    },
    "high-error-rate": {
        "title":    "checkout-service 5xx error rate > 15% — SLA breach imminent",
        "severity": "high",
        "alert_type": "error",
        "logs": [
            "[ERROR] checkout-service: HTTP 500 error rate: 18.4% (threshold: 1%)",
            "[ERROR] checkout-service: POST /checkout → 500 (payments-service timeout after 5s)",
            "[WARN]  checkout-service: payments-service p99=4200ms — circuit breaker threshold approaching",
            "[ERROR] checkout-service: 3/5 downstream health checks failing",
            "[WARN]  checkout-service: Retry budget exhausted — dropping requests to payments-service",
            "[ERROR] checkout-service: HTTP 503 from payments-gateway (connection pool: 200/200)",
            "[WARN]  checkout-service: Error budget at 2.3% remaining (SLO: 99.9% uptime)",
        ],
        "state_change": {},
    },
}


# ── Datadog log shipping ───────────────────────────────────────────────────────

async def ship_logs_to_datadog(log_lines: list[str], scenario: str, backdate_minutes: int = 5) -> int:
    """
    Ship structured log entries to Datadog, backdated by `backdate_minutes`.
    Backdating puts logs inside the query window immediately after ingestion —
    the query `from: now-15m` will match them as soon as Datadog indexes them.

    Returns the HTTP status code, or 0 on failure.
    """
    if not DD_API_KEY:
        return 0

    # Backdate timestamps: puts logs inside the query window straight away
    ts = (datetime.now(timezone.utc) - timedelta(minutes=backdate_minutes)).strftime(
        "%Y-%m-%dT%H:%M:%S.000Z"
    )

    entries = [
        {
            "ddsource":  SERVICE,
            "ddtags":    f"env:{ENV},service:{SERVICE},scenario:{scenario}",
            "hostname":  "checkout-web-01.railway.app",
            "message":   line,
            "service":   SERVICE,
            "status":    "error" if "[ERROR]" in line else "warn" if "[WARN]" in line else "info",
            "timestamp": ts,
        }
        for line in log_lines
    ]

    try:
        async with httpx.AsyncClient(timeout=8) as client:
            resp = await client.post(
                f"https://http-intake.logs.{DD_SITE}/api/v2/logs",
                headers={
                    "DD-API-KEY":     DD_API_KEY,
                    "Content-Type":   "application/json",
                },
                json=entries,
            )
            return resp.status_code
    except Exception as exc:
        print(f"[checkout-service] Datadog log shipping failed: {exc}")
        return 0


# ── Orq webhook ───────────────────────────────────────────────────────────────

async def fire_orq_webhook(scenario: str, title: str, severity: str, alert_type: str, log_lines: list[str]) -> Optional[str]:
    """
    Fire the Orq webhook directly (fast path — skips Datadog monitor polling delay).
    Includes the actual log lines in the payload so Orq can use them immediately
    without waiting for Datadog indexing (~60s on free tier).
    Returns the execution_id Orq assigned, or None on failure.
    """
    if not ORQ_WEBHOOK_URL:
        return None

    payload = {
        "title":       title,
        "alert_type":  alert_type,
        "service":     SERVICE,
        "environment": ENV,
        "severity":    severity,
        "source":      "checkout-service",
        "scenario":    scenario,
        "tags":        f"service:{SERVICE},env:{ENV},scenario:{scenario}",
        # Real logs from this running service — same ones shipped to Datadog.
        # Orq uses these directly (no indexing wait). They appear in DD ~60s later.
        "logs":        log_lines,
    }

    try:
        async with httpx.AsyncClient(timeout=12) as client:
            resp = await client.post(ORQ_WEBHOOK_URL, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                return data.get("execution_id")
    except Exception as exc:
        print(f"[checkout-service] Orq webhook failed: {exc}")
    return None


# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status":           "degraded" if not all([_state["orders_table"], _state["redis"], _state["memory_ok"]]) else "ok",
        "service":          SERVICE,
        "environment":      ENV,
        "orders_table":     _state["orders_table"],
        "redis":            _state["redis"],
        "memory_ok":        _state["memory_ok"],
        "active_scenario":  _state["active_scenario"],
        "version":          "1.0.0",
    }


@app.get("/scenarios")
async def list_scenarios():
    """List all available failure scenarios."""
    return {
        k: {
            "title":     v["title"],
            "severity":  v["severity"],
            "log_count": len(v["logs"]),
        }
        for k, v in SCENARIOS.items()
    }


class CheckoutRequest(BaseModel):
    user_id: str
    items:   list[dict]
    payment_method: str = "card"


@app.post("/checkout")
async def checkout(req: CheckoutRequest):
    if not _state["orders_table"]:
        raise HTTPException(500, "relation 'orders' does not exist")
    if not _state["redis"]:
        raise HTTPException(503, "Session validation failed — Redis unavailable")
    if not _state["memory_ok"]:
        raise HTTPException(503, "Service temporarily unavailable — memory critical")
    return {
        "order_id":       str(uuid.uuid4())[:8].upper(),
        "status":         "confirmed",
        "user_id":        req.user_id,
        "items_count":    len(req.items),
        "payment_method": req.payment_method,
    }


@app.get("/orders/{order_id}")
async def get_order(order_id: str):
    if not _state["orders_table"]:
        raise HTTPException(500, f"relation 'orders' does not exist (order_id={order_id})")
    return {
        "order_id": order_id,
        "status":   "fulfilled",
        "service":  SERVICE,
    }


@app.post("/simulate/{scenario}")
async def simulate(scenario: str, fire_webhook: bool = True):
    """
    Trigger a controlled failure scenario.

    - Ships structured logs to Datadog (backdated 5 min)
    - Optionally fires the Orq webhook directly (fast-path demo)
    - Updates in-memory service state to simulate real degradation
    - Returns { status, scenario, logs_sent, datadog_status, orq_execution_id }

    Source label: 'checkout-service' — logs are generated by this real service,
    not invented inside Orq. They ARE in Datadog (indexing ~30-90s after ingestion).
    """
    if scenario not in SCENARIOS:
        raise HTTPException(
            400,
            detail={
                "error":     f"Unknown scenario '{scenario}'",
                "available": list(SCENARIOS.keys()),
            },
        )

    cfg = SCENARIOS[scenario]

    # Apply state change (makes /health and /checkout reflect the failure)
    for k, v in cfg.get("state_change", {}).items():
        _state[k] = v
    _state["active_scenario"] = scenario

    # Ship logs to Datadog (non-blocking — logs appear in DD ~30-90s later)
    dd_status = await ship_logs_to_datadog(cfg["logs"], scenario, backdate_minutes=5)

    # Fire Orq webhook directly (fast path) — includes logs in payload
    exec_id = None
    if fire_webhook:
        exec_id = await fire_orq_webhook(
            scenario   = scenario,
            title      = cfg["title"],
            severity   = cfg["severity"],
            alert_type = cfg["alert_type"],
            log_lines  = cfg["logs"],
        )

    return {
        "status":           "triggered",
        "scenario":         scenario,
        "title":            cfg["title"],
        "severity":         cfg["severity"],
        "logs_sent":        len(cfg["logs"]),
        "datadog_status":   dd_status,
        "orq_execution_id": exec_id,
        "note":             "Logs shipped to Datadog (backdated 5m). They appear in DD Logs Explorer ~60s after ingestion.",
    }


@app.post("/reset")
async def reset():
    """Restore service to fully healthy state."""
    _state.update({
        "orders_table":    True,
        "redis":           True,
        "memory_ok":       True,
        "active_scenario": None,
    })
    return {"status": "healthy", "message": "Service state reset to nominal."}
