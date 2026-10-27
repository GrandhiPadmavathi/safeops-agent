import type { Session } from "./types";

export class AuthExpired extends Error {}

type Options = { token?: string; body?: unknown; form?: Record<string, string> };

export async function api<T>(path: string, { token, body, form }: Options = {}): Promise<T> {
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  let payload: BodyInit | undefined;
  if (form) {
    headers["Content-Type"] = "application/x-www-form-urlencoded";
    payload = new URLSearchParams(form);
  } else if (body !== undefined) {
    headers["Content-Type"] = "application/json";
    payload = JSON.stringify(body);
  }
  const res = await fetch(`/api${path}`, { method: payload === undefined ? "GET" : "POST", headers, body: payload });
  const text = await res.text();
  let data: unknown = null;
  try {
    data = text ? JSON.parse(text) : null;
  } catch {
    if (res.ok) throw new Error(`Unexpected response from ${path}`);
  }
  if (!res.ok) {
    const detail = (data as { detail?: unknown } | null)?.detail;
    const message = `${res.status} ${typeof detail === "string" ? detail : res.statusText}`;
    if (res.status === 401 && token) throw new AuthExpired(message);
    throw new Error(message);
  }
  return data as T;
}

export async function signIn(username: string, password: string): Promise<Session> {
  const res = await api<{ access_token: string; user: Session["user"] }>("/auth/token", {
    form: { username, password },
  });
  return { token: res.access_token, user: res.user };
}
