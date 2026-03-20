"use client";

import { useCallback, useState } from "react";
import { getAlerts, getUniverse } from "@/lib/api";
import { usePolling } from "@/hooks/usePolling";
import { TopBar } from "@/components/layout/TopBar";
import { AlertFilters } from "@/components/alerts/AlertFilters";
import { AlertsTable } from "@/components/alerts/AlertsTable";
import { Card } from "@/components/ui/Card";
import type { AlertLevel, AlertStatus } from "@/lib/types";

export default function AlertsPage() {
  const [symbol, setSymbol] = useState("");
  const [alertLevel, setAlertLevel] = useState<AlertLevel | "">("");
  const [status, setStatus] = useState<AlertStatus | "">("active");

  const fetchUniverse = useCallback(() => getUniverse(), []);
  const { data: universe } = usePolling(fetchUniverse, 60_000);

  const fetchAlerts = useCallback(
    () =>
      getAlerts({
        symbol: symbol || undefined,
        alert_level: alertLevel || undefined,
        status: status || undefined,
        limit: 200,
      }),
    [symbol, alertLevel, status]
  );

  const {
    data: alerts,
    loading,
    lastUpdated,
    refetch,
  } = usePolling(fetchAlerts, 30_000);

  const handleFilterChange = (key: string, value: string) => {
    if (key === "symbol") setSymbol(value);
    if (key === "alertLevel") setAlertLevel(value as AlertLevel | "");
    if (key === "status") setStatus(value as AlertStatus | "");
  };

  return (
    <div className="flex flex-col h-full">
      <TopBar
        title="Alerts"
        lastUpdated={lastUpdated}
        onRefresh={refetch}
        loading={loading}
      />

      <div className="flex-1 overflow-y-auto p-6 space-y-4">
        <AlertFilters
          symbol={symbol}
          alertLevel={alertLevel}
          status={status}
          universe={universe ?? []}
          onChange={handleFilterChange}
        />

        <Card>
          <div className="flex items-center justify-between px-4 py-2.5 border-b border-border">
            <span className="text-xs text-text-subtle font-mono">
              {alerts
                ? `${alerts.length} alert${alerts.length !== 1 ? "s" : ""}${status ? ` · ${status}` : ""}`
                : "Loading…"}
            </span>
          </div>
          <AlertsTable alerts={alerts ?? []} />
        </Card>
      </div>
    </div>
  );
}
