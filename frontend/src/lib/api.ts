/**
 * API client configuration for Transaction Twin backend.
 *
 * All API calls go through /api/v1/* prefix.
 * Authentication is handled via JWT Bearer tokens stored in memory
 * and refresh tokens stored as HttpOnly cookies.
 * Never exposes secrets to the client — backend handles all sensitive operations.
 */

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const API_V1_PREFIX = "/api/v1";

interface ApiError {
  error?: {
    code: string;
    message: string;
  };
  detail?: string | Array<{ msg?: string; message?: string; type?: string; loc?: (string | number)[] }>;
}

interface RequestOptions extends Omit<RequestInit, "body" | "method"> {
  body?: unknown;
  method?: string;
}

// ── Token management ──────────────────────────────────────────────

// Access tokens are stored in memory (not localStorage) for XSS safety.
// Refresh tokens are HttpOnly cookies — invisible to JavaScript.
let _accessToken: string | null = null;

export function getStoredToken(): string | null {
  return _accessToken;
}

export function setStoredToken(token: string): void {
  _accessToken = token;
}

export function clearStoredToken(): void {
  _accessToken = null;
}

export function isAuthenticated(): boolean {
  return _accessToken !== null;
}

// ── Logout ───────────────────────────────────────────────────────

export async function logout(): Promise<void> {
  // Call the backend to revoke the refresh token and clear the cookie.
  // Always clear the in-memory access token regardless of backend response.
  try {
    const url = `${API_BASE_URL}${API_V1_PREFIX}/auth/logout`;
    await fetch(url, {
      method: "POST",
      credentials: "include", // Send HttpOnly refresh token cookie
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
    });
  } catch {
    // Backend unavailable — token still cleared below
  } finally {
    clearStoredToken();
  }
}

// Prevent infinite refresh loops
let _isRefreshing = false;
let _refreshPromise: Promise<boolean> | null = null;

// ── Token refresh ─────────────────────────────────────────────────

async function tryRefreshToken(): Promise<boolean> {
  // If already refreshing, wait for the existing refresh
  if (_isRefreshing && _refreshPromise) {
    return _refreshPromise;
  }

  _isRefreshing = true;
  _refreshPromise = _doRefresh();

  try {
    return await _refreshPromise;
  } finally {
    _isRefreshing = false;
    _refreshPromise = null;
  }
}

async function _doRefresh(): Promise<boolean> {
  try {
    const url = `${API_BASE_URL}${API_V1_PREFIX}/auth/refresh`;
    const response = await fetch(url, {
      method: "POST",
      credentials: "include", // Send HttpOnly refresh token cookie
      headers: {
        Accept: "application/json",
        "Content-Type": "application/json",
      },
    });

    if (response.ok) {
      const data = await response.json();
      if (data.access_token) {
        setStoredToken(data.access_token);
        return true;
      }
    }

    // Refresh failed — clear token and redirect to login
    clearStoredToken();
    return false;
  } catch {
    clearStoredToken();
    return false;
  }
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

export async function apiPut<T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> {
  return apiRequest<T>(path, {
    ...options,
    method: "PUT",
    body: body ? JSON.stringify(body) : undefined,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
}

export async function apiDelete<T>(path: string, options?: RequestOptions): Promise<T> {
  return apiRequest<T>(path, { ...options, method: "DELETE" });
}

async function apiRequest<T>(path: string, options: RequestOptions = {}): Promise<T> {
  return _apiRequestWithRetry<T>(path, options, false);
}

async function _apiRequestWithRetry<T>(
  path: string,
  options: RequestOptions,
  isRetry: boolean,
): Promise<T> {
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
    credentials: "include", // Always send cookies (for refresh token)
    headers: {
      Accept: "application/json",
      ...authHeaders,
      ...reqHeaders,
    },
    body: typeof reqBody === "string" ? reqBody : undefined,
  });

  // Handle 401 — try refresh token flow (once)
  if (response.status === 401 && !isRetry && path !== "/auth/refresh") {
    const refreshed = await tryRefreshToken();
    if (refreshed) {
      // Retry the original request with the new access token
      return _apiRequestWithRetry<T>(path, options, true);
    }
    // Refresh failed — redirect to login
    clearStoredToken();
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      window.location.replace("/login");
    }
    throw new ApiRequestError("UNAUTHORIZED", "Authentication required", 401);
  }

  if (!response.ok) {
    let code = "UNKNOWN_ERROR";
    let message = "An error occurred";
    try {
      const errorBody: ApiError = await response.json();
      // Handle our custom error format: { error: { code, message } }
      if (errorBody.error?.code && errorBody.error?.message) {
        code = errorBody.error.code;
        message = errorBody.error.message;
      }
      // Handle FastAPI HTTPException format: { detail: "..." }
      else if (typeof errorBody.detail === "string") {
        code = response.status === 409 ? "CONFLICT" : response.status === 429 ? "RATE_LIMIT" : `HTTP_${response.status}`;
        message = errorBody.detail;
      }
      // Handle FastAPI validation error format: { detail: [...] }
      else if (Array.isArray(errorBody.detail) && errorBody.detail.length > 0) {
        code = "VALIDATION_ERROR";
        message = errorBody.detail
          .map((e) => e.msg || e.message || String(e))
          .join("; ");
      }
    } catch {
      code = "NETWORK_ERROR";
      message = "Failed to reach the server";
    }
    throw new ApiRequestError(code, message, response.status);
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
