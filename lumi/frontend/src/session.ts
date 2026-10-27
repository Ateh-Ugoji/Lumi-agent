/** Browser storage keys owned by the app, so a logout can wipe what belongs to the session. */
export const CHATS_KEY = "lumi_agent_chats";
export const ACTIVE_KEY = "lumi_agent_active";
export const DRAFTS_KEY = "lumi_agent_drafts";
export const ACTIVE_PROFILE_KEY = "lumi_active_profile";

const SESSION_KEYS = [CHATS_KEY, ACTIVE_KEY, DRAFTS_KEY, ACTIVE_PROFILE_KEY];

/** Forget local chats and the selected profile. Chats are local, so they must not outlive the user. */
export function clearLocalSession(
  store: Pick<Storage, "removeItem"> | null = typeof localStorage === "undefined"
    ? null
    : localStorage,
): void {
  for (const key of SESSION_KEYS) {
    try {
      store?.removeItem(key);
    } catch {
      // storage blocked: nothing was written either
    }
  }
}
