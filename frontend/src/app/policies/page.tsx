"use client";

import { useCallback, useEffect, useState } from "react";
import { AppShell } from "@/components/layout/app-shell";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { LoadingState } from "@/components/ui/loading-state";
import { EmptyState } from "@/components/ui/empty-state";
import { ErrorState } from "@/components/ui/error-state";
import {
  listPolicies,
  createPolicy,
  updatePolicy,
  deletePolicy,
  type PolicyRead,
} from "@/lib/policies-api";

export default function PoliciesPage() {
  const [policies, setPolicies] = useState<PolicyRead[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newDesc, setNewDesc] = useState("");
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listPolicies();
      setPolicies(res.policies);
      setTotal(res.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load policies");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  const handleCreate = useCallback(async () => {
    if (!newName.trim()) return;
    setCreating(true);
    try {
      await createPolicy({ name: newName.trim(), description: newDesc.trim() || null });
      setShowCreate(false);
      setNewName("");
      setNewDesc("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create policy");
    } finally {
      setCreating(false);
    }
  }, [newName, newDesc, load]);

  const handleToggleStatus = useCallback(async (p: PolicyRead) => {
    const newStatus = p.status === "active" ? "draft" : "active";
    try {
      await updatePolicy(p.id, { status: newStatus });
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update policy");
    }
  }, [load]);

  const handleDelete = useCallback(async (p: PolicyRead) => {
    if (!confirm(`Delete policy "${p.name}"?`)) return;
    try {
      await deletePolicy(p.id);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete policy");
    }
  }, [load]);

  const statusVariant = (s: string): "success" | "default" | "destructive" => {
    if (s === "active") return "success";
    if (s === "draft") return "default";
    return "destructive";
  };

  return (
    <AppShell>
      <div className="space-y-6 max-w-6xl">
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h2 className="text-2xl font-bold tracking-tight">Policies</h2>
            <p className="text-muted-foreground mt-1">
              {total} policies · Security and business rule management
            </p>
          </div>
          <Button variant="primary" size="sm" onClick={() => setShowCreate(!showCreate)}>
            {showCreate ? "Cancel" : "Create Policy"}
          </Button>
        </div>

        {loading && <LoadingState message="Loading policies…" />}
        {!loading && error && <ErrorState message={error} onRetry={load} />}

        {!loading && !error && (
          <>
            {/* Create form */}
            {showCreate && (
              <Card>
                <CardHeader>
                  <CardTitle>New Policy</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="space-y-3">
                    <input
                      type="text"
                      placeholder="Policy name"
                      value={newName}
                      onChange={(e) => setNewName(e.target.value)}
                      className="w-full px-3 py-2 text-sm border border-border rounded-lg bg-background"
                    />
                    <input
                      type="text"
                      placeholder="Description (optional)"
                      value={newDesc}
                      onChange={(e) => setNewDesc(e.target.value)}
                      className="w-full px-3 py-2 text-sm border border-border rounded-lg bg-background"
                    />
                    <div className="flex gap-2">
                      <Button
                        variant="primary"
                        size="sm"
                        onClick={handleCreate}
                        disabled={creating || !newName.trim()}
                      >
                        {creating ? "Creating…" : "Create"}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setShowCreate(false)}
                      >
                        Cancel
                      </Button>
                    </div>
                  </div>
                </CardContent>
              </Card>
            )}

            {/* Policies list */}
            {policies.length === 0 ? (
              <EmptyState
                icon="📋"
                title="No policies"
                description="Create a policy to define security rules and constraints for agent transactions."
              />
            ) : (
              <div className="grid gap-3">
                {policies.map((p) => (
                  <Card key={p.id}>
                    <CardContent className="pt-4">
                      <div className="flex items-center gap-3 flex-wrap">
                        <Badge variant={statusVariant(p.status)}>{p.status}</Badge>
                        <span className="font-medium">{p.name}</span>
                        <span className="text-xs text-muted-foreground">v{p.version}</span>
                        {p.description && (
                          <span className="text-xs text-muted-foreground truncate max-w-[200px]">
                            {p.description}
                          </span>
                        )}
                        <div className="ml-auto flex gap-2">
                          <Button
                            variant={p.status === "active" ? "destructive" : "primary"}
                            size="sm"
                            onClick={() => handleToggleStatus(p)}
                          >
                            {p.status === "active" ? "Disable" : "Enable"}
                          </Button>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleDelete(p)}
                          >
                            Delete
                          </Button>
                        </div>
                      </div>
                      <div className="flex gap-4 mt-2 text-xs text-muted-foreground">
                        <span>Created: {new Date(p.created_at).toLocaleDateString()}</span>
                        <span>Updated: {new Date(p.updated_at).toLocaleDateString()}</span>
                      </div>
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
