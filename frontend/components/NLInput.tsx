"use client";
import { useState } from "react";
import { parseWorkflow, type WorkflowDefinition } from "@/lib/api";

interface Props {
  onWorkflowParsed: (wf: WorkflowDefinition) => void;
}

const EXAMPLES = [
  "When a Stripe payment fails, send a Slack alert to #finance and create a Jira ticket",
  "Every Monday morning, summarize last week's tasks and email the team",
  "When a GitHub PR is opened, run an AI code review and post the result as a comment",
];

export default function NLInput({ onWorkflowParsed }: Props) {
  const [description, setDescription] = useState("");
  const [loading, setLoading] = useState(false);
  const [clarification, setClarification] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(force = false) {
    if (!description.trim()) return;
    setLoading(true);
    setError(null);
    setClarification(null);
    try {
      const result = await parseWorkflow(description, force);
      if (result.needs_clarification && result.question) {
        setClarification(result.question);
      } else if (result.workflow) {
        onWorkflowParsed(result.workflow);
        setDescription("");
      }
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-3">
      <div className="flex gap-2">
        <textarea
          className="flex-1 rounded-lg border border-gray-300 p-3 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-indigo-500"
          rows={3}
          placeholder="Describe your workflow in plain English…"
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) handleSubmit(); }}
        />
        <button
          onClick={() => handleSubmit()}
          disabled={loading || !description.trim()}
          className="px-5 rounded-lg bg-indigo-600 text-white font-medium text-sm hover:bg-indigo-700 disabled:opacity-50 transition-colors"
        >
          {loading ? "…" : "Build"}
        </button>
      </div>

      {/* Example chips */}
      <div className="flex flex-wrap gap-2">
        {EXAMPLES.map((ex) => (
          <button
            key={ex}
            onClick={() => setDescription(ex)}
            className="text-xs px-3 py-1 rounded-full border border-gray-300 hover:border-indigo-400 hover:text-indigo-600 transition-colors truncate max-w-xs"
          >
            {ex}
          </button>
        ))}
      </div>

      {/* Clarification banner */}
      {clarification && (
        <div className="rounded-lg bg-amber-50 border border-amber-200 p-3 text-sm flex items-start gap-3">
          <span className="text-amber-500 mt-0.5">❓</span>
          <div className="flex-1">
            <p className="font-medium text-amber-800">{clarification}</p>
            <button
              onClick={() => handleSubmit(true)}
              className="mt-2 text-xs text-amber-700 underline"
            >
              Looks good, proceed anyway
            </button>
          </div>
        </div>
      )}

      {/* Error */}
      {error && (
        <p className="text-sm text-red-600 bg-red-50 rounded-lg p-2 border border-red-200">{error}</p>
      )}
    </div>
  );
}
