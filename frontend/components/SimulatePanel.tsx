"use client";

import { useState } from "react";

// ── Types ────────────────────────────────────────────────────────────────────

interface ScenarioResult {
  status: string;
  scenario: string;
  title: string;
  severity: string;
  logs_sent: number;
  datadog_status: number;
  orq_execution_id: string | null;
  note: string;
}

interface Scenario {
  id: string;
  label: string;
  description: string;
  severity: "critical" | "high";
  icon: string;
  color: string; // tailwind color key
}

// ── Scenario definitions ──────────────────────────────────────────────────────

const SCENARIOS: Scenario[] = [
  {
    id: "db-migration-failure",
    label: "DB Migration Failure",
    description: "Drops the orders table — checkout 100% down",
    severity: "critical",
    icon: "🔴",
    color: "red",
  },
  {
    id: "redis-failure",
    label: "Redis Down",
    description: "Connection refused — p99 latency spikes to 4.8 s",
    severity: "high",
    icon: "🟠",
    color: "orange",
  },
  {
    id: "oom",
    label: "Memory Leak / OOM",
    description: "Heap at 94% — JVM refusing new requests",
    severity: "high",
    icon: "🟡",
    color: "yellow",
  },
  {
    id: "high-error-rate",
    label: "High Error Rate",
    description: "5xx rate > 15% — payments-service timeout",
    severity: "high",
    icon: "🟠",
    color: "orange",
  },
];

// ── Color maps ────────────────────────────────────────────────────────────────

const severityBadge: Record<string, string> = {
  critical: "bg-red-100 text-red-700 border-red-200",
  high:     "bg-orange-100 text-orange-700 border-orange-200",
};

const scenarioButton: Record<string, { idle: string; active: string }> = {
  red:    { idle: "border-red-200 hover:border-red-400 hover:bg-red-50",    active: "border-red-400 bg-red-50" },
  orange: { idle: "border-orange-200 hover:border-orange-400 hover:bg-orange-50", active: "border-orange-400 bg-orange-50" },
  yellow: { idle: "border-yellow-200 hover:border-yellow-400 hover:bg-yellow-50", active: "border-yellow-400 bg-yellow-50" },
};

// ── Component ─────────────────────────────────────────────────────────────────

