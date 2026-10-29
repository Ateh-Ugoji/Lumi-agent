import { ApiError, request } from "./http.ts";
import { t } from "../i18n/index.ts";

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
    throw new ApiError(502, "upstream_error", t("conn.no_link"));
  }
  return res.authorize_url;
}

export type LinkResult = {
  provider: Provider;
  profile_id: number;
  account: ConnectedAccount;
  replaced_account_id: string | null;
  moved_from_profile_id: number | null;
};

/**
 * Choose which connected account publishes for a profile (a Meta login can hold many Pages).
 * Repeating the call changes nothing. Linking another account replaces the previous one, which
 * stays connected.
 */
export function linkAccount(
  provider: Provider,
  accountId: string,
  profileId: number,
): Promise<LinkResult> {
  return request<LinkResult>(`/connections/${provider}/link`, {
    method: "POST",
    body: { account_id: accountId, profile_id: profileId },
  });
}

/** What the panel offers for one account next to the active profile. */
export type LinkChoice = "linked" | "available" | "other_network" | "reconnect";

export function linkChoice(
  account: Pick<ConnectedAccount, "platform" | "status" | "profile_id">,
  profile: { id: number; platform: string },
): LinkChoice {
  if (account.status === "revoked" || account.status === "error") return "reconnect";
  if (account.profile_id === profile.id) return "linked";
  // An account with no platform links to any profile, like the server does.
  if (account.platform && account.platform !== profile.platform) return "other_network";
  return "available";
}

const LINK_ERROR_KEYS: Record<string, string> = {
  "connections.account_unusable": "conn.need_reconnect",
  "connections.platform_mismatch": "conn.wrong_network",
  not_found: "conn.gone",
};

export function linkErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    const key = LINK_ERROR_KEYS[err.code];
    if (key) return t(key);
    return err.message;
  }
  return t("conn.link_failed");
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
  | { kind: "error"; code: string; provider?: string };

/** Codes whose message is looked up in the dictionary; two map to a `conn.*` key. */
const RETURN_ERROR_KEYS: Record<string, string> = {
  "connections.state_invalid": "connections.state_invalid",
  "connections.state_expired": "connections.state_expired",
  "connections.state_mismatch": "connections.state_mismatch",
  "connections.access_denied": "connections.access_denied",
  "connections.account_taken": "connections.account_taken",
  "connections.no_accounts": "connections.no_accounts",
  "connections.pfm_failed": "connections.pfm_failed",
  "connections.provider_rejected": "connections.provider_rejected",
  "connections.unknown_provider": "connections.unknown_provider",
  upstream_error: "conn.upstream_no_response",
  internal_error: "conn.server_error",
};

/** Facebook lists Pages only, so a personal profile finishes the login and then has nothing to store. */
const NO_ACCOUNTS_BY_PROVIDER: Record<string, string> = {
  meta: "conn.meta_no_pages",
};

export function connectErrorMessage(code: string, provider?: string): string {
  if (provider && (code === "connections.no_accounts" || code === "no_accounts")) {
    const specific = NO_ACCOUNTS_BY_PROVIDER[provider];
    if (specific) return t(specific);
  }
  // CONTRATOS lists the codes bare; the callback sends most of them as `connections.<code>`.
  const key = RETURN_ERROR_KEYS[code] ?? RETURN_ERROR_KEYS[`connections.${code}`];
  return key ? t(key) : t("conn.connect_failed");
}

/** A message for a failed `startConnect`, naming the missing variables when there are any. */
export function startConnectMessage(err: unknown): string {
  if (!(err instanceof ApiError)) return t("conn.start_failed");
  if (err.code === "not_configured") {
    const vars = err.details.env_vars;
    const list = Array.isArray(vars) ? vars.filter((v) => typeof v === "string").join(", ") : "";
    return list ? t("conn.server_missing", { vars: list }) : t("conn.not_configured");
  }
  if (err.code === "connections.live_disabled") {
    return t("conn.x_off_setup");
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
