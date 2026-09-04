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
import { listAgents, createAgent, updateAgent } from "@/lib/agents-api";
import type { AgentRead, AgentCreate, AgentUpdate } from "@/types/api";

const statusVariant: Record<string, "success" | "warning" | "destructive" | "default"> = {
  active: "success",
  inactive: "warning",
  suspended: "destructive",
};

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  } catch {
    return iso;
  }
}

export default function AgentsPage() {
  const [agents, setAgents] = useState<AgentRead[]>([]);
  const [total, setTotal] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [editing, setEditing] = useState<AgentRead | null>(null);
  const [saving, setSaving] = useState(false);
  const [actionMessage, setActionMessage] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listAgents();
      setAgents(res.agents);
      setTotal(res.total);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load agents");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleCreate = useCallback(
    async (data: AgentCreate) => {
      setSaving(true);
      setActionMessage(null);
      try {
        await createAgent(data);
        setActionMessage({ type: "success", text: `Agent "${data.name}" created` });
        setShowCreate(false);
        await load();
      } catch (err) {
        setActionMessage({
          type: "error",
          text: err instanceof Error ? err.message : "Failed to create agent",
        });
      } finally {
        setSaving(false);
      }
    },
    [load],
  );

  const handleUpdate = useCallback(
    async (agentId: string, data: AgentUpdate) => {
      setSaving(true);
      setActionMessage(null);
      try {
        await updateAgent(agentId, data);
        setActionMessage({ type: "success", text: "Agent updated" });
        setEditing(null);
        await load();
      } catch (err) {
        setActionMessage({
          type: "error",
          text: err instanceof Error ? err.message : "Failed to update agent",
        });
      } finally {
        setSaving(false);
      }
    },
    [load],
  );

  return (
    <AppShell>
      <div className="space-y-6 max-w-6xl">
        {/* Page header */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h2 className="text-2xl font-bold tracking-tight">Agents</h2>
            <p className="text-muted-foreground mt-1">
              Manage AI agents that act on your behalf
            </p>
          </div>
          <Button
            variant="primary"
            size="sm"
            onClick={() => {
              setShowCreate(true);
              setEditing(null);
            }}
          >
            New Agent
          </Button>
        </div>

        {/* Action feedback */}
        {actionMessage && (
          <div
            className={`rounded-lg p-3 text-sm ${
              actionMessage.type === "success"
                ? "bg-success/15 text-success"
                : "bg-destructive/15 text-destructive"
            }`}
          >
            {actionMessage.text}
            <button
              type="button"
              className="ml-2 underline"
              onClick={() => setActionMessage(null)}
            >
              dismiss
            </button>
          </div>
        )}

        {/* Loading */}
        {loading && <LoadingState message="Loading agents…" />}

        {/* Error */}
        {!loading && error && <ErrorState message={error} onRetry={load} />}

        {/* Create form */}
        {showCreate && (
          <AgentForm
            title="Create Agent"
            saving={saving}
            onSubmit={handleCreate}
            onCancel={() => setShowCreate(false)}
          />
        )}

        {/* Edit form */}
        {editing && (
          <AgentForm
            title="Edit Agent"
            initial={{
              name: editing.name,
              description: editing.description,
              external_reference: editing.external_reference,
              status: editing.status,
            }}
            isEdit
            saving={saving}
            onSubmit={(data) => handleUpdate(editing.id, data)}
            onCancel={() => setEditing(null)}
          />
        )}

        {/* Agent list */}
        {!loading && !error && agents.length === 0 && !showCreate && (
          <EmptyState
            icon="🤖"
            title="No agents yet"
            description="Create your first AI agent to get started with intent parsing and transaction decisions."
          />
        )}

        {!loading && !error && agents.length > 0 && (
          <div className="space-y-4">
            <p className="text-sm text-muted-foreground">
              {total} agent{total !== 1 ? "s" : ""}
            </p>
            <div className="grid gap-4">
              {agents.map((agent) => (
                <div
                  key={agent.id}
                  className="rounded-xl border border-border bg-card p-5 shadow-sm"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-medium text-sm">{agent.name}</span>
                        <Badge
                          variant={statusVariant[agent.status] ?? "default"}
                        >
                          {agent.status}
                        </Badge>
                        {agent.trust_score !== null && (
                          <Badge variant="outline">
                            Trust: {(agent.trust_score * 100).toFixed(0)}%
                          </Badge>
                        )}
                      </div>
                      {agent.description && (
                        <p className="text-xs text-muted-foreground mt-1">
                          {agent.description}
                        </p>
                      )}
                      <p className="text-xs text-muted-foreground mt-1">
                        Created {formatDate(agent.created_at)}
                        {agent.external_reference &&
                          ` · Ref: ${agent.external_reference}`}
                      </p>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => {
                        setEditing(agent);
                        setShowCreate(false);
                      }}
                    >
                      Edit
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </AppShell>
  );
}

// ── Agent Form ─────────────────────────────────────────────

interface AgentFormProps {
  title: string;
  initial?: {
    name: string;
    description: string | null;
    external_reference: string | null;
    status?: string;
  };
  isEdit?: boolean;
  saving: boolean;
  onSubmit: (data: AgentCreate & { status?: string }) => void;
  onCancel: () => void;
}

function AgentForm({
  title,
  initial,
  isEdit,
  saving,
  onSubmit,
  onCancel,
}: AgentFormProps) {
  const [name, setName] = useState(initial?.name ?? "");
  const [description, setDescription] = useState(initial?.description ?? "");
  const [externalRef, setExternalRef] = useState(
    initial?.external_reference ?? "",
  );
  const [status, setStatus] = useState(initial?.status ?? "active");

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    const data: AgentCreate & { status?: string } = {
      name: name.trim(),
      description: description.trim() || null,
      external_reference: externalRef.trim() || null,
    };
    if (isEdit) {
      data.status = status;
    }
    onSubmit(data);
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>{title}</CardTitle>
          <Button variant="ghost" size="sm" onClick={onCancel}>
            Cancel
          </Button>
        </div>
        <CardDescription>
          {isEdit
            ? "Update the agent configuration"
            : "Create a new AI agent to handle transactions"}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label htmlFor="agent-name" className="block text-sm font-medium mb-1">
              Name
            </label>
            <input
              id="agent-name"
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
              maxLength={255}
              className="w-full px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
              placeholder="e.g. Payment Agent"
            />
          </div>

          <div>
            <label
              htmlFor="agent-description"
              className="block text-sm font-medium mb-1"
            >
              Description
            </label>
            <textarea
              id="agent-description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              rows={2}
              className="w-full px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
              placeholder="What does this agent do?"
            />
          </div>

          <div>
            <label
              htmlFor="agent-external-ref"
              className="block text-sm font-medium mb-1"
            >
              External Reference
            </label>
            <input
              id="agent-external-ref"
              type="text"
              value={externalRef}
              onChange={(e) => setExternalRef(e.target.value)}
              className="w-full px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
              placeholder="Optional external system reference"
            />
          </div>

          {isEdit && (
            <div>
              <label
                htmlFor="agent-status"
                className="block text-sm font-medium mb-1"
              >
                Status
              </label>
              <select
                id="agent-status"
                value={status}
                onChange={(e) => setStatus(e.target.value)}
                className="w-full px-3 py-2 rounded-lg border border-border bg-background text-foreground text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
              >
                <option value="active">Active</option>
                <option value="inactive">Inactive</option>
                <option value="suspended">Suspended</option>
              </select>
            </div>
          )}

          <div className="flex items-center gap-3 pt-2">
            <Button type="submit" variant="primary" size="sm" disabled={saving}>
              {saving ? "Saving…" : isEdit ? "Update" : "Create"}
            </Button>
            <Button variant="ghost" size="sm" onClick={onCancel}>
              Cancel
            </Button>
          </div>
        </form>
      </CardContent>
    </Card>
  );
}
