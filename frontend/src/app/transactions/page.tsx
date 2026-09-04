"use client";

import { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/layout/app-shell";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { LoadingState } from "@/components/ui/loading-state";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import { listTransactions, getTransaction } from "@/lib/transactions-api";
import type {
  TransactionListItem,
  TransactionDetailResponse,
} from "@/types/api";

export default function TransactionsPage() {
  const [transactions, setTransactions] = useState<TransactionListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [selected, setSelected] = useState<TransactionDetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listTransactions();
      setTransactions(res.transactions);
      setTotal(res.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load transactions");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleViewDetail = useCallback(async (txnId: string) => {
    try {
      const detail = await getTransaction(txnId);
      setSelected(detail);
    } catch (err) {
      // ignore for now
    }
  }, []);

  const filtered = transactions.filter((t) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      t.id.toLowerCase().includes(q) ||
      t.transaction_type.toLowerCase().includes(q) ||
      t.status.toLowerCase().includes(q) ||
      (t.decision ?? "").toLowerCase().includes(q)
    );
  });

  const decisionVariant = (d: string | null): "success" | "destructive" | "warning" | "default" => {
    if (d === "allow") return "success";
    if (d === "block") return "destructive";
    if (d === "review") return "warning";
    return "default";
  };

  const riskVariant = (r: string | null): "destructive" | "warning" | "success" | "default" => {
    if (r === "critical" || r === "high") return "destructive";
    if (r === "medium") return "warning";
    if (r === "low") return "success";
    return "default";
  };

  return (
    <AppShell>
      <div className="space-y-6 max-w-6xl">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h2 className="text-2xl font-bold tracking-tight">Transactions</h2>
            <p className="text-muted-foreground mt-1">
              {total} transactions · Risk-analyzed payment decisions
            </p>
          </div>
        </div>

        {loading && <LoadingState message="Loading transactions…" />}
        {!loading && error && <ErrorState message={error} onRetry={load} />}

        {!loading && !error && (
          <>
            {/* Search */}
            <div className="flex gap-2">
              <input
                type="text"
                placeholder="Search by ID, type, status, or decision…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="flex-1 px-3 py-2 text-sm border border-border rounded-lg bg-background"
              />
            </div>

            {filtered.length === 0 ? (
              <EmptyState
                icon="⚡"
                title="No transactions"
                description="Transactions will appear here after running decisions through the Transaction Decision endpoint."
              />
            ) : (
              <div className="grid gap-3">
                {filtered.map((txn) => (
                  <Card
                    key={txn.id}
                    className="cursor-pointer hover:border-primary/50 transition-colors"
                    onClick={() => handleViewDetail(txn.id)}
                  >
                    <CardContent className="pt-4">
                      <div className="flex items-center gap-3 flex-wrap text-sm">
                        <span className="font-mono text-xs text-muted-foreground truncate max-w-[100px]">
                          {txn.id.slice(0, 8)}
                        </span>
                        <Badge variant="outline">{txn.transaction_type}</Badge>
                        <span className="font-medium">
                          {txn.amount.toLocaleString()} {txn.currency}
                        </span>
                        <Badge variant={decisionVariant(txn.decision)}>
                          {txn.decision ?? "pending"}
                        </Badge>
                        {txn.risk_level && (
                          <Badge variant={riskVariant(txn.risk_level)}>
                            {txn.risk_level}
                          </Badge>
                        )}
                        <span className="text-xs text-muted-foreground ml-auto">
                          {new Date(txn.created_at).toLocaleDateString()}
                        </span>
                      </div>
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}

            {/* Detail drawer */}
            {selected && (
              <Card>
                <CardHeader>
                  <div className="flex items-center justify-between">
                    <CardTitle>Transaction Detail</CardTitle>
                    <Button variant="ghost" size="sm" onClick={() => setSelected(null)}>
                      Close
                    </Button>
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-2 sm:grid-cols-3 gap-4 text-sm">
                    <Field label="ID" value={selected.id} mono />
                    <Field label="Type" value={selected.transaction_type} />
                    <Field label="Amount" value={`${selected.amount.toLocaleString()} ${selected.currency}`} />
                    <Field label="Status" value={selected.status} />
                    <Field label="Decision" value={selected.decision ?? "—"} />
                    <Field label="Risk Level" value={selected.risk_level ?? "—"} />
                    <Field label="Decision Reason" value={selected.decision_reason ?? "—"} />
                    <Field label="Agent" value={selected.agent_id.slice(0, 8)} mono />
                    <Field label="Intent" value={selected.intent_id.slice(0, 8)} mono />
                    <Field label="Created" value={new Date(selected.created_at).toLocaleString()} />
                  </div>
                  {selected.events.length > 0 && (
                    <div className="mt-4">
                      <h4 className="font-medium text-sm mb-2">Events ({selected.events.length})</h4>
                      <div className="space-y-1">
                        {selected.events.map((ev, i) => (
                          <div key={i} className="flex items-center gap-3 text-xs">
                            <Badge variant="outline" className="text-xs">#{ev.sequence_number as number}</Badge>
                            <span>{ev.event_type as string}</span>
                            <span className="text-muted-foreground">{ev.source as string ?? "—"}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </CardContent>
              </Card>
            )}
          </>
        )}
      </div>
    </AppShell>
  );
}

function Field({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div>
      <p className="text-muted-foreground text-xs">{label}</p>
      <p className={`mt-0.5 ${mono ? "font-mono text-xs" : ""}`}>{value}</p>
    </div>
  );
}
