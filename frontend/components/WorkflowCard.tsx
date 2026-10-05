"use client";
import { useState } from "react";
import { executeWorkflow, pollMockStatus, pollTemporalStatus, normalizeTemporalStatus, deleteWorkflow, type WorkflowDefinition, type ExecutionRecord } from "@/lib/api";
import TriggerPayloadModal, { type TriggerPayload } from "@/components/TriggerPayloadModal";

interface Props {
  workflow: WorkflowDefinition;
  onSelect: () => void;
  onDelete: () => void;
  onExecution: (record: ExecutionRecord) => void;
  isSelected: boolean;
}

const TRIGGER_COLORS: Record<string, string> = {
  webhook: "bg-blue-50 text-blue-700",
  cron:    "bg-purple-50 text-purple-700",
  event:   "bg-green-50 text-green-700",
  manual:  "bg-gray-100 text-gray-600",
};

export default function WorkflowCard({ workflow, onSelect, onDelete, onExecution, isSelected }: Props) {
  const [executing, setExecuting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [showModal, setShowModal] = useState(false);
  const [pendingMock, setPendingMock] = useState(false); // which button opened the modal

  function openModal(mock: boolean) {
    setPendingMock(mock);
    setShowModal(true);
  }

  async function handleDemo() {
    setExecuting(true);
    const startedAt = new Date().toISOString();
    try {
      // demo_preset=true → backend injects checkout-service critical incident
      const initial = await executeWorkflow(workflow.workflow_id, {}, false, true);
      const execId = initial.execution_id ?? `exec-${Date.now()}`;
      onExecution({ id: execId, workflow_id: workflow.workflow_id, status: "running", started_at: startedAt, node_statuses: {} });

      const deadline = Date.now() + 5 * 60 * 1000;
      while (Date.now() < deadline) {
        await new Promise((r) => setTimeout(r, 5000));
        try {
          const result = await pollTemporalStatus(workflow.workflow_id, execId);
          const status = normalizeTemporalStatus(result.status ?? "running");
          onExecution({ id: execId, workflow_id: workflow.workflow_id, status, started_at: startedAt, node_statuses: {} });
          if (status !== "running") break;
        } catch { /* ignore transient */ }
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      onExecution({ id: `exec-${Date.now()}`, workflow_id: workflow.workflow_id, status: "failed", started_at: startedAt, node_statuses: {}, error: msg });
    } finally {
      setExecuting(false);
    }
  }

  async function handleExecute(payload: TriggerPayload, mock: boolean) {
    setShowModal(false);
    setExecuting(true);
    const startedAt = new Date().toISOString();

    try {
      const initial = await executeWorkflow(workflow.workflow_id, payload as Record<string, unknown>, mock);
      const execId = initial.execution_id ?? `exec-${Date.now()}`;

      onExecution({
        id: execId,
        workflow_id: workflow.workflow_id,
        status: "running",
        started_at: startedAt,
        node_statuses: {},
      });

      if (mock && initial.status === "running") {
        // Poll until the background mock execution finishes
        const deadline = Date.now() + 6 * 60 * 1000;
        let result = initial;
        while (result.status === "running" && Date.now() < deadline) {
          await new Promise((r) => setTimeout(r, 2000));
          result = await pollMockStatus(execId);
        }
        onExecution({
          id: execId,
          workflow_id: workflow.workflow_id,
          status: result.status ?? "success",
          started_at: startedAt,
          node_statuses: result.node_statuses ?? {},
        });
      } else if (!mock) {
        // Real Temporal run — poll every 5s up to 5 min for quick completions
        const deadline = Date.now() + 5 * 60 * 1000;
        while (Date.now() < deadline) {
          await new Promise((r) => setTimeout(r, 5000));
          try {
            const result = await pollTemporalStatus(workflow.workflow_id, execId);
            const status = normalizeTemporalStatus(result.status ?? "running");
            onExecution({
              id: execId,
              workflow_id: workflow.workflow_id,
              status,
              started_at: startedAt,
              node_statuses: {},
            });
            if (status !== "running") break;
          } catch {
            // ignore transient errors
          }
        }
      }
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : String(err);
      onExecution({
        id: `exec-${Date.now()}`,
        workflow_id: workflow.workflow_id,
        status: "failed",
        started_at: startedAt,
        node_statuses: {},
        error: msg,
      });
    } finally {
      setExecuting(false);
    }
  }

  async function handleDelete(e: React.MouseEvent) {
    e.stopPropagation();
    if (!confirm(`Delete "${workflow.name}"?`)) return;
    setDeleting(true);
    try {
      await deleteWorkflow(workflow.workflow_id);
      onDelete();
    } catch {
      setDeleting(false);
    }
  }

  return (
    <>
      {showModal && (
        <TriggerPayloadModal
          workflowName={workflow.name}
          defaultMock={pendingMock}
          onExecute={handleExecute}
          onCancel={() => setShowModal(false)}
        />
      )}

      <div
        onClick={onSelect}
        className={`cursor-pointer rounded-xl border p-4 transition-all bg-white space-y-2 ${
          isSelected
            ? "border-indigo-400 shadow-sm ring-1 ring-indigo-200"
            : "border-gray-200 hover:border-indigo-300 hover:shadow-sm"
        }`}
      >
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <h3 className="font-semibold text-gray-900 text-sm truncate">{workflow.name}</h3>
            <p className="text-xs text-gray-500 mt-0.5 line-clamp-2">{workflow.description}</p>
          </div>
          <div className="flex items-center gap-1 shrink-0">
            <span className={`text-xs px-2 py-0.5 rounded-full font-medium ${TRIGGER_COLORS[workflow.trigger.type] ?? "bg-gray-100 text-gray-600"}`}>
              {workflow.trigger.type}
            </span>
            <button
              onClick={handleDelete}
              disabled={deleting}
              className="p-1 text-gray-300 hover:text-red-500 transition-colors rounded"
              title="Delete workflow"
            >
              {deleting ? "…" : "✕"}
            </button>
          </div>
        </div>

        <div className="flex flex-wrap gap-1">
          {workflow.nodes.map((n) => (
            <span key={n.id} className="text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded-full font-mono">
              {n.tool}
            </span>
          ))}
        </div>

        <div className="flex items-center justify-between pt-1">
          <span className="text-xs text-gray-400">{workflow.nodes.length} step{workflow.nodes.length !== 1 ? "s" : ""}</span>
          <div className="flex gap-1.5">
            <button
              onClick={(e) => { e.stopPropagation(); openModal(true); }}
              disabled={executing}
              className="text-xs px-2.5 py-1.5 rounded-lg border border-gray-200 text-gray-500 hover:bg-gray-50 disabled:opacity-50 transition-colors"
              title="Simulate locally without Temporal"
            >
              {executing ? "…" : "⚡"}
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); openModal(false); }}
              disabled={executing}
              className="text-xs px-2.5 py-1.5 rounded-lg border border-indigo-300 text-indigo-600 hover:bg-indigo-50 disabled:opacity-50 transition-colors font-medium"
              title="Run on Temporal with custom payload"
            >
              {executing ? "…" : "▶ Run"}
            </button>
            <button
              onClick={(e) => { e.stopPropagation(); handleDemo(); }}
              disabled={executing}
              className="text-xs px-2.5 py-1.5 rounded-lg bg-indigo-600 text-white hover:bg-indigo-700 disabled:opacity-50 transition-colors font-medium"
              title="Run with checkout-service demo incident"
            >
              {executing ? "…" : "🎯 Demo"}
            </button>
          </div>
        </div>
      </div>
    </>
  );
}
