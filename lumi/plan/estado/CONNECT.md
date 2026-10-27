# Estado de LUMI-CONNECT

Rama `lumi-orquestador`. Se actualiza en cada reporte.

## Tareas

| Tarea | Estado | Nota |
| --- | --- | --- |
| T0 Preparar | hecha | Línea base 418 pruebas pasan |
| T1 CONEXIONES.md y API_KEYS.md | hecha | Revalidado el 2026-10-27 |
| T2 Fusión de frontends | en curso | |
| T3 a T14 | pendientes | Dependen del contrato de ARCHITECT (no hay `manage.py`, `SCHEMA.md` ni `CONTRATOS.md`) |

## Bloqueos

- Contrato de ARCHITECT sin publicar. Se construye la capa de adaptadores dentro de `lumi/apps/connections/` y se anota la dependencia.

## Último SHA verde

Ver el reporte.

## Pendiente de avisar al orquestador

Variables nuevas: `PUBLIC_BASE_URL`, `FRONTEND_URL`, `XPOZ_LIVE_ENABLED`, `XPOZ_RUN_CREDIT_BUDGET`, `HANDLE_CACHE_TTL_MINUTES`, `TOKEN_ENCRYPTION_KEY_PREVIOUS`, `LINKEDIN_API_VERSION`, `META_GRAPH_VERSION`. Ya están en `docs/API_KEYS.md`. ARCHITECT debe copiarlas a `.env.example`.
