"use client";
import { useState, lazy, Suspense, useCallback } from "react";
import NLInput from "@/components/NLInput";
import WorkflowCard from "@/components/WorkflowCard";
import TemplatesPanel from "@/components/TemplatesPanel";
import ObservabilityPanel from "@/components/ObservabilityPanel";
import ApprovalInbox from "@/components/ApprovalInbox";
import WebhookTestPanel from "@/components/WebhookTestPanel";
import MetricsBar from "@/components/MetricsBar";
import SimulatePanel from "@/components/SimulatePanel";
import type { WorkflowDefinition, ExecutionRecord } from "@/lib/api";

const WorkflowCanvas = lazy(() => import("@/components/WorkflowCanvas"));

type RightTab = "canvas" | "history";

// Parse "0 9 * * 1" → "Every Monday at 9:00 AM UTC"
function humanCron(expr: string, tz = "UTC"): string {
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return expr;
  const [min, hour, , , dow] = parts;
  const days: Record<string, string> = { "0": "Sunday", "1": "Monday", "2": "Tuesday", "3": "Wednesday", "4": "Thursday", "5": "Friday", "6": "Saturday" };
  const h = parseInt(hour), m = parseInt(min);
  const timeStr = `${h % 12 || 12}:${m.toString().padStart(2, "0")} ${h < 12 ? "AM" : "PM"}`;
  if (dow !== "*" && days[dow]) return `Every ${days[dow]} at ${timeStr} ${tz}`;
  if (hour !== "*") return `Daily at ${timeStr} ${tz}`;
  return expr;
}

// Determine BFS execution order from workflow DAG
function getExecutionOrder(wf: WorkflowDefinition): string[] {
  const adjacency: Record<string, string[]> = {};
  for (const edge of wf.edges) {
    adjacency[edge.from] = [...(adjacency[edge.from] ?? []), edge.to];
  }
  const order: string[] = [];
  const queue = ["trigger"];
  const visited = new Set<string>();
  while (queue.length) {
    const curr = queue.shift()!;
    if (visited.has(curr)) continue;
    visited.add(curr);
    if (curr !== "trigger") order.push(curr);
    for (const next of adjacency[curr] ?? []) queue.push(next);
  }
  return order;
}

