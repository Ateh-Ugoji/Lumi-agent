import { ApiError, errorMessage } from "../api/http.ts";
import { t } from "../i18n/index.ts";

/** Turn a failed auth call into a sentence the user can act on. */
export function authErrorMessage(err: unknown, mode: "login" | "register"): string {
  if (err instanceof ApiError) {
    if (err.status === 409) return t("auth.account_exists");
    if (err.status === 401 || (mode === "login" && err.code === "validation_error")) {
      return t("auth.bad_credentials");
    }
    if (err.code === "rate_limited") return t("auth.rate_limited");
  }
  return errorMessage(err, t("auth.request_failed"));
}
