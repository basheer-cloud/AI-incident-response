"use client";
import { useEffect, useState, useCallback } from "react";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

interface Approval {
  approval_id: string;
  execution_id: string;
  workflow_id: string;
  title: string;
  description: string;
  channel: string;
  status: string;
  created_at: string;
}

export default function ApprovalInbox() {
  const [approvals, setApprovals] = useState<Approval[]>([]);
  const [deciding, setDeciding] = useState<string | null>(null);

  const fetchApprovals = useCallback(async () => {
    try {
      const res = await fetch(`${BASE}/approvals/`);
      if (res.ok) setApprovals(await res.json());
    } catch {}
  }, []);

  useEffect(() => {
    fetchApprovals();
    const id = setInterval(fetchApprovals, 3000);
    return () => clearInterval(id);
  }, [fetchApprovals]);

  async function respond(approvalId: string, decision: "approved" | "rejected") {
    setDeciding(approvalId);
    try {
      await fetch(`${BASE}/approvals/${approvalId}/respond`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ decision }),
      });
      setApprovals((prev) => prev.filter((a) => a.approval_id !== approvalId));
    } finally {
      setDeciding(null);
    }
  }

  if (!approvals.length) return null;

  return (
    <div className="rounded-xl border-2 border-amber-300 bg-amber-50 overflow-hidden">
      <div className="px-4 py-2.5 bg-amber-100 border-b border-amber-200 flex items-center gap-2">
        <span className="text-amber-600 font-bold text-sm">⏸ Pending Approvals</span>
        <span className="ml-auto text-xs bg-amber-500 text-white px-2 py-0.5 rounded-full font-bold">
          {approvals.length}
        </span>
      </div>

      <div className="divide-y divide-amber-100">
        {approvals.map((a) => (
          <div key={a.approval_id} className="p-4 space-y-3">
            <div>
              <p className="font-semibold text-gray-900 text-sm">{a.title}</p>
              <p className="text-xs text-gray-600 mt-1 whitespace-pre-wrap">{a.description}</p>
            </div>
            <div className="flex items-center gap-2 text-xs text-gray-400">
              <span className="font-mono">{a.approval_id}</span>
              <span>·</span>
              <span>{a.channel}</span>
              <span>·</span>
              <span>{new Date(a.created_at).toLocaleTimeString()}</span>
            </div>
            <div className="flex gap-2">
              <button
                onClick={() => respond(a.approval_id, "approved")}
                disabled={deciding === a.approval_id}
                className="flex-1 py-2 rounded-lg bg-green-600 text-white text-sm font-semibold hover:bg-green-700 disabled:opacity-50 transition-colors"
              >
                {deciding === a.approval_id ? "…" : "✅ Approve"}
              </button>
              <button
                onClick={() => respond(a.approval_id, "rejected")}
                disabled={deciding === a.approval_id}
                className="flex-1 py-2 rounded-lg bg-red-500 text-white text-sm font-semibold hover:bg-red-600 disabled:opacity-50 transition-colors"
              >
                {deciding === a.approval_id ? "…" : "❌ Reject"}
              </button>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
