/**
 * Tiny i18n layer: English (default) and Spanish, switchable at runtime.
 *
 * `t()` reads the current language, so plain modules (error builders, api
 * helpers) can translate without React. Components re-render on switch through
 * `useT()`, which subscribes to the same store.
 *
 * The site shipped in Spanish; `es` keeps those originals verbatim and `en`
 * carries the translations. Strings that were already English live in both
 * dictionaries unchanged.
 */

import { useCallback, useSyncExternalStore } from "react";

export type Lang = "en" | "es";

const STORAGE_KEY = "lumi.lang";
export const LANGS: readonly Lang[] = ["en", "es"];

const en: Record<string, string> = {
  // --- api/http.ts ---
  "http.unavailable": "Lumi's server isn't responding. Try again in a moment.",
  "http.server_problem": "Lumi's server had a problem. Try again in a moment.",
  "http.unreachable": "Couldn't reach the Lumi server. Check that it is running.",
  "http.no_data": "The server sent no data.",
  "http.something_wrong": "Something went wrong.",

  // --- api/connections.ts ---
  "conn.no_link": "The server did not return a connect link.",
  "conn.need_reconnect": "That account needs to be reconnected before use.",
  "conn.wrong_network": "That account belongs to a different network than this profile.",
  "conn.gone": "The account or profile no longer exists. Refresh the list.",
  "conn.link_failed": "Couldn't link the account.",
  "conn.connect_failed": "Couldn't connect the account.",
  "conn.start_failed": "Couldn't start the connection.",
  "conn.server_missing": "Server configuration is missing: {vars}.",
  "conn.not_configured": "This provider isn't configured on the server.",
  "conn.x_off_setup": "X is off: no calls are made until X_LIVE_ENABLED is enabled.",
  "conn.upstream_no_response": "The provider did not respond. Try again in a few minutes.",
  "conn.server_error": "Something failed on the server. Try again.",
  "conn.meta_no_pages":
    "Facebook returned no Pages. Lumi connects Facebook Pages, not personal profiles: " +
    "you need to be an admin of a Page and pick it while authorizing.",
  "connections.state_invalid": "That connect link isn't valid. Start again.",
  "connections.state_expired": "That connect link expired. Start again.",
  "connections.state_mismatch":
    "A different Lumi account started this connect link. Nothing was connected.",
  "connections.access_denied": "You cancelled the authorization. Nothing was connected.",
  "connections.account_taken": "That account is already connected to another Lumi user.",
  "connections.no_accounts": "The authorization included no accounts.",
  "connections.pfm_failed": "Post for Me didn't confirm the account. Try again.",
  "connections.provider_rejected": "The provider rejected the connection.",
  "connections.unknown_provider": "Unknown provider.",

  // --- Settings › Connected Accounts ---
  "panel.checking": "Checking…",
  "panel.connected": "Connected",
  "panel.reconnect": "Reconnect",
  "panel.not_connected": "Not connected",
  "panel.close": "Close",
  "panel.disconnect": "Disconnect",
  "panel.refresh": "Refresh",
  "panel.state_failed": "Couldn't read the status.",
  "panel.refresh_failed": "Couldn't refresh.",
  "panel.publishes_for": "Publishes for @{handle}",
  "panel.use_for": "Use for @{handle}",
  "panel.expires": "Access expires {date}. It renews by itself.",
  "panel.connected_msg": "{provider} connected.",
  "panel.disconnect_failed": "Couldn't disconnect.",
  "panel.linked_now":
    "This account now publishes for @{handle}. The previous one stays connected.",
  "panel.will_publish": "This account will publish for @{handle}.",
  "panel.no_keys":
    "This provider has no keys on the server yet. It activates once you paste its credentials into `lumi/.env`.",
  "panel.hint.meta": "Facebook Pages. Used to publish.",
  "panel.hint.linkedin": "LinkedIn profile. Used to publish.",
  "panel.hint.x": "Reading and publishing on X.",
  "panel.hint.pfm": "Social accounts linked through Post for Me.",
  "panel.hint.google":
    "One Google permission covers reading Drive, the files Lumi creates and Docs.",
  "panel.select_network": "Network to connect",
  "panel.connect": "Connect",
  "panel.connect_another": "Connect another account",
  "panel.wrong_network": "Different network",
  "panel.reconnect_account": "Reconnect this account",

  // --- auth ---
  "auth.session_expired": "Your session ended. Sign in again.",
  "auth.invalid_email": "Enter a valid email.",
  "auth.password_short": "Password needs at least 8 characters.",
  "auth.title_signin": "Sign in to Lumi",
  "auth.title_signup": "Create your account",
  "auth.name": "Name",
  "auth.email": "Email",
  "auth.password": "Password",
  "auth.signin": "Sign in",
  "auth.signup": "Create account",
  "auth.no_account": "I don't have an account",
  "auth.have_account": "I already have an account",
  "auth.one_moment": "One moment…",
  "auth.account_exists": "An account with that email already exists. Sign in instead.",
  "auth.bad_credentials": "Email or password is incorrect.",
  "auth.rate_limited": "Too many attempts. Wait a minute.",
  "auth.request_failed": "Couldn't complete the request.",

  // --- publish errors + draft rules ---
  "publish.not_connected":
    "This profile has no account connected on that network. Connect it in Settings.",
  "publish.x_off": "X is off on this server.",
  "publish.not_configured": "This provider isn't configured on the server.",
  "publish.key_reused": "That publish key was already used for different text.",
  "publish.failed": "Couldn't complete the publish.",
  "draft.failed": "Failed.",
  "draft.write_text": "Write the text.",
  "draft.unavailable": "Publishing to this network isn't available yet.",
  "draft.over_limit": "Over the {limit}-character limit.",
  "draft.already_published": "Already published.",

  // --- Publish studio ---
  "publish.add_profile_hint": "Add a profile in Settings to prepare posts.",
  "publish.drafts_unavailable":
    "Draft generation isn't available on this server. You can write the text yourself.",
  "publish.generate_failed": "The drafts couldn't be generated.",
  "publish.blurb": "Generate a draft per network from an idea, edit it, review it and publish it.",
  "publish.active_profile": " Active profile: @{handle}.",
  "publish.idea_label": "Idea or base text",
  "publish.networks_label": "Networks",
  "publish.generating": "Generating…",
  "publish.generate": "Generate drafts",
  "publish.write_by_hand": "Write by hand",
  "publish.draft_aria": "{network} draft",
  "publish.text_for": "Text for {network}",
  "publish.score": " · score {score}",
  "publish.voice_match": " · matches your voice {pct}%",
  "publish.edited_after_eval": "You edited the text after evaluating it.",
  "publish.your_profile": "Your profile",
  "publish.empty_preview": "Empty preview",
  "publish.open_settings": "Open Settings",
  "publish.preview_ok": "Review without publishing: the text is valid",
  "publish.est_cost": " · estimated cost US$ {cost}",
  "publish.published": "Published",
  "publish.published_replayed": " (already sent, wasn't repeated)",
  "publish.view_post": "View post",
  "publish.confirm_aria": "Confirm publish",
  "publish.confirm_now": "This publishes now to {network}",
  "publish.confirm_as": " as @{handle}",
  "publish.confirm_public": " and is public.",
  "publish.yes_publish": "Yes, publish",
  "publish.cancel": "Cancel",

  // --- Settings ---
  "settings.title": "Settings",
  "settings.section_profile": "Profile",
  "settings.section_appearance": "Appearance",
  "settings.section_social": "Connected Accounts",
  "settings.section_connectors": "Connectors",
  "settings.account": "Account",
  "settings.profiles": "Profiles",
  "settings.logout": "Log out",
  "settings.appearance": "Appearance",
  "settings.theme_hint": "The theme applies everywhere, including the chat.",
  "settings.theme": "Theme",
  "settings.dark": "Dark",
  "settings.light": "Light",
  "settings.profile_error": "Couldn't create the profile.",
  "settings.delete_confirm": "Delete the chat history of @{handle} from the server?",
  "settings.history_cleared": "History deleted.",
  "settings.history_error": "Couldn't delete the history.",
  "settings.profiles_blurb":
    "Each profile is a social account that Lumi analyses. The active profile drives the chat, the trends and publishing.",
  "settings.no_profiles": "You have no profiles yet. Add the first one below.",
  "settings.voice_ready": " · voice ready",
  "settings.active": "Active",
  "settings.use_this": "Use this",
  "settings.new_network": "Network for the new profile",
  "settings.new_handle": "Handle for the new profile",
  "settings.handle_placeholder": "@handle",
  "settings.add_profile": "Add profile",
  "settings.clear_history": "Delete the chat history of @{handle}",
  "settings.language": "Language",
  "settings.language_hint": "Applies across the app, including the chat and this page.",
  "profiles.load_failed": "Couldn't load the profiles.",

  // --- Chronic Online ---
  "chronic.scan_failed": "The scan failed. Try again.",
  "chronic.trends_failed": "Couldn't load the trends.",
};

