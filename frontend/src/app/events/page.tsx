"use client";

import { useCallback, useState } from "react";
import {
  createEvent,
  deleteEvent,
  getEvents,
  getUpcomingEvents,
} from "@/lib/api";
import { usePolling } from "@/hooks/usePolling";
import { TopBar } from "@/components/layout/TopBar";
import { Card, CardHeader } from "@/components/ui/Card";
import { Table, THead, Th, TBody, Tr, Td } from "@/components/ui/Table";
import type { SymbolEventCreate, SymbolEventOut, UpcomingEventSummary } from "@/lib/types";

// ── helpers ──────────────────────────────────────────────────────────────────

const EVENT_TYPE_LABELS: Record<string, string> = {
  earnings: "Earnings",
  fda_decision: "FDA Decision",
  pdufa: "PDUFA",
  regulatory: "Regulatory",
  investor_day: "Investor Day",
  product_event: "Product Event",
  macro_relevant: "Macro",
  custom: "Custom",
};

const EVENT_TYPES = Object.keys(EVENT_TYPE_LABELS);

function urgencyClass(days: number) {
  if (days <= 1) return "text-critical border-critical/40 bg-critical/5";
  if (days <= 3) return "text-high border-high/40 bg-high/5";
  if (days <= 7) return "text-accent border-accent/40 bg-accent/5";
  return "text-text-muted border-border bg-transparent";
}

function CatalystBadge({ days, label }: { days: number; label: string }) {
  return (
    <span
      className={`text-[10px] font-mono px-1.5 py-0.5 rounded-sm border ${urgencyClass(days)}`}
    >
      {label}
    </span>
  );
}

function daysLabel(days: number) {
  if (days === 0) return "Today";
  if (days === 1) return "Tomorrow";
  return `In ${days} days`;
}

// ── Add Event form ────────────────────────────────────────────────────────────

const BLANK_FORM: SymbolEventCreate = {
  symbol: "",
  event_type: "earnings",
  title: "",
  event_date: "",
  event_time: null,
  source: null,
  notes: null,
};

interface AddEventFormProps {
  onCreated: () => void;
}

