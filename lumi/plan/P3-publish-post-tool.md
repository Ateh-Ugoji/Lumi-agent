# P3 — `publish_post` agent tool: what is missing

Status 2026-10-28: P0, P1, P2, P4 done. P3 not started. English first (for the repo and the agents),
Spanish below (for review and delegation).

---

# English

## Goal
In the Lumi chat the user says "publish this on LinkedIn". The agent shows the exact post (preview),
the user says yes, and only then the post goes out. Text only, publish now only.

## What already exists (do not rebuild)
- REST service `apps/connections/publish_api.py::publish_post(user, profile_id, platform, text,
  attempt_id, link, confirm, dry_run, idempotency_key)`. It already does `dry_run` (sends nothing),
  `confirm=true` + `Idempotency-Key` (publishes once, replays the same `PublishJob`), typed `ApiError`s
  (`publish.unsupported_platform`, `publish.confirmation_required`, no connected account, reconnect).
- `providers/routes.py::publish_provider()` — facebook→meta, linkedin→linkedin, x→x; instagram/tiktok → `None`.
- Tool pattern: `ToolSpec(name, description, parameters, handler, cost, side_effects, cache_ttl)` in
  `lumi_ai/tools/`; assembled in `apps/intelligence/wiring.py` through the `extra=[...]` list.
- Write-tool precedent: `backfill_posts` (`lumi_ai/tools/account.py`) — the registry hands writes a cancel token.
- Pending-write precedent for the confirm step: `apps/connections/mcp/gateway.py::PendingWrite`.

## What is missing
1. **Port** in `lumi_ai/ports.py`: a `PostPublisher` protocol (`preview(...)`, `publish(...)`) so
   `lumi_ai` stays free of Django (same rule as `OwnPostSync`).
2. **Adapter** `apps/connections/agent_publish.py` (`DjangoPostPublisher`): wraps `publish_api.publish_post`,
   resolves the profile's `user`, generates the `Idempotency-Key`, maps `ApiError` to a typed
   `ProviderUnavailable`/`UnsupportedPlatform` the agent can explain.
3. **Tool** `lumi_ai/tools/publish.py`: `publish_post`, `cost="write"`, `side_effects="external_write"`,
   `cache_ttl=0`. Two calls: `step="preview"` (dry_run → returns exact text, platform, target account,
   `estimated_cost_usd`, a `confirmation_token`) and `step="confirm"` (needs that token).
4. **Confirmation rule**: confirm must only work on a preview from the *same* turn chain and only after a
   *user* message agreed — the model must not be able to preview and confirm in one go. Reuse the
   pending-write pattern (token bound to profile + text + platform, short TTL, single use).
5. **Wiring**: add the tool to `extra=[...]` in `apps/intelligence/wiring.py`; add `post_publisher` to `ToolDeps`.
6. **System prompt**: tell the agent to always preview first, show the text verbatim, ask yes/no,
   never claim success without a `done` result, and say plainly that Instagram/TikTok cannot publish.
7. **Tests** (mock transports, no network): preview publishes nothing; confirm publishes once; repeated
   confirm replays the same `PublishJob`; confirm without/with a wrong token is refused; no connected
   account → typed error the agent explains; unsupported platform → typed error, never a fake result;
   `profile_id` from the model is ignored (turn decides). Measure tool-schema tokens before/after.
8. **Docs** in the same change: `AGENTS.md`, `docs/flow-map.md(.html)`, this plan, `decisions.tsv`.

## Risks / decisions to confirm
- X publishing costs real credits ($0.015/post, $0.20 with a link) when `X_LIVE_ENABLED=true`.
- Redirect URIs (`http://localhost:3011/connections/<provider>/callback`) must be registered in the X,
  LinkedIn, Meta and Google portals, or no account can connect and nothing can be published (P0 external step).
- Token TTL and whether the confirm token lives in memory or in the DB (`mcp_pending_writes` is DB-backed).

## Suggested split
| Task | Owner | Depends on |
|---|---|---|
| 1 Port + 2 Adapter | backend | — |
| 3 Tool + 4 Confirmation rule | backend / agent | 1 |
| 5 Wiring + 6 Prompt | agent | 3 |
| 7 Tests | whoever writes 2–4 | 2–5 |
| 8 Docs | architect | all |
| Portal redirect URIs (human) | Ateh / owner of the dev accounts | — (blocks real demo) |

