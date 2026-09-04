/**
 * Shared TypeScript types for Transaction Twin API.
 *
 * These types mirror the backend Pydantic schemas.
 * Keep in sync as the API evolves.
 */

export interface HealthResponse {
  status: string;
  database?: boolean;
}

export interface ErrorResponse {
  error: {
    code: string;
    message: string;
  };
}

// ── Calibration Intelligence Types ──────────────────────────

export interface RecommendationResponse {
  recommendation_id: string;
  recommendation_type: string;
  engine: string;
  parameter: string | null;
  current_value: Record<string, unknown> | null;
  proposed_value: Record<string, unknown> | null;
  evidence: Record<string, unknown>;
  sample_count: number;
  data_sufficiency: string;
  rationale: string;
  severity: string;
  generated_at: string;
  calibration_version: string;
  status: string;
  reviewed_at: string | null;
  reviewed_by: string | null;
  approved_at: string | null;
  approved_by: string | null;
  rejection_reason: string | null;
}

export interface RecommendationsListResponse {
  recommendations: RecommendationResponse[];
  total: number;
  by_status: Record<string, number>;
}

export interface VersionResponse {
  id: string;
  version_id: string;
  source_window_days: number;
  total_samples: number;
  eligible_samples: number;
  excluded_samples: number;
  recommendation_count: number;
  status: string;
  activated_at: string | null;
  activated_by: string | null;
  previous_version: string | null;
  created_at: string;
}

export interface VersionDetailResponse {
  version: VersionResponse;
  recommendations: RecommendationResponse[];
}

export interface VersionsListResponse {
  versions: VersionResponse[];
  total: number;
}

export interface GenerateResponse {
  version_id: string;
  status: string;
  total_samples: number;
  eligible_samples: number;
  excluded_samples: number;
  recommendation_count: number;
  generated_at: string;
  idempotent: boolean;
}

export interface ReviewResponse {
  recommendation_id: string;
  status: string;
  reviewed_at: string;
  idempotent: boolean;
}

export interface ActivateResponse {
  version_id: string;
  status: string;
  activated_at: string;
  previous_version: string | null;
  recommendations_applied: number;
  idempotent: boolean;
}

export interface RollbackResponse {
  rolled_back: boolean;
  previous_active_version: string;
  restored_version: string;
  message: string;
}

export interface EffectiveConfigResponse {
  calibration_active: boolean;
  source_version_id: string;
  signal_weights: Record<string, number>;
  risk_level_thresholds: Record<string, number>;
  confidence_reductions: Record<string, number>;
  confidence_floor: number;
  confidence_ceiling: number;
  validation_passed: boolean;
  validation_errors: string[];
  parameters_applied: string[];
  parameters_rejected: string[];
}

export interface CalibrationMetricsResponse {
  total_decisions: number;
  calibration_active_count: number;
  default_count: number;
  validation_failed_count: number;
  no_active_calibration_count: number;
  usage_by_version: Record<string, number>;
  risk_level_distribution: Record<string, number>;
}

// ── Simulate Outcome Types ─────────────────────────────────

export interface SimulateEventResult {
  event_id: string;
  event_type: string;
  sequence_number: number;
  verification_state: string;
}

export interface SimulateOutcomeResponse {
  transaction_id: string;
  final_status: string;
  events_created: SimulateEventResult[];
  target_event: string;
}

// ── Calibration Outcomes Types ─────────────────────────────

export interface OutcomesSample {
  transaction_id: string;
  decision_id: string;
  original_decision: string;
  final_lifecycle_status: string;
  feedback_type: string;
  feedback_confidence: number;
  verification_state: string;
  risk_level: string | null;
  risk_available: boolean;
  sample_eligible: boolean;
  exclusion_reason: string | null;
}

export interface OutcomesResponse {
  samples: OutcomesSample[];
  total_samples: number;
  eligible_samples: number;
  excluded_samples: number;
  exclusion_summary: Record<string, number>;
  data_sufficiency: Record<string, unknown>;
  window_days: number;
  computed_at: string;
}

export type CalibrationVersionStatus =
  | "generated"
  | "active"
  | "superseded";

export type RecommendationStatus =
  | "generated"
  | "reviewed"
  | "approved"
  | "rejected";

// ── Agent Types ────────────────────────────────────────────────

export interface AgentRead {
  id: string;
  user_id: string;
  external_reference: string | null;
  name: string;
  description: string | null;
  status: string;
  trust_score: number | null;
  created_at: string;
  updated_at: string;
}

export interface AgentCreate {
  name: string;
  description?: string | null;
  external_reference?: string | null;
}

export interface AgentUpdate {
  name?: string | null;
  description?: string | null;
  external_reference?: string | null;
  status?: string | null;
}

export interface AgentListResponse {
  agents: AgentRead[];
  total: number;
}

// ── Transaction Types ───────────────────────────────────────

export interface TransactionListItem {
  id: string;
  agent_id: string;
  transaction_type: string;
  amount: number;
  currency: string;
  status: string;
  decision: string | null;
  decision_reason: string | null;
  risk_level: string | null;
  risk_score: number | null;
  created_at: string;
}

export interface TransactionListResponse {
  transactions: TransactionListItem[];
  total: number;
}

export interface TransactionDetailResponse {
  id: string;
  user_id: string;
  agent_id: string;
  intent_id: string;
  transaction_type: string;
  amount: number;
  currency: string;
  status: string;
  decision: string | null;
  decision_reason: string | null;
  decision_explanation: Record<string, unknown> | null;
  risk_level: string | null;
  risk_score: number | null;
  risk_features: Record<string, unknown> | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
  updated_at: string;
  events: Array<Record<string, unknown>>;
}

