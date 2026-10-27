/**
 * The one HTTP client of the app. Every call to the Django backend goes through `request` or
 * `openStream`: they add the base URL, the `Authorization: Token` header, turn the
 * `{"error": {"code", "message", "details"}}` body into an `ApiError` and, on a 401, clear the
 * token and tell the app to go back to the login screen.
 */

type Env = { VITE_API_BASE?: string };

const env: Env = (import.meta as unknown as { env?: Env }).env ?? {};

export const DEFAULT_API_BASE = "http://localhost:8000/api/v1";
export const API_BASE: string = (env.VITE_API_BASE || DEFAULT_API_BASE).replace(/\/+$/, "");

const TOKEN_KEY = "lumi_token";

/** Minimal storage surface, so tests can inject a plain object. */
export type KeyValueStore = {
  getItem(key: string): string | null;
  setItem(key: string, value: string): void;
  removeItem(key: string): void;
};

function browserStore(): KeyValueStore | null {
  try {
    return typeof localStorage === "undefined" ? null : localStorage;
  } catch {
    return null;
  }
}

export function readToken(store: KeyValueStore | null = browserStore()): string | null {
  try {
    return store?.getItem(TOKEN_KEY) || null;
  } catch {
    return null;
  }
}

export function writeToken(token: string, store: KeyValueStore | null = browserStore()): void {
  if (!store) {
    memoryToken = token;
    return;
  }
  try {
    store.setItem(TOKEN_KEY, token);
  } catch {
    // storage blocked: the session lasts until the page closes
    memoryToken = token;
  }
}

export function clearToken(store: KeyValueStore | null = browserStore()): void {
  memoryToken = null;
  try {
    store?.removeItem(TOKEN_KEY);
  } catch {
    // nothing to clear
  }
}

let memoryToken: string | null = null;

export function currentToken(): string | null {
  return readToken() ?? memoryToken;
}

/** A failed API call. `code` is the stable machine code; `message` is for display. */
export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly details: Record<string, unknown>;

  constructor(
    status: number,
    code: string,
    message: string,
    details: Record<string, unknown> = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

/** What the user reads when a failed response carries no usable message (an HTML error page, say). */
export function statusMessage(status: number): string {
  if (status === 502 || status === 503 || status === 504) {
    return "El servidor de Lumi no está respondiendo. Inténtalo de nuevo en un momento.";
  }
  if (status >= 500) {
    return "El servidor de Lumi tuvo un problema. Inténtalo de nuevo en un momento.";
  }
  return `Error ${status}`;
}

/** Build an `ApiError` from a response status and its (already read) body text. */
export function errorFromBody(status: number, bodyText: string): ApiError {
  let code = status === 401 ? "unauthenticated" : "http_error";
  let message = statusMessage(status);
  let details: Record<string, unknown> = {};
  try {
    const parsed = JSON.parse(bodyText) as {
      error?: { code?: unknown; message?: unknown; details?: unknown };
    };
    const err = parsed?.error;
    if (err && typeof err === "object") {
      if (typeof err.code === "string") code = err.code;
      if (typeof err.message === "string" && err.message) message = err.message;
      if (err.details && typeof err.details === "object") {
        details = err.details as Record<string, unknown>;
      }
    }
  } catch {
    // not JSON (a proxy page, a network layer): keep the generic message
  }
  return new ApiError(status, code, message, details);
}

export function buildUrl(
  path: string,
  query?: Record<string, string | number | boolean | null | undefined>,
  base: string = API_BASE,
): string {
  const url = `${base}${path.startsWith("/") ? path : `/${path}`}`;
  if (!query) return url;
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(query)) {
    if (value === undefined || value === null || value === "") continue;
    params.set(key, String(value));
  }
  const qs = params.toString();
  return qs ? `${url}?${qs}` : url;
}

type Listener = () => void;
const unauthorizedListeners = new Set<Listener>();

/** Called once when a request comes back 401 (the token is already cleared). */
export function onUnauthorized(listener: Listener): () => void {
  unauthorizedListeners.add(listener);
  return () => unauthorizedListeners.delete(listener);
}

function handleUnauthorized(): void {
  clearToken();
  for (const listener of [...unauthorizedListeners]) listener();
}

export type RequestOptions = {
  method?: "GET" | "POST" | "PUT" | "DELETE";
  query?: Record<string, string | number | boolean | null | undefined>;
  body?: unknown;
  form?: FormData;
  headers?: Record<string, string>;
  signal?: AbortSignal;
  /** Public routes (login, register) send no token and never trigger the 401 handler. */
  auth?: boolean;
};

function buildInit(opts: RequestOptions, accept: string): RequestInit {
  const headers: Record<string, string> = { Accept: accept, ...opts.headers };
  if (opts.auth !== false) {
    const token = currentToken();
    if (token) headers.Authorization = `Token ${token}`;
  }
  let body: BodyInit | undefined;
  if (opts.form) {
    body = opts.form;
  } else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  return { method: opts.method ?? "GET", headers, body, signal: opts.signal };
}

async function send(path: string, opts: RequestOptions, accept: string): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(buildUrl(path, opts.query), buildInit(opts, accept));
  } catch (err) {
    if (opts.signal?.aborted) throw err;
    throw new ApiError(
      0,
      "network_error",
      "No se pudo contactar con el servidor de Lumi. Revisa que esté en marcha.",
    );
  }
  if (!res.ok) {
    const error = errorFromBody(res.status, await res.text());
    if (res.status === 401 && opts.auth !== false) handleUnauthorized();
    throw error;
  }
  return res;
}

/** JSON request. A 204 or an empty body resolves to `undefined`. */
export async function request<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const res = await send(path, opts, "application/json");
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

/** Open a response stream (server-sent events). The caller reads `response.body`. */
export async function openStream(path: string, opts: RequestOptions = {}): Promise<Response> {
  // The chat view accepts a lone `text/event-stream` (`EventStreamRenderer`) and still sends its
  // errors as JSON, so the header asks for nothing else.
  const res = await send(path, opts, "text/event-stream");
  if (!res.body) throw new ApiError(res.status, "stream_error", "El servidor no envió datos.");
  return res;
}

export function errorMessage(err: unknown, fallback = "Algo salió mal."): string {
  if (err instanceof ApiError) return err.message;
  if (err instanceof Error && err.message) return err.message;
  return fallback;
}
