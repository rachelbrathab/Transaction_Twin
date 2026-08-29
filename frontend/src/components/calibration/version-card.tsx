"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { VersionResponse } from "@/types/api";

const statusVariant: Record<string, "success" | "warning" | "destructive" | "default" | "outline"> = {
  active: "success",
  generated: "default",
  superseded: "outline",
};

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  } catch {
    return iso;
  }
}

interface VersionCardProps {
  version: VersionResponse;
  isActive: boolean;
  onViewDetail: (versionId: string) => void;
  onActivate?: (versionId: string) => void;
  onRollback?: () => void;
  activating?: boolean;
}

export function VersionCard({
  version,
  isActive,
  onViewDetail,
  onActivate,
  onRollback,
  activating,
}: VersionCardProps) {
  return (
    <div className="rounded-xl border border-border bg-card p-5 shadow-sm space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-mono text-sm font-medium truncate">
              {version.version_id}
            </span>
            <Badge variant={statusVariant[version.status] ?? "default"}>
              {version.status.toUpperCase()}
            </Badge>
            {isActive && (
              <Badge variant="success">ACTIVE</Badge>
            )}
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            Created {formatDate(version.created_at)}
            {version.activated_at && ` · Activated ${formatDate(version.activated_at)}`}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4 text-sm">
        <div>
          <p className="text-muted-foreground text-xs">Total Samples</p>
          <p className="font-medium">{version.total_samples}</p>
        </div>
        <div>
          <p className="text-muted-foreground text-xs">Eligible</p>
          <p className="font-medium">{version.eligible_samples}</p>
        </div>
        <div>
          <p className="text-muted-foreground text-xs">Recommendations</p>
          <p className="font-medium">{version.recommendation_count}</p>
        </div>
      </div>

      {version.previous_version && (
        <p className="text-xs text-muted-foreground">
          Previous: <span className="font-mono">{version.previous_version}</span>
        </p>
      )}

      <div className="flex items-center gap-2 pt-1">
        <Button
          variant="ghost"
          size="sm"
          onClick={() => onViewDetail(version.version_id)}
        >
          View Details
        </Button>
        {version.status === "generated" && onActivate && (
          <Button
            variant="primary"
            size="sm"
            onClick={() => onActivate(version.version_id)}
            disabled={activating}
          >
            {activating ? "Activating…" : "Activate"}
          </Button>
        )}
        {isActive && onRollback && (
          <Button
            variant="destructive"
            size="sm"
            onClick={onRollback}
          >
            Rollback
          </Button>
        )}
      </div>
    </div>
  );
}
