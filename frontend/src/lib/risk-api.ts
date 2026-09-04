/**
 * Risk Intelligence API client.
 *
 * Read-only risk statistics and transaction risk data.
 */

import { apiGet } from "./api";

export interface RiskSummaryResponse {
  total_decisions: number;
  allow_count: number;
  block_count: number;
  review_count: number;
  risk_level_distribution: Record<string, number>;
  avg_risk_score: number | null;
  high_risk_count: number;
  window_days: number;
}

export interface RiskTransactionItem {
  transaction_id: string;
  agent_id: string;
  transaction_type: string;
  amount: number;
  currency: string;
  status: string;
  decision: string;
  risk_level: string | null;
  risk_score: number | null;
  decision_reason: string | null;
  created_at: string;
}

export interface RiskTransactionsResponse {
  transactions: RiskTransactionItem[];
  total: number;
}

export async function getRiskSummary(
  windowDays: number = 30,
): Promise<RiskSummaryResponse> {
  return apiGet<RiskSummaryResponse>(
    `/risk-intelligence/summary?window_days=${windowDays}`,
  );
}

export async function getRiskTransactions(
  limit: number = 50,
  offset: number = 0,
): Promise<RiskTransactionsResponse> {
  return apiGet<RiskTransactionsResponse>(
    `/risk-intelligence/transactions?limit=${limit}&offset=${offset}`,
  );
}
