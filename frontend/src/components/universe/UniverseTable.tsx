"use client";

import { useState } from "react";
import { Trash2, Plus } from "lucide-react";
import type { ScannerUniverseEntry } from "@/lib/types";
import { Table, THead, Th, TBody, Tr, Td } from "@/components/ui/Table";
import { createUniverseEntry, deleteUniverseEntry, patchUniverseEntry } from "@/lib/api";

interface UniverseTableProps {
  entries: ScannerUniverseEntry[];
  onRefresh: () => void;
}

export function UniverseTable({ entries, onRefresh }: UniverseTableProps) {
  const [newSymbol, setNewSymbol] = useState("");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleToggle = async (entry: ScannerUniverseEntry) => {
    try {
      await patchUniverseEntry(entry.id, { enabled: !entry.enabled });
      onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Toggle failed");
    }
  };

  const handleDelete = async (entry: ScannerUniverseEntry) => {
    if (!confirm(`Remove ${entry.symbol} from universe?`)) return;
    try {
      await deleteUniverseEntry(entry.id);
      onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Delete failed");
    }
  };

  const handleAdd = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newSymbol.trim()) return;
    setAdding(true);
    setError(null);
    try {
      await createUniverseEntry({ symbol: newSymbol.trim().toUpperCase() });
      setNewSymbol("");
      onRefresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Add failed");
    } finally {
      setAdding(false);
    }
  };

  return (
    <div className="space-y-4">
      {/* Add form */}
      <form
        onSubmit={handleAdd}
        className="flex items-end gap-3 border border-border bg-bg-card px-4 py-3"
      >
        <div className="flex flex-col gap-1">
          <label className="text-[10px] text-text-subtle uppercase tracking-widest">
            Add Symbol
          </label>
          <input
            type="text"
            value={newSymbol}
            onChange={(e) => setNewSymbol(e.target.value.toUpperCase())}
            placeholder="e.g. AMZN"
            maxLength={10}
            className="bg-bg-base border border-border text-text-primary font-mono text-sm px-3 py-1.5 w-40 focus:outline-none focus:border-accent placeholder:text-text-subtle"
          />
        </div>
        <button
          type="submit"
          disabled={adding || !newSymbol.trim()}
          className="flex items-center gap-1.5 px-4 py-1.5 text-sm bg-accent/10 border border-accent/40 text-accent hover:bg-accent/20 transition-colors disabled:opacity-40"
        >
          <Plus className="w-3.5 h-3.5" />
          {adding ? "Adding..." : "Add"}
        </button>
        {error && <p className="text-xs text-critical">{error}</p>}
      </form>

      {/* Table */}
      <Table>
        <THead>
          <Th>Symbol</Th>
          <Th>Status</Th>
          <Th align="right">Priority</Th>
          <Th>Added</Th>
          <Th align="center">Actions</Th>
        </THead>
        <TBody>
          {entries.length === 0 && (
            <Tr>
              <Td className="text-text-subtle py-6" colSpan={5}>
                No symbols in universe.
              </Td>
            </Tr>
          )}
          {entries.map((entry) => (
            <Tr key={entry.id}>
              <Td mono className="font-semibold text-text-primary">
                {entry.symbol}
              </Td>
              <Td>
                <button
                  onClick={() => handleToggle(entry)}
                  className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 text-xs font-mono border transition-colors ${
                    entry.enabled
                      ? "bg-low/10 text-low border-low/30 hover:bg-low/20"
                      : "bg-bg-card text-text-subtle border-border hover:text-text-muted"
                  }`}
                >
                  <span
                    className={`inline-block w-1.5 h-1.5 rounded-full ${
                      entry.enabled ? "bg-low" : "bg-text-subtle"
                    }`}
                  />
                  {entry.enabled ? "Enabled" : "Disabled"}
                </button>
              </Td>
              <Td align="right" mono className="text-text-muted">
                {entry.priority}
              </Td>
              <Td className="text-text-subtle text-xs font-mono">
                {new Date(entry.created_at).toLocaleDateString()}
              </Td>
              <Td align="center">
                <button
                  onClick={() => handleDelete(entry)}
                  className="text-text-subtle hover:text-critical transition-colors p-1"
                  title={`Remove ${entry.symbol}`}
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </Td>
            </Tr>
          ))}
        </TBody>
      </Table>
    </div>
  );
}
