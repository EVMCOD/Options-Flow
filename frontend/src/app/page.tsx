"use client";

import { useCallback, useState } from "react";
import { useRouter } from "next/navigation";
import { getAlerts, getMetricsSummary, getUpcomingEvents, triggerIngestion } from "@/lib/api";
import { usePolling } from "@/hooks/usePolling";
import { TopBar } from "@/components/layout/TopBar";
import { SummaryCards } from "@/components/overview/SummaryCards";
import { LatestAlerts } from "@/components/overview/LatestAlerts";
import { Card, CardHeader } from "@/components/ui/Card";
import type { AlertsByLevel, MetricsSummary, UpcomingEventSummary } from "@/lib/types";

// ── Alert level distribution bars ────────────────────────────────────────────

const LEVEL_ORDER: (keyof AlertsByLevel)[] = ["CRITICAL", "HIGH", "MEDIUM", "LOW"];
const LEVEL_COLORS: Record<string, string> = {
  CRITICAL: "bg-critical",
  HIGH: "bg-high",
  MEDIUM: "bg-medium",
  LOW: "bg-low",
};

function AlertLevelBars({ data }: { data: AlertsByLevel }) {
  const total = Object.values(data).reduce((a, b) => a + b, 0);
  return (
    <Card>
      <CardHeader title="Alert Distribution" subtitle="Active alerts by severity" />
      <div className="px-4 py-4 space-y-3">
        {LEVEL_ORDER.map((level) => {
          const count = data[level];
          const pct = total > 0 ? (count / total) * 100 : 0;
          return (
            <div key={level} className="space-y-1">
              <div className="flex justify-between text-xs">
                <span className="font-mono text-text-muted">{level}</span>
                <span className="font-mono tabular-nums text-text-primary">
                  {count.toLocaleString()}
                </span>
              </div>
              <div className="w-full h-1.5 bg-bg-base">
                <div
                  className={`h-full ${LEVEL_COLORS[level]} transition-all duration-300`}
                  style={{ width: `${pct.toFixed(1)}%` }}
                />
              </div>
            </div>
          );
        })}
        {total === 0 && (
          <p className="text-xs text-text-subtle">No active alerts.</p>
        )}
      </div>
    </Card>
  );
}

// ── Upcoming catalysts strip ──────────────────────────────────────────────────

const EVENT_TYPE_LABELS: Record<string, string> = {
  earnings: "Earnings",
  fda_decision: "FDA",
  pdufa: "PDUFA",
  regulatory: "Regulatory",
  investor_day: "Investor Day",
  product_event: "Product Event",
  macro_relevant: "Macro",
  custom: "Event",
};

function urgencyStyles(days: number) {
  if (days <= 1) return "border-critical/40 bg-critical/5 text-critical";
  if (days <= 3) return "border-high/40 bg-high/5 text-high";
  if (days <= 7) return "border-accent/30 bg-accent/5 text-accent";
  return "border-border bg-bg-panel text-text-muted";
}

function daysLabel(days: number) {
  if (days === 0) return "Today";
  if (days === 1) return "Tomorrow";
  return `${days}d`;
}

