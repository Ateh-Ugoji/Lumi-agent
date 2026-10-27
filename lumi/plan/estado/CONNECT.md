# Estado de LUMI-CONNECT

Rama `lumi-orquestador`. Se actualiza en cada reporte.

## Tareas

| Tarea | Estado | Nota |
| --- | --- | --- |
| T0 Preparar | hecha | Línea base 418 pruebas pasan |
| T1 CONEXIONES.md y API_KEYS.md | hecha | Revalidado el 2026-10-27 |
| T2 Fusión de frontends | hecho | `lumi/frontend` es el único frontend. Typecheck, build y 17 pruebas Node pasan. No hay linter en ninguno de los dos (solo `tsc`). |
| T3 a T14 | pendientes | Dependen del contrato de ARCHITECT (no hay `manage.py`, `SCHEMA.md` ni `CONTRATOS.md`) |

## Bloqueos

- Contrato de ARCHITECT sin publicar. Se construye la capa de adaptadores dentro de `lumi/apps/connections/` y se anota la dependencia.

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
