/**
 * Calibration Intelligence API client.
 *
 * All calls go through /api/v1/analytics/calibration/*.
 * Authentication identity is resolved server-side from the trusted
 * reverse-proxy header — the frontend never sends user_id.
 */

import { apiGet, apiPost } from "./api";
import type {
  VersionsListResponse,
  VersionDetailResponse,
  RecommendationsListResponse,
  RecommendationResponse,
  GenerateResponse,
  ReviewResponse,
  ActivateResponse,
  RollbackResponse,
  EffectiveConfigResponse,
  CalibrationMetricsResponse,
  SimulateOutcomeResponse,
  OutcomesResponse,
} from "@/types/api";

const BASE = "/analytics/calibration";

export async function listVersions(
  status?: string,
): Promise<VersionsListResponse> {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  const qs = params.toString();
  return apiGet<VersionsListResponse>(`${BASE}/versions${qs ? `?${qs}` : ""}`);
}

export async function getVersion(
  versionId: string,
): Promise<VersionDetailResponse> {
  return apiGet<VersionDetailResponse>(
    `${BASE}/versions/${versionId}`,
  );
}

export async function getRecommendations(
  opts?: { status?: string; engine?: string; version?: string },
): Promise<RecommendationsListResponse> {
  const params = new URLSearchParams();
  if (opts?.status) params.set("status", opts.status);
  if (opts?.engine) params.set("engine", opts.engine);
  if (opts?.version) params.set("version", opts.version);
  const qs = params.toString();
  return apiGet<RecommendationsListResponse>(
    `${BASE}/recommendations${qs ? `?${qs}` : ""}`,
  );
}

export async function getRecommendation(
  recommendationId: string,
): Promise<RecommendationResponse> {
  return apiGet<RecommendationResponse>(
    `${BASE}/recommendations/${recommendationId}`,
  );
}

export async function reviewRecommendation(
  recommendationId: string,
  action: "approve" | "reject",
  reason?: string,
): Promise<ReviewResponse> {
  return apiPost<ReviewResponse>(
    `${BASE}/recommendations/${recommendationId}/review`,
    { action, reason: reason ?? null },
  );
}

export async function generateCalibration(
  windowDays: number = 30,
): Promise<GenerateResponse> {
  return apiPost<GenerateResponse>(
    `${BASE}/generate`,
    { window_days: windowDays },
  );
}

export async function activateVersion(
  versionId: string,
): Promise<ActivateResponse> {
  return apiPost<ActivateResponse>(
    `${BASE}/versions/${versionId}/activate`,
    { confirm: true },
  );
}

export async function rollbackCalibration(): Promise<RollbackResponse> {
  return apiPost<RollbackResponse>(`${BASE}/rollback`, {
    confirm: true,
  });
}

export async function getEffectiveConfig(): Promise<EffectiveConfigResponse> {
  return apiGet<EffectiveConfigResponse>(`${BASE}/effective-config`);
}

export async function getCalibrationMetrics(): Promise<CalibrationMetricsResponse> {
  return apiGet<CalibrationMetricsResponse>(`${BASE}/metrics`);
}

// ── Simulate Outcome ───────────────────────────────────────

export async function simulateOutcome(
  transactionId: string,
  eventType: string,
): Promise<SimulateOutcomeResponse> {
  return apiPost<SimulateOutcomeResponse>(
    `/transactions/${transactionId}/simulate-outcome`,
    { event_type: eventType },
  );
}

// ── Test Data Setup ────────────────────────────────────────

export async function setupTestData(): Promise<SetupTestDataResponse> {
  return apiPost<SetupTestDataResponse>(`/calibration/test-data`);
}

export async function getOutcomes(
  windowDays: number = 30,
): Promise<OutcomesResponse> {
  return apiGet<OutcomesResponse>(
    `${BASE}/outcomes?window_days=${windowDays}`,
  );
}

interface SetupTestDataResponse {
  agent_id: string;
  intent_id: string;
  transactions: Array<{
    transaction_id: string;
    decision: string;
    outcome: string;
    final_status: string;
    amount: number;
  }>;
  message: string;
}
