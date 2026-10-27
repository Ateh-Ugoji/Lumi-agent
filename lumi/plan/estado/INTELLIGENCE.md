# Estado de LUMI-INTELLIGENCE

Rama: `lumi-orquestador`. Última actualización: 2026-10-27 (T10 y T12 hechos; T4/T11 ver abajo).

## Línea base (T0)

- `GROQ_API_KEY=x OPENROUTER_API_KEY=x TYPESAFE_API_KEY=x NEATLOGS_API_KEY=x SECRET_KEY=x uv run pytest -q` en `b4d039a`: 418 pasan (7,6 s). Es la referencia de comportamiento del legado.

## Tareas

| Tarea | Estado | Nota |
| --- | --- | --- |
| T0 Arranque | hecha | Línea base de 418 tests; `estado/` creado. |
| T1 Esqueleto y puertos | hecha | `lumi_ai/ports.py` v1.0, `lumi_ai/config.py`, `lumi_ai/json_utils.py`, `lumi_ai/agent/result.py`. `uv run pytest lumi_ai -q`: 25 pasan. |
| T2 Proveedores | hecha | `lumi_ai/providers/{chain,factory,audio,errors,urls}.py`, `lumi_ai/observability.py`, `lumi_ai/keys.py` (`build_probes(config)`: groq, openrouter, openlux, typesafe, neatlogs, video). `uv run pytest lumi_ai -q`: 64 pasan, 0 se omiten. Las sondas no se ejecutaron contra proveedores reales (sin keys). |
| T3 Loop y tools | hecho (a falta del pegamento Django, T4) | `agent/{context,gates,turn_class,prompts,loop,streaming,support,result}.py`, `judge/` (Jev → LLM pequeño), `tools/` (registry sin estado global + 12 tools con puerto). El bucle recibe todo por `AgentDeps` (LLMChain, ToolRegistry, ChatStore, ProfileGateway, Clock, MemoryStore, TurnLogStore, SemanticJudge, McpGateway, MemoryExtractor); no hay estado de módulo. Las tools de memoria, competidores, voz-extracción, repurpose y tendencias se registran en T5-T8 (traen su servicio). `uv run pytest lumi_ai -q`: 197 pasan, 0 se omiten. |
| T4 Pegamento Django | en curso: `apps.py` y `models.py` + migración 0001 hechos; faltan `runtime.py` y `repos.py` | |
| T5 Perfil de estilo | hecho salvo repos Django (T4) | `style/{schema,extract,service,questions,tools}.py`: JSON robusto con `extract_json` + pydantic + un reintento de reparación; voz por plataforma; arranque en frío con `STYLE_QUESTIONS` (`source=questions`, nunca pisa una voz de posts); tool `extract_voice_profile`. La transacción con `select_for_update` y el mapeo `None` ↔ `general` son del repo Django (T4). `uv run pytest lumi_ai -q`: 217 pasan. |
| T6 RAG y memoria | hecho salvo repos Django y comando `reindex_vectors` (T4) | `rag/{vector_store,embedder,indexer,retrieval,reindex,memory,extractor,tools,collections,errors}.py`. Chroma solo guarda vectores con id `{tipo}:{id de Postgres}` y metadatos de filtro; el texto se lee de Postgres al recuperar y los vectores huérfanos se borran. Memoria: Postgres primero, vector después; si indexar falla la nota se guarda con `indexed=false` y `reindex_vectors` la repara. Extractor de fin de turno (`LLMMemoryExtractor`) y tools `remember`/`recall_memory`. `uv run pytest lumi_ai -q`: 249 pasan, 1 deseleccionado (`live`: ONNX real + Chroma en disco, pasa con `LUMI_RUN_LIVE=1 -m live`). |
| T8 Generación | en curso: hecho `generation/{platforms,difficulty,enforcement,writer,context,flow,tools}.py` con 57+ tests; falta el pegamento Django (`test_repurpose_endpoint.py`, T4) | `generate_post` y `repurpose_caption` se registran con `build_registry(..., extra=generation.tools.build(service, posts))`. Los intentos se guardan todos, en UNA transacción y DESPUÉS del trabajo. `PORTS_VERSION` 1.7: `create_request_with_attempts(source_post_id=)`. |
| T9 Evaluación | hecho en `lumi_ai` (falta guardar con `EvalStore` real en T4) | `evaluation/{checks,rubric,style,gate,evaluator,reviewer}.py` y `evaluation/golden/` (26 casos SINTÉTICOS). `manage.py ai_eval --suite golden [--live] [--min-agreement 0.85]`: sin `--live` repite las notas grabadas (100% de coincidencia, mide la puerta, no a los jueces); con `--live` pregunta a Jev y a Groq pequeño. Las evaluaciones se guardan DESPUÉS de los intentos (otra transacción), con aviso si fallan. Umbrales sin calibrar: criterio 0.5, media 0.7, fallo 0.3, similitud de estilo apagada. |
| T10 Video | hecho, apagado por defecto | `lumi_ai/video/` (puerto `VideoAnalyzer`, adaptador Gemini REST, `fake.py` solo para tests, descarga con guarda SSRF, caché por media+proveedor+versión de prompt en `video_analysis_records`, tool `analyze_video`, probe `video`). `PORTS_VERSION` 1.10. Comparación y propuesta (Gemini `gemini-3.5-flash-lite`, plan de pago): `docs/VIDEO_API_COMPARISON.md`. Sin `VIDEO_PROVIDER` el pipeline es idéntico (test). Decide Christian. |
| T11 Pruebas con keys reales | escritas, nunca ejecutadas | `lumi_ai/tests/test_live.py` (`@pytest.mark.live`, `LUMI_RUN_LIVE=1` + key). No se corren: costarían dinero. |
| T12 Documentación | `docs/AI.md` hecho; `/interrogate` no se corrió (usa varios modelos de pago) | Revisión manual de `agent/loop.py`, `evaluation/gate.py`, `rag/vector_store.py`: un hallazgo corregido (el fallo al guardar el turno solo iba a debug; ahora warning sin texto del mensaje). Hallazgo corregido después: un timeout de herramienta no detenía el hilo del ORM y una escritura podía confirmarse tras el timeout; ahora `lumi_ai/cancel.py` + `@aio` lo impiden (rollback antes del commit). Límite: HTTP externos y vectores de Chroma no se deshacen. |
| `reindex_vectors` | hecho (faltaba) | `apps/intelligence/management/commands/reindex_vectors.py` + `apps/intelligence/reindex.py`; `apps/intelligence/tests/test_reindex.py` (ida y vuelta con los mismos ids). Probes: `typesafe` (antes `jev`) y `chroma` para que valga el comando de PLAN §9. |

