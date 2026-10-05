"use client";
import { useState, useEffect, useRef } from "react";
import { fetchTimeline, type TimelineNode, type TimelineData } from "@/lib/api";

// ── Source badge ─────────────────────────────────────────────────────────────
const SOURCE_STYLE: Record<string, { label: string; cls: string }> = {
  datadog:           { label: "Datadog",          cls: "bg-purple-100 text-purple-700 border-purple-200" },
  grafana:           { label: "Grafana",           cls: "bg-orange-100 text-orange-700 border-orange-200" },
  pagerduty:         { label: "PagerDuty",         cls: "bg-green-100 text-green-700 border-green-200" },
  "checkout-service":{ label: "checkout-service",  cls: "bg-teal-100 text-teal-700 border-teal-200" },
  demo:              { label: "Demo",              cls: "bg-indigo-100 text-indigo-700 border-indigo-200" },
  mock:              { label: "Mock",              cls: "bg-gray-100 text-gray-600 border-gray-200" },
  temporal:          { label: "Temporal",          cls: "bg-blue-100 text-blue-700 border-blue-200" },
  generic:           { label: "Webhook",           cls: "bg-teal-100 text-teal-700 border-teal-200" },
};

function SourceBadge({ source }: { source: string | null | undefined }) {
  if (!source) return null;
  const cfg = SOURCE_STYLE[source] ?? { label: source, cls: "bg-gray-100 text-gray-600 border-gray-200" };
  return (
    <span className={`text-[10px] font-medium px-1.5 py-0.5 rounded border ${cfg.cls}`}>
      {cfg.label}
    </span>
  );
}

