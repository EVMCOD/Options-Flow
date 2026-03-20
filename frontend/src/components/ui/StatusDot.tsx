type DotStatus = "online" | "offline" | "degraded";

const DOT_STYLES: Record<DotStatus, string> = {
  online: "bg-low shadow-[0_0_6px_#22c55e]",
  offline: "bg-critical shadow-[0_0_6px_#ef4444]",
  degraded: "bg-medium shadow-[0_0_6px_#eab308]",
};

const LABEL_STYLES: Record<DotStatus, string> = {
  online: "text-low",
  offline: "text-critical",
  degraded: "text-medium",
};

interface StatusDotProps {
  status: DotStatus;
  label?: string;
}

export function StatusDot({ status, label }: StatusDotProps) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`inline-block w-2 h-2 rounded-full ${DOT_STYLES[status]}`} />
      {label && (
        <span className={`text-xs font-mono ${LABEL_STYLES[status]}`}>{label}</span>
      )}
    </span>
  );
}
