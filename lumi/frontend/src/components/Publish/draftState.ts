import {
  NETWORK_LIMITS,
  PUBLISHABLE,
  newIdempotencyKey,
  remainingChars,
  type Draft,
  type Network,
  type PublishResult,
} from "../../api/publish.ts";
import { t } from "../../i18n/index.ts";

/** One post being prepared for one network. `key` identifies the card in the list. */
export type DraftCard = {
  key: string;
  platform: Network;
  text: string;
  /** The server draft this text started from. Kept after edits so the ledger links the two. */
  attemptId: number | null;
  /** Server evaluation of the generated text. It describes the original, not later edits. */
  evaluation: Extract<Draft, { ok: true }>["evaluation"];
  warnings: string[];
  edited: boolean;
  /** Stays the same across retries of one publish, changes when the text changes. */
  idempotencyKey: string | null;
  preview: PublishResult | null;
  published: PublishResult | null;
};

let counter = 0;
const nextKey = () => `draft-${++counter}`;

export function manualCard(platform: Network): DraftCard {
  return {
    key: nextKey(),
    platform,
    text: "",
    attemptId: null,
    evaluation: null,
    warnings: [],
    edited: false,
    idempotencyKey: null,
    preview: null,
    published: null,
  };
}

/** Cards for the drafts that worked, plus a list of the networks that failed with their message. */
export function cardsFromDrafts(drafts: Draft[]): {
  cards: DraftCard[];
  failures: { platform: Network; message: string }[];
} {
  const cards: DraftCard[] = [];
  const failures: { platform: Network; message: string }[] = [];
  for (const draft of drafts) {
    if (draft.ok) {
      cards.push({
        ...manualCard(draft.platform),
        text: draft.output,
        attemptId: draft.attempt_id,
        evaluation: draft.evaluation,
        warnings: draft.warnings ?? [],
      });
    } else {
      failures.push({ platform: draft.platform, message: draft.error?.message ?? t("draft.failed") });
    }
  }
  return { cards, failures };
}

/** Editing invalidates the earlier preview and the idempotency key: it is a different post now. */
export function editCard(card: DraftCard, text: string): DraftCard {
  return {
    ...card,
    text,
    edited: true,
    idempotencyKey: null,
    preview: null,
    published: null,
  };
}

export function withKey(card: DraftCard): DraftCard {
  return card.idempotencyKey ? card : { ...card, idempotencyKey: newIdempotencyKey() };
}

export function isPublishable(platform: Network): boolean {
  return PUBLISHABLE.includes(platform);
}

/** Why the card cannot be sent right now, or null when it can. */
export function blockedReason(card: DraftCard): string | null {
  if (!isPublishable(card.platform)) return t("draft.unavailable");
  if (!card.text.trim()) return t("draft.write_text");
  if (remainingChars(card.platform, card.text) < 0) {
    return t("draft.over_limit", { limit: NETWORK_LIMITS[card.platform] });
  }
  if (card.published) return t("draft.already_published");
  return null;
}
