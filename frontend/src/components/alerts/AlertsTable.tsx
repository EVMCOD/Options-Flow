"use client";

import { useRouter } from "next/navigation";
import { formatDistanceToNow } from "date-fns";
import type { AlertSummary } from "@/lib/types";
import { AlertLevelBadge, StatusBadge } from "@/components/ui/Badge";
import { Table, THead, Th, TBody, Tr, Td } from "@/components/ui/Table";

interface AlertsTableProps {
  alerts: AlertSummary[];
}

export function AlertsTable({ alerts }: AlertsTableProps) {
  const router = useRouter();

  return (
    <Table>
      <THead>
        <Th>Level</Th>
        <Th>Symbol</Th>
        <Th>Catalyst</Th>
        <Th>Expiry</Th>
        <Th>Strike</Th>
        <Th>Type</Th>
        <Th align="right">Score</Th>
        <Th>Time</Th>
        <Th>Status</Th>
      </THead>
      <TBody>
        {alerts.length === 0 && (
          <Tr>
            <Td className="text-text-subtle py-8 text-center" colSpan={10}>
              No alerts match the current filters.
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
            <Td mono className="font-semibold">
              {alert.underlying_symbol}
            </Td>
            <Td>
              {alert.catalyst_context ? (
                <span
                  className={`text-[10px] font-mono px-1.5 py-0.5 rounded-sm border ${
                    alert.days_to_event !== null && alert.days_to_event <= 1
                      ? "border-critical/40 text-critical bg-critical/5"
                      : alert.days_to_event !== null && alert.days_to_event <= 3
                      ? "border-high/40 text-high bg-high/5"
                      : "border-accent/30 text-accent/80 bg-accent/5"
                  }`}
                >
                  {alert.catalyst_context}
                </span>
              ) : (
                <span className="text-text-subtle text-xs">—</span>
              )}
            </Td>
            <Td mono>{alert.expiry}</Td>
            <Td mono>${parseFloat(alert.strike).toFixed(0)}</Td>
            <Td>
              <span
                className={`text-xs font-mono font-semibold ${
                  alert.option_type === "C" ? "text-accent" : "text-high"
                }`}
              >
                {alert.option_type === "C" ? "CALL" : "PUT"}
              </span>
            </Td>
            <Td align="right" mono>
              <span
                className={
                  alert.anomaly_score >= 7
                    ? "text-critical font-semibold"
                    : alert.anomaly_score >= 5
                    ? "text-high font-semibold"
                    : alert.anomaly_score >= 3
                    ? "text-medium"
                    : "text-low"
                }
              >
                {alert.anomaly_score.toFixed(2)}
              </span>
            </Td>
            <Td className="text-text-subtle text-xs">
              {formatDistanceToNow(new Date(alert.created_at), {
                addSuffix: true,
              })}
            </Td>
            <Td>
              <StatusBadge status={alert.status} />
            </Td>
          </Tr>
        ))}
      </TBody>
    </Table>
  );
}
