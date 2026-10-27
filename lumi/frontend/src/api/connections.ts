import { ApiError, request } from "./http.ts";

export type Provider = "meta" | "linkedin" | "x" | "pfm" | "google";

export type ConnectedAccount = {
  id: string;
  platform: string | null;
  display_name: string | null;
  handle: string | null;
  status: string;
  profile_id: number | null;
  scopes?: string[] | string | null;
  expires_at?: string | null;
  last_refreshed_at?: string | null;
  last_error?: string | null;
};

export type ConnectionStatus = {
  provider: Provider;
  configured: boolean;
  connected: boolean;
  stale: boolean;
  accounts: ConnectedAccount[];
  /** Provider data that is not an account. Google: scopes, expires_at, has_refresh_token. */
  details?: {
    scopes?: string | string[] | null;
    expires_at?: string | null;
    has_refresh_token?: boolean;
  };
};

export const PFM_PLATFORMS = ["x", "linkedin", "facebook", "instagram", "tiktok"] as const;

/** Read what the server stores. It never calls the provider and never writes. */
export function getConnectionStatus(provider: Provider): Promise<ConnectionStatus> {
  return request<ConnectionStatus>(`/connections/${provider}/status`);
}

/**
 * Ask the server to read this user's accounts from Post for Me and store them. Post for Me sends
 * no `state`, so this call is how the accounts reach Lumi. It is a POST because it writes, and
 * the server limits how often it can run.
 */
export function syncPfm(): Promise<ConnectionStatus> {
  return request<ConnectionStatus>("/connections/pfm/sync", { method: "POST" });
}

/**
 * Ask the server for the provider's authorization URL. The browser cannot send the token on a
 * plain navigation, so this is a `fetch`; the caller then sets `window.location`.
 */
export async function startConnect(
  provider: Provider,
  opts: { profileId?: number | null; platform?: string; redirectAfter?: string } = {},
): Promise<string> {
  const res = await request<{ authorize_url?: string }>(`/connections/${provider}/connect`, {
    method: "POST",
    body: {
      ...(opts.profileId ? { profile_id: opts.profileId } : {}),
      ...(opts.platform ? { platform: opts.platform } : {}),
      ...(opts.redirectAfter ? { redirect_after: opts.redirectAfter } : {}),
    },
  });
  if (!res.authorize_url) {
    throw new ApiError(502, "upstream_error", "El servidor no devolvió un enlace de conexión.");
  }
  return res.authorize_url;
}

export function disconnect(
  provider: Provider,
  accountId?: string,
): Promise<{ provider: string; disconnected: number; remote_revoked: number }> {
  return request(`/connections/${provider}`, {
    method: "DELETE",
    query: { account_id: accountId },
  });
}

/**
 * What the provider left in the URL of the frontend callback page
 * (`/connections/<provider>/callback`). The provider redirects the browser here, and this page
 * finishes the grant with the user's own Token. The server accepts a `state` only from the user
 * who started it, so a link someone else crafted connects nothing.
 */
export type CallbackLanding =
  | { kind: "grant"; provider: Provider; state: string; code: string }
  | { kind: "denied"; provider: Provider; state: string; error: string }
  | { kind: "pfm"; success: boolean };

const GRANT_PROVIDERS: readonly string[] = ["meta", "linkedin", "x", "google"];
const CALLBACK_PATH = /^\/connections\/([a-z]+)\/callback\/?$/;

export function parseCallbackLanding(pathname: string, search: string): CallbackLanding | null {
  const match = CALLBACK_PATH.exec(pathname);
  if (!match) return null;
  const provider = match[1];
  const params = new URLSearchParams(search);
  if (provider === "pfm") {
    // Post for Me sends no state: the grant was bound to the user when the link was minted.
    return { kind: "pfm", success: params.get("isSuccess") === "true" };
  }
  if (!GRANT_PROVIDERS.includes(provider)) return null;
  const state = params.get("state");
  if (!state) return null;
  const error = params.get("error");
  if (error) return { kind: "denied", provider: provider as Provider, state, error: error.slice(0, 80) };
  const code = params.get("code");
  if (!code) return null;
  return { kind: "grant", provider: provider as Provider, state, code };
}

