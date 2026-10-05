"use client";
import { useState } from "react";
import type { WorkflowDefinition } from "@/lib/api";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

const SOURCES = ["pagerduty", "grafana", "datadog", "generic"] as const;
type Source = typeof SOURCES[number];

const SOURCE_LABELS: Record<Source, string> = {
  pagerduty: "PagerDuty",
  grafana: "Grafana",
  datadog: "Datadog",
  generic: "Generic",
};

const SOURCE_COLORS: Record<Source, string> = {
  pagerduty: "bg-green-50 border-green-200 text-green-800",
  grafana: "bg-orange-50 border-orange-200 text-orange-800",
  datadog: "bg-purple-50 border-purple-200 text-purple-800",
  generic: "bg-gray-50 border-gray-200 text-gray-800",
};

interface Props {
  workflow: WorkflowDefinition;
  onTriggered: (payload: Record<string, unknown>) => void;
}

export default function WebhookTestPanel({ workflow, onTriggered }: Props) {
  const [source, setSource] = useState<Source>("pagerduty");
  const [firing, setFiring] = useState(false);
  const [result, setResult] = useState<string | null>(null);
  const [testPayload, setTestPayload] = useState<string | null>(null);
  const [loadingPayload, setLoadingPayload] = useState(false);

  async function loadTestPayload(src: Source) {
    setLoadingPayload(true);
    try {
      const res = await fetch(`${BASE}/webhooks/test-payloads/${src}`);
      const data = await res.json();
      setTestPayload(JSON.stringify(data, null, 2));
    } catch {
      setTestPayload("{}");
    } finally {
      setLoadingPayload(false);
    }
  }

  async function fireWebhook() {
    setFiring(true);
    setResult(null);
    try {
      let payload = {};
      if (testPayload) {
        try { payload = JSON.parse(testPayload); } catch {}
      }
      const res = await fetch(`${BASE}/webhooks/${workflow.workflow_id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      setResult(JSON.stringify(data, null, 2));
      onTriggered(data.trigger_payload ?? payload);
    } catch (err: unknown) {
      setResult(`Error: ${err instanceof Error ? err.message : String(err)}`);
    } finally {
      setFiring(false);
    }
  }

  return (
    <div className="rounded-xl border border-blue-200 bg-blue-50 overflow-hidden">
      <div className="px-4 py-2.5 bg-blue-100 border-b border-blue-200 flex items-center gap-2">
        <span className="text-blue-700 font-semibold text-sm">⚡ Webhook Test</span>
        <span className="text-xs text-blue-500 font-mono ml-1">
          POST /api/v1/webhooks/{workflow.workflow_id.slice(0, 8)}
        </span>
      </div>

      <div className="p-4 space-y-3">
        {/* Source selector */}
        <div className="flex flex-wrap gap-2">
          {SOURCES.map((s) => (
            <button
              key={s}
              onClick={() => { setSource(s); setTestPayload(null); setResult(null); }}
              className={`text-xs px-3 py-1.5 rounded-lg border font-medium transition-colors ${
                source === s ? SOURCE_COLORS[s] + " font-bold" : "bg-white border-gray-200 text-gray-600 hover:border-gray-300"
              }`}
            >
              {SOURCE_LABELS[s]}
            </button>
          ))}
          <button
            onClick={() => loadTestPayload(source)}
            disabled={loadingPayload}
            className="text-xs px-3 py-1.5 rounded-lg border border-gray-200 text-gray-500 hover:text-indigo-600 hover:border-indigo-300 transition-colors ml-auto"
          >
            {loadingPayload ? "…" : "Load sample"}
          </button>
        </div>

        {/* Payload editor */}
        {testPayload !== null && (
          <textarea
            className="w-full h-36 text-xs font-mono rounded-lg border border-gray-200 p-2 resize-none focus:outline-none focus:ring-1 focus:ring-blue-400 bg-white"
            value={testPayload}
            onChange={(e) => setTestPayload(e.target.value)}
          />
        )}

        <button
          onClick={fireWebhook}
          disabled={firing}
          className="w-full py-2.5 rounded-lg bg-blue-600 text-white text-sm font-semibold hover:bg-blue-700 disabled:opacity-50 transition-colors"
        >
          {firing ? "Firing…" : `🔥 Fire ${SOURCE_LABELS[source]} Alert`}
        </button>

        {result && (
          <pre className="text-xs bg-white rounded-lg border border-gray-200 p-3 overflow-x-auto max-h-40 text-gray-700">
            {result}
          </pre>
        )}
      </div>
    </div>
  );
}
