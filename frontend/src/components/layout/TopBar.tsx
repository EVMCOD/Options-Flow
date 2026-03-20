"use client";

import { RefreshCw } from "lucide-react";
import { format } from "date-fns";

interface TopBarProps {
  title: string;
  lastUpdated: Date | null;
  onRefresh: () => void;
  loading?: boolean;
}

export function TopBar({ title, lastUpdated, onRefresh, loading }: TopBarProps) {
  return (
    <header className="flex items-center justify-between px-6 py-3 border-b border-border bg-bg-panel shrink-0">
      <h1 className="text-base font-semibold text-text-primary tracking-wide">
        {title}
      </h1>
      <div className="flex items-center gap-4">
        {lastUpdated && (
          <span className="text-xs text-text-subtle font-mono">
            Updated {format(lastUpdated, "HH:mm:ss")}
          </span>
        )}
        <button
          onClick={onRefresh}
          disabled={loading}
          className="flex items-center gap-1.5 px-3 py-1.5 text-xs text-text-muted border border-border hover:text-text-primary hover:border-text-muted transition-colors duration-100 disabled:opacity-40"
          title="Refresh"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? "animate-spin" : ""}`} />
          Refresh
        </button>
      </div>
    </header>
  );
}
