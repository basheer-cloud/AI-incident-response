"use client";
import { useState } from "react";
import ExecutionTimeline from "@/components/ExecutionTimeline";
import type { ExecutionRecord, WorkflowDefinition } from "@/lib/api";

interface Props {
  executions: ExecutionRecord[];
  workflow: WorkflowDefinition;
}

// ── Webhook execution lookup ──────────────────────────────────────────────────
// Lets you paste a webhook-triggered execution_id (e.g. wh-tpl-inci-e4374968)
// and watch it live in the timeline without needing to trigger from the UI.
function WebhookLookup({ workflow }: { workflow: WorkflowDefinition }) {
  const [input, setInput] = useState("");
  const [submitted, setSubmitted] = useState("");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const id = input.trim();
    if (id) setSubmitted(id);
  }

  return (
    <div className="rounded-xl border border-dashed border-indigo-200 bg-indigo-50/40 p-3 space-y-2">
      <p className="text-xs font-medium text-indigo-700">🔗 Look up a webhook-triggered run</p>
      <form onSubmit={handleSubmit} className="flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="wh-tpl-inci-e4374968"
          className="flex-1 text-xs font-mono px-2.5 py-1.5 border border-indigo-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-300 bg-white"
        />
        <button
          type="submit"
          className="text-xs px-3 py-1.5 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition-colors font-medium shrink-0"
        >
          Watch live
        </button>
      </form>
      {submitted && (
        <div className="rounded-lg border border-indigo-100 bg-white p-2">
          <p className="text-[10px] text-indigo-400 font-mono mb-1.5">{submitted}</p>
          <ExecutionTimeline
            workflowId={workflow.workflow_id}
            executionId={submitted}
            workflowNodes={workflow.nodes}
          />
        </div>
      )}
    </div>
  );
}

const STATUS_STYLES: Record<string, { dot: string; badge: string; label: string }> = {
  success:  { dot: "bg-green-500",                    badge: "bg-green-50 text-green-700",   label: "Success" },
  failed:   { dot: "bg-red-500",                      badge: "bg-red-50 text-red-700",       label: "Failed"  },
  running:  { dot: "bg-yellow-400 animate-pulse",     badge: "bg-yellow-50 text-yellow-700", label: "Running" },
  pending:  { dot: "bg-gray-300",                     badge: "bg-gray-50 text-gray-500",     label: "Pending" },
  skipped:  { dot: "bg-gray-300",                     badge: "bg-gray-50 text-gray-400",     label: "Skipped" },
};

function fmt(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export default function ObservabilityPanel({ executions, workflow }: Props) {
  const [openId, setOpenId] = useState<string | null>(
    executions.length > 0 ? executions[0].id : null
  );

  // Auto-open the latest execution
  const latest = executions[0];
  if (latest && openId === null) setOpenId(latest.id);

  if (!executions.length) {
    return (
      <div className="space-y-4 py-2">
        <div className="text-center py-4">
          <p className="text-sm text-gray-400">No UI-triggered runs yet.</p>
          <p className="text-xs text-gray-400 mt-1">Hit 🎯 Demo or ▶ Run — or look up a webhook run below.</p>
        </div>
        <WebhookLookup workflow={workflow} />
      </div>
    );
  }

  const isMockRun = (exec: ExecutionRecord) =>
    Object.keys(exec.node_statuses).length > 0 || exec.id.startsWith("exec-") === false;

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between mb-1">
        <h3 className="font-semibold text-gray-800 text-sm">Execution History</h3>
        <span className="text-xs text-gray-400">{executions.length} run{executions.length !== 1 ? "s" : ""}</span>
      </div>

      <WebhookLookup workflow={workflow} />

      <div className="space-y-2 max-h-[480px] overflow-y-auto pr-0.5">
        {executions.map((exec) => {
          const s = STATUS_STYLES[exec.status] ?? STATUS_STYLES.pending;
          const isOpen = openId === exec.id;
          const hasMockNodes = Object.keys(exec.node_statuses).length > 0;

          return (
            <div key={exec.id} className="rounded-xl border border-gray-200 overflow-hidden">
              {/* Summary row — click to expand/collapse */}
              <button
                onClick={() => setOpenId(isOpen ? null : exec.id)}
                className="w-full flex items-center gap-3 px-4 py-3 hover:bg-gray-50 transition-colors text-left"
              >
                <span className={`w-2.5 h-2.5 rounded-full shrink-0 ${s.dot}`} />
                <span className="text-xs font-mono text-gray-500 shrink-0">{exec.id.slice(-8)}</span>
                <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${s.badge}`}>{s.label}</span>
                {exec.error && (
                  <span className="text-xs text-red-500 truncate flex-1">{exec.error}</span>
                )}
                <span className="text-xs text-gray-400 ml-auto shrink-0">{fmt(exec.started_at)}</span>
                <span className={`text-gray-300 text-xs transition-transform ${isOpen ? "rotate-90" : ""}`}>▶</span>
              </button>

              {/* Expanded: timeline */}
              {isOpen && (
                <div className="border-t border-gray-100 p-3 bg-gray-50/50">
                  <ExecutionTimeline
                    workflowId={exec.workflow_id}
                    executionId={exec.id}
                    isMock={hasMockNodes}
                    mockNodes={hasMockNodes ? exec.node_statuses : undefined}
                    workflowNodes={workflow.nodes}
                  />
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
