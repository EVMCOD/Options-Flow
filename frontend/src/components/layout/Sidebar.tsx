"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, Bell, BookOpen, Calendar, LayoutDashboard, SlidersHorizontal } from "lucide-react";
import { StatusDot } from "@/components/ui/StatusDot";
import { useEffect, useState } from "react";

const NAV_ITEMS = [
  { href: "/", label: "Overview", icon: LayoutDashboard },
  { href: "/alerts", label: "Alerts", icon: Bell },
  { href: "/universe", label: "Universe", icon: BookOpen },
  { href: "/events", label: "Events", icon: Calendar },
  { href: "/signal-settings", label: "Signal Settings", icon: SlidersHorizontal },
];

export function Sidebar() {
  const pathname = usePathname();
  const [connected, setConnected] = useState<boolean | null>(null);

  useEffect(() => {
    const check = async () => {
      try {
        const res = await fetch(
          `${process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000"}/api/v1/health`,
          { cache: "no-store" }
        );
        setConnected(res.ok);
      } catch {
        setConnected(false);
      }
    };
    check();
    const id = setInterval(check, 30_000);
    return () => clearInterval(id);
  }, []);

  return (
    <aside className="flex flex-col w-56 min-h-screen bg-bg-panel border-r border-border shrink-0">
      {/* Logo / App name */}
      <div className="px-4 py-5 border-b border-border">
        <div className="flex items-center gap-2">
          <Activity className="w-5 h-5 text-accent shrink-0" />
          <div>
            <p className="text-sm font-semibold text-text-primary leading-tight">
              Options Flow
            </p>
            <p className="text-[10px] text-text-subtle font-mono tracking-widest uppercase">
              Radar
            </p>
          </div>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-2 py-4 space-y-0.5">
        {NAV_ITEMS.map(({ href, label, icon: Icon }) => {
          const isActive =
            href === "/" ? pathname === "/" : pathname.startsWith(href);
          return (
            <Link
              key={href}
              href={href}
              className={`flex items-center gap-3 px-3 py-2 text-sm rounded-sm transition-colors duration-100 ${
                isActive
                  ? "bg-accent/10 text-accent border-l-2 border-accent pl-[10px]"
                  : "text-text-muted hover:text-text-primary hover:bg-bg-hover border-l-2 border-transparent pl-[10px]"
              }`}
            >
              <Icon className="w-4 h-4 shrink-0" />
              {label}
            </Link>
          );
        })}
      </nav>

      {/* Connection status */}
      <div className="px-4 py-4 border-t border-border">
        <p className="text-[10px] text-text-subtle uppercase tracking-widest mb-1.5">
          API Status
        </p>
        <StatusDot
          status={
            connected === null
              ? "degraded"
              : connected
              ? "online"
              : "offline"
          }
          label={
            connected === null ? "Checking..." : connected ? "Connected" : "Offline"
          }
        />
      </div>
    </aside>
  );
}
