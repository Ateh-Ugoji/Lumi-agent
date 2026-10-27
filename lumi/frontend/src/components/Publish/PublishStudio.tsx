import { useState } from "react";
import {
  ApiError,
  NETWORK_LABELS,
  NETWORK_LIMITS,
  errorMessage,
  previewPublish,
  publishNow,
  remainingChars,
  repurpose,
  type Network,
} from "../../api";
import {
  blockedReason,
  cardsFromDrafts,
  editCard,
  manualCard,
  withKey,
  type DraftCard,
} from "./draftState";
import { publishErrorMessage } from "./errors";
import styles from "./PublishStudio.module.css";

const ALL: Network[] = ["x", "linkedin", "facebook", "instagram", "tiktok"];

export default function PublishStudio({
  profileId,
  handle,
  onOpenConnections,
}: {
  profileId: number | null;
  handle: string | null;
  onOpenConnections: () => void;
}) {
  const [source, setSource] = useState("");
  const [networks, setNetworks] = useState<Network[]>(["x", "linkedin"]);
  const [cards, setCards] = useState<DraftCard[]>([]);
  const [notes, setNotes] = useState<string[]>([]);
  const [generating, setGenerating] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [confirmKey, setConfirmKey] = useState<string | null>(null);

  const toggle = (n: Network) =>
    setNetworks((cur) => (cur.includes(n) ? cur.filter((x) => x !== n) : [...cur, n]));

  const setCard = (key: string, next: (c: DraftCard) => DraftCard) =>
    setCards((cur) => cur.map((c) => (c.key === key ? next(c) : c)));

  const setError = (key: string, message: string | null) =>
    setErrors((cur) => {
      const copy = { ...cur };
      if (message) copy[key] = message;
      else delete copy[key];
      return copy;
    });

  if (profileId === null) {
    return (
      <div className={styles.root}>
        <div className={styles.wrap}>
          <h1 className={styles.title}>Publish</h1>
          <p className={styles.hint}>Añade un perfil en Settings para preparar publicaciones.</p>
        </div>
      </div>
    );
  }

  const generate = async () => {
    if (!source.trim() || networks.length === 0 || generating) return;
    setGenerating(true);
    setNotes([]);
    setCards([]);
    setErrors({});
    try {
      const drafts = await repurpose({ profileId, sourceText: source, platforms: networks });
      const { cards: made, failures } = cardsFromDrafts(drafts);
      setCards(made);
      setNotes(failures.map((f) => `${NETWORK_LABELS[f.platform]}: ${f.message}`));
    } catch (err) {
      const unavailable = err instanceof ApiError && (err.status === 404 || err.status === 405);
      setNotes([
        unavailable
          ? "La generación de borradores no está disponible en este servidor. Puedes escribir el texto a mano."
          : errorMessage(err, "No se pudieron generar los borradores."),
      ]);
    } finally {
      setGenerating(false);
    }
  };

  const writeByHand = () => {
    setNotes([]);
    setErrors({});
    setCards(networks.map(manualCard).map((c) => ({ ...c, text: c.platform === networks[0] ? source : "" })));
  };

  const preview = async (card: DraftCard) => {
    setBusyKey(card.key);
    setError(card.key, null);
    try {
      const result = await previewPublish({
        profileId,
        platform: card.platform,
        text: card.text,
        attemptId: card.attemptId,
      });
      setCard(card.key, (c) => ({ ...c, preview: result }));
    } catch (err) {
      setError(card.key, publishErrorMessage(err));
    } finally {
      setBusyKey(null);
    }
  };

  const publish = async (card: DraftCard) => {
    const keyed = withKey(card);
    setCard(card.key, () => keyed);
    setConfirmKey(null);
    setBusyKey(card.key);
    setError(card.key, null);
    try {
      const result = await publishNow(
        { profileId, platform: card.platform, text: card.text, attemptId: card.attemptId },
        keyed.idempotencyKey as string,
      );
      setCard(card.key, (c) => ({ ...c, published: result }));
    } catch (err) {
      // the key is kept on purpose: retrying the same post must not publish it twice
      setError(card.key, publishErrorMessage(err));
    } finally {
      setBusyKey(null);
    }
  };

  return (
    <div className={styles.root}>
      <div className={styles.wrap}>
        <h1 className={styles.title}>Publish</h1>
        <p className={styles.hint}>
          Genera un borrador por red a partir de una idea, edítalo, revísalo y publícalo.
          {handle ? ` Perfil activo: @${handle}.` : ""}
        </p>

        <section className={styles.card}>
          <label className={styles.field}>
            <span>Idea o texto base</span>
            <textarea
              className={styles.textarea}
              rows={4}
              value={source}
              onChange={(e) => setSource(e.target.value)}
              data-testid="publish-source"
            />
          </label>
          <div className={styles.networks} role="group" aria-label="Redes">
            {ALL.map((n) => (
              <label key={n} className={styles.check}>
                <input type="checkbox" checked={networks.includes(n)} onChange={() => toggle(n)} />
                {NETWORK_LABELS[n]}
              </label>
            ))}
          </div>
          <div className={styles.actions}>
            <button
              type="button"
              className={styles.primary}
              disabled={!source.trim() || networks.length === 0 || generating}
              onClick={() => void generate()}
              data-testid="publish-generate"
            >
              {generating ? "Generando…" : "Generar borradores"}
            </button>
            <button
              type="button"
              className={styles.ghost}
              disabled={networks.length === 0}
              onClick={writeByHand}
              data-testid="publish-manual"
            >
              Escribir a mano
            </button>
          </div>
          {notes.map((note) => (
            <p key={note} role="status" className={styles.note}>
              {note}
            </p>
          ))}
        </section>

        {cards.map((card) => {
          const left = remainingChars(card.platform, card.text);
          const reason = blockedReason(card);
          const busy = busyKey === card.key;
          const ev = card.evaluation;
          return (
            <section
              key={card.key}
              className={styles.card}
              data-testid={`draft-${card.platform}`}
              aria-label={`Borrador de ${NETWORK_LABELS[card.platform]}`}
            >
              <div className={styles.cardHead}>
                <h2 className={styles.cardTitle}>{NETWORK_LABELS[card.platform]}</h2>
                <span className={left < 0 ? styles.over : styles.count} data-testid="char-count">
                  {left} / {NETWORK_LIMITS[card.platform]}
                </span>
              </div>

              {ev && (
                <div className={styles.eval} data-testid="evaluation">
                  <strong>{ev.decision}</strong>
                  {ev.mean_score !== null && ` · nota ${ev.mean_score.toFixed(1)}`}
                  {ev.style_similarity !== null && ` · parecido a tu voz ${Math.round(ev.style_similarity * 100)}%`}
                  {ev.critique && <p className={styles.critique}>{ev.critique}</p>}
                  {ev.deterministic_failures.length > 0 && (
                    <ul>
                      {ev.deterministic_failures.map((f) => (
                        <li key={f}>{f}</li>
                      ))}
                    </ul>
                  )}
                  {card.edited && <p className={styles.critique}>Editaste el texto después de evaluarlo.</p>}
                </div>
              )}
              {card.warnings.map((w) => (
                <p key={w} className={styles.note}>
                  {w}
                </p>
              ))}

              <textarea
                className={styles.textarea}
                rows={card.platform === "x" ? 4 : 8}
                value={card.text}
                aria-label={`Texto para ${NETWORK_LABELS[card.platform]}`}
                onChange={(e) => setCard(card.key, (c) => editCard(c, e.target.value))}
              />

              <div className={styles.previewBox} data-testid="post-preview">
                <div className={styles.previewHead}>
                  {handle ? `@${handle}` : "Tu perfil"} · {NETWORK_LABELS[card.platform]}
                </div>
                <div className={styles.previewBody}>{card.text || "Vista previa vacía"}</div>
              </div>

              {reason && !card.published && <p className={styles.note}>{reason}</p>}
              {errors[card.key] && (
                <p role="alert" className={styles.error}>
                  {errors[card.key]}{" "}
                  {errors[card.key].includes("Settings") && (
                    <button type="button" className={styles.link} onClick={onOpenConnections}>
                      Abrir Settings
                    </button>
                  )}
                </p>
              )}

              {card.preview && !card.published && (
                <p className={styles.ok} data-testid="preview-result">
                  Revisión sin publicar: el texto es válido
                  {card.preview.estimated_cost_usd !== null && ` · costo estimado US$ ${card.preview.estimated_cost_usd}`}.
                  {card.preview.warnings.map((w) => ` ${w}`)}
                </p>
              )}
              {card.published && (
                <p className={styles.ok} data-testid="publish-result">
                  Publicado{card.published.replayed ? " (ya estaba enviado, no se repitió)" : ""}.{" "}
                  {card.published.url && (
                    <a href={card.published.url} target="_blank" rel="noopener noreferrer">
                      Ver publicación
                    </a>
                  )}
                </p>
              )}

              {confirmKey === card.key ? (
                <div className={styles.confirm} role="alertdialog" aria-label="Confirmar publicación">
                  <span>
                    Esto se publica ahora en {NETWORK_LABELS[card.platform]}
                    {handle ? ` como @${handle}` : ""} y es público.
                  </span>
                  <button
                    type="button"
                    className={styles.primary}
                    disabled={busy}
                    onClick={() => void publish(card)}
                    data-testid="publish-confirm"
                  >
                    Sí, publicar
                  </button>
                  <button type="button" className={styles.ghost} onClick={() => setConfirmKey(null)}>
                    Cancelar
                  </button>
                </div>
              ) : (
                <div className={styles.actions}>
                  <button
                    type="button"
                    className={styles.ghost}
                    disabled={Boolean(reason) || busy}
                    onClick={() => void preview(card)}
                    data-testid="publish-preview"
                  >
                    Revisar sin publicar
                  </button>
                  <button
                    type="button"
                    className={styles.primary}
                    disabled={Boolean(reason) || busy}
                    onClick={() => setConfirmKey(card.key)}
                    data-testid="publish-start"
                  >
                    Publicar
                  </button>
                </div>
              )}
            </section>
          );
        })}
      </div>
    </div>
  );
}
