/**
 * Transactions API client.
 *
 * All calls go through /api/v1/transactions/*.
 */

import { apiGet } from "./api";
import type {
  TransactionListResponse,
  TransactionDetailResponse,
} from "@/types/api";

export async function listTransactions(
  limit: number = 100,
  offset: number = 0,
): Promise<TransactionListResponse> {
  return apiGet<TransactionListResponse>(
    `/transactions?limit=${limit}&offset=${offset}`,
  );
}

export async function getTransaction(
  transactionId: string,
): Promise<TransactionDetailResponse> {
  return apiGet<TransactionDetailResponse>(
    `/transactions/${transactionId}`,
  );
}
