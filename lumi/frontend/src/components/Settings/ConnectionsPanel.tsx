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
  startConnect,
  startConnectMessage,
  type ConnectReturn,
  type ConnectionStatus,
  type Provider,
} from "../../api";
import styles from "./Settings.module.css";

const HINTS: Record<Provider, string> = {
  meta: "Páginas de Facebook. Se usan para publicar.",
  linkedin: "Perfil de LinkedIn. Se usa para publicar.",
  x: "Lectura y publicación en X.",
  pfm: "Cuentas de redes sociales enlazadas con Post for Me.",
  google: "Un solo permiso de Google cubre leer Drive, los archivos que crea Lumi y Docs.",
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
  returned,
  onDismissReturn,
  onChanged,
}: {
  providers: Provider[];
  profileId: number | null;
  returned: ConnectReturn | null;
  onDismissReturn: () => void;
  onChanged?: () => void;
}) {
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
        patch(provider, { loading: false, error: errorMessage(err, "No se pudo leer el estado.") });
      }
    },
    [patch],
  );

  // Post for Me sync its accounts when its status is read, so the return from PFM needs this call.
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

  const remove = async (provider: Provider, accountId?: string) => {
    patch(provider, { busy: true, error: null });
    try {
      await disconnect(provider, accountId);
      patch(provider, { busy: false });
      await load(provider);
      onChanged?.();
    } catch (err) {
      patch(provider, { busy: false, error: errorMessage(err, "No se pudo desconectar.") });
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
              ? connectErrorMessage(returned.code)
              : `${PROVIDER_LABELS[returned.provider as Provider] ?? returned.provider} conectado.`}
          </span>
          <button type="button" className={styles.textBtn} onClick={onDismissReturn}>
            Cerrar
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
                <p className={styles.cardHint}>{HINTS[provider]}</p>
              </div>
              <span
                className={status?.connected ? styles.chipOn : styles.chipOff}
                data-testid={`status-${provider}`}
              >
                {card.loading
                  ? "Comprobando…"
                  : status?.connected
                    ? status.stale
                      ? "Reconectar"
                      : "Conectado"
                    : "Sin conectar"}
              </span>
            </div>

            {status && !status.configured && (
              <p className={styles.noteText}>
                Este proveedor aún no tiene claves en el servidor. Se activa al pegar sus
                credenciales en <code>lumi/.env</code>.
              </p>
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
                    El acceso caduca {formatExpiry(status.details.expires_at)}. Se renueva solo.
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
                    <button
                      type="button"
                      className={styles.textBtn}
                      disabled={card.busy}
                      onClick={() => void remove(provider, account.id)}
                    >
                      Desconectar
                    </button>
                  </li>
                ))}
              </ul>
            )}

            <div className={styles.cardActions}>
              {provider === "pfm" && (
                <select
                  className={styles.select}
                  aria-label="Red social a conectar"
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
                {status?.connected ? "Conectar otra cuenta" : "Conectar"}
              </button>
              {provider === "google" && status?.connected && (
                <button
                  type="button"
                  className={styles.textBtn}
                  disabled={card.busy}
                  onClick={() => void remove("google")}
                >
                  Desconectar
                </button>
              )}
              <button type="button" className={styles.textBtn} onClick={() => void load(provider)}>
                Actualizar
              </button>
            </div>
          </section>
        );
      })}
    </>
  );
}
