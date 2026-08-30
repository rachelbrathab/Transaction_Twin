/**
 * API client configuration for Transaction Twin backend.
 *
 * All API calls go through /api/v1/* prefix.
 * Authentication is handled via JWT Bearer tokens stored in localStorage.
 * Never exposes secrets to the client — backend handles all sensitive operations.
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const API_V1_PREFIX = "/api/v1";
const TOKEN_KEY = "tt_access_token";

interface ApiError {
  error: {
    code: string;
    message: string;
  };
}

interface RequestOptions extends Omit<RequestInit, "body" | "method"> {
  body?: unknown;
  method?: string;
}

// ── Token management ──────────────────────────────────────────────

export function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function setStoredToken(token: string): void {
  if (typeof window === "undefined") return;
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearStoredToken(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(TOKEN_KEY);
}

export function isAuthenticated(): boolean {
  return getStoredToken() !== null;
}

// ── API request functions ─────────────────────────────────────────

export async function apiGet<T>(path: string, options?: RequestOptions): Promise<T> {
  return apiRequest<T>(path, { ...options, method: "GET" });
}

export async function apiPost<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
  return apiRequest<T>(path, {
    ...options,
    method: "POST",
    body: body ? JSON.stringify(body) : undefined,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
}

async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const url = `${API_BASE_URL}${API_V1_PREFIX}${path}`;

  const { body: reqBody, headers: reqHeaders, ...restOptions } = options;

  // Attach JWT token if available
  const token = getStoredToken();
  const authHeaders: Record<string, string> = {};
  if (token) {
    authHeaders["Authorization"] = `Bearer ${token}`;
  }

  const response = await fetch(url, {
    ...restOptions,
    headers: {
      Accept: "application/json",
      ...authHeaders,
      ...reqHeaders,
    },
    body: typeof reqBody === "string" ? reqBody : undefined,
  });

  // Handle 401 — clear token and redirect to login
  if (response.status === 401) {
    clearStoredToken();
    // Use a soft redirect via location to handle both server and client contexts
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.replace("/login");
    }
    throw new ApiRequestError("UNAUTHORIZED", "Authentication required", 401);
  }

  if (!response.ok) {
    let errorBody: ApiError;
    try {
      errorBody = await response.json();
    } catch {
      errorBody = {
        error: { code: "NETWORK_ERROR", message: "Failed to reach the server" },
      };
    }
    throw new ApiRequestError(errorBody.error.code, errorBody.error.message, response.status);
  }

  return response.json() as Promise<T>;
}

export class ApiRequestError extends Error {
  code: string;
  statusCode: number;

  constructor(code: string, message: string, statusCode: number) {
    super(message);
    this.name = "ApiRequestError";
    this.code = code;
    this.statusCode = statusCode;
  }
}
