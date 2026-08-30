/**
 * Authentication API client for Transaction Twin backend.
 *
 * Provides login and signup functions that return JWT tokens.
 */

import { apiPost } from "./api";

export interface AuthResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  display_name: string;
}

export interface SignupRequest {
  email: string;
  password: string;
  display_name: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export async function login(email: string, password: string): Promise<AuthResponse> {
  return apiPost<AuthResponse>("/auth/login", { email, password });
}

export async function signup(
  email: string,
  password: string,
  displayName: string,
): Promise<AuthResponse> {
  return apiPost<AuthResponse>("/auth/signup", {
    email,
    password,
    display_name: displayName,
  });
}
