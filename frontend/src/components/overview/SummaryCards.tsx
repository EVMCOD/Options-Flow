"use client";

import { formatDistanceToNow } from "date-fns";
import type { MetricsSummary } from "@/lib/types";
import { Card } from "@/components/ui/Card";

interface MetricCardProps {
  label: string;
  value: string | number;
  sub?: string;
  valueClass?: string;
}

function MetricCard({ label, value, sub, valueClass = "" }: MetricCardProps) {
  return (
    <Card className="px-4 py-4">
      <p className="text-xs text-text-subtle uppercase tracking-widest mb-2">{label}</p>
      <p className={`text-3xl font-mono font-bold tabular-nums ${valueClass}`}>{value}</p>
      {sub && <p className="text-xs text-text-subtle mt-1">{sub}</p>}
    </Card>
  );
}

interface SummaryCardsProps {
  data: MetricsSummary;
}

export function SummaryCards({ data }: SummaryCardsProps) {
  const criticalHigh = data.alerts_by_level.CRITICAL + data.alerts_by_level.HIGH;

  const lastScanValue = data.last_run_at
    ? formatDistanceToNow(new Date(data.last_run_at), { addSuffix: true })
    : "Never";

  const lastScanClass = !data.last_run_at
    ? "text-text-subtle"
    : Date.now() - new Date(data.last_run_at).getTime() > 30 * 60 * 1000
    ? "text-high"
    : "text-accent";

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <MetricCard
        label="Active H/C"
        value={data.active_alerts.toLocaleString()}
        sub="HIGH + CRITICAL active"
        valueClass={data.active_alerts > 0 ? "text-accent" : "text-text-primary"}
      />
      <MetricCard
        label="Critical / High"
        value={criticalHigh.toLocaleString()}
        sub={`${data.alerts_by_level.CRITICAL} CRIT · ${data.alerts_by_level.HIGH} HIGH`}
        valueClass={criticalHigh > 0 ? "text-critical" : "text-text-primary"}
      />
      <MetricCard
        label="Last Scan"
        value={lastScanValue}
        sub="Most recent ingestion run"
        valueClass={lastScanClass}
      />
      <MetricCard
        label="Top Symbols"
        value={data.top_symbols.length > 0 ? data.top_symbols.length : "—"}
        sub="With H/C flow today"
      />
    </div>
  );
}
