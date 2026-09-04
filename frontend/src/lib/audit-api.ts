/**
 * Audit Vault API client.
 *
 * Read-only audit event history.
 */

import { apiGet } from "./api";

export interface AuditEventItem {
  id: string;
  entity_type: string;
  entity_id: string;
  event_type: string;
  actor_type: string | null;
  actor_id: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface AuditEventListResponse {
  events: AuditEventItem[];
  total: number;
}

export interface AuditEventDetailResponse extends AuditEventItem {
  previous_hash: string | null;
  current_hash: string | null;
}

export async function listAuditEvents(
  opts?: { entityType?: string; eventType?: string; limit?: number; offset?: number },
): Promise<AuditEventListResponse> {
  const params = new URLSearchParams();
  if (opts?.entityType) params.set("entity_type", opts.entityType);
  if (opts?.eventType) params.set("event_type", opts.eventType);
  if (opts?.limit) params.set("limit", String(opts.limit));
  if (opts?.offset) params.set("offset", String(opts.offset));
  const qs = params.toString();
  return apiGet<AuditEventListResponse>(`/audit/events${qs ? `?${qs}` : ""}`);
}

export async function getAuditEvent(
  eventId: string,
): Promise<AuditEventDetailResponse> {
  return apiGet<AuditEventDetailResponse>(`/audit/events/${eventId}`);
}
