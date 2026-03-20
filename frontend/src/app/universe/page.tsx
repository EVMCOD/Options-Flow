"use client";

import { useCallback } from "react";
import { getUniverse } from "@/lib/api";
import { usePolling } from "@/hooks/usePolling";
import { TopBar } from "@/components/layout/TopBar";
import { UniverseTable } from "@/components/universe/UniverseTable";
import { Card, CardHeader } from "@/components/ui/Card";

export default function UniversePage() {
  const fetchUniverse = useCallback(() => getUniverse(), []);
  const {
    data: universe,
    loading,
    lastUpdated,
    refetch,
  } = usePolling(fetchUniverse, 30_000);

  return (
    <div className="flex flex-col h-full">
      <TopBar
        title="Scanner Universe"
        lastUpdated={lastUpdated}
        onRefresh={refetch}
        loading={loading}
      />

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        <Card>
          <CardHeader
            title="Tracked Symbols"
            subtitle="Symbols included in each ingestion run"
          />
          <div className="p-4">
            <UniverseTable entries={universe ?? []} onRefresh={refetch} />
          </div>
        </Card>
      </div>
    </div>
  );
}
