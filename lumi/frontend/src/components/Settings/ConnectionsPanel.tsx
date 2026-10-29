import { useCallback, useEffect, useState } from "react";
import {
  PFM_PLATFORMS,
  PROVIDER_LABELS,
  connectErrorMessage,
  disconnect,
  errorMessage,
  getConnectionStatus,
  googleScopeLabels,
  isLiveDisabled,
  linkAccount,
  linkChoice,
  linkErrorMessage,
  startConnect,
  startConnectMessage,
  syncPfm,
  type ConnectReturn,
  type ConnectionStatus,
  type LinkChoice,
  type Provider,
  type ProfileSummary,
} from "../../api";
import { useT } from "../../i18n/index.ts";
import styles from "./Settings.module.css";

/** Message keys, resolved with `t` at render so the language switch applies. */
const HINTS: Record<Provider, string> = {
  meta: "panel.hint.meta",
  linkedin: "panel.hint.linkedin",
  x: "panel.hint.x",
  pfm: "panel.hint.pfm",
  google: "panel.hint.google",
};

type Card = {
  status: ConnectionStatus | null;
  loading: boolean;
  error: string | null;
  note: string | null;
  busy: boolean;
};

const EMPTY: Card = { status: null, loading: true, error: null, note: null, busy: false };

const formatExpiry = (iso: string): string => {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
};

