"use client";

import { Fragment, useCallback, useEffect, useState } from "react";
import { ChevronDown, ChevronUp, Plus, RotateCcw, Save, Trash2, X } from "lucide-react";
import { TopBar } from "@/components/layout/TopBar";
import { Card, CardHeader } from "@/components/ui/Card";
import { Table, TBody, Td, THead, Th, Tr } from "@/components/ui/Table";
import {
  deleteSymbolSignalSettings,
  getEffectiveSignalSettings,
  getTenantSignalSettings,
  getUniverse,
  listSymbolSignalSettings,
  putSymbolSignalSettings,
  putTenantSignalSettings,
} from "@/lib/api";
import type {
  AlertLevel,
  EffectiveSignalSettings,
  SignalSettingsInput,
  SymbolSignalSettings,
  TenantSignalSettings,
} from "@/lib/types";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const GLOBAL_DEFAULTS = {
  min_premium_proxy: 500,
  max_dte_days: 60,
  max_moneyness_pct: 0.2,
  min_open_interest: 0,
  min_alert_level: "LOW" as AlertLevel,
  enabled: true,
};

const ALERT_LEVELS: AlertLevel[] = ["LOW", "MEDIUM", "HIGH", "CRITICAL"];

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function nullableFloat(s: string): number | null {
  const n = parseFloat(s);
  return isNaN(n) ? null : n;
}
function nullableInt(s: string): number | null {
  const n = parseInt(s, 10);
  return isNaN(n) ? null : n;
}

function fmtOrInherit(val: number | null | undefined, suffix = ""): string {
  if (val === null || val === undefined) return "—";
  return `${val}${suffix}`;
}

