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
import { VersionCard } from "@/components/calibration/version-card";
import { RecommendationCard } from "@/components/calibration/recommendation-card";
import { ConfirmDialog } from "@/components/calibration/confirm-dialog";
import {
  listVersions,
  getVersion,
  getRecommendations,
  generateCalibration,
  reviewRecommendation,
  activateVersion,
  rollbackCalibration,
  getEffectiveConfig,
  getCalibrationMetrics,
} from "@/lib/calibration-api";
import type {
  VersionResponse,
  VersionDetailResponse,
  RecommendationResponse,
  EffectiveConfigResponse,
  CalibrationMetricsResponse,
} from "@/types/api";

type Tab = "versions" | "recommendations" | "config" | "metrics";

export default function CalibrationPage() {
  const [tab, setTab] = useState<Tab>("versions");
  const [versions, setVersions] = useState<VersionResponse[]>([]);
  const [selectedVersion, setSelectedVersion] =
    useState<VersionDetailResponse | null>(null);
  const [recommendations, setRecommendations] = useState<
    RecommendationResponse[]
  >([]);
  const [config, setConfig] = useState<EffectiveConfigResponse | null>(null);
  const [metrics, setMetrics] = useState<CalibrationMetricsResponse | null>(
    null,
  );
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activating, setActivating] = useState<string | null>(null);
  const [reviewing, setReviewing] = useState<string | null>(null);
  const [generating, setGenerating] = useState(false);
  const [actionMessage, setActionMessage] = useState<{
    type: "success" | "error";
    text: string;
  } | null>(null);

  // Confirm dialog state
  const [rollbackDialog, setRollbackDialog] = useState(false);
  const [activateDialog, setActivateDialog] = useState<string | null>(null);

  const activeVersion = versions.find((v) => v.status === "active");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const [v, r, c, m] = await Promise.allSettled([
        listVersions(),
        getRecommendations(),
        getEffectiveConfig(),
        getCalibrationMetrics(),
      ]);
      if (cancelled) return;
      setLoading(false);
      if (v.status === "fulfilled") setVersions(v.value.versions);
      else setError(v.reason instanceof Error ? v.reason.message : "Failed to load versions");
      if (r.status === "fulfilled") setRecommendations(r.value.recommendations);
      if (c.status === "fulfilled") setConfig(c.value);
      if (m.status === "fulfilled") setMetrics(m.value);
    }
    load();
    return () => { cancelled = true; };
  }, []);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    const [v, r, c, m] = await Promise.allSettled([
      listVersions(),
      getRecommendations(),
      getEffectiveConfig(),
      getCalibrationMetrics(),
    ]);
    setLoading(false);
    if (v.status === "fulfilled") setVersions(v.value.versions);
    else setError(v.reason instanceof Error ? v.reason.message : "Failed to load versions");
    if (r.status === "fulfilled") setRecommendations(r.value.recommendations);
    if (c.status === "fulfilled") setConfig(c.value);
    if (m.status === "fulfilled") setMetrics(m.value);
  }, []);

  const handleViewDetail = useCallback(
    async (versionId: string) => {
      try {
        const detail = await getVersion(versionId);
        setSelectedVersion(detail);
      } catch (err) {
        setActionMessage({
          type: "error",
          text: err instanceof Error ? err.message : "Failed to load version",
        });
      }
    },
    [],
  );

  const handleActivate = useCallback(
    async (versionId: string) => {
      setActivating(versionId);
      setActionMessage(null);
      try {
        const res = await activateVersion(versionId);
        setActionMessage({
          type: "success",
          text: `Activated ${res.version_id}${res.idempotent ? " (already active)" : ""}`,
        });
        await reload();
      } catch (err) {
        setActionMessage({
          type: "error",
          text: err instanceof Error ? err.message : "Activation failed",
        });
      } finally {
        setActivating(null);
        setActivateDialog(null);
      }
    },
    [reload],
  );

  const handleRollback = useCallback(async () => {
    setActionMessage(null);
    try {
      const res = await rollbackCalibration();
      setActionMessage({
        type: "success",
        text: res.message,
      });
      await reload();
    } catch (err) {
      setActionMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Rollback failed",
      });
    } finally {
      setRollbackDialog(false);
    }
  }, [reload]);

  const handleReview = useCallback(
    async (recommendationId: string, action: "approve" | "reject") => {
      setReviewing(recommendationId);
      setActionMessage(null);
      try {
        const res = await reviewRecommendation(
          recommendationId,
          action,
        );
        setActionMessage({
          type: "success",
          text: `Recommendation ${action}d${res.idempotent ? " (already done)" : ""}`,
        });
        await reload();
      } catch (err) {
        setActionMessage({
          type: "error",
          text:
            err instanceof Error
              ? err.message
              : `Failed to ${action} recommendation`,
        });
      } finally {
        setReviewing(null);
      }
    },
    [reload],
  );

  const handleGenerate = useCallback(async () => {
    setGenerating(true);
    setActionMessage(null);
    try {
      const res = await generateCalibration();
      setActionMessage({
        type: "success",
        text: `Generated ${res.version_id} (${res.recommendation_count} recommendations)`,
      });
      await reload();
    } catch (err) {
      setActionMessage({
        type: "error",
        text: err instanceof Error ? err.message : "Generation failed",
      });
    } finally {
      setGenerating(false);
    }
  }, [reload]);

  const tabs: { key: Tab; label: string }[] = [
    { key: "versions", label: "Versions" },
    { key: "recommendations", label: "Recommendations" },
    { key: "config", label: "Effective Config" },
    { key: "metrics", label: "Health Metrics" },
  ];

  return (
    <AppShell>
      <div className="space-y-6 max-w-6xl">
        {/* Page header */}
        <div className="flex items-start justify-between gap-4 flex-wrap">
          <div>
            <h2 className="text-2xl font-bold tracking-tight">
              Calibration Intelligence
            </h2>
            <p className="text-muted-foreground mt-1">
              Manage calibration versions, review recommendations, and monitor
              runtime configuration
            </p>
          </div>
          <Button
            variant="primary"
            size="sm"
            onClick={handleGenerate}
            disabled={generating}
          >
            {generating ? "Generating…" : "Generate Calibration"}
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

        {/* Active version banner */}
        {activeVersion && (
          <Card>
            <CardContent className="pt-6">
              <div className="flex items-center gap-3 flex-wrap">
                <Badge variant="success">ACTIVE</Badge>
                <span className="font-mono text-sm">
                  {activeVersion.version_id}
                </span>
                <span className="text-xs text-muted-foreground">
                  Activated{" "}
                  {activeVersion.activated_at
                    ? new Date(activeVersion.activated_at).toLocaleDateString()
                    : "—"}
                </span>
                {activeVersion.previous_version && (
                  <Button
                    variant="destructive"
                    size="sm"
                    className="ml-auto"
                    onClick={() => setRollbackDialog(true)}
                  >
                    Rollback
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>
        )}

        {/* Tab navigation */}
        <div className="flex gap-1 border-b border-border">
          {tabs.map((t) => (
            <button
              key={t.key}
              type="button"
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                tab === t.key
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground hover:text-foreground"
              }`}
              onClick={() => setTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>

        {/* Loading */}
        {loading && <LoadingState message="Loading calibration data…" />}

        {/* Error */}
        {!loading && error && (
          <ErrorState message={error} onRetry={reload} />
        )}

        {/* Content */}
        {!loading && !error && (
          <>
            {/* ── Versions Tab ── */}
            {tab === "versions" && (
              <div className="space-y-4">
                {versions.length === 0 ? (
                  <EmptyState
                    icon="📊"
                    title="No calibration versions"
                    description="Generate a calibration version from verified outcomes to get started."
                  />
                ) : (
                  <div className="grid gap-4">
                    {versions.map((v) => (
                      <VersionCard
                        key={v.version_id}
                        version={v}
                        isActive={v.status === "active"}
                        onViewDetail={handleViewDetail}
                        onActivate={(id) => setActivateDialog(id)}
                        onRollback={
                          v.status === "active" && v.previous_version
                            ? () => setRollbackDialog(true)
                            : undefined
                        }
                        activating={activating === v.version_id}
                      />
                    ))}
                  </div>
                )}

                {/* Version detail drawer */}
                {selectedVersion && (
                  <Card>
                    <CardHeader>
                      <div className="flex items-center justify-between">
                        <CardTitle>
                          Version: {selectedVersion.version.version_id}
                        </CardTitle>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => setSelectedVersion(null)}
                        >
                          Close
                        </Button>
                      </div>
                      <CardDescription>
                        Source window: {selectedVersion.version.source_window_days} days
                        {" · "}
                        {selectedVersion.version.total_samples} total samples
                        {" · "}
                        {selectedVersion.version.eligible_samples} eligible
                      </CardDescription>
                    </CardHeader>
                    <CardContent>
                      <h4 className="font-medium text-sm mb-3">
                        Recommendations ({selectedVersion.recommendations.length})
                      </h4>
                      <div className="grid gap-3">
                        {selectedVersion.recommendations.map((rec) => (
                          <RecommendationCard
                            key={rec.recommendation_id}
                            recommendation={rec}
                            onReview={handleReview}
                            reviewing={reviewing === rec.recommendation_id}
                          />
                        ))}
                        {selectedVersion.recommendations.length === 0 && (
                          <p className="text-sm text-muted-foreground">
                            No recommendations for this version.
                          </p>
                        )}
                      </div>
                    </CardContent>
                  </Card>
                )}
              </div>
            )}

            {/* ── Recommendations Tab ── */}
            {tab === "recommendations" && (
              <div className="space-y-4">
                {recommendations.length === 0 ? (
                  <EmptyState
                    icon="📋"
                    title="No recommendations"
                    description="Generate a calibration version to produce recommendations."
                  />
                ) : (
                  <div className="grid gap-4">
                    {recommendations.map((rec) => (
                      <RecommendationCard
                        key={rec.recommendation_id}
                        recommendation={rec}
                        onReview={handleReview}
                        reviewing={reviewing === rec.recommendation_id}
                      />
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* ── Effective Config Tab ── */}
            {tab === "config" && (
              <div className="space-y-4">
                {!config ? (
                  <EmptyState
                    icon="⚙️"
                    title="No configuration available"
                    description="No calibration is currently active. Default Risk Engine configuration is in use."
                  />
                ) : (
                  <>
                    <Card>
                      <CardHeader>
                        <CardTitle>Runtime Configuration</CardTitle>
                        <CardDescription>
                          {config.calibration_active
                            ? `Active from version: ${config.source_version_id}`
                            : "Using Risk Engine defaults — no active calibration"}
                        </CardDescription>
                      </CardHeader>
                      <CardContent>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
                          <div>
                            <p className="text-muted-foreground text-xs">
                              Calibration Active
                            </p>
                            <Badge
                              variant={
                                config.calibration_active ? "success" : "default"
                              }
                            >
                              {config.calibration_active ? "Yes" : "No"}
                            </Badge>
                          </div>
                          <div>
                            <p className="text-muted-foreground text-xs">
                              Validation Passed
                            </p>
                            <Badge
                              variant={
                                config.validation_passed ? "success" : "destructive"
                              }
                            >
                              {config.validation_passed ? "Yes" : "No"}
                            </Badge>
                          </div>
                        </div>

                        {config.calibration_active && (
                          <div className="mt-4 space-y-4">
                            <ConfigSection
                              title="Signal Weights"
                              data={config.signal_weights}
                            />
                            <ConfigSection
                              title="Risk Level Thresholds"
                              data={config.risk_level_thresholds}
                            />
                            <ConfigSection
                              title="Confidence Reductions"
                              data={config.confidence_reductions}
                            />
                            <div className="grid grid-cols-2 gap-4 text-sm">
                              <div>
                                <p className="text-muted-foreground text-xs">
                                  Confidence Floor
                                </p>
                                <p className="font-mono">
                                  {config.confidence_floor}
                                </p>
                              </div>
                              <div>
                                <p className="text-muted-foreground text-xs">
                                  Confidence Ceiling
                                </p>
                                <p className="font-mono">
                                  {config.confidence_ceiling}
                                </p>
                              </div>
                            </div>
                          </div>
                        )}

                        {config.validation_errors.length > 0 && (
                          <div className="mt-4 rounded-lg bg-destructive/10 p-3">
                            <p className="text-xs font-medium text-destructive mb-1">
                              Validation Errors
                            </p>
                            <ul className="text-xs space-y-0.5">
                              {config.validation_errors.map((err) => (
                                <li key={err}>{err}</li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </CardContent>
                    </Card>
                  </>
                )}
              </div>
            )}

            {/* ── Metrics Tab ── */}
            {tab === "metrics" && (
              <div className="space-y-4">
                {!metrics || metrics.total_decisions === 0 ? (
                  <EmptyState
                    icon="📈"
                    title="No metrics yet"
                    description="Metrics will appear after transaction decisions have been processed."
                  />
                ) : (
                  <div className="grid gap-4">
                    <Card>
                      <CardHeader>
                        <CardTitle>Decision Summary</CardTitle>
                      </CardHeader>
                      <CardContent>
                        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4 text-sm">
                          <MetricStat
                            label="Total Decisions"
                            value={metrics.total_decisions}
                          />
                          <MetricStat
                            label="Calibrated"
                            value={metrics.calibration_active_count}
                          />
                          <MetricStat
                            label="Default"
                            value={metrics.default_count}
                          />
                          <MetricStat
                            label="Validation Failed"
                            value={metrics.validation_failed_count}
                          />
                        </div>
                      </CardContent>
                    </Card>

                    {Object.keys(metrics.usage_by_version).length > 0 && (
                      <Card>
                        <CardHeader>
                          <CardTitle>Usage by Version</CardTitle>
                        </CardHeader>
                        <CardContent>
                          <div className="space-y-2">
                            {Object.entries(metrics.usage_by_version).map(
                              ([ver, count]) => (
                                <div
                                  key={ver}
                                  className="flex items-center justify-between text-sm"
                                >
                                  <span className="font-mono text-xs">{ver}</span>
                                  <span className="font-medium">{count}</span>
                                </div>
                              ),
                            )}
                          </div>
                        </CardContent>
                      </Card>
                    )}

                    {Object.keys(metrics.risk_level_distribution).length >
                      0 && (
                      <Card>
                        <CardHeader>
                          <CardTitle>Risk Level Distribution</CardTitle>
                        </CardHeader>
                        <CardContent>
                          <div className="space-y-2">
                            {Object.entries(metrics.risk_level_distribution).map(
                              ([level, count]) => (
                                <div
                                  key={level}
                                  className="flex items-center justify-between text-sm"
                                >
                                  <span className="capitalize">{level}</span>
                                  <span className="font-medium">{count}</span>
                                </div>
                              ),
                            )}
                          </div>
                        </CardContent>
                      </Card>
                    )}
                  </div>
                )}
              </div>
            )}
          </>
        )}

        {/* ── Confirm Dialogs ── */}
        <ConfirmDialog
          open={activateDialog !== null}
          title="Activate Calibration Version"
          description={`This will activate version ${activateDialog ?? ""} and supersede the current active calibration. This change takes effect immediately for all future transaction decisions.`}
          confirmLabel="Activate"
          variant="primary"
          onConfirm={() => {
            if (activateDialog) handleActivate(activateDialog);
          }}
          onCancel={() => setActivateDialog(null)}
        />

        <ConfirmDialog
          open={rollbackDialog}
          title="Rollback Calibration"
          description={
            activeVersion
              ? `This will restore version ${activeVersion.previous_version ?? "—"} as the active calibration. The current active version (${activeVersion.version_id}) will be superseded.`
              : "No active calibration to roll back."
          }
          confirmLabel="Rollback"
          variant="destructive"
          onConfirm={handleRollback}
          onCancel={() => setRollbackDialog(false)}
        />
      </div>
    </AppShell>
  );
}

// ── Helper sub-components ─────────────────────────────────────

function ConfigSection({
  title,
  data,
}: {
  title: string;
  data: Record<string, number>;
}) {
  const entries = Object.entries(data);
  if (entries.length === 0) return null;
  return (
    <div>
      <p className="text-xs font-medium text-muted-foreground mb-1">{title}</p>
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
        {entries.map(([key, val]) => (
          <div key={key} className="text-sm">
            <span className="text-muted-foreground text-xs">{key}: </span>
            <span className="font-mono">{val}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function MetricStat({
  label,
  value,
}: {
  label: string;
  value: number;
}) {
  return (
    <div>
      <p className="text-muted-foreground text-xs">{label}</p>
      <p className="text-2xl font-bold mt-0.5">{value}</p>
    </div>
  );
}
