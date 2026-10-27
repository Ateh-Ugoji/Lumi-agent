import { ApiError, errorMessage } from "../../api/http.ts";

/** A sentence for a failed preview or publish. */
export function publishErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.code === "publish.not_connected") {
      return "Este perfil no tiene una cuenta conectada en esa red. Conéctala en Settings.";
    }
    if (err.code === "connections.live_disabled") return "X está apagado en este servidor.";
    if (err.code === "not_configured") return "Falta configurar este proveedor en el servidor.";
    if (err.code === "conflict") return "Esa clave de publicación ya se usó para otro texto.";
  }
  return errorMessage(err, "No se pudo completar la publicación.");
}
