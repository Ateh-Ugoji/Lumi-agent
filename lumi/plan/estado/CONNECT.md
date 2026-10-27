# Estado de LUMI-CONNECT

Rama `lumi-orquestador`. Se actualiza en cada reporte.

## Tareas

| Tarea | Estado | Nota |
| --- | --- | --- |
| T0 Preparar | hecha | Línea base 418 pruebas pasan |
| T1 CONEXIONES.md y API_KEYS.md | hecha | Revalidado el 2026-10-27 |
| T2 Fusión de frontends | hecho | `lumi/frontend` es el único frontend. Typecheck, build y 17 pruebas Node pasan. No hay linter en ninguno de los dos (solo `tsc`). |
| T13 MUSE.md | hecha | Solo documentación, fuentes de dev.meta.ai con fecha 2026-10-27 |
| Capa de adaptadores | hecha (sin Django) | Cifrado, OAuth, http, Meta, LinkedIn, X, publicación, claves. 139 pruebas sin red. |
| T3 modelos | hecho | 7 modelos, `0001_initial`, almacenes Django y 53 pruebas contra Postgres real. Ida y vuelta de migración y `makemigrations --check` limpios |
| T7 clientes PFM y Xpoz | hecha (sin red) | Mocks y fixtures. Sin llamadas en vivo. La ingesta a Postgres espera `apps.profiles.services` (T5 de ARCHITECT) |
| T8 búsqueda de handles | almacén Postgres hecho | Falta la ruta `/handles/*` (T5) |
| T5 cuentas y rutas de conexión | hecho (sin montar) | `connect`, `callback`, `status`, `DELETE`, renovación. 36 pruebas de API en Postgres real. Falta que ARCHITECT monte `apps.connections.urls` |
| T4, T6, T9 a T12 y T14 | pendientes | `CONTRATOS.md` v1.0 ya está aceptado. Sigue T6 (publicación) y `/handles/*` |

## Contrato

CONTRATO ARCHITECT ACEPTADO f212586 (`CONTRATOS.md` v1.0, completo).

Compatible. Puntos concretos:

- Aceptados sin cambios: sección 11, filas 3 a 7 (`pfm_account_id` vive en `connected_accounts`, `PublishJob.status` con `fingerprint`, `OAuthState.consume` en un solo `UPDATE ... RETURNING`, `EncryptedTextField` en `apps.core.fields`, `connect` en JSON y `callback` público con `302`).
- Rutas: el plan de CONNECT decía `/connections/<provider>/start`. Se usa `/connect` como fija el contrato. El contrato no trae `GET /connections` ni un `refresh` manual. Se propone añadirlos en una versión menor si el frontend los necesita. Mientras tanto, `status` por proveedor basta.
- `publish_jobs.attempt_id` apunta a `repurpose_attempts`, que aún no existe (la app `intelligence` no tiene migraciones). `0001` crea la columna como `bigint` nula sin FK y `0002` añade la FK cuando INTELLIGENCE publique su migración. Esto es una desviación temporal de SCHEMA §8.
- `google` aparece en las rutas pero no en `connected_accounts.provider`. Se mantiene así: Google vive en `mcp_auth_accounts` y `OAuthState` (T9).
- `xpoz_credit_ledger` será tabla (auditoría por clave y corrida). `mcp_pending_writes` se decide en T9. El presupuesto de una corrida es un contador en memoria de esa corrida y no sustituye al registro.
- Los handles de Reddit salen de la capa de búsqueda porque SCHEMA v2 quitó `reddit` de `Platform`. El cliente Xpoz conserva la capacidad.

## Bloqueos

- ARCHITECT publicó `manage.py`, ajustes, `apps.core` y `SCHEMA.md` v1 (propuesta). Falta `CONTRATOS.md` y las migraciones de `accounts` y `profiles`.
- La sección 8 de `SCHEMA.md` es compatible con la capa de adaptadores. Respuestas a sus preguntas 2 y 8: de acuerdo con los defectos propuestos.
- Nota para ARCHITECT: `apps/core/tests/test_keys.py::test_core_registers_its_services` falla en solitario (`pytest apps/core`) porque otro test vacía el registro sin restaurarlo.

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
