const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

export interface WorkflowNode {
  id: string;
  name: string;
  tool: string;
  inputs: Record<string, unknown>;
  retry_policy: { max_attempts: number; backoff: string };
  timeout_seconds: number;
  description: string;
}

export interface WorkflowEdge {
  from: string;
  to: string;
  condition?: string;
}

export interface WorkflowDefinition {
  workflow_id: string;
  name: string;
  description: string;
  trigger: { type: string; config: Record<string, unknown> };
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  tags: string[];
}

export interface ParseResponse {
  needs_clarification: boolean;
  question?: string;
  workflow?: WorkflowDefinition;
}

export async function parseWorkflow(description: string, force = false): Promise<ParseResponse> {
  const res = await fetch(`${BASE}/workflows/parse`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ description, force }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function listWorkflows(): Promise<WorkflowDefinition[]> {
  const res = await fetch(`${BASE}/workflows/`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export async function deleteWorkflow(workflowId: string): Promise<void> {
  const res = await fetch(`${BASE}/workflows/${workflowId}`, { method: "DELETE" });
  if (!res.ok) throw new Error(await res.text());
}

export interface ExecutionRecord {
  id: string;
  workflow_id: string;
  status: "success" | "failed" | "running" | "skipped";
  started_at: string;
  node_statuses: Record<string, string>;
  error?: string;
}

export async function executeWorkflow(
  workflowId: string,
  triggerPayload: Record<string, unknown> = {},
  mock = false,
  demoPreset = false,
) {
  const res = await fetch(`${BASE}/workflows/${workflowId}/execute`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ trigger_payload: triggerPayload, mock, demo_preset: demoPreset }),
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export interface TimelineNode {
  node_id: string;
  name: string;
  tool: string;
  status: "pending" | "running" | "success" | "failed" | "waiting_approval" | "approved" | "rejected" | "skipped";
  scheduled_at: string | null;
  started_at: string | null;
  completed_at: string | null;
  error: string | null;
  waiting_since?: string;
  decision?: string;
  // logs.fetch metadata
  logs_source?: string;
  logs_count?: number;
  logs_time_window?: string;
  logs_query?: string;
  // integration mock flag — true when no real API key configured
  is_simulated?: boolean;
}

export interface TimelineData {
  execution_id: string;
  status: "running" | "completed" | "failed";
  nodes: TimelineNode[];
  approval_waiting: boolean;
  approval_since: string | null;
  approval_decision: string | null;
  trigger_source?: string | null;  // "datadog" | "grafana" | "pagerduty" | "demo" | "mock" | "temporal"
  rca_analysis?: string | null;    // full RCA text from ai.root_cause_analysis node
  rca_service?: string | null;
  rca_evidence?: string[];         // key log lines that ground the RCA
}

export async function fetchTimeline(workflowId: string, execId: string): Promise<TimelineData> {
  const res = await fetch(`${BASE}/workflows/${workflowId}/executions/${execId}/timeline`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export async function pollMockStatus(execId: string): Promise<any> {
  const res = await fetch(`${BASE}/workflows/mock-status/${execId}`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export async function pollTemporalStatus(workflowId: string, execId: string): Promise<any> {
  const res = await fetch(`${BASE}/workflows/${workflowId}/executions/${execId}`);
  if (!res.ok) return { execution_id: execId, status: "running" };
  return res.json();
}

export interface MetricsSummary {
  total_incidents: number;
  completed: number;
  failed: number;
  running: number;
  auto_resolved_pct: number | null;
  avg_mttr_seconds: number | null;
  p95_mttr_seconds: number | null;
  sample_size: number;
  error?: string;
}

export async function fetchMetricsSummary(): Promise<MetricsSummary> {
  const res = await fetch(`${BASE}/workflows/metrics/summary`);
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

/** Map Temporal status strings to our ExecutionRecord status values */
export function normalizeTemporalStatus(status: string): "running" | "success" | "failed" {
  const s = (status ?? "").toLowerCase();
  if (s === "completed" || s.includes("completed")) return "success";
  if (s === "failed" || s === "canceled" || s === "terminated" || s === "timed_out" || s.includes("failed")) return "failed";
  return "running";
}
