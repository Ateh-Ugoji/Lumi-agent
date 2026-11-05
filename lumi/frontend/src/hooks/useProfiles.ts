import { useCallback, useEffect, useMemo, useState } from "react";
import { createProfile, getProfiles, type ProfileSummary } from "../api";
import { ACTIVE_PROFILE_KEY } from "../session.ts";
import { pickActiveId } from "./activeProfile.ts";
import { t } from "../i18n/index.ts";

function readStored(): number | null {
  try {
    const raw = localStorage.getItem(ACTIVE_PROFILE_KEY);
    const n = raw ? Number(raw) : NaN;
    return Number.isInteger(n) && n > 0 ? n : null;
  } catch {
    return null;
  }
}

/** The user's profiles and the one the app is working on. There is no hidden default id. */
export function useProfiles() {
  const [profiles, setProfiles] = useState<ProfileSummary[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [storedId, setStoredId] = useState<number | null>(readStored);

  const refresh = useCallback(async () => {
    try {
      setProfiles(await getProfiles());
      setLoadError(null);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : t("profiles.load_failed"));
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  const activeId = useMemo(() => pickActiveId(profiles, storedId), [profiles, storedId]);
  const active = useMemo(() => profiles.find((p) => p.id === activeId) ?? null, [profiles, activeId]);

  const select = useCallback((id: number) => {
    setStoredId(id);
    try {
      localStorage.setItem(ACTIVE_PROFILE_KEY, String(id));
    } catch {
      // the choice lasts until reload
    }
  }, []);

  const create = useCallback(
    async (platform: string, handle: string) => {
      const created = await createProfile(platform, handle);
      await refresh();
      select(created.id);
      return created;
    },
    [refresh, select],
  );

  return { profiles, loaded, loadError, activeId, active, select, create, refresh };
}
