# Estado de LUMI-CONNECT

Rama `lumi-orquestador`. Se actualiza en cada reporte.

## Tareas

| Tarea | Estado | Nota |
| --- | --- | --- |
| T0 Preparar | hecha | Línea base 418 pruebas pasan |
| T1 CONEXIONES.md y API_KEYS.md | hecha | Revalidado el 2026-10-27 |
| T2 Fusión de frontends | hecha | `lumi/frontend` es el único frontend. Typecheck, build y 17 pruebas Node pasan |
| T3 modelos | hecha | `0001` a `0005`. `makemigrations --check` limpio, ida y vuelta probada |
| T4 a T7 adaptadores, clientes PFM y Xpoz, cuentas y rutas | hechas (sin red) | Rutas montadas por ARCHITECT en `config/urls.py` y probadas con el `ROOT_URLCONF` real |
| T6 publicación | hecha para X, LinkedIn y Facebook | Instagram y TikTok no publican: falta la ruta de publicación de PFM. Límites desde `lumi_ai.generation.platforms` |
| `/handles/*` | hecha | Presupuesto de Xpoz por plataforma (defecto 12) |
| T8 importador | hecha | `apps/connections/legacy_import.py`: `mcp_auth_accounts` y cuentas pfm |
| T9 Google MCP | hecha (sin servidor real) | Solo servidores simulados en loopback |
| T10 `check_keys` | hecha | Sondas `pfm`, `xpoz`, `google` y las de cada red |
| T11 frontend | pendiente | Siguiente en la cola |
| T12, T14 | pendientes | |
| T13 MUSE.md | hecha | Fuentes de dev.meta.ai con fecha 2026-10-27 |

## Contrato

CONTRATO ARCHITECT ACEPTADO f212586 (`CONTRATOS.md` v1.0, completo).

Compatible. Puntos concretos:

- Aceptados sin cambios: sección 11, filas 3 a 7 (`pfm_account_id` vive en `connected_accounts`, `PublishJob.status` con `fingerprint`, `OAuthState.consume` en un solo `UPDATE ... RETURNING`, `EncryptedTextField` en `apps.core.fields`, `connect` en JSON y `callback` público con `302`).
- Rutas: el plan de CONNECT decía `/connections/<provider>/start`. Se usa `/connect` como fija el contrato. El contrato no trae `GET /connections` ni un `refresh` manual. Se propone añadirlos en una versión menor si el frontend los necesita. Mientras tanto, `status` por proveedor basta.
- `publish_jobs.attempt_id` es una FK nula a `repurpose_attempts` desde la migración `0003`, que depende de `intelligence.0001_initial`.
- `google` está en `Provider` (migración `0005`, CHECK ampliado) a petición de ARCHITECT. En la práctica Google vive en `mcp_auth_accounts` y `OAuthState`, no en `connected_accounts`.
- `xpoz_credit_ledger` será tabla (auditoría por clave y corrida). `mcp_pending_writes` se decide en T9. El presupuesto de una corrida es un contador en memoria de esa corrida y no sustituye al registro.
- Los handles de Reddit salen de la capa de búsqueda porque SCHEMA v2 quitó `reddit` de `Platform`. El cliente Xpoz conserva la capacidad.

## Bloqueos

Bloqueos reales a 2026-10-27:

- No hay claves en `.env` de Meta, LinkedIn, X, Post for Me ni Xpoz. Todo lo probado usa respuestas simuladas. Sin verificar contra el servicio real: `redirect_url_override` de PFM, la revocación y la renovación de Meta, los límites de PFM, si Xpoz cobra una llamada fallida y el servidor MCP real de Google.
- El token de PFM está caducado y a Xpoz le quedan pocos créditos. No hay llamadas en vivo. `X_LIVE_ENABLED=false` y `XPOZ_LIVE_ENABLED=false`.
- `PostIn.media` no se puede rellenar con lo que devuelven PFM y Xpoz hoy (investigación en `docs/CONEXIONES.md`).
- Falta programar `connections.refresh_expiring` en Celery beat (ARCHITECT lo documentó como cron en CONTRATOS §8).
- INTELLIGENCE aún no llama a `apps.connections.mcp_gateway.build_mcp_gateway()` ni a `resolve_pending`.
- `.env.example` (de ARCHITECT) conserva `XPOZ_RUN_CREDIT_BUDGET=10`. El defecto real es 12.

Resueltos: `CONTRATOS.md` v1.0 y las migraciones de `accounts` y `profiles` existen. Las rutas están montadas. La FK `publish_jobs.attempt_id` está aplicada en `0003` sin choque con `intelligence.0001`.

## Último SHA verde

Ver el reporte.

## Pendiente de avisar al orquestador

Variables nuevas: `PUBLIC_BASE_URL`, `FRONTEND_URL`, `XPOZ_LIVE_ENABLED`, `XPOZ_RUN_CREDIT_BUDGET`, `HANDLE_CACHE_TTL_MINUTES`, `TOKEN_ENCRYPTION_KEY_PREVIOUS`, `LINKEDIN_API_VERSION`, `META_GRAPH_VERSION`. Ya están en `docs/API_KEYS.md`. ARCHITECT debe copiarlas a `.env.example`.

## Fusión de frontends (T2)

Base: `lumi/frontend` (versión más nueva, sin `WorkingMark`). Se portó desde el `frontend/` de la raíz y luego se borró.

| Función | Archivo |
|---|---|
| Revelado suave del texto del agente | `src/reveal/revealEngine.ts`, `src/reveal/useSmoothText.ts`, `tests/revealEngine.test.ts` |
| Voz: grabación, endpointer, TTS | `src/voice/recorder.ts`, `src/voice/speak.ts`, `src/api/voice.ts`, botón de micrófono en `components/PromptBar/PromptBar.tsx` |
| Botón Stop y AbortController | `src/App.tsx`, `src/App.module.css` (`.stopRow`, `.stopBtn`) |
| Conector Google (Settings > Connectors) | `components/Settings/Settings.tsx`, `src/api/client.ts` (`getGoogleConnectorStatus`, `openGoogleConsent`) |
| Se conservó de lumi | gating de bordes, `userProfile` y avatar, analytics por mensaje, `formatClock`, `usePrefersReducedMotion`, búsqueda de handles, `scanError` |

Comandos: `cd lumi/frontend && npm ci && npm run typecheck && npm run build && npx -y node@22 --test tests/*.test.ts`.
`package.json` pide Node >= 22.6 (`engines`, `.nvmrc`). Se borró `pnpm-lock.yaml`.
