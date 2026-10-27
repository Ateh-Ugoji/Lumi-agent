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
| T3 modelos | bloqueada | Faltan `accounts.0001_initial` y `profiles.0001_initial` de ARCHITECT |
| T4 a T12 y T14 | pendientes | T5 y T11 exigen `CONTRATOS.md`, que aún no está publicado |

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
