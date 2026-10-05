"use client";
import { useCallback, useEffect } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  addEdge,
  useNodesState,
  useEdgesState,
  type Connection,
  type Node,
  type Edge,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import type { WorkflowDefinition } from "@/lib/api";

interface Props {
  workflow: WorkflowDefinition;
  liveStatus?: Record<string, string>; // nodeId → "pending"|"running"|"success"|"failed"
}

const TOOL_COLORS: Record<string, string> = {
  "slack.send_message": "#4A154B",
  "email.send": "#EA4335",
  "http.post": "#0066CC",
  "http.get": "#0066CC",
  "jira.create_ticket": "#0052CC",
  "openai.summarize": "#10A37F",
  "zendesk.create_ticket": "#03363D",
  "github.create_issue": "#24292F",
  "stripe.retry_payment": "#635BFF",
  "notion.create_page": "#000000",
};

const STATUS_OVERLAY: Record<string, { border: string; glow: string; icon: string }> = {
  running: { border: "#FBBF24", glow: "0 0 12px 3px rgba(251,191,36,0.6)", icon: "⏳" },
  success: { border: "#22C55E", glow: "0 0 12px 3px rgba(34,197,94,0.5)",  icon: "✓" },
  failed:  { border: "#EF4444", glow: "0 0 12px 3px rgba(239,68,68,0.5)",   icon: "✕" },
  pending: { border: "transparent", glow: "none", icon: "" },
};

function buildNodes(wf: WorkflowDefinition, liveStatus: Record<string, string>): Node[] {
  const triggerStatus = liveStatus["trigger"];
  const triggerOverlay = triggerStatus ? STATUS_OVERLAY[triggerStatus] : null;

  const triggerNode: Node = {
    id: "trigger",
    type: "input",
    position: { x: 260, y: 0 },
    data: { label: `⚡ Trigger · ${wf.trigger.type}` },
    style: {
      background: "#F59E0B",
      color: "#fff",
      fontWeight: 700,
      borderRadius: 10,
      width: 180,
      border: triggerOverlay ? `2px solid ${triggerOverlay.border}` : "2px solid transparent",
      boxShadow: triggerOverlay?.glow ?? "none",
      transition: "all 0.4s ease",
    },
  };

  const flowNodes: Node[] = [
    triggerNode,
    ...wf.nodes.map((node, i) => {
      const st = liveStatus[node.id];
      const overlay = st ? STATUS_OVERLAY[st] : null;
      const baseColor = TOOL_COLORS[node.tool] ?? "#6366F1";
      const isDimmed = Object.keys(liveStatus).length > 0 && !st;

      return {
        id: node.id,
        position: { x: 260, y: (i + 1) * 130 },
        data: {
          label: (
            <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
              {overlay?.icon && (
                <span style={{ fontSize: 14, lineHeight: 1 }}>{overlay.icon}</span>
              )}
              <div>
                <div style={{ fontWeight: 700, fontSize: 13 }}>{node.name}</div>
                <div style={{ fontSize: 10, opacity: 0.8, fontFamily: "monospace" }}>{node.tool}</div>
              </div>
            </div>
          ),
        },
        style: {
          background: baseColor,
          color: "#fff",
          borderRadius: 10,
          width: 200,
          opacity: isDimmed ? 0.4 : 1,
          border: overlay ? `2px solid ${overlay.border}` : "2px solid transparent",
          boxShadow: overlay?.glow ?? "none",
          transition: "all 0.4s ease",
        },
      };
    }),
  ];

  return flowNodes;
}

function buildEdges(wf: WorkflowDefinition): Edge[] {
  return wf.edges.map((e, i) => ({
    id: `e-${i}`,
    source: e.from,
    target: e.to,
    label: e.condition ? e.condition.replace("node_\\d+\\.status == ", "if ") : undefined,
    animated: true,
    style: { stroke: "#6366F1", strokeWidth: 2 },
    labelStyle: { fontSize: 10, fill: "#6B7280" },
    labelBgStyle: { fill: "#F9FAFB", fillOpacity: 0.9 },
  }));
}

export default function WorkflowCanvas({ workflow, liveStatus = {} }: Props) {
  const [nodes, setNodes, onNodesChange] = useNodesState(buildNodes(workflow, liveStatus));
  const [edges, setEdges, onEdgesChange] = useEdgesState(buildEdges(workflow));

  // Re-build nodes whenever liveStatus changes (this drives the animation)
  useEffect(() => {
    setNodes(buildNodes(workflow, liveStatus));
  }, [liveStatus, workflow, setNodes]);

  const onConnect = useCallback(
    (connection: Connection) => setEdges((eds) => addEdge(connection, eds)),
    [setEdges]
  );

  return (
    <div style={{ height: 480, borderRadius: 12, overflow: "hidden", border: "1px solid #E5E7EB" }}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        fitView
      >
        <Background />
        <Controls />
        <MiniMap nodeColor={(n) => (n.style?.background as string) ?? "#6366F1"} />
      </ReactFlow>
    </div>
  );
}