function AddEventForm({ onCreated }: AddEventFormProps) {
  const [form, setForm] = useState<SymbolEventCreate>(BLANK_FORM);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = (key: keyof SymbolEventCreate, value: string | null) =>
    setForm((f) => {
      const next = { ...f, [key]: value || null };
      // Auto-generate title when symbol + type are set and title is empty/auto
      if ((key === "symbol" || key === "event_type") && !f.title) {
        const sym = key === "symbol" ? (value ?? "") : f.symbol;
        const typ = key === "event_type" ? (value ?? "earnings") : f.event_type;
        const typeLabel = EVENT_TYPE_LABELS[typ] ?? typ;
        if (sym) next.title = `${sym.toUpperCase()} ${typeLabel}`;
      }
      return next;
    });

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!form.symbol || !form.event_date) return;
    setSaving(true);
    setError(null);
    try {
      await createEvent({
        ...form,
        symbol: form.symbol.toUpperCase(),
        title: form.title || `${form.symbol.toUpperCase()} ${EVENT_TYPE_LABELS[form.event_type] ?? form.event_type}`,
      });
      setForm(BLANK_FORM);
      onCreated();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create event");
    } finally {
      setSaving(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="px-4 py-4 space-y-3">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <div className="space-y-1">
          <label className="text-[10px] uppercase tracking-widest text-text-subtle">Symbol</label>
          <input
            className="w-full bg-bg-base border border-border text-text-primary font-mono text-sm px-2 py-1.5 rounded-sm focus:outline-none focus:border-accent/60 uppercase"
            placeholder="AAPL"
            value={form.symbol}
            onChange={(e) => set("symbol", e.target.value)}
            maxLength={10}
            required
          />
        </div>
        <div className="space-y-1">
          <label className="text-[10px] uppercase tracking-widest text-text-subtle">Type</label>
          <select
            className="w-full bg-bg-base border border-border text-text-primary font-mono text-sm px-2 py-1.5 rounded-sm focus:outline-none focus:border-accent/60"
            value={form.event_type}
            onChange={(e) => set("event_type", e.target.value)}
          >
            {EVENT_TYPES.map((t) => (
              <option key={t} value={t}>{EVENT_TYPE_LABELS[t]}</option>
            ))}
          </select>
        </div>
        <div className="space-y-1">
          <label className="text-[10px] uppercase tracking-widest text-text-subtle">Date</label>
          <input
            type="date"
            className="w-full bg-bg-base border border-border text-text-primary font-mono text-sm px-2 py-1.5 rounded-sm focus:outline-none focus:border-accent/60"
            value={form.event_date}
            onChange={(e) => set("event_date", e.target.value)}
            required
          />
        </div>
        <div className="space-y-1">
          <label className="text-[10px] uppercase tracking-widest text-text-subtle">Timing</label>
          <select
            className="w-full bg-bg-base border border-border text-text-primary font-mono text-sm px-2 py-1.5 rounded-sm focus:outline-none focus:border-accent/60"
            value={form.event_time ?? ""}
            onChange={(e) => set("event_time", e.target.value || null)}
          >
            <option value="">Unknown</option>
            <option value="BMO">BMO (Before Open)</option>
            <option value="AMC">AMC (After Close)</option>
            <option value="intraday">Intraday</option>
          </select>
        </div>
      </div>
      <div className="space-y-1">
        <label className="text-[10px] uppercase tracking-widest text-text-subtle">Title</label>
        <input
          className="w-full bg-bg-base border border-border text-text-primary font-mono text-sm px-2 py-1.5 rounded-sm focus:outline-none focus:border-accent/60"
          placeholder="AAPL Q2 2026 Earnings"
          value={form.title}
          onChange={(e) => set("title", e.target.value)}
          maxLength={255}
        />
      </div>
      <div className="flex items-center gap-3">
        <button
          type="submit"
          disabled={saving || !form.symbol || !form.event_date}
          className="px-4 py-1.5 text-xs font-mono border border-accent/40 text-accent hover:bg-accent/10 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
          {saving ? "Adding..." : "Add Event"}
        </button>
        {error && <span className="text-xs text-critical font-mono">{error}</span>}
      </div>
    </form>
  );
}

// ── Events table ──────────────────────────────────────────────────────────────

interface EventsTableProps {
  events: SymbolEventOut[];
  onDeleted: () => void;
}

function EventsTable({ events, onDeleted }: EventsTableProps) {
  const [deleting, setDeleting] = useState<string | null>(null);

  const handleDelete = async (id: string) => {
    if (!confirm("Delete this event?")) return;
    setDeleting(id);
    try {
      await deleteEvent(id);
      onDeleted();
    } finally {
      setDeleting(null);
    }
  };

  const today = new Date();
  today.setHours(0, 0, 0, 0);

  return (
    <Table>
      <THead>
        <Th>Symbol</Th>
        <Th>Type</Th>
        <Th>Title</Th>
        <Th>Date</Th>
        <Th>Timing</Th>
        <Th>Source</Th>
        <Th>Actions</Th>
      </THead>
      <TBody>
        {events.length === 0 && (
          <Tr>
            <Td className="text-text-subtle py-8 text-center" colSpan={7}>
              No events yet. Add one above or use the bulk seed command.
            </Td>
          </Tr>
        )}
        {events.map((ev) => {
          const evDate = new Date(ev.event_date + "T00:00:00");
          const diffMs = evDate.getTime() - today.getTime();
          const days = Math.round(diffMs / 86400000);
          const isPast = days < 0;

          return (
            <Tr key={ev.id} className={isPast ? "opacity-40" : ""}>
              <Td mono className="font-semibold">{ev.symbol}</Td>
              <Td>
                <span className="text-xs font-mono text-text-muted">
                  {EVENT_TYPE_LABELS[ev.event_type] ?? ev.event_type}
                </span>
              </Td>
              <Td className="text-sm text-text-primary">{ev.title}</Td>
              <Td mono>
                <div className="flex items-center gap-2">
                  <span>{ev.event_date}</span>
                  {!isPast && (
                    <CatalystBadge days={days} label={daysLabel(days)} />
                  )}
                  {isPast && (
                    <span className="text-[10px] font-mono text-text-subtle">passed</span>
                  )}
                </div>
              </Td>
              <Td mono className="text-text-muted">
                {ev.event_time ?? "—"}
              </Td>
              <Td className="text-xs text-text-subtle">{ev.source ?? "—"}</Td>
              <Td>
                <button
                  onClick={() => handleDelete(ev.id)}
                  disabled={deleting === ev.id}
                  className="text-xs font-mono text-text-subtle hover:text-critical transition-colors disabled:opacity-40"
                >
                  {deleting === ev.id ? "..." : "Delete"}
                </button>
              </Td>
            </Tr>
          );
        })}
      </TBody>
    </Table>
  );
}