## Puertos publicados (`lumi_ai/ports.py`, `PORTS_VERSION = "1.10"` (1.10: `VideoAnalysisStore`; 1.9: `MediaRef.kind` puede ser `None` y `McpGateway.resolve_pending`; 1.8: `create_request_with_attempts(evaluations=)`; 1.7: `RepurposeStore.create_request_with_attempts(..., source_post_id=None)`; 1.6: `MatchStore.record_listening_match(profile_id, post_id, score=None) -> bool` para `listening_matches`, aditivo; 1.5: `tool_call_id` en `ChatMessageIn/Out`; `NicheReportIn.query/peers_analyzed/peer_handles` y `NicheReportOut.query/peers_analyzed`; `RepurposeStore.create_request_with_attempts(..., *, mode, brief)`; `RequestStore.save_user_request(..., *, platform=None)`; el bucle guarda `tool_call_id` en las filas `tool`; 1.4: `VoiceStore.save_voice(..., *, model="", prompt_version="")` y `MemoryStore.touch_notes(ids)` para `last_accessed_at`/`access_count`; 1.3: `AttemptIn.is_fallback`, `EvaluationRecord.attempt_id` obligatorio por palabra clave))

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

- **T10 (vídeo) bloqueada en origen de datos.** Ni PFM ni Xpoz rellenan `PostIn.media`, así que en el ingest `post_media` queda vacío y no hay URL de vídeo que analizar. El análisis de vídeo necesita otra fuente de URLs de medios (p. ej. que CONNECT las obtenga con otra llamada del proveedor, o que el usuario pegue el enlace del vídeo). Hasta decidirlo, T10 solo puede trabajar con una URL dada explícitamente.
- **Presupuesto de Xpoz e Instagram.** Una ejecución de Instagram cuesta 12 créditos y `XPOZ_RUN_CREDIT_BUDGET` vale 10 por defecto. El pipeline de competidores ya no falla en silencio: devuelve `insufficient_data` con "credit budget insufficient before @handle (N of M credits spent) … raise XPOZ_RUN_CREDIT_BUDGET". El tope lo aplica el adaptador de Xpoz (CONNECT): para que Instagram funcione, subir el valor a 12 o más, o hacerlo por plataforma.