export default function Home() {
  const [workflows, setWorkflows] = useState<WorkflowDefinition[]>([]);
  const [selected, setSelected] = useState<WorkflowDefinition | null>(null);
  const [executions, setExecutions] = useState<Record<string, ExecutionRecord[]>>({});
  const [rightTab, setRightTab] = useState<RightTab>("canvas");
  const [liveStatus, setLiveStatus] = useState<Record<string, string>>({});

  function handleParsed(wf: WorkflowDefinition) {
    setWorkflows((prev) => [wf, ...prev]);
    setSelected(wf);
    setRightTab("canvas");
    setLiveStatus({});
  }

  function handleDelete(workflowId: string) {
    setWorkflows((prev) => prev.filter((w) => w.workflow_id !== workflowId));
    if (selected?.workflow_id === workflowId) { setSelected(null); setLiveStatus({}); }
  }

  // Animate nodes on canvas when a mock execution runs
  const handleExecution = useCallback((record: ExecutionRecord, wf: WorkflowDefinition) => {
    setExecutions((prev) => {
      const existing = prev[record.workflow_id] ?? [];
      const without = existing.filter((r) => r.id !== record.id);
      return { ...prev, [record.workflow_id]: [record, ...without].slice(0, 20) };
    });

    // Real Temporal run (no node_statuses) — switch to history immediately
    // ExecutionTimeline will poll and fill in the node detail live
    if (Object.keys(record.node_statuses).length === 0) {
      setRightTab("history");
      return;
    }

    // Mock run — animate node-by-node on canvas
    setRightTab("canvas");
    const order = getExecutionOrder(wf);
    const finalStatuses = record.node_statuses;

    // Step through each node with a delay
    order.forEach((nodeId, i) => {
      // Mark as running
      setTimeout(() => {
        setLiveStatus((prev) => ({ ...prev, [nodeId]: "running" }));
      }, i * 450);
      // Mark final status
      setTimeout(() => {
        setLiveStatus((prev) => ({ ...prev, [nodeId]: finalStatuses[nodeId] ?? "success" }));
      }, i * 450 + 400);
    });

    // Clear live status after animation completes, then switch to history
    setTimeout(() => {
      setRightTab("history");
      setTimeout(() => setLiveStatus({}), 1500);
    }, order.length * 450 + 600);
  }, []);

  const selectedExecutions = selected ? (executions[selected.workflow_id] ?? []) : [];

  return (
    <div className="min-h-screen bg-gray-50 font-sans">
      <header className="bg-white border-b border-gray-200 px-6 py-3.5 flex items-center gap-3">
        <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center text-white font-bold text-sm">O</div>
        <div>
          <span className="font-bold text-gray-900 tracking-tight">Orq</span>
          <span className="text-xs text-gray-400 ml-2 hidden sm:inline">Durable incident response, powered by Temporal</span>
        </div>
        <span className="text-xs bg-indigo-50 text-indigo-600 px-2 py-0.5 rounded-full ml-auto font-medium">Incident Response</span>
      </header>

      <MetricsBar />

      <div className="max-w-6xl mx-auto p-6 grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Left panel */}
        <div className="lg:col-span-1 space-y-4">
          <ApprovalInbox />

          <div className="bg-white rounded-xl border border-gray-200 p-4 space-y-3">
            <h2 className="font-semibold text-gray-800 text-sm">Describe a workflow</h2>
            <NLInput onWorkflowParsed={handleParsed} />
          </div>

          {workflows.length > 0 && (
            <div className="space-y-2">
              <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider px-1">Your Workflows</h2>
              {workflows.map((wf) => (
                <WorkflowCard
                  key={wf.workflow_id}
                  workflow={wf}
                  isSelected={selected?.workflow_id === wf.workflow_id}
                  onSelect={() => { setSelected(wf); setRightTab("canvas"); setLiveStatus({}); }}
                  onDelete={() => handleDelete(wf.workflow_id)}
                  onExecution={(record) => handleExecution(record, wf)}
                />
              ))}
            </div>
          )}

          <TemplatesPanel onImport={(wf) => {
            setWorkflows((prev) => [wf, ...prev]);
            setSelected(wf);
            setRightTab("canvas");
            setLiveStatus({});
          }} />

          <SimulatePanel />
        </div>

        {/* Right panel */}
        <div className="lg:col-span-2 space-y-4">
          {selected ? (
            <div className="bg-white rounded-xl border border-gray-200 overflow-hidden">
              {/* Tab bar */}
              <div className="flex border-b border-gray-100 items-center">
                <button
                  onClick={() => setRightTab("canvas")}
                  className={`px-5 py-3 text-sm font-medium transition-colors ${rightTab === "canvas" ? "text-indigo-600 border-b-2 border-indigo-600 bg-indigo-50/40" : "text-gray-500 hover:text-gray-700"}`}
                >
                  Canvas
                </button>
                <button
                  onClick={() => setRightTab("history")}
                  className={`px-5 py-3 text-sm font-medium transition-colors flex items-center gap-2 ${rightTab === "history" ? "text-indigo-600 border-b-2 border-indigo-600 bg-indigo-50/40" : "text-gray-500 hover:text-gray-700"}`}
                >
                  Execution History
                  {selectedExecutions.length > 0 && (
                    <span className="text-xs bg-indigo-100 text-indigo-700 px-1.5 py-0.5 rounded-full">{selectedExecutions.length}</span>
                  )}
                </button>
                <div className="ml-auto px-4 flex items-center gap-3">
                  {/* Export button */}
                  <button
                    onClick={() => {
                      const blob = new Blob([JSON.stringify(selected, null, 2)], { type: "application/json" });
                      const a = document.createElement("a");
                      a.href = URL.createObjectURL(blob);
                      a.download = `${selected.name.replace(/\s+/g, "-").toLowerCase()}.json`;
                      a.click();
                    }}
                    className="text-xs text-gray-400 hover:text-indigo-600 transition-colors"
                    title="Export as JSON"
                  >
                    ↓ Export
                  </button>
                  <span className="text-xs text-gray-300">{selected.workflow_id.slice(0, 8)}</span>
                </div>
              </div>

              {/* Canvas tab */}
              {rightTab === "canvas" && (
                <div className="p-4 space-y-3">
                  <div>
                    <h2 className="font-semibold text-gray-900">{selected.name}</h2>
                    <p className="text-xs text-gray-500 mt-0.5">{selected.description}</p>
                    {selected.trigger.type === "cron" && (selected.trigger.config as Record<string, string>).schedule && (
                      <p className="text-xs text-purple-600 mt-1 font-medium">
                        ⏰ {humanCron(
                          (selected.trigger.config as Record<string, string>).schedule,
                          (selected.trigger.config as Record<string, string>).timezone ?? "UTC"
                        )}
                      </p>
                    )}
                    {selected.trigger.type === "webhook" && (
                      <p className="text-xs text-blue-500 mt-1 font-mono">
                        POST /api/v1/webhooks/{selected.workflow_id}
                      </p>
                    )}
                  </div>

                  {/* Live status legend (visible during animation) */}
                  {Object.keys(liveStatus).length > 0 && (
                    <div className="flex items-center gap-4 text-xs text-gray-500 bg-gray-50 rounded-lg px-3 py-2">
                      <span className="font-medium text-gray-600">Live execution:</span>
                      <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-yellow-400 animate-pulse inline-block" /> Running</span>
                      <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-green-500 inline-block" /> Success</span>
                      <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-full bg-red-500 inline-block" /> Failed</span>
                    </div>
                  )}

                  <Suspense fallback={<div className="h-96 flex items-center justify-center text-gray-400 text-sm">Loading canvas…</div>}>
                    <WorkflowCanvas
                      key={selected.workflow_id}
                      workflow={selected}
                      liveStatus={liveStatus}
                    />
                  </Suspense>

                  {/* Webhook test panel (webhook-triggered workflows only) */}
                  {selected.trigger.type === "webhook" && (
                    <WebhookTestPanel
                      workflow={selected}
                      onTriggered={(payload) => {
                        handleExecution({
                          id: `webhook-${Date.now()}`,
                          workflow_id: selected.workflow_id,
                          status: "running",
                          started_at: new Date().toISOString(),
                          node_statuses: Object.fromEntries(selected.nodes.map((n) => [n.id, "pending"])),
                        }, selected);
                      }}
                    />
                  )}

                  {/* Node table */}
                  <div className="overflow-x-auto">
                    <table className="w-full text-xs text-left">
                      <thead>
                        <tr className="border-b border-gray-100">
                          <th className="pb-2 text-gray-500 font-medium pr-4">Node</th>
                          <th className="pb-2 text-gray-500 font-medium pr-4">Tool</th>
                          <th className="pb-2 text-gray-500 font-medium pr-4">Retries</th>
                          <th className="pb-2 text-gray-500 font-medium">Description</th>
                        </tr>
                      </thead>
                      <tbody>
                        {selected.nodes.map((n) => (
                          <tr key={n.id} className={`border-b border-gray-50 transition-colors ${liveStatus[n.id] === "running" ? "bg-yellow-50" : liveStatus[n.id] === "success" ? "bg-green-50" : liveStatus[n.id] === "failed" ? "bg-red-50" : ""}`}>
                            <td className="py-1.5 pr-4 font-medium text-gray-700">{n.name}</td>
                            <td className="py-1.5 pr-4 font-mono text-indigo-600">{n.tool}</td>
                            <td className="py-1.5 pr-4 text-gray-500">{n.retry_policy.max_attempts}×</td>
                            <td className="py-1.5 text-gray-500">{n.description}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              )}

              {/* History tab */}
              {rightTab === "history" && (
                <div className="p-4">
                  <ObservabilityPanel executions={selectedExecutions} workflow={selected} />
                </div>
              )}
            </div>
          ) : (
            <div className="h-full min-h-96 bg-white rounded-xl border border-dashed border-gray-300 flex flex-col items-center justify-center text-center p-8 space-y-4">
              <div className="w-16 h-16 rounded-2xl bg-indigo-50 flex items-center justify-center text-3xl">🎯</div>
              <div>
                <p className="font-semibold text-gray-800">Import the AI Incident Response Operator</p>
                <p className="text-sm text-gray-400 max-w-xs mt-1">
                  Select a template below, then hit <strong>🎯 Demo</strong> to watch Orq run a full incident end-to-end on Temporal Cloud.
                </p>
              </div>
              <div className="flex flex-wrap justify-center gap-2 text-xs text-gray-500 max-w-sm">
                {["Fetch logs → AI RCA", "PagerDuty + Jira auto-filed", "Slack approval gate", "Postmortem drafted"].map((step) => (
                  <span key={step} className="px-3 py-1 rounded-full bg-indigo-50 border border-indigo-100 text-indigo-600">{step}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
