import { ApiError, errorMessage } from "../api/http.ts";

/** Turn a failed auth call into a sentence the user can act on. */
export function authErrorMessage(err: unknown, mode: "login" | "register"): string {
  if (err instanceof ApiError) {
    if (err.status === 409) return "Ya existe una cuenta con ese correo. Entra en su lugar.";
    if (err.status === 401 || (mode === "login" && err.code === "validation_error")) {
      return "Correo o contraseña incorrectos.";
    }
    if (err.code === "rate_limited") return "Demasiados intentos. Espera un minuto.";
  }
  return errorMessage(err, "No se pudo completar la solicitud.");
}
