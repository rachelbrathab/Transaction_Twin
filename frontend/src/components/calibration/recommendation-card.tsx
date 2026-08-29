"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import type { RecommendationResponse } from "@/types/api";

const statusVariant: Record<string, "success" | "warning" | "destructive" | "default" | "outline"> = {
  approved: "success",
  reviewed: "warning",
  generated: "default",
  rejected: "destructive",
};

const severityVariant: Record<string, "warning" | "destructive" | "default" | "outline"> = {
  high: "destructive",
  medium: "warning",
  low: "outline",
  info: "default",
};

function formatValue(val: Record<string, unknown> | null): string {
  if (!val) return "—";
  const entries = Object.entries(val);
  if (entries.length === 0) return "—";
  return entries.map(([k, v]) => `${k}: ${String(v)}`).join(", ");
}

interface RecommendationCardProps {
  recommendation: RecommendationResponse;
  onReview?: (id: string, action: "approve" | "reject") => void;
  reviewing?: boolean;
}

export function RecommendationCard({
  recommendation,
  onReview,
  reviewing,
}: RecommendationCardProps) {
  const isReviewable =
    recommendation.status === "generated" ||
    recommendation.status === "reviewed";

  return (
    <div className="rounded-xl border border-border bg-card p-5 shadow-sm space-y-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-medium text-sm">
              {recommendation.parameter ?? recommendation.recommendation_type}
            </span>
            <Badge variant={statusVariant[recommendation.status] ?? "default"}>
              {recommendation.status.toUpperCase()}
            </Badge>
            <Badge variant={severityVariant[recommendation.severity] ?? "default"}>
              {recommendation.severity}
            </Badge>
          </div>
          <p className="text-xs text-muted-foreground mt-1">
            {recommendation.engine} · {recommendation.recommendation_type}
            {recommendation.sample_count > 0 && ` · ${recommendation.sample_count} samples`}
          </p>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 text-sm">
        <div>
          <p className="text-muted-foreground text-xs">Current Value</p>
          <p className="font-mono text-xs mt-0.5 break-all">
            {formatValue(recommendation.current_value)}
          </p>
        </div>
        <div>
          <p className="text-muted-foreground text-xs">Proposed Value</p>
          <p className="font-mono text-xs mt-0.5 break-all">
            {formatValue(recommendation.proposed_value)}
          </p>
        </div>
      </div>

      {recommendation.rationale && (
        <div>
          <p className="text-muted-foreground text-xs">Rationale</p>
          <p className="text-sm mt-0.5">{recommendation.rationale}</p>
        </div>
      )}

      {recommendation.rejection_reason && (
        <div className="rounded-lg bg-destructive/10 p-3">
          <p className="text-xs font-medium text-destructive">Rejection Reason</p>
          <p className="text-sm mt-0.5">{recommendation.rejection_reason}</p>
        </div>
      )}

      {isReviewable && onReview && (
        <div className="flex items-center gap-2 pt-1">
          <Button
            variant="primary"
            size="sm"
            onClick={() => onReview(recommendation.recommendation_id, "approve")}
            disabled={reviewing}
          >
            {reviewing ? "Reviewing…" : "Approve"}
          </Button>
          <Button
            variant="destructive"
            size="sm"
            onClick={() => onReview(recommendation.recommendation_id, "reject")}
            disabled={reviewing}
          >
            Reject
          </Button>
        </div>
      )}
    </div>
  );
}