const es: Record<string, string> = {
  // --- api/http.ts ---
  "http.unavailable": "El servidor de Lumi no está respondiendo. Inténtalo de nuevo en un momento.",
  "http.server_problem": "El servidor de Lumi tuvo un problema. Inténtalo de nuevo en un momento.",
  "http.unreachable": "No se pudo contactar con el servidor de Lumi. Revisa que esté en marcha.",
  "http.no_data": "El servidor no envió datos.",
  "http.something_wrong": "Algo salió mal.",

  // --- api/connections.ts ---
  "conn.no_link": "El servidor no devolvió un enlace de conexión.",
  "conn.need_reconnect": "Esa cuenta necesita reconectarse antes de usarla.",
  "conn.wrong_network": "Esa cuenta es de otra red social que este perfil.",
  "conn.gone": "La cuenta o el perfil ya no existen. Actualiza la lista.",
  "conn.link_failed": "No se pudo enlazar la cuenta.",
  "conn.connect_failed": "No se pudo conectar la cuenta.",
  "conn.start_failed": "No se pudo iniciar la conexión.",
  "conn.server_missing": "Falta configurar el servidor: {vars}.",
  "conn.not_configured": "Este proveedor no está configurado en el servidor.",
  "conn.x_off_setup": "X está apagado: no se hacen llamadas hasta que se active X_LIVE_ENABLED.",
  "conn.upstream_no_response": "El proveedor no respondió. Inténtalo en unos minutos.",
  "conn.server_error": "Algo falló en el servidor. Inténtalo otra vez.",
  "conn.meta_no_pages":
    "Facebook no devolvió ninguna Página. Lumi conecta Páginas de Facebook, no perfiles personales: " +
    "necesitas ser administrador de una Página y elegirla al autorizar.",
  "connections.state_invalid": "El enlace de conexión no es válido. Empieza de nuevo.",
  "connections.state_expired": "El enlace de conexión caducó. Empieza de nuevo.",
  "connections.state_mismatch":
    "Este enlace de conexión lo inició otra cuenta de Lumi. No se conectó nada.",
  "connections.access_denied": "Cancelaste la autorización. No se conectó nada.",
  "connections.account_taken": "Esa cuenta ya está conectada a otro usuario de Lumi.",
  "connections.no_accounts": "La autorización no incluyó ninguna cuenta.",
  "connections.pfm_failed": "Post for Me no confirmó la cuenta. Inténtalo otra vez.",
  "connections.provider_rejected": "El proveedor rechazó la conexión.",
  "connections.unknown_provider": "Proveedor desconocido.",

  // --- Settings › Connected Accounts ---
  "panel.checking": "Comprobando…",
  "panel.connected": "Conectado",
  "panel.reconnect": "Reconectar",
  "panel.not_connected": "Sin conectar",
  "panel.close": "Cerrar",
  "panel.disconnect": "Desconectar",
  "panel.refresh": "Actualizar",
  "panel.state_failed": "No se pudo leer el estado.",
  "panel.refresh_failed": "No se pudo actualizar.",
  "panel.publishes_for": "Publica para @{handle}",
  "panel.use_for": "Usar para @{handle}",
  "panel.expires": "El acceso caduca {date}. Se renueva solo.",
  "panel.connected_msg": "{provider} conectado.",
  "panel.disconnect_failed": "No se pudo desconectar.",
  "panel.linked_now": "Ahora publica esta cuenta para @{handle}. La anterior sigue conectada.",
  "panel.will_publish": "Esta cuenta publicará para @{handle}.",
  "panel.no_keys":
    "Este proveedor aún no tiene claves en el servidor. Se activa al pegar sus credenciales en `lumi/.env`.",
  "panel.hint.meta": "Páginas de Facebook. Se usan para publicar.",
  "panel.hint.linkedin": "Perfil de LinkedIn. Se usa para publicar.",
  "panel.hint.x": "Lectura y publicación en X.",
  "panel.hint.pfm": "Cuentas de redes sociales enlazadas con Post for Me.",
  "panel.hint.google":
    "Un solo permiso de Google cubre leer Drive, los archivos que crea Lumi y Docs.",
  "panel.select_network": "Red social a conectar",
  "panel.connect": "Conectar",
  "panel.connect_another": "Conectar otra cuenta",
  "panel.wrong_network": "Es de otra red",
  "panel.reconnect_account": "Reconecta esta cuenta",

  // --- auth ---
  "auth.session_expired": "Tu sesión terminó. Entra otra vez.",
  "auth.invalid_email": "Escribe un correo válido.",
  "auth.password_short": "La contraseña necesita al menos 8 caracteres.",
  "auth.title_signin": "Entra a Lumi",
  "auth.title_signup": "Crea tu cuenta",
  "auth.name": "Nombre",
  "auth.email": "Correo",
  "auth.password": "Contraseña",
  "auth.signin": "Entrar",
  "auth.signup": "Crear cuenta",
  "auth.no_account": "No tengo cuenta",
  "auth.have_account": "Ya tengo cuenta",
  "auth.one_moment": "Un momento…",
  "auth.account_exists": "Ya existe una cuenta con ese correo. Entra en su lugar.",
  "auth.bad_credentials": "Correo o contraseña incorrectos.",
  "auth.rate_limited": "Demasiados intentos. Espera un minuto.",
  "auth.request_failed": "No se pudo completar la solicitud.",

  // --- publish errors + draft rules ---
  "publish.not_connected":
    "Este perfil no tiene una cuenta conectada en esa red. Conéctala en Settings.",
  "publish.x_off": "X está apagado en este servidor.",
  "publish.not_configured": "Falta configurar este proveedor en el servidor.",
  "publish.key_reused": "Esa clave de publicación ya se usó para otro texto.",
  "publish.failed": "No se pudo completar la publicación.",
  "draft.failed": "Falló.",
  "draft.write_text": "Escribe el texto.",
  "draft.unavailable": "Publicar en esta red aún no está disponible.",
  "draft.over_limit": "Supera el límite de {limit} caracteres.",
  "draft.already_published": "Ya se publicó.",

  // --- Publish studio ---
  "publish.add_profile_hint": "Añade un perfil en Settings para preparar publicaciones.",
  "publish.drafts_unavailable":
    "La generación de borradores no está disponible en este servidor. Puedes escribir el texto a mano.",
  "publish.generate_failed": "No se pudieron generar los borradores.",
  "publish.blurb":
    "Genera un borrador por red a partir de una idea, edítalo, revísalo y publícalo.",
  "publish.active_profile": " Perfil activo: @{handle}.",
  "publish.idea_label": "Idea o texto base",
  "publish.networks_label": "Redes",
  "publish.generating": "Generando…",
  "publish.generate": "Generar borradores",
  "publish.write_by_hand": "Escribir a mano",
  "publish.draft_aria": "Borrador de {network}",
  "publish.text_for": "Texto para {network}",
  "publish.score": " · nota {score}",
  "publish.voice_match": " · parecido a tu voz {pct}%",
  "publish.edited_after_eval": "Editaste el texto después de evaluarlo.",
  "publish.your_profile": "Tu perfil",
  "publish.empty_preview": "Vista previa vacía",
  "publish.open_settings": "Abrir Settings",
  "publish.preview_ok": "Revisión sin publicar: el texto es válido",
  "publish.est_cost": " · costo estimado US$ {cost}",
  "publish.published": "Publicado",
  "publish.published_replayed": " (ya estaba enviado, no se repitió)",
  "publish.view_post": "Ver publicación",
  "publish.confirm_aria": "Confirmar publicación",
  "publish.confirm_now": "Esto se publica ahora en {network}",
  "publish.confirm_as": " como @{handle}",
  "publish.confirm_public": " y es público.",
  "publish.yes_publish": "Sí, publicar",
  "publish.cancel": "Cancelar",

  // --- Settings ---
  "settings.title": "Ajustes",
  "settings.section_profile": "Perfil",
  "settings.section_appearance": "Apariencia",
  "settings.section_social": "Cuentas conectadas",
  "settings.section_connectors": "Conectores",
  "settings.account": "Cuenta",
  "settings.profiles": "Perfiles",
  "settings.logout": "Cerrar sesión",
  "settings.appearance": "Apariencia",
  "settings.theme_hint": "El tema se aplica en todas partes, incluido el chat.",
  "settings.theme": "Tema",
  "settings.dark": "Oscuro",
  "settings.light": "Claro",
  "settings.profile_error": "No se pudo crear el perfil.",
  "settings.delete_confirm": "¿Borrar del servidor el historial de chat de @{handle}?",
  "settings.history_cleared": "Historial borrado.",
  "settings.history_error": "No se pudo borrar el historial.",
  "settings.profiles_blurb":
    "Cada perfil es una cuenta social que Lumi analiza. El perfil activo guía el chat, las tendencias y la publicación.",
  "settings.no_profiles": "Aún no tienes perfiles. Añade el primero abajo.",
  "settings.voice_ready": " · voz lista",
  "settings.active": "Activo",
  "settings.use_this": "Usar este",
  "settings.new_network": "Red del nuevo perfil",
  "settings.new_handle": "Usuario del nuevo perfil",
  "settings.handle_placeholder": "@usuario",
  "settings.add_profile": "Añadir perfil",
  "settings.clear_history": "Borrar historial de chat de @{handle}",
  "settings.language": "Idioma",
  "settings.language_hint": "Se aplica en toda la app, incluido el chat y esta página.",
  "profiles.load_failed": "No se pudieron cargar los perfiles.",

  // --- Chronic Online ---
  "chronic.scan_failed": "El escaneo falló. Inténtalo otra vez.",
  "chronic.trends_failed": "No se pudieron cargar las tendencias.",
};