// ── Evidence panel ────────────────────────────────────────────────────────────
function EvidencePanel({ evidence }: { evidence: string[] }) {
  if (!evidence || evidence.length === 0) return null;
  return (
    <div className="mt-2 rounded-lg border border-amber-100 bg-amber-50/50 px-3 py-2.5">
      <p className="text-[10px] font-semibold text-amber-700 uppercase tracking-wider mb-1.5">
        Evidence used by AI
      </p>
      <ul className="space-y-1">
        {evidence.map((line, i) => (
          <li key={i} className="flex items-start gap-1.5">
            <span className="text-amber-400 shrink-0 mt-0.5">›</span>
            <code className="text-[10px] text-gray-700 font-mono leading-relaxed break-all">{line}</code>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ── RCA Detail Panel ─────────────────────────────────────────────────────────
// Shown below the timeline when the execution carries RCA output from the backend.
// The full analysis text is stored in the raw Temporal response; we surface it here
// so Slack can stay concise.
function RCAPanel({ analysis, service, evidence }: { analysis: string; service?: string; evidence?: string[] }) {
  const [open, setOpen] = useState(false);
  if (!analysis) return null;
  return (
    <div className="mt-3 rounded-lg border border-purple-100 bg-purple-50/40 overflow-hidden">
      <button
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-3 py-2.5 text-left hover:bg-purple-50 transition-colors"
      >
        <span className="flex items-center gap-2">
          <span className="text-xs font-medium text-purple-800">🔍 Full AI Root Cause Analysis</span>
          {service && <span className="text-xs text-purple-500 font-mono">{service}</span>}
        </span>
        <span className={`text-purple-400 text-xs transition-transform ${open ? "rotate-90" : ""}`}>▶</span>
      </button>
      {open && (
        <div className="px-3 pb-3 border-t border-purple-100 space-y-2">
          {evidence && evidence.length > 0 && <EvidencePanel evidence={evidence} />}
          <pre className="text-xs text-gray-700 whitespace-pre-wrap font-sans leading-relaxed mt-1 max-h-72 overflow-y-auto">
            {analysis}
          </pre>
        </div>
      )}
    </div>
  );
}

// ── Execution provenance strip ────────────────────────────────────────────────
// Shows the full Trigger → Logs → RCA → Approval → Runtime chain at a glance.
function ExecutionProvenanceStrip({
  triggerSource,
  nodes,
}: {
  triggerSource: string | null | undefined;
  nodes: TimelineNode[];
}) {
  const logsNode = nodes.find((n) => n.tool === "logs.fetch" && n.status === "success");

  const logsIsService = logsNode?.logs_source === "checkout-service";
  const logsIsReal    = logsNode?.logs_source === "datadog";
  const logsIsDemo    = logsNode?.logs_source === "demo";
  const logsLabel     = logsNode
    ? `${logsIsService ? "checkout-service" : logsIsReal ? "Datadog" : logsIsDemo ? "Demo" : "Mock"} · ${logsNode.logs_count ?? 0}`
    : null;
  const logsStyle     = logsIsService
    ? "bg-teal-50 text-teal-700 border-teal-200"
    : logsIsReal
    ? "bg-purple-50 text-purple-700 border-purple-200"
    : logsIsDemo
    ? "bg-amber-50 text-amber-700 border-amber-200"
    : "bg-gray-50 text-gray-500 border-gray-200";

  const triggerLabel = triggerSource
    ? (SOURCE_STYLE[triggerSource]?.label ?? triggerSource)
    : "Webhook";
  const triggerStyle = triggerSource
    ? SOURCE_STYLE[triggerSource]?.cls
    : "bg-gray-100 text-gray-600 border-gray-200";

  type ProvenanceItem = { label: string; value: string; style: string; sub?: string | null };
  const items: ProvenanceItem[] = [
    { label: "Trigger", value: triggerLabel, style: triggerStyle ?? "bg-gray-100 text-gray-600 border-gray-200" },
    ...(logsLabel
      ? [{ label: "Logs", value: logsLabel, style: logsStyle, sub: logsNode?.logs_query }]
      : []),
    { label: "RCA",      value: "Claude AI",  style: "bg-violet-50 text-violet-700 border-violet-200" },
    { label: "Approval", value: "Slack",       style: "bg-green-50 text-green-700 border-green-200" },
    { label: "Runtime",  value: "Temporal",    style: "bg-blue-50 text-blue-700 border-blue-200" },
  ];

  return (
    <div className="flex items-start gap-1.5 flex-wrap px-1 py-2 rounded-lg bg-gray-50/60 border border-gray-100">
      {items.map((item, i) => (
        <div key={item.label} className="flex items-center gap-1">
          {i > 0 && <span className="text-gray-300 text-[10px] select-none">→</span>}
          <div className="flex flex-col items-start">
            <div className="flex items-center gap-1">
              <span className="text-[9px] text-gray-400 uppercase tracking-wide">{item.label}</span>
              <span
                className={`text-[10px] font-medium px-1.5 py-0.5 rounded border ${item.style}`}
                title={item.sub ?? undefined}
              >
                {item.value}
              </span>
            </div>
            {item.sub && (
              <span className="text-[9px] font-mono text-gray-400 ml-8 max-w-[160px] truncate" title={item.sub}>
                {item.sub}
              </span>
            )}
          </div>
        </div>
      ))}
      {!logsIsReal && !logsIsService && logsLabel && (
        <span className="ml-auto text-[9px] text-gray-400 italic self-center">
          {logsIsDemo ? "scenario logs — no real app in DD" : "controlled demo logs"}
        </span>
      )}
    </div>
  );
}

interface Props {
  workflowId: string;
  executionId: string;
  isMock?: boolean;
  mockNodes?: Record<string, string>; // nodeId -> status (for mock runs)
  workflowNodes: Array<{ id: string; name: string; tool: string }>;
}

// ── Status config ────────────────────────────────────────────────────────────
const STATUS: Record<string, { dot: string; label: string; row: string; text: string }> = {
  success:         { dot: "bg-green-500",                      label: "Done",     row: "bg-green-50/40 border-green-100",  text: "text-green-700" },
  approved:        { dot: "bg-green-500",                      label: "Approved", row: "bg-green-50/40 border-green-100",  text: "text-green-700" },
  failed:          { dot: "bg-red-500",                        label: "Failed",   row: "bg-red-50/40 border-red-100",      text: "text-red-600"   },
  rejected:        { dot: "bg-red-500",                        label: "Rejected", row: "bg-red-50/40 border-red-100",      text: "text-red-600"   },
  running:         { dot: "bg-yellow-400 animate-pulse",       label: "Running",  row: "bg-yellow-50/40 border-yellow-100",text: "text-yellow-700"},
  waiting_approval:{ dot: "bg-blue-400 animate-pulse",         label: "Paused",   row: "bg-blue-50/40 border-blue-200",    text: "text-blue-700"  },
  pending:         { dot: "bg-gray-200",                       label: "Pending",  row: "border-gray-100",                  text: "text-gray-400"  },
  skipped:         { dot: "bg-gray-200",                       label: "Skipped",  row: "border-gray-100",                  text: "text-gray-400"  },
};

// ── Helpers ───────────────────────────────────────────────────────────────────
function elapsed(isoSince: string): string {
  const ms = Date.now() - new Date(isoSince).getTime();
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  return `${Math.floor(s / 60)}m ${s % 60}s`;
}

function duration(start: string | null, end: string | null): string | null {
  if (!start || !end) return null;
  const ms = new Date(end).getTime() - new Date(start).getTime();
  if (ms < 1000) return `${ms}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1)}s`;
  return `${Math.floor(ms / 60000)}m ${Math.floor((ms % 60000) / 1000)}s`;
}

function toolCategory(tool: string): string {
  if (tool.startsWith("ai.")) return "AI";
  if (tool.startsWith("slack.")) return "Slack";
  if (tool.startsWith("logs.")) return "Logs";
  if (tool.startsWith("pagerduty.")) return "PD";
  if (tool.startsWith("jira.")) return "Jira";
  if (tool.startsWith("incidents.")) return "History";
  return tool.split(".")[0];
}

const CATEGORY_COLOR: Record<string, string> = {
  AI: "bg-purple-100 text-purple-700",
  Slack: "bg-green-100 text-green-700",
  Logs: "bg-gray-100 text-gray-600",
  PD: "bg-red-100 text-red-700",
  Jira: "bg-blue-100 text-blue-700",
  History: "bg-orange-100 text-orange-700",
};

// ── Node row ─────────────────────────────────────────────────────────────────
function NodeRow({ node, approvalSince }: { node: TimelineNode; approvalSince: string | null }) {
  const cfg = STATUS[node.status] ?? STATUS.pending;
  const dur = duration(node.started_at, node.completed_at);
  const cat = toolCategory(node.tool);
  const isApproval = node.status === "waiting_approval";

  const isLogsNode    = node.tool === "logs.fetch" && node.status === "success" && node.logs_source;
  const logsIsReal    = isLogsNode && (node.logs_source === "datadog" || node.logs_source === "checkout-service");

  return (
    <div className="relative">
      {/* Main row */}
      <div className={`flex items-center gap-2.5 px-3 py-2.5 rounded-lg border transition-all ${cfg.row}`}>
        <span className={`w-2 h-2 rounded-full shrink-0 ${cfg.dot}`} />

        <span className={`text-xs px-1.5 py-0.5 rounded font-medium shrink-0 ${CATEGORY_COLOR[cat] ?? "bg-gray-100 text-gray-600"}`}>
          {cat}
        </span>

        <span className="text-xs font-medium text-gray-800 flex-1 truncate">{node.name}</span>

        {/* Simulated integration badge */}
        {node.is_simulated && (
          <span className="text-[9px] px-1.5 py-0.5 rounded border border-gray-200 bg-gray-50 text-gray-400 font-medium shrink-0"
                title="No real API key configured — this integration is simulated for demo">
            Simulated
          </span>
        )}

        {/* Logs provenance badge — full details */}
        {isLogsNode && (
          <div className="shrink-0 flex flex-col items-end gap-0.5">
            <span className={`text-[10px] px-1.5 py-0.5 rounded border font-medium ${
              node.logs_source === "checkout-service"
                ? "bg-teal-50 text-teal-700 border-teal-200"
                : node.logs_source === "datadog"
                ? "bg-purple-50 text-purple-700 border-purple-200"
                : node.logs_source === "demo"
                ? "bg-amber-50 text-amber-700 border-amber-200"
                : "bg-gray-50 text-gray-500 border-gray-200"
            }`}>
              {node.logs_source === "checkout-service" ? "checkout-service" : node.logs_source === "datadog" ? "Datadog" : node.logs_source === "demo" ? "Demo scenario" : "Mock"} · {node.logs_count ?? 0} logs{node.logs_time_window ? ` · ${node.logs_time_window}` : ""}
            </span>
            {node.logs_query && (
              <span className="text-[9px] font-mono text-gray-400 max-w-[200px] truncate" title={node.logs_query}>
                {node.logs_query}
              </span>
            )}
          </div>
        )}

        {/* Duration / waiting time */}
        {dur && <span className="text-xs text-gray-400 shrink-0">{dur}</span>}
        {isApproval && approvalSince && (
          <span className="text-xs text-blue-500 shrink-0 tabular-nums">
            {elapsed(approvalSince)}
          </span>
        )}
        {node.status === "approved" && (
          <span className="text-xs text-green-600 font-medium shrink-0">✓ Approved</span>
        )}
        {node.status === "rejected" && (
          <span className="text-xs text-red-500 font-medium shrink-0">✗ Rejected</span>
        )}

        <span className={`text-xs font-medium shrink-0 ${cfg.text}`}>{cfg.label}</span>
      </div>

      {/* Approval gate banner */}
      {isApproval && (
        <div className="mt-1 mx-1 p-3 rounded-lg border border-blue-200 bg-blue-50">
          <div className="flex items-start gap-2.5">
            <span className="text-xl leading-none mt-0.5">⏸</span>
            <div>
              <p className="text-xs font-semibold text-blue-800">
                Workflow durably paused in Temporal Cloud
              </p>
              <p className="text-xs text-blue-600 mt-0.5">
                Awaiting human decision · Check <code className="bg-blue-100 px-1 rounded">#incidents</code> in Slack
                {approvalSince && (
                  <span className="ml-1 text-blue-500">· {elapsed(approvalSince)} elapsed</span>
                )}
              </p>
              <p className="text-xs text-blue-400 mt-1">
                Orq will resume execution the moment you approve — no polling, no re-run needed.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Error */}
      {node.error && (
        <div className="mt-1 mx-1 px-2.5 py-1.5 rounded border border-red-100 bg-red-50">
          <p className="text-xs text-red-600 font-mono break-all">{node.error}</p>
        </div>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
export default function ExecutionTimeline({ workflowId, executionId, isMock, mockNodes, workflowNodes }: Props) {
  const [data, setData] = useState<TimelineData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [, setTick] = useState(0);
  const stopRef = useRef(false);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // Mock run: build synthetic timeline from node_statuses
  if (isMock && mockNodes) {
    const nodes: TimelineNode[] = workflowNodes.map((n) => ({
      node_id: n.id,
      name: n.name,
      tool: n.tool,
      status: (mockNodes[n.id] as TimelineNode["status"]) ?? "pending",
      scheduled_at: null,
      started_at: null,
      completed_at: null,
      error: null,
    }));
    const allDone = nodes.every((n) => n.status !== "pending" && n.status !== "running");
    const anyFailed = nodes.some((n) => n.status === "failed");
    return (
      <TimelineView
        nodes={nodes}
        overallStatus={allDone ? (anyFailed ? "failed" : "completed") : "running"}
        approvalWaiting={false}
        approvalSince={null}
        approvalDecision={null}
        executionId={executionId}
        isMock
        triggerSource="mock"
        rcaAnalysis={null}
        rcaService={null}
        rcaEvidence={[]}
      />
    );
  }

  // Real Temporal run: poll the timeline endpoint
  // eslint-disable-next-line react-hooks/rules-of-hooks
  useEffect(() => {
    stopRef.current = false;

    async function poll() {
      try {
        const result = await fetchTimeline(workflowId, executionId);
        if (stopRef.current) return;
        setData(result);
        setError(null);
        if (result.status !== "running") {
          if (timerRef.current) clearInterval(timerRef.current);
        }
      } catch (e) {
        if (!stopRef.current) setError(String(e));
      }
    }

    poll();
    timerRef.current = setInterval(poll, 3000);

    // Tick every second to refresh elapsed-time displays during approval wait
    const tickId = setInterval(() => setTick((t) => t + 1), 1000);

    return () => {
      stopRef.current = true;
      if (timerRef.current) clearInterval(timerRef.current);
      clearInterval(tickId);
    };
  }, [workflowId, executionId]);

  if (error) {
    return <p className="text-xs text-red-500 italic">Could not load timeline: {error}</p>;
  }
  if (!data) {
    return (
      <div className="flex items-center gap-2 text-xs text-gray-400 py-2">
        <span className="w-2 h-2 rounded-full bg-yellow-400 animate-pulse" />
        Connecting to Temporal…
      </div>
    );
  }

  return (
    <TimelineView
      nodes={data.nodes}
      overallStatus={data.status}
      approvalWaiting={data.approval_waiting}
      approvalSince={data.approval_since}
      approvalDecision={data.approval_decision}
      executionId={executionId}
      isMock={false}
      triggerSource={data.trigger_source ?? null}
      rcaAnalysis={data.rca_analysis ?? null}
      rcaService={data.rca_service ?? null}
      rcaEvidence={data.rca_evidence ?? []}
    />
  );
}

// ── Pure view (no side-effects) ───────────────────────────────────────────────
function TimelineView({
  nodes, overallStatus, approvalWaiting, approvalSince, approvalDecision, executionId, isMock,
  triggerSource, rcaAnalysis, rcaService, rcaEvidence,
}: {
  nodes: TimelineNode[];
  overallStatus: string;
  approvalWaiting: boolean;
  approvalSince: string | null;
  approvalDecision: string | null;
  executionId: string;
  isMock: boolean;
  triggerSource?: string | null;
  rcaAnalysis?: string | null;
  rcaService?: string | null;
  rcaEvidence?: string[];
}) {
  const headerColor =
    overallStatus === "completed" ? "text-green-700 bg-green-50 border-green-200" :
    overallStatus === "failed"    ? "text-red-700 bg-red-50 border-red-200" :
                                    "text-yellow-700 bg-yellow-50 border-yellow-200";

  const headerLabel =
    overallStatus === "completed" ? "✅ Completed" :
    overallStatus === "failed"    ? "❌ Failed" :
    approvalWaiting               ? "⏸ Paused — awaiting approval" :
                                    "⚡ Running";

  const completedCount = nodes.filter((n) => ["success", "approved"].includes(n.status)).length;
  const totalCount = nodes.length;

  return (
    <div className="space-y-2">
      {/* Header bar */}
      <div className={`flex items-center justify-between px-3 py-2 rounded-lg border text-xs font-medium ${headerColor}`}>
        <span className="flex items-center gap-2">
          {overallStatus === "running" && !approvalWaiting && (
            <span className="w-1.5 h-1.5 rounded-full bg-yellow-400 animate-pulse" />
          )}
          {headerLabel}
        </span>
        <div className="flex items-center gap-2 text-xs">
          {triggerSource && <SourceBadge source={triggerSource} />}
          <span className="opacity-60">{completedCount}/{totalCount} nodes</span>
          <span className="font-mono opacity-40">{executionId.slice(-8)}</span>
        </div>
      </div>

      {/* Post-approval resume notice */}
      {approvalDecision && (
        <div className={`flex items-center gap-2 px-3 py-2 rounded-lg border text-xs ${
          approvalDecision === "approved"
            ? "bg-green-50 border-green-200 text-green-700"
            : "bg-red-50 border-red-200 text-red-600"
        }`}>
          <span>{approvalDecision === "approved" ? "✅" : "❌"}</span>
          <span className="font-medium">
            {approvalDecision === "approved"
              ? "Approved in Slack — workflow resumed"
              : "Rejected in Slack — workflow halted"}
          </span>
        </div>
      )}

      {/* Execution provenance strip — real runs only */}
      {!isMock && nodes.length > 0 && (
        <ExecutionProvenanceStrip triggerSource={triggerSource} nodes={nodes} />
      )}

      {/* Node list */}
      <div className="space-y-1.5">
        {nodes.map((node) => (
          <NodeRow
            key={node.node_id}
            node={node}
            approvalSince={approvalWaiting ? approvalSince : null}
          />
        ))}
      </div>

      {/* Full RCA panel — only when analysis is available */}
      {rcaAnalysis && (
        <RCAPanel
          analysis={rcaAnalysis}
          service={rcaService ?? undefined}
          evidence={rcaEvidence}
        />
      )}
    </div>
  );
}
