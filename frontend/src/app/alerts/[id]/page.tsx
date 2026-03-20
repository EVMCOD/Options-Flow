"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft } from "lucide-react";
import { format } from "date-fns";
import { getAlert } from "@/lib/api";
import type { AlertOut } from "@/lib/types";
import { AlertLevelBadge, StatusBadge } from "@/components/ui/Badge";
import { Card, CardHeader } from "@/components/ui/Card";

interface DataRowProps {
  label: string;
  value: string | number | null | undefined;
  mono?: boolean;
  highlight?: boolean;
}

function DataRow({ label, value, mono = true, highlight = false }: DataRowProps) {
  return (
    <div className="flex justify-between items-baseline border-b border-border/40 py-2">
      <span className="text-xs text-text-subtle uppercase tracking-wider">{label}</span>
      <span
        className={`text-sm ${mono ? "font-mono tabular-nums" : ""} ${
          highlight ? "text-text-primary font-semibold" : "text-text-muted"
        }`}
      >
        {value ?? "—"}
      </span>
    </div>
  );
}

export default function AlertDetailPage({ params }: { params: { id: string } }) {
  const router = useRouter();
  const [alert, setAlert] = useState<AlertOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getAlert(params.id)
      .then(setAlert)
      .catch((err) => setError(err instanceof Error ? err.message : "Failed to load"))
      .finally(() => setLoading(false));
  }, [params.id]);

  if (loading) {
    return (
      <div className="p-6 text-text-subtle text-sm font-mono">Loading alert…</div>
    );
  }

  if (error || !alert) {
    return (
      <div className="p-6">
        <p className="text-critical text-sm font-mono">{error ?? "Alert not found"}</p>
        <button
          onClick={() => router.back()}
          className="mt-4 text-xs text-text-muted hover:text-text-primary"
        >
          ← Go back
        </button>
      </div>
    );
  }

  const optionTypeLabel = alert.option_type === "C" ? "Call" : "Put";
  const strikeNum = parseFloat(alert.strike);

  return (
    <div className="flex flex-col h-full">
      {/* Mini topbar */}
      <header className="flex items-center gap-4 px-6 py-3 border-b border-border bg-bg-panel shrink-0">
        <button
          onClick={() => router.back()}
          className="flex items-center gap-1.5 text-xs text-text-muted hover:text-text-primary transition-colors"
        >
          <ArrowLeft className="w-3.5 h-3.5" />
          Back
        </button>
        <div className="flex items-center gap-3">
          <AlertLevelBadge level={alert.alert_level} />
          <h1 className="text-sm font-semibold text-text-primary font-mono">
            {alert.underlying_symbol} · {alert.expiry} · ${strikeNum.toFixed(0)}{" "}
            {optionTypeLabel}
          </h1>
        </div>
        <div className="ml-auto">
          <StatusBadge status={alert.status} />
        </div>
      </header>

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* Explanation */}
        <div className="border-l-4 border-accent bg-accent/5 px-5 py-4">
          <p className="text-xs text-text-subtle uppercase tracking-widest mb-2">
            Signal Explanation
          </p>
          <p className="text-sm text-text-primary leading-relaxed">{alert.explanation}</p>
        </div>

        {/* Two column layout */}
        <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {/* Contract info */}
          <Card>
            <CardHeader title="Contract Details" />
            <div className="px-4 py-2">
              <DataRow label="Symbol" value={alert.underlying_symbol} highlight />
              <DataRow label="Expiry" value={alert.expiry} />
              <DataRow label="Strike" value={`$${strikeNum.toFixed(2)}`} highlight />
              <DataRow
                label="Option Type"
                value={optionTypeLabel}
                highlight
              />
              <DataRow label="As of" value={format(new Date(alert.as_of_ts), "yyyy-MM-dd HH:mm:ss")} />
              <DataRow label="Alert created" value={format(new Date(alert.created_at), "yyyy-MM-dd HH:mm:ss")} />
              <DataRow label="Snapshot ID" value={alert.snapshot_id.slice(0, 16) + "…"} />
            </div>
          </Card>

          {/* Signal metrics */}
          <Card>
            <CardHeader title="Signal Metrics" />
            <div className="px-4 py-2">
              <DataRow
                label="Anomaly Score"
                value={alert.anomaly_score.toFixed(3) + " / 10.000"}
                highlight
              />
              <DataRow label="Alert Level" value={alert.alert_level} highlight />
              <DataRow label="Status" value={alert.status} mono={false} />
            </div>
          </Card>
        </div>

        {/* Catalyst — only rendered when catalyst context is present */}
        {alert.catalyst_context && (
          <Card>
            <CardHeader
              title="Catalyst"
              subtitle="Upcoming event at alert creation time"
            />
            <div className="px-4 py-2">
              <DataRow
                label="Context"
                value={alert.catalyst_context}
                mono={false}
                highlight
              />
              {alert.next_event_type && (
                <DataRow label="Event type" value={alert.next_event_type} mono={false} />
              )}
              {alert.next_event_date && (
                <DataRow label="Event date" value={alert.next_event_date} />
              )}
              {alert.days_to_event !== null && alert.days_to_event !== undefined && (
                <DataRow
                  label="Days to event"
                  value={`${alert.days_to_event} day${alert.days_to_event !== 1 ? "s" : ""}`}
                />
              )}
              {alert.contributing_factors_json?.catalyst && (
                <DataRow
                  label="Priority boost"
                  value={`×${alert.contributing_factors_json.catalyst.boost_applied.toFixed(2)}`}
                  highlight={alert.contributing_factors_json.catalyst.boost_applied > 1.0}
                />
              )}
            </div>
          </Card>
        )}

        {/* Raw IDs */}
        <Card>
          <CardHeader title="Identifiers" />
          <div className="px-4 py-2">
            <DataRow label="Alert ID" value={alert.id} />
            <DataRow label="Snapshot ID" value={alert.snapshot_id} />
          </div>
        </Card>
      </div>
    </div>
  );
}