function sourceTag(src: string) {
  const colors: Record<string, string> = {
    symbol: "bg-accent/20 text-accent",
    tenant: "bg-yellow-500/20 text-yellow-400",
    global: "bg-white/10 text-text-muted",
  };
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${colors[src] ?? ""}`}>
      {src}
    </span>
  );
}

// ---------------------------------------------------------------------------
// Settings form (shared by tenant defaults and symbol overrides)
// ---------------------------------------------------------------------------

const WATCHLIST_TIERS = [
  { value: "", label: "— none" },
  { value: "core", label: "Core" },
  { value: "secondary", label: "Secondary" },
];

interface SettingsFormProps {
  initial: Partial<SignalSettingsInput>;
  onSave: (data: SignalSettingsInput) => Promise<void>;
  onCancel?: () => void;
  showIntelligenceFields?: boolean; // show priority_weight + watchlist_tier (symbol overrides only)
}

function SettingsForm({ initial, onSave, onCancel, showIntelligenceFields }: SettingsFormProps) {
  const [form, setForm] = useState<Partial<SignalSettingsInput>>(initial);
  const [saving, setSaving] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const set = (key: keyof SignalSettingsInput, value: unknown) =>
    setForm((f) => ({ ...f, [key]: value }));

  const handleSave = async () => {
    setSaving(true);
    setErr(null);
    try {
      await onSave({
        min_premium_proxy: form.min_premium_proxy ?? null,
        max_dte_days: form.max_dte_days ?? null,
        max_moneyness_pct: form.max_moneyness_pct ?? null,
        min_open_interest: form.min_open_interest ?? null,
        min_alert_level: form.min_alert_level ?? null,
        enabled: form.enabled ?? null,
        priority_weight: form.priority_weight ?? null,
        watchlist_tier: form.watchlist_tier ?? null,
      });
    } catch (e: unknown) {
      setErr(e instanceof Error ? e.message : "Save failed");
    } finally {
      setSaving(false);
    }
  };

  const numField = (
    key: "min_premium_proxy" | "max_dte_days" | "max_moneyness_pct" | "min_open_interest",
    label: string,
    placeholder: string,
    step = 1
  ) => (
    <div className="flex flex-col gap-1">
      <label className="text-[11px] text-text-muted uppercase tracking-wide">{label}</label>
      <input
        type="number"
        step={step}
        value={form[key] ?? ""}
        placeholder={placeholder}
        onChange={(e) => {
          const parsed = step < 1 ? nullableFloat(e.target.value) : nullableInt(e.target.value);
          set(key, parsed);
        }}
        className="w-full bg-bg-base border border-border rounded px-2.5 py-1.5 text-sm text-text-primary
                   placeholder:text-text-subtle focus:outline-none focus:ring-1 focus:ring-accent"
      />
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {numField("min_premium_proxy", "Min Premium ($)", `${GLOBAL_DEFAULTS.min_premium_proxy} (global)`)}
        {numField("max_dte_days", "Max DTE (days)", `${GLOBAL_DEFAULTS.max_dte_days} (global)`)}
        {numField("max_moneyness_pct", "Max Moneyness", `${GLOBAL_DEFAULTS.max_moneyness_pct} (global)`, 0.01)}
        {numField("min_open_interest", "Min Open Interest", `${GLOBAL_DEFAULTS.min_open_interest} (global)`)}

        <div className="flex flex-col gap-1">
          <label className="text-[11px] text-text-muted uppercase tracking-wide">
            Min Alert Level
          </label>
          <select
            value={form.min_alert_level ?? ""}
            onChange={(e) =>
              set("min_alert_level", e.target.value === "" ? null : (e.target.value as AlertLevel))
            }
            className="w-full bg-bg-base border border-border rounded px-2.5 py-1.5 text-sm text-text-primary
                       focus:outline-none focus:ring-1 focus:ring-accent"
          >
            <option value="">— inherit ({GLOBAL_DEFAULTS.min_alert_level})</option>
            {ALERT_LEVELS.map((l) => (
              <option key={l} value={l}>{l}</option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-1">
          <label className="text-[11px] text-text-muted uppercase tracking-wide">Signals enabled</label>
          <select
            value={form.enabled === null || form.enabled === undefined ? "" : String(form.enabled)}
            onChange={(e) =>
              set("enabled", e.target.value === "" ? null : e.target.value === "true")
            }
            className="w-full bg-bg-base border border-border rounded px-2.5 py-1.5 text-sm text-text-primary
                       focus:outline-none focus:ring-1 focus:ring-accent"
          >
            <option value="">— inherit (true)</option>
            <option value="true">Yes</option>
            <option value="false">No (mute)</option>
          </select>
        </div>
      </div>

      {showIntelligenceFields && (
        <div className="mt-4 pt-4 border-t border-border space-y-3">
          <p className="text-[11px] text-text-subtle uppercase tracking-widest">Intelligence / Ranking</p>
          <div className="grid grid-cols-2 gap-3">
            <div className="flex flex-col gap-1">
              <label className="text-[11px] text-text-muted uppercase tracking-wide">Priority Weight</label>
              <input
                type="number"
                step={0.1}
                min={0}
                max={3}
                value={form.priority_weight ?? ""}
                placeholder="1.0 (neutral)"
                onChange={(e) => set("priority_weight", nullableFloat(e.target.value))}
                className="w-full bg-bg-base border border-border rounded px-2.5 py-1.5 text-sm text-text-primary
                           placeholder:text-text-subtle focus:outline-none focus:ring-1 focus:ring-accent"
              />
              <p className="text-[10px] text-text-subtle">0 = deprioritise · 1 = neutral · 2–3 = featured</p>
            </div>

            <div className="flex flex-col gap-1">
              <label className="text-[11px] text-text-muted uppercase tracking-wide">Watchlist Tier</label>
              <select
                value={form.watchlist_tier ?? ""}
                onChange={(e) =>
                  set("watchlist_tier", e.target.value === "" ? null : (e.target.value as "core" | "secondary"))
                }
                className="w-full bg-bg-base border border-border rounded px-2.5 py-1.5 text-sm text-text-primary
                           focus:outline-none focus:ring-1 focus:ring-accent"
              >
                {WATCHLIST_TIERS.map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </div>
          </div>
        </div>
      )}

      {err && <p className="text-xs text-critical">{err}</p>}

      <div className="flex gap-2">
        <button
          onClick={handleSave}
          disabled={saving}
          className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-accent text-white rounded
                     hover:bg-accent/80 disabled:opacity-50 transition-colors"
        >
          <Save className="w-3.5 h-3.5" />
          {saving ? "Saving…" : "Save"}
        </button>
        {onCancel && (
          <button
            onClick={onCancel}
            className="flex items-center gap-1.5 px-3 py-1.5 text-sm border border-border
                       text-text-muted rounded hover:text-text-primary hover:bg-bg-hover transition-colors"
          >
            <X className="w-3.5 h-3.5" />
            Cancel
          </button>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Effective config popover / panel
// ---------------------------------------------------------------------------

function EffectivePanel({ symbol, onClose }: { symbol: string; onClose: () => void }) {
  const [eff, setEff] = useState<EffectiveSignalSettings | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    getEffectiveSignalSettings(symbol)
      .then(setEff)
      .finally(() => setLoading(false));
  }, [symbol]);

  const rows: Array<{ label: string; key: keyof Omit<EffectiveSignalSettings, "sources"> }> = [
    { label: "Min premium ($)", key: "min_premium_proxy" },
    { label: "Max DTE", key: "max_dte_days" },
    { label: "Max moneyness", key: "max_moneyness_pct" },
    { label: "Min open interest", key: "min_open_interest" },
    { label: "Min alert level", key: "min_alert_level" },
    { label: "Enabled", key: "enabled" },
  ];

  return (
    <div className="mt-3 p-3 bg-bg-base border border-border rounded text-sm">
      <div className="flex items-center justify-between mb-2">
        <span className="text-text-muted text-xs uppercase tracking-wide">
          Effective config — {symbol}
        </span>
        <button onClick={onClose} className="text-text-subtle hover:text-text-primary">
          <X className="w-3.5 h-3.5" />
        </button>
      </div>
      {loading && <p className="text-text-subtle text-xs">Loading…</p>}
      {!loading && eff && (
        <div className="space-y-1">
          {rows.map(({ label, key }) => (
            <div key={key} className="flex items-center justify-between">
              <span className="text-text-muted text-xs">{label}</span>
              <div className="flex items-center gap-2">
                <span className="font-mono text-text-primary text-xs">
                  {String(eff[key])}
                </span>
                {sourceTag(eff.sources[key] ?? "global")}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function SignalSettingsPage() {
  // Tenant defaults
  const [tenantSettings, setTenantSettings] = useState<TenantSignalSettings | null>(null);
  const [loadingTenant, setLoadingTenant] = useState(true);
  const [tenantErr, setTenantErr] = useState<string | null>(null);

  // Symbol overrides
  const [symbolSettings, setSymbolSettings] = useState<SymbolSignalSettings[]>([]);
  const [universe, setUniverse] = useState<string[]>([]);
  const [loadingSymbols, setLoadingSymbols] = useState(true);

  // Edit state
  const [editingSymbol, setEditingSymbol] = useState<string | null>(null);
  const [addingSymbol, setAddingSymbol] = useState(false);
  const [newSymbol, setNewSymbol] = useState("");
  const [effectiveSymbol, setEffectiveSymbol] = useState<string | null>(null);

  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  const loadAll = useCallback(async () => {
    setLastUpdated(null);
    try {
      const [ts, syms, univ] = await Promise.all([
        getTenantSignalSettings().catch(() => null),
        listSymbolSignalSettings().catch(() => []),
        getUniverse().catch(() => []),
      ]);
      setTenantSettings(ts);
      setSymbolSettings(syms);
      setUniverse(univ.map((u) => u.symbol));
    } catch (e: unknown) {
      setTenantErr(e instanceof Error ? e.message : "Failed to load settings");
    } finally {
      setLoadingTenant(false);
      setLoadingSymbols(false);
      setLastUpdated(new Date());
    }
  }, []);

  useEffect(() => { loadAll(); }, [loadAll]);

  // Symbols that don't yet have an override
  const availableSymbols = universe.filter(
    (s) => !symbolSettings.some((ss) => ss.symbol === s)
  );

  // Handlers
  const handleSaveTenant = async (data: SignalSettingsInput) => {
    const saved = await putTenantSignalSettings(data);
    setTenantSettings(saved);
  };

  const handleSaveSymbol = async (symbol: string, data: SignalSettingsInput) => {
    const saved = await putSymbolSignalSettings(symbol, data);
    setSymbolSettings((prev) => {
      const idx = prev.findIndex((s) => s.symbol === symbol);
      return idx >= 0 ? [...prev.slice(0, idx), saved, ...prev.slice(idx + 1)] : [...prev, saved];
    });
    setEditingSymbol(null);
    setAddingSymbol(false);
    setNewSymbol("");
  };

  const handleDeleteSymbol = async (symbol: string) => {
    if (!confirm(`Remove override for ${symbol}?`)) return;
    await deleteSymbolSignalSettings(symbol);
    setSymbolSettings((prev) => prev.filter((s) => s.symbol !== symbol));
    if (effectiveSymbol === symbol) setEffectiveSymbol(null);
    if (editingSymbol === symbol) setEditingSymbol(null);
  };

  const toggleEffective = (symbol: string) =>
    setEffectiveSymbol((prev) => (prev === symbol ? null : symbol));

  return (
    <div className="flex flex-col h-full">
      <TopBar
        title="Signal Settings"
        onRefresh={loadAll}
        lastUpdated={lastUpdated}
      />

      <div className="flex-1 overflow-y-auto p-6 space-y-6">
        {tenantErr && (
          <div className="text-critical text-sm p-3 bg-critical/10 border border-critical/30 rounded">
            {tenantErr}
          </div>
        )}

        {/* ---- Tenant defaults ---- */}
        <Card>
          <CardHeader
            title="Tenant Defaults"
            subtitle="Global signal thresholds for all symbols. Null fields inherit global config.py values."
          />
          <div className="p-4">
            {loadingTenant ? (
              <p className="text-text-subtle text-sm">Loading…</p>
            ) : (
              <SettingsForm
                initial={{
                  min_premium_proxy: tenantSettings?.min_premium_proxy ?? null,
                  max_dte_days: tenantSettings?.max_dte_days ?? null,
                  max_moneyness_pct: tenantSettings?.max_moneyness_pct ?? null,
                  min_open_interest: tenantSettings?.min_open_interest ?? null,
                  min_alert_level: tenantSettings?.min_alert_level ?? null,
                  enabled: tenantSettings?.enabled ?? null,
                }}
                onSave={handleSaveTenant}
              />
            )}
          </div>
        </Card>

        {/* ---- Symbol overrides ---- */}
        <Card>
          <CardHeader
            title="Symbol Overrides"
            subtitle="Per-symbol settings that take precedence over tenant defaults."
            action={
              !addingSymbol && availableSymbols.length > 0 ? (
                <button
                  onClick={() => setAddingSymbol(true)}
                  className="flex items-center gap-1.5 px-3 py-1.5 text-sm bg-accent text-white
                             rounded hover:bg-accent/80 transition-colors"
                >
                  <Plus className="w-3.5 h-3.5" />
                  Add Override
                </button>
              ) : undefined
            }
          />

          <div className="p-4 space-y-4">
            {/* Add new symbol form */}
            {addingSymbol && (
              <div className="p-3 border border-accent/30 rounded bg-accent/5 space-y-3">
                <p className="text-sm text-text-primary font-medium">New symbol override</p>
                <div className="flex items-center gap-2">
                  {availableSymbols.length > 0 ? (
                    <select
                      value={newSymbol}
                      onChange={(e) => setNewSymbol(e.target.value)}
                      className="bg-bg-base border border-border rounded px-2.5 py-1.5 text-sm
                                 text-text-primary focus:outline-none focus:ring-1 focus:ring-accent"
                    >
                      <option value="">Select symbol…</option>
                      {availableSymbols.map((s) => (
                        <option key={s} value={s}>{s}</option>
                      ))}
                    </select>
                  ) : (
                    <input
                      placeholder="SYMBOL"
                      value={newSymbol}
                      onChange={(e) => setNewSymbol(e.target.value.toUpperCase())}
                      className="w-32 bg-bg-base border border-border rounded px-2.5 py-1.5 text-sm
                                 text-text-primary focus:outline-none focus:ring-1 focus:ring-accent"
                    />
                  )}
                  <button
                    onClick={() => { setAddingSymbol(false); setNewSymbol(""); }}
                    className="text-text-muted hover:text-text-primary"
                  >
                    <X className="w-4 h-4" />
                  </button>
                </div>
                {newSymbol && (
                  <SettingsForm
                    initial={{}}
                    onSave={(data) => handleSaveSymbol(newSymbol, data)}
                    onCancel={() => { setAddingSymbol(false); setNewSymbol(""); }}
                    showIntelligenceFields
                  />
                )}
              </div>
            )}

            {/* Existing overrides table */}
            {loadingSymbols ? (
              <p className="text-text-subtle text-sm">Loading…</p>
            ) : symbolSettings.length === 0 && !addingSymbol ? (
              <p className="text-text-subtle text-sm">
                No symbol overrides configured. All symbols use tenant defaults (or global defaults).
              </p>
            ) : (
              <Table>
                <THead>
                  <tr>
                    <Th>Symbol</Th>
                    <Th>Tier</Th>
                    <Th>Priority ×</Th>
                    <Th>Min Premium</Th>
                    <Th>Max DTE</Th>
                    <Th>Min Level</Th>
                    <Th>Enabled</Th>
                    <Th align="right">Actions</Th>
                  </tr>
                </THead>
                <TBody>
                  {symbolSettings.map((sym) => (
                    <Fragment key={sym.id}>
                    <Tr
                      onClick={() =>
                        setEditingSymbol((prev) => (prev === sym.symbol ? null : sym.symbol))
                      }
                      className="cursor-pointer"
                    >
                        <Td mono>
                          <span className="font-semibold text-text-primary">{sym.symbol}</span>
                        </Td>
                        <Td>
                          {sym.watchlist_tier === "core" ? (
                            <span className="text-[10px] px-1.5 py-0.5 rounded font-mono bg-accent/20 text-accent">core</span>
                          ) : sym.watchlist_tier === "secondary" ? (
                            <span className="text-[10px] px-1.5 py-0.5 rounded font-mono bg-white/10 text-text-muted">secondary</span>
                          ) : (
                            <span className="text-text-subtle">—</span>
                          )}
                        </Td>
                        <Td>
                          {sym.priority_weight != null ? (
                            <span className={sym.priority_weight >= 2 ? "text-accent font-semibold" : sym.priority_weight <= 0.5 ? "text-text-subtle" : ""}>
                              {sym.priority_weight.toFixed(1)}×
                            </span>
                          ) : (
                            <span className="text-text-subtle">1.0×</span>
                          )}
                        </Td>
                        <Td>{fmtOrInherit(sym.min_premium_proxy, " $")}</Td>
                        <Td>{fmtOrInherit(sym.max_dte_days, "d")}</Td>
                        <Td>{sym.min_alert_level ?? "—"}</Td>
                        <Td>
                          {sym.enabled === null ? (
                            <span className="text-text-subtle">—</span>
                          ) : sym.enabled ? (
                            <span className="text-low">Yes</span>
                          ) : (
                            <span className="text-critical">Muted</span>
                          )}
                        </Td>
                        <Td align="right">
                          <div className="flex items-center justify-end gap-1">
                            <button
                              onClick={(e) => { e.stopPropagation(); toggleEffective(sym.symbol); }}
                              title="Show effective config"
                              className="p-1 text-text-subtle hover:text-accent transition-colors"
                            >
                              {effectiveSymbol === sym.symbol
                                ? <ChevronUp className="w-3.5 h-3.5" />
                                : <ChevronDown className="w-3.5 h-3.5" />}
                            </button>
                            <button
                              onClick={(e) => { e.stopPropagation(); handleDeleteSymbol(sym.symbol); }}
                              title="Remove override"
                              className="p-1 text-text-subtle hover:text-critical transition-colors"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </Td>
                      </Tr>

                      {/* Inline edit form */}
                      {editingSymbol === sym.symbol && (
                        <Tr key={`${sym.id}-edit`}>
                          <Td colSpan={10}>
                            <div className="py-3 px-2">
                              <p className="text-xs text-text-muted mb-3 uppercase tracking-wide">
                                Editing override — {sym.symbol}
                              </p>
                              <SettingsForm
                                initial={{
                                  min_premium_proxy: sym.min_premium_proxy,
                                  max_dte_days: sym.max_dte_days,
                                  max_moneyness_pct: sym.max_moneyness_pct,
                                  min_open_interest: sym.min_open_interest,
                                  min_alert_level: sym.min_alert_level,
                                  enabled: sym.enabled,
                                  priority_weight: sym.priority_weight,
                                  watchlist_tier: sym.watchlist_tier,
                                }}
                                onSave={(data) => handleSaveSymbol(sym.symbol, data)}
                                onCancel={() => setEditingSymbol(null)}
                                showIntelligenceFields
                              />
                            </div>
                          </Td>
                        </Tr>
                      )}

                      {/* Effective config panel */}
                      {effectiveSymbol === sym.symbol && (
                        <Tr key={`${sym.id}-eff`}>
                          <Td colSpan={10}>
                            <EffectivePanel
                              symbol={sym.symbol}
                              onClose={() => setEffectiveSymbol(null)}
                            />
                          </Td>
                        </Tr>
                      )}
                    </Fragment>
                  ))}
                </TBody>
              </Table>
            )}
          </div>
        </Card>

        {/* ---- Resolution order reference ---- */}
        <Card>
          <CardHeader title="How resolution works" />
          <div className="p-4 text-sm text-text-muted space-y-1.5">
            <p>
              For each symbol, the signal engine applies settings in this priority order:
            </p>
            <ol className="list-decimal list-inside space-y-1 mt-2 text-text-primary">
              <li>
                {sourceTag("symbol")} <span className="ml-1">Symbol override</span> — set above per symbol
              </li>
              <li>
                {sourceTag("tenant")} <span className="ml-1">Tenant defaults</span> — set in the form above
              </li>
              <li>
                {sourceTag("global")} <span className="ml-1">Global defaults</span> — from config.py (MIN_PREMIUM_PROXY=500, MAX_DTE_DAYS=60, etc.)
              </li>
            </ol>
            <p className="mt-2">
              Use <span className="font-mono text-accent">— inherit</span> (null) to fall through to the next layer.
              Click the <ChevronDown className="w-3 h-3 inline" /> icon on any symbol to see its fully resolved effective config.
            </p>
          </div>
        </Card>
      </div>
    </div>
  );
}
