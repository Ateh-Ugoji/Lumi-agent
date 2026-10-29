import { ApiError, errorMessage } from "../../api/http.ts";
import { t } from "../../i18n/index.ts";

/** A sentence for a failed preview or publish. */
export function publishErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === "publish.not_connected") return t("publish.not_connected");
    if (err.code === "connections.live_disabled") return t("publish.x_off");
    if (err.code === "not_configured") return t("publish.not_configured");
    if (err.code === "conflict") return t("publish.key_reused");
  }
  return errorMessage(err, t("publish.failed"));
}