/** Where the browser goes once the landing is handled: no code, no state, no way to replay it. */
export const CALLBACK_DONE_URL = "/";

export type ConnectResult = { provider: string; connected: boolean };

/** Finish the grant. Every outcome is an `ApiError` code the panel can explain. */
export async function finishConnect(landing: CallbackLanding): Promise<ConnectResult> {
  if (landing.kind === "pfm") {
    if (!landing.success) throw new ApiError(400, "connections.pfm_failed", "pfm");
    // The sync call reads the accounts Post for Me now holds for this user and stores them.
    const status = await syncPfm();
    return { provider: "pfm", connected: status.connected };
  }
  const body =
    landing.kind === "grant"
      ? { state: landing.state, code: landing.code }
      : { state: landing.state, error: landing.error };
  return request<ConnectResult>(`/connections/${landing.provider}/callback`, {
    method: "POST",
    body,
  });
}

/** What the page shows once the landing is handled. */
export type ConnectReturn =
  | { kind: "connected"; provider: string }
  | { kind: "error"; code: string };

const RETURN_ERRORS: Record<string, string> = {
  "connections.state_invalid": "El enlace de conexión no es válido. Empieza de nuevo.",
  "connections.state_expired": "El enlace de conexión caducó. Empieza de nuevo.",
  "connections.state_mismatch":
    "Este enlace de conexión lo inició otra cuenta de Lumi. No se conectó nada.",
  "connections.access_denied": "Cancelaste la autorización. No se conectó nada.",
  "connections.account_taken": "Esa cuenta ya está conectada a otro usuario de Lumi.",
  "connections.no_accounts": "La autorización no incluyó ninguna cuenta.",
  "connections.pfm_failed": "Post for Me no confirmó la cuenta. Inténtalo otra vez.",
  "connections.provider_rejected": "El proveedor rechazó la conexión.",
  "connections.unknown_provider": "Proveedor desconocido.",
  upstream_error: "El proveedor no respondió. Inténtalo en unos minutos.",
  internal_error: "Algo falló en el servidor. Inténtalo otra vez.",
};

export function connectErrorMessage(code: string): string {
  // CONTRATOS lists the codes bare; the callback sends most of them as `connections.<code>`.
  return RETURN_ERRORS[code] ?? RETURN_ERRORS[`connections.${code}`] ?? "No se pudo conectar la cuenta.";
}

/** A message for a failed `startConnect`, naming the missing variables when there are any. */
export function startConnectMessage(err: unknown): string {
  if (!(err instanceof ApiError)) return "No se pudo iniciar la conexión.";
  if (err.code === "not_configured") {
    const vars = err.details.env_vars;
    const list = Array.isArray(vars) ? vars.filter((v) => typeof v === "string").join(", ") : "";
    return list
      ? `Falta configurar el servidor: ${list}.`
      : "Este proveedor no está configurado en el servidor.";
  }
  if (err.code === "connections.live_disabled") {
    return "X está apagado: no se hacen llamadas hasta que se active X_LIVE_ENABLED.";
  }
  return err.message;
}

export function isLiveDisabled(err: unknown): boolean {
  return err instanceof ApiError && err.code === "connections.live_disabled";
}

export const PROVIDER_LABELS: Record<Provider, string> = {
  meta: "Facebook",
  linkedin: "LinkedIn",
  x: "X",
  pfm: "Post for Me",
  google: "Google Drive y Docs",
};

const GOOGLE_SCOPE_LABELS: Record<string, string> = {
  "https://www.googleapis.com/auth/drive.readonly": "Leer archivos de Drive",
  "https://www.googleapis.com/auth/drive.file": "Crear y editar los archivos que crea Lumi",
  "https://www.googleapis.com/auth/documents": "Crear y editar Google Docs",
};

export function scopeList(scopes: string | string[] | null | undefined): string[] {
  const raw = Array.isArray(scopes) ? scopes : (scopes || "").split(/[\s,]+/);
  return raw.filter(Boolean);
}

export function googleScopeLabels(scopes: string | string[] | null | undefined): string[] {
  return scopeList(scopes).map((scope) => GOOGLE_SCOPE_LABELS[scope] ?? scope);
}
