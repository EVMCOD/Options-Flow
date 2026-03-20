"use client";

import type { AlertLevel, AlertStatus, ScannerUniverseEntry } from "@/lib/types";

interface AlertFiltersProps {
  symbol: string;
  alertLevel: AlertLevel | "";
  status: AlertStatus | "";
  universe: ScannerUniverseEntry[];
  onChange: (key: string, value: string) => void;
}

const LEVELS: (AlertLevel | "")[] = ["", "CRITICAL", "HIGH", "MEDIUM", "LOW"];
const STATUSES: (AlertStatus | "")[] = ["", "active", "acknowledged", "dismissed"];

export function AlertFilters({
  symbol,
  alertLevel,
  status,
  universe,
  onChange,
}: AlertFiltersProps) {
  return (
    <div className="flex flex-wrap items-center gap-3">
      <div className="flex flex-col gap-1">
        <label className="text-[10px] text-text-subtle uppercase tracking-widest">
          Symbol
        </label>
        <select
          value={symbol}
          onChange={(e) => onChange("symbol", e.target.value)}
          className="bg-bg-card border border-border text-text-primary text-sm px-3 py-1.5 font-mono focus:outline-none focus:border-accent"
        >
          <option value="">All symbols</option>
          {universe.map((u) => (
            <option key={u.id} value={u.symbol}>
              {u.symbol}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-[10px] text-text-subtle uppercase tracking-widest">
          Level
        </label>
        <select
          value={alertLevel}
          onChange={(e) => onChange("alertLevel", e.target.value)}
          className="bg-bg-card border border-border text-text-primary text-sm px-3 py-1.5 font-mono focus:outline-none focus:border-accent"
        >
          {LEVELS.map((l) => (
            <option key={l} value={l}>
              {l === "" ? "All levels" : l}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-[10px] text-text-subtle uppercase tracking-widest">
          Status
        </label>
        <select
          value={status}
          onChange={(e) => onChange("status", e.target.value)}
          className="bg-bg-card border border-border text-text-primary text-sm px-3 py-1.5 font-mono focus:outline-none focus:border-accent"
        >
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {s === "" ? "All statuses" : s}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
