/**
 * Policies API client.
 *
 * CRUD operations for policies.
 */

import { apiGet, apiPost, apiPut, apiDelete } from "./api";

export interface PolicyRead {
  id: string;
  user_id: string;
  name: string;
  description: string | null;
  status: string;
  version: number;
  rules: Record<string, unknown> | null;
  scope: Record<string, unknown> | null;
  effective_from: string | null;
  effective_until: string | null;
  created_at: string;
  updated_at: string;
}

export interface PolicyListResponse {
  policies: PolicyRead[];
  total: number;
}

export interface PolicyCreate {
  name: string;
  description?: string | null;
  rules?: Record<string, unknown> | null;
  scope?: Record<string, unknown> | null;
}

export interface PolicyUpdate {
  name?: string | null;
  description?: string | null;
  status?: string | null;
  rules?: Record<string, unknown> | null;
  scope?: Record<string, unknown> | null;
}

export async function listPolicies(
  status?: string,
): Promise<PolicyListResponse> {
  const params = status ? `?status=${status}` : "";
  return apiGet<PolicyListResponse>(`/policies${params}`);
}

export async function getPolicy(policyId: string): Promise<PolicyRead> {
  return apiGet<PolicyRead>(`/policies/${policyId}`);
}

export async function createPolicy(
  data: PolicyCreate,
): Promise<PolicyRead> {
  return apiPost<PolicyRead>("/policies", data);
}

export async function updatePolicy(
  policyId: string,
  data: PolicyUpdate,
): Promise<PolicyRead> {
  return apiPut<PolicyRead>(`/policies/${policyId}`, data);
}

export async function deletePolicy(policyId: string): Promise<void> {
  await apiDelete(`/policies/${policyId}`);
}