function UpcomingCatalysts({ events }: { events: UpcomingEventSummary[] }) {
  const router = useRouter();

  return (
    <Card>
      <CardHeader
        title="Upcoming Catalysts"
        subtitle={`${events.length} event${events.length !== 1 ? "s" : ""} in monitored universe`}
      />
      <div className="px-4 pb-4">
        <div className="flex flex-wrap gap-2">
          {events.map((ev) => (
            <button
              key={`${ev.symbol}-${ev.event_date}`}
              onClick={() => router.push("/events")}
              className={`flex items-center gap-1.5 px-2.5 py-1.5 border rounded-sm text-xs font-mono transition-opacity hover:opacity-80 ${urgencyStyles(ev.days_to_event)}`}
            >
              <span className="font-bold">{ev.symbol}</span>
              <span className="opacity-70">
                {EVENT_TYPE_LABELS[ev.event_type] ?? ev.event_type}
              </span>
              <span className="font-semibold">{daysLabel(ev.days_to_event)}</span>
            </button>
          ))}
        </div>
      </div>
    </Card>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

const EMPTY_METRICS: MetricsSummary = {
  total_alerts: 0,
  active_alerts: 0,
  top_symbols: [],
  alerts_by_level: { LOW: 0, MEDIUM: 0, HIGH: 0, CRITICAL: 0 },
  last_run_at: null,
};

type IngestionState = "idle" | "triggering" | "triggered" | "error";

export default function OverviewPage() {
  const fetchMetrics = useCallback(() => getMetricsSummary(), []);
  // Active alerts only — overview shows signal, not historical noise
  const fetchAlerts = useCallback(
    () => getAlerts({ limit: 8, status: "active" }),
    []
  );
  const fetchEvents = useCallback(() => getUpcomingEvents(), []);

  const [ingestionState, setIngestionState] = useState<IngestionState>("idle");

  const {
    data: metrics,
    loading: metricsLoading,
    lastUpdated,
    refetch: refetchMetrics,
  } = usePolling(fetchMetrics, 30_000);

  const { data: alerts, refetch: refetchAlerts } = usePolling(fetchAlerts, 30_000);
  const { data: events, refetch: refetchEvents } = usePolling(fetchEvents, 60_000);

  const handleRefresh = () => {
    refetchMetrics();
    refetchAlerts();
    refetchEvents();
  };

  const handleRunIngestion = async () => {
    if (ingestionState === "triggering") return;
    setIngestionState("triggering");
    try {
      await triggerIngestion();
      setIngestionState("triggered");
      setTimeout(handleRefresh, 3000);
      setTimeout(() => setIngestionState("idle"), 5000);
    } catch {
      setIngestionState("error");
      setTimeout(() => setIngestionState("idle"), 5000);
    }
  };

  const summary = metrics ?? EMPTY_METRICS;
  const upcomingEvents = events ?? [];

  return (
    <div className="flex flex-col h-full">
      <TopBar
        title="Overview"
        lastUpdated={lastUpdated}
        onRefresh={handleRefresh}
        loading={metricsLoading}
      />

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* Top action bar */}
        <div className="flex justify-end">
          <button
            onClick={handleRunIngestion}
            disabled={ingestionState === "triggering"}
            className={`px-4 py-1.5 text-xs font-mono border transition-colors disabled:cursor-not-allowed ${
              ingestionState === "triggered"
                ? "border-green-500/40 text-green-400"
                : ingestionState === "error"
                  ? "border-red-500/40 text-red-400"
                  : "border-accent/40 text-accent hover:bg-accent/10"
            }`}
          >
            {ingestionState === "triggering"
              ? "Triggering…"
              : ingestionState === "triggered"
                ? "✓ Triggered"
                : ingestionState === "error"
                  ? "Failed — retry?"
                  : "Run Ingestion"}
          </button>
        </div>

        {/* Summary metrics */}
        <SummaryCards data={summary} />

        {/* Upcoming earnings / catalysts — only rendered when events are seeded */}
        {upcomingEvents.length > 0 && (
          <UpcomingCatalysts events={upcomingEvents} />
        )}

        {/* Two-column: distribution + top symbols */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          <AlertLevelBars data={summary.alerts_by_level} />

          <Card>
            <CardHeader title="Top Symbols" subtitle="H/C alerts in last 24 hours" />
            <div className="px-4 py-4 space-y-2">
              {summary.top_symbols.length === 0 && (
                <p className="text-xs text-text-subtle">
                  No HIGH or CRITICAL activity in the last 24 hours.
                </p>
              )}
              {summary.top_symbols.map((s) => (
                <div key={s.symbol} className="flex justify-between items-center text-sm">
                  <span className="font-mono font-semibold text-text-primary">
                    {s.symbol}
                  </span>
                  <span className="font-mono tabular-nums text-text-muted text-xs">
                    {s.count} alert{s.count !== 1 ? "s" : ""}
                  </span>
                </div>
              ))}
            </div>
          </Card>
        </div>

        {/* Latest active alerts */}
        <LatestAlerts alerts={alerts ?? []} />
      </div>
    </div>
  );
}