---

# Español

## Objetivo
En el chat de Lumi el usuario dice "publica esto en LinkedIn". El agente muestra el post exacto
(vista previa), el usuario dice que sí, y solo entonces se publica. Solo texto, solo publicar ya.

## Lo que ya existe (no reconstruir)
- Servicio REST `apps/connections/publish_api.py::publish_post(...)`. Ya hace `dry_run` (no envía nada),
  `confirm=true` + `Idempotency-Key` (publica una vez y repite el mismo `PublishJob`) y errores tipados
  (`publish.unsupported_platform`, `publish.confirmation_required`, sin cuenta conectada, reconectar).
- `providers/routes.py::publish_provider()` — facebook→meta, linkedin→linkedin, x→x; instagram/tiktok → `None`.
- Patrón de tools: `ToolSpec(...)` en `lumi_ai/tools/`, ensamblado en `apps/intelligence/wiring.py` por la lista `extra=[...]`.
- Precedente de tool de escritura: `backfill_posts` (`lumi_ai/tools/account.py`).
- Precedente para el paso de confirmar: `apps/connections/mcp/gateway.py::PendingWrite`.

## Lo que falta
1. **Puerto** en `lumi_ai/ports.py`: protocolo `PostPublisher` (`preview`, `publish`) para que `lumi_ai` no dependa de Django.
2. **Adaptador** `apps/connections/agent_publish.py` (`DjangoPostPublisher`): envuelve `publish_api.publish_post`,
   resuelve el `user` del perfil, genera el `Idempotency-Key` y convierte `ApiError` en errores tipados que el agente pueda explicar.
3. **Tool** `lumi_ai/tools/publish.py`: `publish_post`, `cost="write"`, `side_effects="external_write"`, sin caché.
   Dos pasos: `preview` (dry_run → texto exacto, red, cuenta destino, costo estimado, `confirmation_token`) y `confirm` (exige ese token).
4. **Regla de confirmación**: confirmar solo funciona sobre un preview y solo después de que el *usuario* aceptó;
   el modelo no puede hacer preview y confirm de golpe. Reutilizar el patrón de escritura pendiente
   (token ligado a perfil + texto + red, TTL corto, un solo uso).
5. **Wiring**: añadir la tool a `extra=[...]` en `wiring.py` y `post_publisher` a `ToolDeps`.
6. **Prompt del sistema**: siempre preview primero, mostrar el texto tal cual, pedir sí/no, nunca decir
   "publicado" sin un resultado `done`, y decir claro que Instagram/TikTok no pueden publicar.
7. **Tests** (transportes simulados, sin red): el preview no publica; confirm publica una vez; confirm repetido
   repite el mismo `PublishJob`; confirm sin token o con token malo se rechaza; sin cuenta conectada → error
   que el agente explica; red no soportada → error tipado, nunca un resultado inventado; el `profile_id` que
   manda el modelo se ignora. Medir tokens del esquema de tools antes/después.
8. **Docs** en el mismo cambio: `AGENTS.md`, `docs/flow-map.md(.html)`, este plan, `decisions.tsv`.

## Riesgos / decisiones por confirmar
- Publicar en X cuesta créditos reales ($0.015 por post, $0.20 con link) con `X_LIVE_ENABLED=true`.
- Hay que registrar los redirect URIs (`http://localhost:3011/connections/<provider>/callback`) en los
  portales de X, LinkedIn, Meta y Google; si no, nadie conecta cuenta y no hay nada que publicar (paso externo de P0).
- Cuánto dura el token de confirmación y si vive en memoria o en BD (`mcp_pending_writes` es en BD).

## División sugerida para delegar
| Tarea | Responsable | Depende de |
|---|---|---|
| 1 Puerto + 2 Adaptador | backend | — |
| 3 Tool + 4 Regla de confirmación | backend / agente | 1 |
| 5 Wiring + 6 Prompt | agente | 3 |
| 7 Tests | quien haga 2–4 | 2–5 |
| 8 Docs | arquitecto | todo |
| Redirect URIs en portales (humano) | Ateh / dueño de las cuentas dev | — (bloquea la demo real) |