export default function SimulatePanel() {
  const [firing, setFiring] = useState<string | null>(null);
  const [result, setResult] = useState<ScenarioResult | null>(null);
  const [error, setError]   = useState<string | null>(null);
  const [resetBusy, setResetBusy] = useState(false);
  const [resetOk, setResetOk]     = useState(false);

  const checkoutUrl =
    process.env.NEXT_PUBLIC_CHECKOUT_SERVICE_URL ||
    "https://checkout-service-production.up.railway.app";

  async function triggerScenario(scenario: Scenario) {
    setFiring(scenario.id);
    setResult(null);
    setError(null);
    setResetOk(false);

    try {
      const resp = await fetch(
        `${checkoutUrl}/simulate/${scenario.id}?fire_webhook=true`,
        { method: "POST" }
      );

      if (!resp.ok) {
        const body = await resp.text();
        throw new Error(`HTTP ${resp.status}: ${body}`);
      }

      const data: ScenarioResult = await resp.json();
      setResult(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setFiring(null);
    }
  }

  async function resetService() {
    setResetBusy(true);
    setResetOk(false);
    setResult(null);
    setError(null);

    try {
      const resp = await fetch(`${checkoutUrl}/reset`, { method: "POST" });
      if (resp.ok) {
        setResetOk(true);
      } else {
        setError(`Reset failed: HTTP ${resp.status}`);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setResetBusy(false);
    }
  }

  const anyFiring = firing !== null || resetBusy;

  return (
    <div className="rounded-xl border border-gray-200 bg-white shadow-sm overflow-hidden">
      {/* Header */}
      <div className="px-4 py-3 border-b border-gray-100 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-base">⚡</span>
          <span className="text-sm font-semibold text-gray-800">Simulate Incident</span>
          <span className="ml-1 text-[10px] px-1.5 py-0.5 rounded border border-teal-200 bg-teal-50 text-teal-700 font-medium">
            checkout-service
          </span>
        </div>
        <button
          onClick={resetService}
          disabled={anyFiring}
          className="text-xs text-gray-500 hover:text-gray-700 disabled:opacity-40 transition-colors"
        >
          {resetBusy ? "Resetting…" : resetOk ? "✓ Reset" : "Reset service"}
        </button>
      </div>

      {/* Demo label */}
      <div className="px-4 pt-3 pb-1">
        <p className="text-[11px] text-gray-400 leading-snug">
          Triggers a real{" "}
          <span className="font-mono text-gray-500">checkout-service</span> failure,
          ships structured logs to Datadog (backdated 5 min so they land inside the
          query window immediately after indexing), then fires the Orq webhook.{" "}
          <span className="text-gray-500">Demo environment — no real orders are affected.</span>
        </p>
      </div>

      {/* Scenario buttons */}
      <div className="px-4 py-3 grid grid-cols-1 gap-2">
        {SCENARIOS.map((s) => {
          const isActive = firing === s.id;
          const colors   = scenarioButton[s.color] ?? scenarioButton.orange;
          return (
            <button
              key={s.id}
              onClick={() => triggerScenario(s)}
              disabled={anyFiring}
              className={`
                w-full text-left px-3 py-2.5 rounded-lg border transition-all duration-150
                disabled:opacity-50 disabled:cursor-not-allowed
                ${isActive ? colors.active : colors.idle}
              `}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="text-sm">{s.icon}</span>
                  <span className="text-xs font-semibold text-gray-800">{s.label}</span>
                  <span className={`text-[10px] px-1 py-px rounded border font-medium ${severityBadge[s.severity]}`}>
                    {s.severity}
                  </span>
                </div>
                {isActive && (
                  <span className="text-[10px] text-gray-400 animate-pulse">firing…</span>
                )}
              </div>
              <p className="mt-0.5 text-[11px] text-gray-500 leading-snug ml-6">
                {s.description}
              </p>
            </button>
          );
        })}
      </div>

      {/* Result / Error */}
      {(result || error) && (
        <div className="mx-4 mb-4">
          {error && (
            <div className="rounded-lg border border-red-200 bg-red-50 px-3 py-2.5">
              <p className="text-xs font-semibold text-red-700 mb-0.5">Error</p>
              <p className="text-[11px] text-red-600 font-mono break-all">{error}</p>
              <p className="mt-1.5 text-[10px] text-red-400">
                Is the checkout-service deployed and reachable at{" "}
                <span className="font-mono">{checkoutUrl}</span>?
              </p>
            </div>
          )}

          {result && (
            <div className="rounded-lg border border-teal-200 bg-teal-50 px-3 py-2.5 space-y-1.5">
              {/* Status row */}
              <div className="flex items-center gap-2">
                <span className="text-[11px] font-semibold text-teal-700">✓ Triggered</span>
                <span className="text-[10px] px-1.5 py-px rounded border border-teal-300 bg-white text-teal-700 font-mono">
                  {result.scenario}
                </span>
              </div>

              {/* Metrics */}
              <div className="grid grid-cols-3 gap-1">
                <Metric label="Logs sent" value={String(result.logs_sent)} />
                <Metric
                  label="Datadog"
                  value={
                    result.datadog_status === 202
                      ? "202 ✓"
                      : result.datadog_status === 0
                      ? "skipped"
                      : String(result.datadog_status)
                  }
                  subtle={result.datadog_status === 0}
                />
                <Metric
                  label="Orq exec"
                  value={
                    result.orq_execution_id
                      ? result.orq_execution_id.slice(0, 8) + "…"
                      : "—"
                  }
                  subtle={!result.orq_execution_id}
                />
              </div>

              {/* Note */}
              <p className="text-[10px] text-teal-600 leading-snug">{result.note}</p>

              {/* Orq link */}
              {result.orq_execution_id && (
                <p className="text-[10px] text-teal-500">
                  Orq execution fired — check the{" "}
                  <span className="font-semibold">Executions</span> panel for the live run.
                </p>
              )}
            </div>
          )}
        </div>
      )}

      {/* Footer */}
      <div className="px-4 pb-3">
        <div className="flex items-center gap-1.5 text-[10px] text-gray-400">
          <span className="inline-block w-1.5 h-1.5 rounded-full bg-teal-400"></span>
          Logs backdated 5 min · real checkout-service on Railway · no real orders
        </div>
      </div>
    </div>
  );
}

// ── Metric chip ───────────────────────────────────────────────────────────────

function Metric({ label, value, subtle = false }: { label: string; value: string; subtle?: boolean }) {
  return (
    <div className="rounded border border-teal-200 bg-white px-2 py-1">
      <p className="text-[9px] text-gray-400 uppercase tracking-wide">{label}</p>
      <p className={`text-[11px] font-semibold font-mono ${subtle ? "text-gray-400" : "text-gray-700"}`}>
        {value}
      </p>
    </div>
  );
}
