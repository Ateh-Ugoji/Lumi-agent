# Estado de LUMI-INTELLIGENCE

Rama: `lumi-orquestador`. Última actualización: 2026-10-27 (T3 hecho salvo Django).

## Línea base (T0)

- `GROQ_API_KEY=x OPENROUTER_API_KEY=x TYPESAFE_API_KEY=x NEATLOGS_API_KEY=x SECRET_KEY=x uv run pytest -q` en `b4d039a`: 418 pasan (7,6 s). Es la referencia de comportamiento del legado.

## Tareas

| Tarea | Estado | Nota |
| --- | --- | --- |
| T0 Arranque | hecha | Línea base de 418 tests; `estado/` creado. |
| T1 Esqueleto y puertos | hecha | `lumi_ai/ports.py` v1.0, `lumi_ai/config.py`, `lumi_ai/json_utils.py`, `lumi_ai/agent/result.py`. `uv run pytest lumi_ai -q`: 25 pasan. |
| T2 Proveedores | hecha | `lumi_ai/providers/{chain,factory,audio,errors,urls}.py`, `lumi_ai/observability.py`, `lumi_ai/keys.py` (`build_probes(config)`: groq, openrouter, openlux, jev, neatlogs, video). `uv run pytest lumi_ai -q`: 64 pasan, 0 se omiten. Las sondas no se ejecutaron contra proveedores reales (sin keys). |
| T3 Loop y tools | hecho (a falta del pegamento Django, T4) | `agent/{context,gates,turn_class,prompts,loop,streaming,support,result}.py`, `judge/` (Jev → LLM pequeño), `tools/` (registry sin estado global + 12 tools con puerto). El bucle recibe todo por `AgentDeps` (LLMChain, ToolRegistry, ChatStore, ProfileGateway, Clock, MemoryStore, TurnLogStore, SemanticJudge, McpGateway, MemoryExtractor); no hay estado de módulo. Las tools de memoria, competidores, voz-extracción, repurpose y tendencias se registran en T5-T8 (traen su servicio). `uv run pytest lumi_ai -q`: 197 pasan, 0 se omiten. |
| T4 Pegamento Django | bloqueada por T4/T5 de ARCHITECT | |
| T5-T12 | pendientes | |

## Puertos publicados (`lumi_ai/ports.py`, `PORTS_VERSION = "1.2"`)

- Para implementar por CONNECT: `SocialData`, `McpGateway`, `ConnectionLinks`, `OwnPostSync` (1.2, la tool `backfill_posts` solo la dispara) (más los errores `SocialDataError`, `BudgetExceeded`, `ProviderUnavailable`, `RateLimited`, `ProviderAuthError`, `LiveDisabled`, `UnsupportedPlatform`).
- Para implementar por INTELLIGENCE sobre el ORM: `ProfileStore`, `PostStore`, `PeerPostStore`, `VoiceStore`, `ReportStore`, `MemoryStore`, `ChatStore`, `TurnLogStore`, `RepurposeStore`, `RequestStore`, `ListeningStore`, `EvalStore`.
- Dentro de `lumi_ai`: `SemanticJudge` (1.1), `Embedder`, `VectorStore`, `VideoAnalyzer`, `Clock`, `KeyProbe` (gancho de `check_keys`).
- Tipos de salida del turno (para ARCHITECT): `lumi_ai/agent/result.py` (`TurnResult`, `SSEEvent`).

## Preguntas de contrato para ARCHITECT

1. `PostIn`/`PostOut`/`PostMetrics` están en `lumi_ai/ports.py`. Si `apps/profiles/services.py` define sus propios tipos, deben ser compatibles campo a campo o ARCHITECT importa estos.
2. Texto de posts de terceros (competidores): hace falta una tabla (`PeerPost`: perfil, plataforma, id externo, autor, texto, métricas, `niche_key`) porque Chroma ya no guarda texto. Propuesta: la pone INTELLIGENCE en `apps/intelligence` (puerto `PeerPostStore`) salvo que `SCHEMA.md` ya tenga algo equivalente (`ListeningMatch`).
3. `MemoryNote` y `ProfileMemorySummary` (INTELLIGENCE) reemplazan `memory.md`.
4. `ChatStore` se implementa sobre `apps.chat.services` (`history`, `append_message`); el puerto devuelve filas de herramienta incluidas.

5. `RepurposeStore.record_user_action` debe lanzar `LookupError` si el intento no existe o es de otro perfil (la tool `submit_action` lo traduce a un error legible).
6. `OwnPostSync.sync_own_posts(profile_id, platform)` (puerto nuevo 1.2): trae y guarda los posts propios de la cuenta conectada; la política de ingesta (métricas NULL, tipo de post) vive en `apps.profiles.services`, no en `lumi_ai`.

## Revisión de `docs/SCHEMA.md` v1 (commit `2da9d51`)

`CONTRATOS.md` aún no está publicado, así que no escribo `CONTRATO ARCHITECT ACEPTADO <sha>`. Del esquema acepto lo siguiente y dejo observaciones. Ninguna bloquea T3.

Resuelve mi pregunta 2: los posts de pares ya viven en `posts` (autor = `social_handles`), `framework_evidence` apunta a ellos. No hace falta tabla `PeerPost`; `PeerPostStore` se implementa sobre `posts` y se acota por perfil a través de `niche_report_peers`/`framework_evidence`.

Observaciones (A = las resuelvo yo añadiendo columnas en `apps/intelligence`, B = necesito a ARCHITECT):

1. B. `Platform` en el esquema incluye `youtube` y `reddit`; `lumi_ai.ports.Platform` solo tiene `x, linkedin, facebook, tiktok, instagram`. Propuesta: los repos convierten y descartan lo demás, y el agente solo genera para las cinco. Dime si prefieres ampliar el literal.
2. B. `generation_evaluations.attempt_id` es FK obligatoria. `EvaluationRecord.attempt_id` es opcional (un borrador evaluado aún sin intento). Propuesta: la evaluación se guarda siempre después de crear el intento (el servicio de generación crea intento y evaluación en una transacción) y el puerto pasa `attempt_id` obligatorio en 1.3. Confirmar.
3. A. `niche_preferences` solo guarda `niche`, `source`, `is_active`; `NicheIn` lleva además `title`, `keywords` y `tracked_handles` por plataforma. Añado columnas jsonb `keywords`, `tracked_handles` y `title`.
4. A. `frameworks` no tiene `title` ni `payload`; los añado. `framework_evidence` cubre `evidence_post_refs` si las refs son `post:<id>`.
5. A. `turn_classifications` no tiene `message_preview`, `path_taken` ni `judge_*` con ese nombre: mapeo `judge_*` a `jev_*` y añado `message_preview` y `path_taken`.
6. A. `repurpose_attempts.is_fallback` es nuevo; añado `is_fallback` a `AttemptIn` en el puerto 1.3 (cambio aditivo).
7. A. `ListeningConfig.keywords` no tiene columna en `poll_configs` (ARCHITECT). Propuesta: columna `keywords` jsonb en `poll_configs`; si no, el puerto pierde `keywords`. Confirmar de quién es.
8. B. `user_search_requests.handle_id` apunta a `social_handles`, que exige plataforma, y la tool `save_user_request` no la recibe. El repo usará la plataforma principal del perfil.
9. A. `voice_profiles.platform` `general` en lugar de nulo: el repo traduce `None` a `general`.
10. A. `post_taggings` es por `post_id`; `TaggingRecord.post_ref` será `post:<id>`.

## Bloqueos

Ninguno por ahora.
