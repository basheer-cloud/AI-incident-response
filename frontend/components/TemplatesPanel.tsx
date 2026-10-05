"use client";
import { useEffect, useState } from "react";
import type { WorkflowDefinition } from "@/lib/api";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";

const TAG_COLORS: Record<string, string> = {
  payments: "bg-green-50 text-green-700",
  ops: "bg-blue-50 text-blue-700",
  scheduling: "bg-purple-50 text-purple-700",
  reporting: "bg-orange-50 text-orange-700",
  github: "bg-gray-100 text-gray-700",
  ai: "bg-indigo-50 text-indigo-700",
  devops: "bg-red-50 text-red-700",
};

interface Props {
  onImport: (wf: WorkflowDefinition) => void;
}

export default function TemplatesPanel({ onImport }: Props) {
  const [templates, setTemplates] = useState<WorkflowDefinition[]>([]);
  const [importing, setImporting] = useState<string | null>(null);

  useEffect(() => {
    fetch(`${BASE}/workflows/templates`)
      .then((r) => r.json())
      .then(setTemplates)
      .catch(() => {});
  }, []);

  async function handleImport(templateId: string) {
    setImporting(templateId);
    try {
      const res = await fetch(`${BASE}/workflows/templates/${templateId}/import`, { method: "POST" });
      const wf: WorkflowDefinition = await res.json();
      onImport(wf);
    } finally {
      setImporting(null);
    }
  }

  if (!templates.length) return null;

  return (
    <div className="space-y-2">
      <h2 className="text-xs font-semibold text-gray-500 uppercase tracking-wider px-1">
        Templates
      </h2>
      {templates.map((t) => (
        <div key={t.workflow_id}
          className="rounded-xl border border-dashed border-gray-200 p-3 bg-white space-y-2 hover:border-indigo-300 transition-colors">
          <div className="flex items-start justify-between gap-2">
            <p className="text-sm font-medium text-gray-800">{t.name}</p>
            <button
              onClick={() => handleImport(t.workflow_id)}
              disabled={importing === t.workflow_id}
              className="shrink-0 text-xs px-2.5 py-1 rounded-lg border border-indigo-300 text-indigo-600 hover:bg-indigo-50 disabled:opacity-50 transition-colors"
            >
              {importing === t.workflow_id ? "…" : "Use"}
            </button>
          </div>
          <p className="text-xs text-gray-500">{t.description}</p>
          <div className="flex flex-wrap gap-1">
            {t.tags.map((tag) => (
              <span key={tag} className={`text-xs px-2 py-0.5 rounded-full ${TAG_COLORS[tag] ?? "bg-gray-100 text-gray-600"}`}>
                {tag}
              </span>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
