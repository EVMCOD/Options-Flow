import type { ReactNode } from "react";

interface TableProps {
  children: ReactNode;
  className?: string;
}

export function Table({ children, className = "" }: TableProps) {
  return (
    <div className={`w-full overflow-x-auto ${className}`}>
      <table className="w-full text-sm border-collapse">{children}</table>
    </div>
  );
}

interface THeadProps {
  children: ReactNode;
}

export function THead({ children }: THeadProps) {
  return (
    <thead>
      <tr className="border-b border-border">{children}</tr>
    </thead>
  );
}

interface ThProps {
  children: ReactNode;
  className?: string;
  align?: "left" | "right" | "center";
}

export function Th({ children, className = "", align = "left" }: ThProps) {
  const alignClass =
    align === "right"
      ? "text-right"
      : align === "center"
      ? "text-center"
      : "text-left";
  return (
    <th
      className={`px-3 py-2 text-xs font-semibold text-text-subtle tracking-widest uppercase whitespace-nowrap ${alignClass} ${className}`}
    >
      {children}
    </th>
  );
}

interface TBodyProps {
  children: ReactNode;
}

export function TBody({ children }: TBodyProps) {
  return <tbody className="divide-y divide-border/50">{children}</tbody>;
}

interface TrProps {
  children: ReactNode;
  onClick?: () => void;
  className?: string;
}

export function Tr({ children, onClick, className = "" }: TrProps) {
  const interactiveClass = onClick
    ? "cursor-pointer hover:bg-bg-hover transition-colors duration-100"
    : "";
  return (
    <tr className={`${interactiveClass} ${className}`} onClick={onClick}>
      {children}
    </tr>
  );
}

interface TdProps {
  children: ReactNode;
  className?: string;
  align?: "left" | "right" | "center";
  mono?: boolean;
  colSpan?: number;
}

export function Td({ children, className = "", align = "left", mono = false, colSpan }: TdProps) {
  const alignClass =
    align === "right"
      ? "text-right"
      : align === "center"
      ? "text-center"
      : "text-left";
  const monoClass = mono ? "font-mono tabular-nums" : "";
  return (
    <td
      colSpan={colSpan}
      className={`px-3 py-2.5 text-text-primary whitespace-nowrap ${alignClass} ${monoClass} ${className}`}
    >
      {children}
    </td>
  );
}
