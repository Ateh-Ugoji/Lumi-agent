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
import { useT } from "../../i18n/index.ts";
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
  const t = useT();

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
          <p className={styles.hint}>{t("publish.add_profile_hint")}</p>
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
          ? t("publish.drafts_unavailable")
          : errorMessage(err, t("publish.generate_failed")),
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
          {t("publish.blurb")}
          {handle ? t("publish.active_profile", { handle }) : ""}
        </p>

        <section className={styles.card}>
          <label className={styles.field}>
            <span>{t("publish.idea_label")}</span>
            <textarea
              className={styles.textarea}
              rows={4}
              value={source}
              onChange={(e) => setSource(e.target.value)}
              data-testid="publish-source"
            />
          </label>
          <div className={styles.networks} role="group" aria-label={t("publish.networks_label")}>
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
              {generating ? t("publish.generating") : t("publish.generate")}
            </button>
            <button
              type="button"
              className={styles.ghost}
              disabled={networks.length === 0}
              onClick={writeByHand}
              data-testid="publish-manual"
            >
              {t("publish.write_by_hand")}
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
              aria-label={t("publish.draft_aria", { network: NETWORK_LABELS[card.platform] })}
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
                  {ev.mean_score !== null &&
                    t("publish.score", { score: ev.mean_score.toFixed(1) })}
                  {ev.style_similarity !== null &&
                    t("publish.voice_match", { pct: Math.round(ev.style_similarity * 100) })}
                  {ev.critique && <p className={styles.critique}>{ev.critique}</p>}
                  {ev.deterministic_failures.length > 0 && (
                    <ul>
                      {ev.deterministic_failures.map((f) => (
                        <li key={f}>{f}</li>
                      ))}
                    </ul>
                  )}
                  {card.edited && <p className={styles.critique}>{t("publish.edited_after_eval")}</p>}
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
                aria-label={t("publish.text_for", { network: NETWORK_LABELS[card.platform] })}
                onChange={(e) => setCard(card.key, (c) => editCard(c, e.target.value))}
              />

              <div className={styles.previewBox} data-testid="post-preview">
                <div className={styles.previewHead}>
                  {handle ? `@${handle}` : t("publish.your_profile")} · {NETWORK_LABELS[card.platform]}
                </div>
                <div className={styles.previewBody}>
                  {card.text || t("publish.empty_preview")}
                </div>
              </div>

              {reason && !card.published && <p className={styles.note}>{reason}</p>}
              {errors[card.key] && (
                <p role="alert" className={styles.error}>
                  {errors[card.key]}{" "}
                  {errors[card.key].includes("Settings") && (
                    <button type="button" className={styles.link} onClick={onOpenConnections}>
                      {t("publish.open_settings")}
                    </button>
                  )}
                </p>
              )}

              {card.preview && !card.published && (
                <p className={styles.ok} data-testid="preview-result">
                  {t("publish.preview_ok")}
                  {card.preview.estimated_cost_usd !== null &&
                    t("publish.est_cost", { cost: card.preview.estimated_cost_usd })}.
                  {card.preview.warnings.map((w) => ` ${w}`)}
                </p>
              )}
              {card.published && (
                <p className={styles.ok} data-testid="publish-result">
                  {t("publish.published")}
                  {card.published.replayed ? t("publish.published_replayed") : ""}.{" "}
                  {card.published.url && (
                    <a href={card.published.url} target="_blank" rel="noopener noreferrer">
                      {t("publish.view_post")}
                    </a>
                  )}
                </p>
              )}

              {confirmKey === card.key ? (
                <div className={styles.confirm} role="alertdialog" aria-label={t("publish.confirm_aria")}>
                  <span>
                    {t("publish.confirm_now", { network: NETWORK_LABELS[card.platform] })}
                    {handle ? t("publish.confirm_as", { handle }) : ""}
                    {t("publish.confirm_public")}
                  </span>
                  <button
                    type="button"
                    className={styles.primary}
                    disabled={busy}
                    onClick={() => void publish(card)}
                    data-testid="publish-confirm"
                  >
                    {t("publish.yes_publish")}
                  </button>
                  <button type="button" className={styles.ghost} onClick={() => setConfirmKey(null)}>
                    {t("publish.cancel")}
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
