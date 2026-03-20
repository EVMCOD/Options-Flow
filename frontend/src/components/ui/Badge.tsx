import type { AlertLevel } from "@/lib/types";

const LEVEL_STYLES: Record<AlertLevel, string> = {
  CRITICAL: "bg-critical/10 text-critical border border-critical/30",
  HIGH: "bg-high/10 text-high border border-high/30",
  MEDIUM: "bg-medium/10 text-medium border border-medium/30",
  LOW: "bg-low/10 text-low border border-low/30",
};

interface BadgeProps {
  level: AlertLevel;
  className?: string;
}

export function AlertLevelBadge({ level, className = "" }: BadgeProps) {
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 text-xs font-mono font-semibold tracking-wider rounded-sm ${LEVEL_STYLES[level]} ${className}`}
    >
      {level}
    </span>
  );
}

interface StatusBadgeProps {
  status: string;
  className?: string;
}

const STATUS_STYLES: Record<string, string> = {
  active: "bg-accent/10 text-accent border border-accent/30",
  acknowledged: "bg-text-muted/10 text-text-muted border border-text-muted/20",
  dismissed: "bg-bg-card text-text-subtle border border-border",
};

export function StatusBadge({ status, className = "" }: StatusBadgeProps) {
  const style = STATUS_STYLES[status] ?? STATUS_STYLES.dismissed;
  return (
    <span
      className={`inline-flex items-center px-2 py-0.5 text-xs font-mono tracking-wider rounded-sm ${style} ${className}`}
    >
      {status}
    </span>
  );
}
