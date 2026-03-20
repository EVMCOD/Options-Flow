"use client";

import { useRouter } from "next/navigation";
import { formatDistanceToNow } from "date-fns";
import type { AlertSummary } from "@/lib/types";
import { AlertLevelBadge } from "@/components/ui/Badge";
import { Table, THead, Th, TBody, Tr, Td } from "@/components/ui/Table";
import { Card, CardHeader } from "@/components/ui/Card";

interface LatestAlertsProps {
  alerts: AlertSummary[];
}

export function LatestAlerts({ alerts }: LatestAlertsProps) {
  const router = useRouter();

  return (
    <Card>
      <CardHeader
        title="Recent Active Alerts"
        subtitle={alerts.length > 0 ? `${alerts.length} most recent active` : "No active alerts"}
      />
      <Table>
        <THead>
          <Th>Level</Th>
          <Th>Symbol</Th>
          <Th>Expiry</Th>
          <Th>Strike</Th>
          <Th>Type</Th>
          <Th align="right">Score</Th>
          <Th>Age</Th>
        </THead>
        <TBody>
          {alerts.length === 0 && (
            <Tr>
              <Td className="text-text-subtle py-6 text-center" colSpan={7}>
                No active alerts. Run an ingestion job to generate data.
              </Td>
            </Tr>
          )}
          {alerts.map((alert) => (
            <Tr
              key={alert.id}
              onClick={() => router.push(`/alerts/${alert.id}`)}
            >
              <Td>
                <AlertLevelBadge level={alert.alert_level} />
              </Td>
              <Td mono>
                <span>{alert.underlying_symbol}</span>
                {alert.catalyst_context && (
                  <span className="block text-[10px] font-mono text-accent/70 leading-tight">
                    {alert.catalyst_context}
                  </span>
                )}
              </Td>
              <Td mono>{alert.expiry}</Td>
              <Td mono>${parseFloat(alert.strike).toFixed(0)}</Td>
              <Td mono>{alert.option_type === "C" ? "Call" : "Put"}</Td>
              <Td align="right" mono>
                <span
                  className={
                    alert.anomaly_score >= 7
                      ? "text-critical"
                      : alert.anomaly_score >= 5
                      ? "text-high"
                      : alert.anomaly_score >= 3
                      ? "text-medium"
                      : "text-low"
                  }
                >
                  {alert.anomaly_score.toFixed(2)}
                </span>
              </Td>
              <Td className="text-text-muted text-xs">
                {formatDistanceToNow(new Date(alert.created_at), {
                  addSuffix: true,
                })}
              </Td>
            </Tr>
          ))}
        </TBody>
      </Table>
    </Card>
  );
}
