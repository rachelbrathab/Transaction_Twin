/**
 * Agents API client for Transaction Twin backend.
 *
 * All calls go through /api/v1/agents.
 * Authentication identity is resolved server-side from the JWT.
 */

import { apiGet, apiPost, apiPut } from "./api";
import type { AgentRead, AgentListResponse, AgentCreate, AgentUpdate } from "@/types/api";

const BASE = "/agents";

export async function listAgents(
  offset: number = 0,
  limit: number = 50,
): Promise<AgentListResponse> {
  const params = new URLSearchParams();
  params.set("offset", String(offset));
  params.set("limit", String(limit));
  return apiGet<AgentListResponse>(`${BASE}?${params.toString()}`);
}

export async function getAgent(agentId: string): Promise<AgentRead> {
  return apiGet<AgentRead>(`${BASE}/${agentId}`);
}

export async function createAgent(data: AgentCreate): Promise<AgentRead> {
  return apiPost<AgentRead>(BASE, data);
}

export async function updateAgent(
  agentId: string,
  data: AgentUpdate,
): Promise<AgentRead> {
  return apiPut<AgentRead>(`${BASE}/${agentId}`, data);
}
