"use client";
import { useState } from "react";

export interface TriggerPayload extends Record<string, unknown> {
  service: string;
  environment: string;
  severity: string;
  title: string;
}

interface Props {
  workflowName: string;
  onExecute: (payload: TriggerPayload, mock: boolean) => void;
  onCancel: () => void;
  defaultMock: boolean;
}

const SEVERITIES = ["critical", "high", "medium", "low"];

const DEMO_PRESETS = [
  {
    label: "DB Migration Failure",
    payload: {
      service: "checkout-service",
      environment: "production",
      severity: "critical",
      title: "DB migration dropped orders table — checkout 100% down",
    },
  },
  {
    label: "Redis Connection Pool",
    payload: {
      service: "payments-api",
      environment: "production",
      severity: "high",
      title: "Redis primary unreachable — connection pool exhausted",
    },
  },
  {
    label: "Memory Leak",
    payload: {
      service: "api-gateway",
      environment: "production",
      severity: "high",
      title: "Heap memory at 94% — OOM imminent under current load",
    },
  },
];

export default function TriggerPayloadModal({ workflowName, onExecute, onCancel, defaultMock }: Props) {
  const [mock, setMock] = useState(defaultMock);
  const [payload, setPayload] = useState<TriggerPayload>(DEMO_PRESETS[0].payload);

  function set(field: keyof TriggerPayload, value: string) {
    setPayload((p) => ({ ...p, [field]: value }));
  }

  return (
    <div className="fixed inset-0 bg-black/40 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-2xl shadow-2xl w-full max-w-md">
        {/* Header */}
        <div className="px-5 py-4 border-b border-gray-100">
          <h2 className="font-semibold text-gray-900 text-sm">Trigger Incident Workflow</h2>
          <p className="text-xs text-gray-400 mt-0.5 truncate">{workflowName}</p>
        </div>

        <div className="p-5 space-y-4">
          {/* Quick presets */}
          <div>
            <p className="text-xs font-medium text-gray-500 mb-2">Quick presets</p>
            <div className="grid grid-cols-3 gap-1.5">
              {DEMO_PRESETS.map((p) => (
                <button
                  key={p.label}
                  onClick={() => setPayload(p.payload)}
                  className={`text-xs px-2.5 py-1.5 rounded-lg border transition-all text-left ${
                    payload.service === p.payload.service && payload.title === p.payload.title
                      ? "border-indigo-400 bg-indigo-50 text-indigo-700 font-medium"
                      : "border-gray-200 text-gray-600 hover:border-indigo-300 hover:bg-indigo-50/40"
                  }`}
                >
                  {p.label}
                </button>
              ))}
            </div>
          </div>

          {/* Payload fields */}
          <div className="space-y-3">
            <div>
              <label className="text-xs font-medium text-gray-600 block mb-1">
                Service <span className="text-gray-400 font-normal">— must exist in Datadog for real logs</span>
              </label>
              <input
                value={payload.service}
                onChange={(e) => set("service", e.target.value)}
                placeholder="checkout-service"
                className="w-full text-sm px-3 py-2 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-300 font-mono"
              />
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="text-xs font-medium text-gray-600 block mb-1">Environment</label>
                <input
                  value={payload.environment}
                  onChange={(e) => set("environment", e.target.value)}
                  placeholder="production"
                  className="w-full text-sm px-3 py-2 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-300"
                />
              </div>
              <div>
                <label className="text-xs font-medium text-gray-600 block mb-1">Severity</label>
                <select
                  value={payload.severity}
                  onChange={(e) => set("severity", e.target.value)}
                  className="w-full text-sm px-3 py-2 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-300 bg-white"
                >
                  {SEVERITIES.map((s) => (
                    <option key={s} value={s}>{s.charAt(0).toUpperCase() + s.slice(1)}</option>
                  ))}
                </select>
              </div>
            </div>

            <div>
              <label className="text-xs font-medium text-gray-600 block mb-1">Incident title</label>
              <input
                value={payload.title}
                onChange={(e) => set("title", e.target.value)}
                placeholder="Describe the incident…"
                className="w-full text-sm px-3 py-2 border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-300"
              />
            </div>
          </div>

          {/* Execution mode toggle */}
          <div className="flex items-center gap-3 bg-gray-50 rounded-lg px-3 py-2.5">
            <div className="flex-1">
              <p className="text-xs font-medium text-gray-700">
                {mock ? "⚡ Mock mode" : "▶ Real Temporal execution"}
              </p>
              <p className="text-xs text-gray-400 mt-0.5">
                {mock
                  ? "Simulated locally — no Temporal, no Slack messages"
                  : "Durable execution on Temporal Cloud — Slack messages will fire"}
              </p>
            </div>
            <button
              onClick={() => setMock((m) => !m)}
              className={`relative w-10 h-5 rounded-full transition-colors shrink-0 ${mock ? "bg-gray-300" : "bg-indigo-500"}`}
            >
              <span className={`absolute top-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${mock ? "left-0.5" : "left-5"}`} />
            </button>
          </div>
        </div>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-gray-100 flex items-center gap-2 justify-end">
          <button
            onClick={onCancel}
            className="text-sm px-4 py-2 text-gray-500 hover:text-gray-700 transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => onExecute(payload, mock)}
            className={`text-sm px-5 py-2 rounded-lg font-medium text-white transition-colors ${
              mock
                ? "bg-indigo-400 hover:bg-indigo-500"
                : "bg-indigo-600 hover:bg-indigo-700"
            }`}
          >
            {mock ? "⚡ Run Mock" : "▶ Run on Temporal"}
          </button>
        </div>
      </div>
    </div>
  );
}