const DICTS: Record<Lang, Record<string, string>> = { en, es };

function readInitial(): Lang {
  if (typeof window === "undefined") return "en";
  const saved = window.localStorage.getItem(STORAGE_KEY);
  return saved === "es" ? "es" : "en";
}

let current: Lang = readInitial();
const listeners = new Set<() => void>();

export function getLang(): Lang {
  return current;
}

export function setLang(lang: Lang): void {
  if (lang === current) return;
  current = lang;
  try {
    window.localStorage.setItem(STORAGE_KEY, lang);
  } catch {
    // private mode: the choice simply does not persist
  }
  for (const listener of [...listeners]) listener();
}

/** Translate with `{placeholder}` substitution; falls back to English, then to the key. */
export function t(key: string, vars?: Record<string, string | number>): string {
  const table = DICTS[current];
  let text = table[key] ?? DICTS.en[key] ?? key;
  if (vars) {
    for (const [name, value] of Object.entries(vars)) {
      text = text.split(`{${name}}`).join(String(value));
    }
  }
  return text;
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Component hook: re-renders the subtree whenever the language changes. */
export function useT(): typeof t {
  useSyncExternalStore(subscribe, getLang, getLang);
  return useCallback((key: string, vars?: Record<string, string | number>) => t(key, vars), []);
}

/** Component hook: the current language, re-rendering on change (for the toggle itself). */
export function useLang(): Lang {
  return useSyncExternalStore(subscribe, getLang, getLang);
}
