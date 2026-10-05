"use client";
import { useState, useEffect } from "react";
import { fetchMetricsSummary, type MetricsSummary } from "@/lib/api";

// ── Helpers ──────────────────────────────────────────────────────────────────
function formatMTTR(seconds: number | null): string {
  if (seconds === null) return "—";
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

// ── Single stat chip ─────────────────────────────────────────────────────────
function Stat({
  label,
  value,
  sub,
  color,
  loading,
}: {
  label: string;
  value: string;
  sub?: string;
  color: string;
  loading: boolean;
}) {
  return (
    <div className="flex flex-col gap-0.5 px-4 py-2.5 first:pl-0 border-r border-gray-100 last:border-0 last:pr-0">
      <span className="text-[10px] font-medium text-gray-400 uppercase tracking-wider">{label}</span>
      {loading ? (
        <span className="h-5 w-12 rounded bg-gray-100 animate-pulse" />
      ) : (
        <span className={`text-lg font-bold tabular-nums leading-tight ${color}`}>{value}</span>
      )}
      {sub && !loading && (
        <span className="text-[10px] text-gray-400">{sub}</span>
      )}
    </div>
  );
}

// ── Main component ────────────────────────────────────────────────────────────
export default function MetricsBar() {
  const [data, setData] = useState<MetricsSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let mounted = true;

    async function load() {
      try {
        const result = await fetchMetricsSummary();
        if (mounted) {
          setData(result);
          setLoading(false);
        }
      } catch {
        // Silently degrade — metrics are non-critical
        if (mounted) setLoading(false);
      }
    }

    load();
    // Refresh every 30s to catch new runs
    const id = setInterval(load, 30_000);
    return () => {
      mounted = false;
      clearInterval(id);
    };
  }, []);

  // Only render when we have something to show
  const hasData = data && (data.total_incidents > 0 || loading);
  if (!hasData && !loading) return null;

  const autoResolvedPct = data?.auto_resolved_pct;
  const avgMTTR = formatMTTR(data?.avg_mttr_seconds ?? null);
  const p95MTTR = formatMTTR(data?.p95_mttr_seconds ?? null);

  // Colour the auto-resolve % based on value
  const resolveColor =
    autoResolvedPct == null ? "text-gray-400" :   // == catches both null and undefined
    autoResolvedPct >= 80 ? "text-green-600" :
    autoResolvedPct >= 60 ? "text-yellow-600" :
    "text-red-500";

  return (
    <div className="bg-white border-b border-gray-100 px-6 py-0.5">
      <div className="max-w-6xl mx-auto flex items-center gap-0 text-sm">
        {/* Live indicator + workspace label */}
        <div className="flex items-center gap-1.5 pr-4 mr-2 border-r border-gray-100">
          <span className="w-1.5 h-1.5 rounded-full bg-green-400 animate-pulse" />
          <span className="text-[10px] font-medium text-gray-400 uppercase tracking-wider">Demo workspace</span>
        </div>

        <Stat
          label="Incidents"
          value={data ? String(data.total_incidents) : "—"}
          sub={data && data.running > 0 ? `${data.running} active` : undefined}
          color="text-gray-900"
          loading={loading}
        />

        <Stat
          label="Approved resolutions"
          value={autoResolvedPct !== null && autoResolvedPct !== undefined ? `${autoResolvedPct}%` : "—"}
          sub={data ? `${data.completed} of ${data.completed + data.failed} runs` : undefined}
          color={resolveColor}
          loading={loading}
        />

        <Stat
          label="Avg MTTR"
          value={avgMTTR}
          sub={data?.sample_size ? `n=${data.sample_size}` : undefined}
          color="text-indigo-600"
          loading={loading}
        />

        <Stat
          label="P95 MTTR"
          value={p95MTTR}
          color="text-gray-700"
          loading={loading}
        />

        {data && data.running > 0 && (
          <div className="ml-auto flex items-center gap-1.5 text-[10px] text-yellow-600 font-medium">
            <span className="w-1.5 h-1.5 rounded-full bg-yellow-400 animate-pulse" />
            {data.running} workflow{data.running > 1 ? "s" : ""} running
          </div>
        )}
      </div>
    </div>
  );
}