// ── Upcoming summary cards ────────────────────────────────────────────────────

function UpcomingCards({ events }: { events: UpcomingEventSummary[] }) {
  if (events.length === 0) {
    return (
      <p className="text-sm text-text-subtle px-1">
        No upcoming events in the scanner universe. Add events below.
      </p>
    );
  }

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
      {events.map((ev) => (
        <div
          key={`${ev.symbol}-${ev.event_date}`}
          className={`px-3 py-3 border rounded-sm ${
            ev.days_to_event <= 1
              ? "border-critical/30 bg-critical/5"
              : ev.days_to_event <= 3
              ? "border-high/30 bg-high/5"
              : ev.days_to_event <= 7
              ? "border-accent/20 bg-accent/5"
              : "border-border bg-bg-panel"
          }`}
        >
          <div className="flex items-baseline justify-between gap-1 mb-1">
            <span className="font-mono font-bold text-text-primary text-sm">{ev.symbol}</span>
            <span
              className={`text-[10px] font-mono ${
                ev.days_to_event <= 1
                  ? "text-critical"
                  : ev.days_to_event <= 3
                  ? "text-high"
                  : "text-accent/80"
              }`}
            >
              {daysLabel(ev.days_to_event)}
            </span>
          </div>
          <p className="text-[10px] text-text-muted font-mono uppercase tracking-wide">
            {EVENT_TYPE_LABELS[ev.event_type] ?? ev.event_type}
          </p>
          <p className="text-xs text-text-subtle mt-0.5 truncate" title={ev.title}>
            {ev.title}
          </p>
          <p className="text-[10px] text-text-subtle font-mono mt-1">{ev.event_date}</p>
        </div>
      ))}
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export default function EventsPage() {
  const fetchUpcoming = useCallback(() => getUpcomingEvents(), []);
  const fetchAll = useCallback(() => getEvents({ limit: 200 }), []);

  const {
    data: upcoming,
    loading: upcomingLoading,
    lastUpdated,
    refetch: refetchUpcoming,
  } = usePolling(fetchUpcoming, 60_000);

  const { data: allEvents, refetch: refetchAll } = usePolling(fetchAll, 60_000);

  const handleRefresh = () => {
    refetchUpcoming();
    refetchAll();
  };

  const near = (upcoming ?? []).filter((e) => e.is_near);

  return (
    <div className="flex flex-col h-full">
      <TopBar
        title="Events"
        lastUpdated={lastUpdated}
        onRefresh={handleRefresh}
        loading={upcomingLoading}
      />

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {/* Upcoming catalysts */}
        <Card>
          <CardHeader
            title="Upcoming Catalysts"
            subtitle={
              near.length > 0
                ? `${near.length} event${near.length !== 1 ? "s" : ""} within 7 days`
                : "Next events for monitored symbols"
            }
          />
          <div className="px-4 pb-4">
            <UpcomingCards events={upcoming ?? []} />
          </div>
        </Card>

        {/* Add event form */}
        <Card>
          <CardHeader title="Add Event" subtitle="Earnings, FDA dates, investor days, and more" />
          <AddEventForm onCreated={handleRefresh} />
        </Card>

        {/* All events */}
        <Card>
          <CardHeader
            title="All Events"
            subtitle={`${allEvents?.length ?? 0} events on record`}
          />
          <EventsTable events={allEvents ?? []} onDeleted={handleRefresh} />
        </Card>
      </div>
    </div>
  );
}
