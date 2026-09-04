"use client";

import { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/layout/app-shell";
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { LoadingState } from "@/components/ui/loading-state";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import {
  getRiskSummary,
  getRiskTransactions,
  type RiskSummaryResponse,
  type RiskTransactionItem,
} from "@/lib/risk-api";

export default function RiskIntelligencePage() {
  const [summary, setSummary] = useState<RiskSummaryResponse | null>(null);
  const [transactions, setTransactions] = useState<RiskTransactionItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [s, t] = await Promise.allSettled([
        getRiskSummary(),
        getRiskTransactions(),
      ]);
      if (s.status === "fulfilled") setSummary(s.value);
      if (t.status === "fulfilled") setTransactions(t.value.transactions);
      if (s.status === "rejected") setError(s.reason instanceof Error ? s.reason.message : "Failed to load summary");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load risk data");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const decisionVariant = (d: string): "success" | "destructive" | "warning" | "default" => {
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
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Risk Intelligence</h2>
          <p className="text-muted-foreground mt-1">
            Risk analysis, decision distribution, and high-risk transaction monitoring
          </p>
        </div>

        {loading && <LoadingState message="Loading risk intelligence…" />}
        {!loading && error && <ErrorState message={error} onRetry={load} />}

        {!loading && !error && summary && (
          <>
            {/* Summary cards */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
              <StatCard label="Total Decisions" value={summary.total_decisions} />
              <StatCard label="Allow" value={summary.allow_count} variant="success" />
              <StatCard label="Block" value={summary.block_count} variant="destructive" />
              <StatCard label="Review" value={summary.review_count} variant="warning" />
            </div>

            <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
              <StatCard
                label="Avg Risk Score"
                value={summary.avg_risk_score !== null ? `${(summary.avg_risk_score * 100).toFixed(1)}%` : "—"}
              />
              <StatCard label="High Risk" value={summary.high_risk_count} variant="destructive" />
              <StatCard label="Window" value={`${summary.window_days}d`} />
            </div>

            {/* Risk level distribution */}
            {Object.keys(summary.risk_level_distribution).length > 0 && (
              <Card>
                <CardHeader>
                  <CardTitle>Risk Level Distribution</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="flex gap-4 flex-wrap">
                    {Object.entries(summary.risk_level_distribution).map(([level, count]) => (
                      <div key={level} className="flex items-center gap-2">
                        <Badge variant={riskVariant(level)}>{level}</Badge>
                        <span className="text-sm font-medium">{count}</span>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Recent risk transactions */}
            {transactions.length === 0 ? (
              <EmptyState
                icon="🛡"
                title="No risk transactions"
                description="Risk-evaluated transactions will appear here after running decisions through the Transaction Decision endpoint."
              />
            ) : (
              <Card>
                <CardHeader>
                  <CardTitle>Recent Risk-Evaluated Transactions</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-2">
                    {transactions.map((txn) => (
                      <div
                        key={txn.transaction_id}
                        className="flex items-center gap-3 text-sm py-2 border-b border-border/50 last:border-0"
                      >
                        <span className="font-mono text-xs text-muted-foreground truncate max-w-[80px]">
                          {txn.transaction_id.slice(0, 8)}
                        </span>
                        <Badge variant={decisionVariant(txn.decision)}>
                          {txn.decision}
                        </Badge>
                        {txn.risk_level && (
                          <Badge variant={riskVariant(txn.risk_level)}>
                            {txn.risk_level}
                          </Badge>
                        )}
                        <span className="font-medium">
                          {txn.amount.toLocaleString()} {txn.currency}
                        </span>
                        <span className="text-xs text-muted-foreground truncate max-w-[120px]">
                          {txn.decision_reason ?? ""}
                        </span>
                        <span className="text-xs text-muted-foreground ml-auto">
                          {new Date(txn.created_at).toLocaleDateString()}
                        </span>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}
          </>
        )}

        {!loading && !error && !summary && (
          <EmptyState
            icon="🛡"
            title="No risk data"
            description="Risk intelligence will appear after transaction decisions are processed."
          />
        )}
      </div>
    </AppShell>
  );
}

function StatCard({
  label,
  value,
  variant,
}: {
  label: string;
  value: number | string;
  variant?: "success" | "destructive" | "warning";
}) {
  return (
    <Card>
      <CardContent className="pt-4">
        <p className="text-xs text-muted-foreground">{label}</p>
        <p className={`text-2xl font-bold mt-0.5 ${variant === "destructive" ? "text-destructive" : variant === "success" ? "text-success" : variant === "warning" ? "text-warning" : ""}`}>
          {value}
        </p>
      </CardContent>
    </Card>
  );
}