export default function ConnectionsPanel({
  providers,
  profileId,
  profile = null,
  returned,
  onDismissReturn,
  onChanged,
}: {
  providers: Provider[];
  profileId: number | null;
  /** The active profile. With it, each account can be chosen as the one that publishes for it. */
  profile?: ProfileSummary | null;
  returned: ConnectReturn | null;
  onDismissReturn: () => void;
  onChanged?: () => void;
}) {
  const t = useT();
  const [cards, setCards] = useState<Partial<Record<Provider, Card>>>({});
  const [pfmPlatform, setPfmPlatform] = useState<string>("x");

  const patch = useCallback((provider: Provider, change: Partial<Card>) => {
    setCards((prev) => ({ ...prev, [provider]: { ...(prev[provider] ?? EMPTY), ...change } }));
  }, []);

  const load = useCallback(
    async (provider: Provider) => {
      patch(provider, { loading: true, error: null });
      try {
        patch(provider, { status: await getConnectionStatus(provider), loading: false });
      } catch (err) {
        patch(provider, { loading: false, error: errorMessage(err, t("panel.state_failed")) });
      }
    },
    [patch],
  );

  // Reading a status never calls the provider. Post for Me accounts are stored by the sync that
  // the callback page runs, or by "Actualizar".
  const providerKey = providers.join(",");
  useEffect(() => {
    for (const provider of providers) void load(provider);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providerKey, load]);

  // The grant is finished after the page loads (the frontend posts it with the user's Token), so
  // the status read at mount may predate it. Read it again once the return banner says connected.
  useEffect(() => {
    if (returned?.kind !== "connected") return;
    const provider = returned.provider as Provider;
    if (providers.includes(provider)) {
      void load(provider);
      onChanged?.();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [returned]);

  const refresh = async (provider: Provider) => {
    if (provider !== "pfm") return load(provider);
    patch(provider, { loading: true, error: null });
    try {
      patch(provider, { status: await syncPfm(), loading: false });
      onChanged?.();
    } catch (err) {
      patch(provider, { loading: false, error: errorMessage(err, t("panel.refresh_failed")) });
    }
  };

  const connect = async (provider: Provider) => {
    patch(provider, { busy: true, error: null, note: null });
    try {
      const url = await startConnect(provider, {
        profileId: provider === "google" ? null : profileId,
        platform: provider === "pfm" ? pfmPlatform : undefined,
        redirectAfter: "/",
      });
      window.location.assign(url);
    } catch (err) {
      patch(provider, {
        busy: false,
        ...(isLiveDisabled(err)
          ? { note: startConnectMessage(err) }
          : { error: startConnectMessage(err) }),
      });
    }
  };

  const link = async (provider: Provider, accountId: string) => {
    if (!profile) return;
    patch(provider, { busy: true, error: null, note: null });
    try {
      const done = await linkAccount(provider, accountId, profile.id);
      patch(provider, {
        busy: false,
        note: done.replaced_account_id
          ? t("panel.linked_now", { handle: profile.handle })
          : t("panel.will_publish", { handle: profile.handle }),
      });
      await load(provider);
      onChanged?.();
    } catch (err) {
      patch(provider, { busy: false, error: linkErrorMessage(err) });
    }
  };

  const remove = async (provider: Provider, accountId?: string) => {
    patch(provider, { busy: true, error: null });
    try {
      await disconnect(provider, accountId);
      patch(provider, { busy: false });
      await load(provider);
      onChanged?.();
    } catch (err) {
      patch(provider, { busy: false, error: errorMessage(err, t("panel.disconnect_failed")) });
    }
  };

  return (
    <>
      {returned && (
        <div
          role={returned.kind === "error" ? "alert" : "status"}
          className={returned.kind === "error" ? styles.bannerError : styles.bannerOk}
          data-testid="connect-return"
        >
          <span>
            {returned.kind === "error"
              ? connectErrorMessage(returned.code, returned.provider)
              : t("panel.connected_msg", {
                  provider:
                    PROVIDER_LABELS[returned.provider as Provider] ?? returned.provider,
                })}
          </span>
          <button type="button" className={styles.textBtn} onClick={onDismissReturn}>
            {t("panel.close")}
          </button>
        </div>
      )}
      {providers.map((provider) => {
        const card = cards[provider] ?? EMPTY;
        const status = card.status;
        const accounts = status?.accounts ?? [];
        return (
          <section
            key={provider}
            className={styles.card}
            data-testid={`provider-${provider}`}
            aria-label={PROVIDER_LABELS[provider]}
          >
            <div className={styles.cardHead}>
              <div>
                <div className={styles.cardTitle}>{PROVIDER_LABELS[provider]}</div>
                <p className={styles.cardHint}>{t(HINTS[provider])}</p>
              </div>
              <span
                className={status?.connected ? styles.chipOn : styles.chipOff}
                data-testid={`status-${provider}`}
              >
                {card.loading
                  ? t("panel.checking")
                  : status?.connected
                    ? status.stale
                      ? t("panel.reconnect")
                      : t("panel.connected")
                    : t("panel.not_connected")}
              </span>
            </div>

            {status && !status.configured && (
              <p className={styles.noteText}>{t("panel.no_keys")}</p>
            )}
            {card.note && (
              <p className={styles.noteText} data-testid={`note-${provider}`}>
                {card.note}
              </p>
            )}
            {card.error && (
              <p role="alert" className={styles.errorText}>
                {card.error}
              </p>
            )}

            {provider === "google" && status?.connected && (
              <div className={styles.scopeList}>
                {googleScopeLabels(status.details?.scopes).map((label) => (
                  <div key={label}>· {label}</div>
                ))}
                {status.details?.expires_at && (
                  <div className={styles.mutedText}>
                    {t("panel.expires", { date: formatExpiry(status.details.expires_at) })}
                  </div>
                )}
              </div>
            )}

            {provider !== "google" && accounts.length > 0 && (
              <ul className={styles.accountList}>
                {accounts.map((account) => (
                  <li key={account.id} className={styles.accountRow}>
                    <span>
                      <strong>{account.display_name || account.handle || account.id}</strong>
                      {account.handle && account.display_name ? ` @${account.handle}` : ""}
                      {account.platform ? ` · ${account.platform}` : ""}
                      {account.status !== "active" ? ` · ${account.status}` : ""}
                    </span>
                    <span className={styles.cardActions}>
                      {profile && (
                        <LinkControl
                          choice={linkChoice(account, profile)}
                          handle={profile.handle}
                          busy={card.busy}
                          testId={`link-${provider}-${account.id}`}
                          onLink={() => void link(provider, account.id)}
                        />
                      )}
                      <button
                        type="button"
                        className={styles.textBtn}
                        disabled={card.busy}
                        onClick={() => void remove(provider, account.id)}
                      >
                        {t("panel.disconnect")}
                      </button>
                    </span>
                  </li>
                ))}
              </ul>
            )}

            <div className={styles.cardActions}>
              {provider === "pfm" && (
                <select
                  className={styles.select}
                  aria-label={t("panel.select_network")}
                  value={pfmPlatform}
                  onChange={(e) => setPfmPlatform(e.target.value)}
                >
                  {PFM_PLATFORMS.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
              )}
              <button
                type="button"
                className={styles.btn}
                data-testid={`connect-${provider}`}
                disabled={card.busy || card.loading || status?.configured === false}
                onClick={() => void connect(provider)}
              >
                {status?.connected ? t("panel.connect_another") : t("panel.connect")}
              </button>
              {provider === "google" && status?.connected && (
                <button
                  type="button"
                  className={styles.textBtn}
                  disabled={card.busy}
                  onClick={() => void remove("google")}
                >
                  {t("panel.disconnect")}
                </button>
              )}
              <button
                type="button"
                className={styles.textBtn}
                data-testid={`refresh-${provider}`}
                disabled={card.busy || card.loading}
                onClick={() => void refresh(provider)}
              >
                {t("panel.refresh")}
              </button>
            </div>
          </section>
        );
      })}
    </>
  );
}

function LinkControl({
  choice,
  handle,
  busy,
  testId,
  onLink,
}: {
  choice: LinkChoice;
  handle: string;
  busy: boolean;
  testId: string;
  onLink: () => void;
}) {
  const t = useT();
  if (choice === "linked") {
    return (
      <span className={styles.chipOn} data-testid={`${testId}-linked`}>
        {t("panel.publishes_for", { handle })}
      </span>
    );
  }
  if (choice === "available") {
    return (
      <button
        type="button"
        className={styles.btn}
        data-testid={testId}
        disabled={busy}
        onClick={onLink}
      >
        {t("panel.use_for", { handle })}
      </button>
    );
  }
  return (
    <span className={styles.mutedText} data-testid={`${testId}-unavailable`}>
      {choice === "other_network" ? t("panel.wrong_network") : t("panel.reconnect_account")}
    </span>
  );
}
