/**
 * Calibration Intelligence API client.
 *
 * All calls go through /api/v1/analytics/calibration/*.
 * user_id is required by the backend for ownership scoping.
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
} from "@/types/api";

const BASE = "/analytics/calibration";

export async function listVersions(
  userId: string,
  status?: string,
): Promise<VersionsListResponse> {
  const params = new URLSearchParams({ user_id: userId });
  if (status) params.set("status", status);
  return apiGet<VersionsListResponse>(`${BASE}/versions?${params}`);
}

export async function getVersion(
  userId: string,
  versionId: string,
): Promise<VersionDetailResponse> {
  const params = new URLSearchParams({ user_id: userId });
  return apiGet<VersionDetailResponse>(
    `${BASE}/versions/${versionId}?${params}`,
  );
}

export async function getRecommendations(
  userId: string,
  opts?: { status?: string; engine?: string; version?: string },
): Promise<RecommendationsListResponse> {
  const params = new URLSearchParams({ user_id: userId });
  if (opts?.status) params.set("status", opts.status);
  if (opts?.engine) params.set("engine", opts.engine);
  if (opts?.version) params.set("version", opts.version);
  return apiGet<RecommendationsListResponse>(
    `${BASE}/recommendations?${params}`,
  );
}

export async function getRecommendation(
  userId: string,
  recommendationId: string,
): Promise<RecommendationResponse> {
  const params = new URLSearchParams({ user_id: userId });
  return apiGet<RecommendationResponse>(
    `${BASE}/recommendations/${recommendationId}?${params}`,
  );
}

export async function reviewRecommendation(
  userId: string,
  recommendationId: string,
  action: "approve" | "reject",
  reason?: string,
): Promise<ReviewResponse> {
  const params = new URLSearchParams({ user_id: userId });
  return apiPost<ReviewResponse>(
    `${BASE}/recommendations/${recommendationId}/review?${params}`,
    { action, reason: reason ?? null },
  );
}

export async function generateCalibration(
  userId: string,
  windowDays: number = 30,
): Promise<GenerateResponse> {
  const params = new URLSearchParams({ user_id: userId });
  return apiPost<GenerateResponse>(
    `${BASE}/generate?${params}`,
    { window_days: windowDays },
  );
}

export async function activateVersion(
  userId: string,
  versionId: string,
): Promise<ActivateResponse> {
  const params = new URLSearchParams({ user_id: userId });
  return apiPost<ActivateResponse>(
    `${BASE}/versions/${versionId}/activate?${params}`,
    { confirm: true },
  );
}

export async function rollbackCalibration(
  userId: string,
): Promise<RollbackResponse> {
  return apiPost<RollbackResponse>(`${BASE}/rollback`, {
    user_id: userId,
    confirm: true,
  });
}

export async function getEffectiveConfig(
  userId: string,
): Promise<EffectiveConfigResponse> {
  const params = new URLSearchParams({ user_id: userId });
  return apiGet<EffectiveConfigResponse>(
    `${BASE}/effective-config?${params}`,
  );
}

export async function getCalibrationMetrics(
  userId: string,
): Promise<CalibrationMetricsResponse> {
  const params = new URLSearchParams({ user_id: userId });
  return apiGet<CalibrationMetricsResponse>(
    `${BASE}/metrics?${params}`,
  );
}