## Revisión de SCHEMA v2 (27 oct, tras `46d1674`)

- Aceptado sin cambios: `Platform` de 5 valores (coincide con `lumi_ai.ports.Platform`, no hace falta ensanchar nada), `listening_keywords`, `niche_preferences` con hijas, `attempt_id` obligatorio, `is_fallback`.
- `voice_profiles.platform = 'general'` en BD y `None` en el puerto: el repo traduce en ambos sentidos.
- `voice_profiles.model` y `prompt_version`: `VoiceStore.save_voice` no los recibe. `lumi_ai` los entrega en `payload["extraction"]`; el repo debe copiarlos a las columnas. Si ARCHITECT prefiere argumentos explícitos pido puertos 1.4.
- `CONTRATOS.md` no ha llegado (ni en `origin/lumi-orquestador` ni en el árbol). No escribo `CONTRATO ARCHITECT ACEPTADO` todavía. Lo que necesito de él: firmas de servicio de `apps.profiles.services` y `apps.intelligence` que implementan los puertos, error de `save_voice` concurrente, y el mapeo de `PostOut.is_deleted_suspect`/`text_truncated` a columnas.

## Revisión de `CONTRATOS.md` v1.0 (`f212586`)

CONTRATO ARCHITECT ACEPTADO f212586

Encaja con lo que necesito. Resuelve mis cuatro preguntas pendientes (firmas de servicio, `attempt_id`, mapeo `general`↔`None`, `tool_call_id`). Los puertos suben a 1.5 por lo acordado con ARCHITECT. Observaciones, ninguna bloquea:

1. `apps.intelligence.runtime` (`run_turn`, `stream_turn`) lo escribo en T4. Propongo `run_turn(profile_id, message) -> TurnResult` y `stream_turn(profile_id, message) -> AsyncIterator[SSEEvent]` (async; `SSEEvent.as_dict()` ya coincide con la sección 3.4). `user_id` lo comprueba la vista con `IsProfileOwner`.
2. `POST /trends/scan` pasa por mi registro de tools. Hace falta una tool `check_niche_trends` y un puerto para escribir y leer `listening_matches` (`record_listening_match(profile_id, post_id, score)` y `GET /trends/matches`). Aún no está en `ports.py`; lo añado como puertos 1.6 cuando llegue a esa tarea. `min_likes` por defecto 20 (el legado usaba 50).
3. `frameworks`: la columna `name` guarda el título; el nombre estable (`pas`, `aida`...) viaja en `payload["key"]`. `framework_evidence` exige que los posts de pares ya estén en `posts`: el repo de `ReportStore` debe resolver `"<plataforma>:<external_id>"` a `posts.id` y la canalización guarda los posts antes del informe.
4. `niche_reports.niche` recibe `niche_key`; `origin = 'pipeline'`; `query`, `peers_analyzed` y `niche_report_peers` salen de los campos nuevos de 1.5.
5. `post_taggings` es por `post_id` y `TaggingRecord.post_ref` es `"<plataforma>:<external_id>"`: el repo resuelve el id.
6. Las sondas: `lumi_ai.keys.build_probes` (T11) devolverá una sonda por proveedor para `register(name, probe, required, env_vars)`; `probe` será `KeyProbe.run`.
7. Sigue abierto el comportamiento de `save_voice` concurrente (`select_for_update` sobre la fila vigente, según `SCHEMA.md`): el repo debe convertir un choque en reintento, no en error al agente.
