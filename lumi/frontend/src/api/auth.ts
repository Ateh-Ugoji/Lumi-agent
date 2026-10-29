import { request, writeToken, clearToken } from "./http.ts";

export type User = { id: number; email: string; display_name: string };

type AuthResponse = { token: string; user: User };

export async function login(email: string, password: string): Promise<User> {
  const res = await request<AuthResponse>("/auth/login", {
    method: "POST",
    body: { email, password, device_name: "web" },
    auth: false,
  });
  writeToken(res.token);
  return res.user;
}

export async function register(
  email: string,
  password: string,
  displayName: string,
): Promise<User> {
  const res = await request<AuthResponse>("/auth/register", {
    method: "POST",
    body: { email, password, ...(displayName.trim() ? { display_name: displayName.trim() } : {}) },
    auth: false,
  });
  writeToken(res.token);
  return res.user;
}

export async function fetchMe(): Promise<User> {
  return request<User>("/auth/me");
}

/** Revokes the key on the server (best effort) and always forgets it locally. */
export async function logout(): Promise<void> {
  try {
    await request<void>("/auth/logout", { method: "POST" });
  } catch {
    // an expired key is already gone; the local copy goes either way
  } finally {
    clearToken();
  }
}
