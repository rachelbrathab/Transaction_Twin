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
import { listAuditEvents, type AuditEventItem } from "@/lib/audit-api";

export default function AuditVaultPage() {
  const [events, setEvents] = useState<AuditEventItem[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [entityFilter, setEntityFilter] = useState("");
  const [eventFilter, setEventFilter] = useState("");
  const [expanded, setExpanded] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listAuditEvents({
        entityType: entityFilter || undefined,
        eventType: eventFilter || undefined,
      });
      setEvents(res.events);
      setTotal(res.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load audit events");
    } finally {
      setLoading(false);
    }
  }, [entityFilter, eventFilter]);

  useEffect(() => { load(); }, [load]);

  const eventTypeVariant = (t: string): "success" | "destructive" | "warning" | "default" | "outline" => {
    if (t.includes("created") || t.includes("activated") || t.includes("approved")) return "success";
    if (t.includes("deleted") || t.includes("rejected") || t.includes("revoked")) return "destructive";
    if (t.includes("review") || t.includes("updated")) return "warning";
    if (t.includes("generated") || t.includes("simulated")) return "outline";
    return "default";
  };

  return (
    <AppShell>
      <div className="space-y-6 max-w-6xl">
        <div>
          <h2 className="text-2xl font-bold tracking-tight">Audit Vault</h2>
          <p className="text-muted-foreground mt-1">
            {total} events · Append-only audit trail
          </p>
        </div>

        {loading && <LoadingState message="Loading audit events…" />}
        {!loading && error && <ErrorState message={error} onRetry={load} />}

        {!loading && !error && (
          <>
            {/* Filters */}
            <div className="flex gap-2 flex-wrap">
              <input
                type="text"
                placeholder="Filter by entity type (e.g. decision, calibration_version)"
                value={entityFilter}
                onChange={(e) => setEntityFilter(e.target.value)}
                className="flex-1 min-w-[200px] px-3 py-2 text-sm border border-border rounded-lg bg-background"
              />
              <input
                type="text"
                placeholder="Filter by event type"
                value={eventFilter}
                onChange={(e) => setEventFilter(e.target.value)}
                className="flex-1 min-w-[200px] px-3 py-2 text-sm border border-border rounded-lg bg-background"
              />
              <Button variant="secondary" size="sm" onClick={load}>
                Apply
              </Button>
            </div>

            {events.length === 0 ? (
              <EmptyState
                icon="🔒"
                title="No audit events"
                description="Audit events are recorded automatically when transactions, decisions, and calibration actions occur."
              />
            ) : (
              <div className="grid gap-2">
                {events.map((evt) => (
                  <Card
                    key={evt.id}
                    className="cursor-pointer hover:border-primary/50 transition-colors"
                    onClick={() => setExpanded(expanded === evt.id ? null : evt.id)}
                  >
                    <CardContent className="pt-3 pb-3">
                      <div className="flex items-center gap-3 text-sm">
                        <span className="font-mono text-xs text-muted-foreground truncate max-w-[80px]">
                          {evt.id.slice(0, 8)}
                        </span>
                        <Badge variant={eventTypeVariant(evt.event_type)}>
                          {evt.event_type}
                        </Badge>
                        <Badge variant="outline" className="text-xs">
                          {evt.entity_type}
                        </Badge>
                        {evt.actor_type && (
                          <span className="text-xs text-muted-foreground">
                            by {evt.actor_type}
                          </span>
                        )}
                        <span className="text-xs text-muted-foreground ml-auto">
                          {new Date(evt.created_at).toLocaleString()}
                        </span>
                      </div>

                      {expanded === evt.id && evt.metadata && (
                        <div className="mt-3 p-3 rounded-lg bg-muted/50 text-xs font-mono overflow-x-auto">
                          <pre className="whitespace-pre-wrap">
                            {JSON.stringify(evt.metadata, null, 2)}
                          </pre>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </AppShell>
  );
}
