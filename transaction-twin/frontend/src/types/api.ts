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
