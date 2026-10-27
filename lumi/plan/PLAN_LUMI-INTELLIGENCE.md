# PLAN LUMI-INTELLIGENCE

Bot: LUMI-INTELLIGENCE (`a84a1345-b5b8-4313-8388-58ea71766c79`). Orquestador: Grok Bot. Plan escrito el 2026-10-27 sobre el commit `cce6ca3` de `main`.

Lee primero `lumi/plan/ContextoTareas.md`. **La IA es la prioridad número uno del proyecto**: si hay que recortar alcance en cualquier bot, se recorta en los otros, no aquí. Ejecuta este plan sin preguntar al usuario; decide lo reversible, anótalo en `decisiones.tsv` y sigue.

## 0. Protocolo común (idéntico en los tres planes)

- Una sola rama compartida: `lumi-orquestador`. `git fetch origin && git checkout lumi-orquestador`. Nunca `push --force`, nunca merge a `main`, nunca deploy, nunca abrir PR (el orquestador abre un Draft PR al final).
- Commits en tu ámbito de archivos, en español, formato `[INTELLIGENCE] área: qué cambió`. Commitea al terminar cada tarea o cambio importante y como mínimo cada hora de trabajo. Antes de cada push: `git pull --rebase origin lumi-orquestador`, corre los tests de tu ámbito y luego `git push origin lumi-orquestador`.
- Conflictos: si el conflicto toca archivos fuera de tu ámbito, no lo resuelvas a ciegas; conserva la versión del dueño y avisa al orquestador. Conflicto en `lumi/uv.lock`: `git checkout --theirs uv.lock && uv lock`, y commitea. Puedes añadir tus dependencias con `uv add`; nada más de `pyproject.toml`.
- Estado propio: `lumi/plan/estado/INTELLIGENCE.md` (qué terminaste, qué sigue, bloqueos, SHA del último commit verde) y `lumi/plan/estado/INTELLIGENCE-decisiones.tsv` (una fila por decisión: fecha, qué, por qué, evidencia, resultado; skill `/show-me-your-work`). Actualízalos en cada commit.
- Reporte al orquestador al cambiar de fase y ante cualquier bloqueo, con: fase, SHA, tareas hechas, comandos de verificación con resultado, riesgos y qué necesitas de otro bot.
- Skills permitidas: `/architect`, `/tdd`, `/blast-radius`, `/correct`, `/show-me-your-work`, `/figure-it-out`, `/how`, `/why`, `/create-verification-skill`, `/interrogate`. Prohibida `/arena`. Aplica `/correct` en todo el trabajo de repo y `/unslop` en lo que escribas para personas.
- Seguridad: nunca escribas valores de keys en archivos, commits, logs ni salidas. Los docs solo nombran variables. Las pruebas con llamadas reales gastan cuota: mínimas, marcadas `live`, y nunca en bucle.
- Límite de uso: no pases el límite semanal Premium de Christian. Sin créditos extra ni cargos. Si el límite se llena, detente y reporta.
- Idioma: docs para Christian en español. Código, identificadores, docstrings y prompts del agente en inglés (como el repo actual). Con Christian, español.
- No cambies código fuera de tu ámbito (sección 2); pide los cambios al dueño.

## 1. Misión

Construir y dejar demostrablemente bien la inteligencia de Lumi: un agente con tool calling (Groq con respaldo en OpenRouter) que aprende el estilo del usuario, entiende su nicho y su audiencia, analiza las publicaciones que mejor funcionan en su nicho (texto y video), recupera contexto con RAG sobre ChromaDB y genera posts por plataforma (X, LinkedIn, Facebook) que luego se evalúan solos en calidad y fidelidad de estilo.

Reglas:

- Reutiliza lo que funciona en `lumi/app/` (es código real con 418 tests). Portas, no reinventas. Donde el plan pide mejorar, mejora con tests.
- Sin respuestas simuladas en el camino de producción. Los dobles de prueba viven solo en `tests/` y `fixtures/`.
- El paquete `lumi/lumi_ai/` es Python puro: no importa Django. Habla con el resto por puertos (`Protocol`). El pegamento con Django vive en `lumi/apps/intelligence/`.
- Todo funciona al pegar keys en `lumi/.env`; las funciones que dependen de una key opcional se apagan con aviso, no con error.

## 2. Ámbito de archivos

Tuyos:

- `lumi/lumi_ai/**` (incluye `tests/` y `fixtures/` propios)
- `lumi/apps/intelligence/**` (modelos de IA, repos, `runtime.py`, `tasks.py`, vistas de `voice/transcribe` y `repurpose`, `urls.py`, migraciones)
- `lumi/docs/AI.md` (arquitectura de la IA), `lumi/docs/VIDEO_API_COMPARISON.md`, `lumi/docs/ADR-IA-*.md`
- Tu bloque `# --- INTELLIGENCE ---` en `lumi/.env.example`
- `lumi/plan/estado/INTELLIGENCE*.{md,tsv}`

No toques: `lumi/config/**`, `lumi/apps/{core,accounts,profiles,chat}/**`, `lumi/pyproject.toml` (salvo `uv add`), Docker, CI, `lumi/docs/{SCHEMA,CONTRATOS}.md` (ARCHITECT); `lumi/apps/connections/**`, `lumi/frontend/**`, `frontend/**` (CONNECT); `lumi/plan/ContextoTareas.md`, `lumi/plan/PLAN_*.md`, `lumi/docs/API_KEYS.md`, `lumi/docs/AGENT_KEYS_SETUP.md` (orquestador). No borres nada de `lumi/app/` (lo retira ARCHITECT al final). Puedes leer `lumi/app/` y `lumi/tests/` todo lo que quieras.

## 3. Estado actual de la IA (verificado en `cce6ca3`)

- **Loop del agente** (`lumi/app/agent/loop.py`, 1167 líneas): `MAX_TOOL_ITERATIONS=6`, `MAX_HISTORY_MESSAGES=10`, `TOOL_CONTEXT_CHAR_LIMIT=4000`, `OLD_TOOL_CONTEXT_CHAR_LIMIT=1200`, `MAX_REQUEST_TOKENS=6700` (3,5 caracteres por token), `TOOL_TIMEOUT_SECONDS=120`, `SUFFICIENCY_THRESHOLD=0.75`. Compuerta de afirmaciones (`_claims_action_without_tools`), compuerta de cobertura (`_coverage_block`), umbral de memoria digna de 0,6.
- **Clasificación de turnos** (`lumi/app/agent/turn_class.py`, 436 líneas): reglas, luego etapa 2 con Jev (apagada por defecto), camino rápido o completo, niveles de tools, `effort=low`. Se guarda en `turn_classifications` y alimenta `/health`.
- **Proveedores** (`lumi/app/agent/providers.py`): Groq `openai/gpt-oss-120b` primero, luego `qwen/qwen3.8-27b` (el muro de Groq está en ~7.000 tokens y la cuota de qwen casi agotada), OpenRouter `meta-llama/llama-3.3-70b-instruct` (el saldo vacío da 402). OpenLux opcional. `TIER_MODELS = {small: openai/gpt-oss-20b, large: openai/gpt-oss-120b}`. Un 400 por `reasoning_effort` reintenta el mismo candidato sin él. Whisper de Groq para voz a texto (`whisper-large-v3-turbo`). neatlogs se inicializa en `get_providers` y hoy es obligatorio. Los IDs de modelo están fijos en código y no se han verificado contra el catálogo actual.
- **Jev/TypeSafe**: capa de decisión (Noul/Choice) que sirve de juez y de etapa 2 del clasificador. Cadena de respaldo: Groq pequeño, luego solo reglas deterministas. Código en `lumi/app/services/jev.py`, `repurpose.py` (`classify_difficulty`).
- **Pipeline de competidores** (`lumi/app/services/peer_pipeline.py` 301 líneas; `lumi/app/analysis/{extract,winners,own_lift,own_tagging,lift,synthesize,metrics}.py`): línea base de 28 días, ganadores con ≥1,5× la mediana propia, etiquetado ciego cacheado por (`post_id`, `prompt_version`), lift y síntesis. Estados honestos `insufficient_data`/`failed`. Esquemas en `lumi/app/schemas/{peer,niche}.py` (los de `niche.py`, 403 líneas, están preparados pero sin conectar; planean `social_handles` y `niche_registry` con `niche_key = slug:geo_scope`).
- **Chroma** (`lumi/app/services/chroma.py`): colecciones `voice_corpus`, `voice_profiles`, `peer_frameworks`, `peer_posts`, `agent_memory`, más `handle_mappings`/`handle_cache` en `handle_db.py`. Usa Cloud si hay `CHROMA_API_KEY`, si no `PersistentClient` en `CHROMA_PATH`. **Hoy guarda `documents` (texto) además de metadatos: no es solo vectores. Hay que cambiarlo.** `memory.md` es un archivo continuo ignorado por git (`app/services/memory.py`, `MEMORY_PATH`) que debe pasar a la base.
- **Voz** (`lumi/app/services/voice.py` 250 líneas, `voice_corpus.py`): necesita ≥5 posts auténticos; si no hay, hace backfill de PFM y si aún no, devuelve `needs_style_questions: True`. Los replies alimentan `reply_style`; los retweets nunca son voz.
- **Reescritura multiplataforma** (`lumi/app/services/repurpose.py` 245 líneas, `repurpose_flow.py`, `enforcement.py` 190): plataformas X, LinkedIn, TikTok, Instagram (**sin Facebook**); límites en `enforcement.py` (X 280, LinkedIn 3000...); dificultad `easy|standard|hard`; intentos en `repurpose_attempts`.
- **20 tools nativas** (`lumi/app/tools/registry.py`, decorador `@tool`): `submit_action`, `dismiss_alert`, `backfill_posts`, `get_analytics`, `get_user_activity`, `get_peer_advice`, `get_posts`, `repurpose_caption`, `connect_account`, `remember`, `recall_memory`, `save_user_request`, `extract_voice_profile`, `get_voice_profile`, `answer_style_questions`, `start_listening`, `stop_listening`, `check_trending`, `check_niche_trends`, `discover_and_extract_niche_frameworks`. Más tools dinámicas `mcp__*`. `POST /trends/scan` hoy se salta el registro.
- **Prompt del agente** (`lumi/app/agent/prompts.py`): centrado en X, con "@AtehOfficial" fijo en las reglas y `DEFAULT_NICHE_HANDLES = [sama, levelsio, paulg, karpathy]`. `background/bootstrap.py` usa `DEFAULT_NICHE_QUERY` fijo. `tools/connect.py` fija `ateh_x_connect`.
- **Defectos conocidos en tu zona**: `raw.strip("`")` para quitar cercas de código en `voice.py` y `repurpose.py` (frágil); `repurpose_caption` guarda la solicitud antes de hacer el trabajo; `SSE create_task` sin referencia ni manejo de desconexión; OAuth/MCP con estado en proceso (CONNECT lo corrige); neatlogs obligatorio.
- **Tests** (en `lumi/tests/`, mayormente herméticos: ~523 líneas de mock): ver tabla de la sección 7. Con variables ficticias pasan 418 en ~5 s.

## 4. Decisiones fijas

- Groq primero, OpenRouter de respaldo; OpenLux opcional si hay key. Los IDs de modelo van en configuración (`GROQ_MODEL_LARGE`, `GROQ_MODEL_SMALL`, `GROQ_MODEL_FALLBACK`, `OPENROUTER_MODEL`, con los valores actuales como defecto) y `check_keys` los valida contra el catálogo real del proveedor (lista de modelos) avisando si alguno ya no existe.
- Jev/TypeSafe se conserva como juez y etapa 2 del clasificador, con la cadena: Jev, Groq pequeño, solo reglas. Sin `TYPESAFE_API_KEY` la cadena empieza en Groq pequeño y avisa una vez.
- neatlogs es opcional: sin `NEATLOGS_API_KEY` no se inicializa y el loop funciona igual.
- ChromaDB guarda solo vectores. Ids con forma `<tipo>:<id_postgres>` (por ejemplo `post:812`, `voice_example:55`, `framework:19`, `memory:403`). Metadatos mínimos solo para filtrar (`profile_id`, `platform`, `kind`, `niche_key`). Sin `documents`. El texto sale de Postgres tras la búsqueda. Postgres es la fuente de verdad; `manage.py reindex_vectors` reconstruye todo Chroma desde Postgres.
- Embeddings: por defecto local con la función por defecto de Chroma (ONNX `all-MiniLM-L6-v2`, sin key; descarga el modelo la primera vez, avísalo en `docs/AI.md`), calculados en el cliente y pasados como `embeddings=`. Detrás de la interfaz `Embedder` para cambiarlos. Tests con un embedder determinista (hash) que no descarga nada.
- Video: comparar opciones y proponer una; ver T10. No se paga nada sin que Christian lo apruebe.
- Plataformas objetivo de generación: X, LinkedIn, Facebook. Se conservan TikTok e Instagram porque ya existen y no se quita funcionalidad.
- El agente no publica por su cuenta. La publicación la dispara el usuario desde el frontend (CONNECT). Tu agente puede proponer y guardar borradores.
- Sin handles, cuentas ni niches de Ateh fijos en prompts, constantes ni tools. El nicho es configuración por perfil (tabla `NichePreference` de tu app) y se deduce del perfil de voz y de lo que el usuario dice; si falta, el agente pregunta.

## 5. Estructura objetivo

```
lumi/lumi_ai/
  ports.py            Protocols: ProfileStore, PostStore, VoiceStore, ReportStore, MemoryStore, ChatStore,
                      TurnLogStore, EvalStore, SocialData, McpGateway, Embedder, VectorStore, VideoAnalyzer, Clock
  config.py           AIConfig (modelos, límites, umbrales) construida desde un dict que pasa Django
  providers/          chain.py (candidatos, fallback, cooldown por 402/429), groq.py, openrouter.py, openlux.py,
                      tiers.py, audio.py (Whisper), errors.py, usage.py
  agent/              loop.py, context.py, gates.py, turn_class.py, prompts.py, streaming.py, result.py
  tools/              registry.py + un módulo por grupo (las 20 tools, mismos nombres)
  style/              voice.py (extracción), schema.py (pydantic), questions.py, platform_voice.py
  competitors/        pipeline.py, extract.py, winners.py, own_lift.py, lift.py, synthesize.py, metrics.py, schemas/{peer,niche}.py
  rag/                embedder.py, vector_store.py (Chroma), voice_corpus.py, peer_corpus.py, memory.py, retrieval.py
  generation/         platforms.py (X, LinkedIn, Facebook, TikTok, Instagram), generate_post.py, repurpose.py,
                      enforcement.py, difficulty.py
  evaluation/         deterministic.py, judge.py (Jev -> Groq pequeño -> reglas), style_score.py, quality_gate.py, golden/
  video/              base.py, schema.py (VideoAnalysis), fake.py, <proveedor elegido>.py
  json_utils.py       extracción robusta de JSON (sustituye strip("`"))
  keys.py             sondas para check_keys
  tests/, fixtures/recorded/
lumi/apps/intelligence/
  models.py, repos.py, runtime.py, tasks.py, views.py, urls.py, apps.py, migrations/, tests/
```

## 6. Contratos con los otros bots

Con ARCHITECT:

- Te da (T2 de ARCHITECT): `docs/SCHEMA.md`, `docs/CONTRATOS.md`, el registro de keys (`apps.core.keys.register`) y la capa `apps/profiles/services.py` y `apps/chat/services.py`. Hasta que existan, trabaja `lumi_ai/` (no depende de Django) y dobles de prueba.
- Tú le das: `apps.intelligence.runtime.run_turn(profile_id, message) -> TurnResult`, `stream_turn(profile_id, message) -> AsyncIterator[SSEEvent]` (mismos eventos SSE que hoy: ver `lumi/docs/routers.md` y `lumi/app/routers/chat.py`), `apps.intelligence.tasks.bootstrap_profile(profile_id)`, `apps.intelligence.services.scan_trends(profile_id, ...)`.
- Tus modelos (en `apps/intelligence/models.py`) siguen `SCHEMA.md`: `VoiceProfile`, `VoiceProfileExample`, `StyleAnswer`, `NichePreference`, `PostTagging`, `NicheReport`, `Framework`, `RepurposeRequest`, `RepurposeAttempt`, `UserAction`, `TurnClassification`, `UserSearchRequest`, `MemoryNote`, `ProfileMemorySummary`, `GenerationEvaluation`, `VideoAnalysisRecord`. Si discrepas del esquema, propón el cambio en tu archivo de estado y avisa al orquestador antes de divergir.
- Aprobación de contrato: cuando ARCHITECT publique `CONTRATOS.md`, escribe en `estado/INTELLIGENCE.md` la línea `CONTRATO ARCHITECT ACEPTADO <sha>` o la lista de cambios pedidos, en 1 hora como máximo.

Con CONNECT:

- Te da `SocialData` (implementación en `apps/connections/socialdata.py`): `fetch_user_posts(platform, handle, since, limit)`, `search_posts(platform, query, limit)`, `get_user(platform, handle)`, `search_users(platform, query, limit)`, con presupuesto de créditos de Xpoz por ejecución (`XPOZ_RUN_CREDIT_BUDGET`) y errores tipados (`BudgetExceeded`, `ProviderUnavailable`, `RateLimited`). Y `McpGateway`: `list_tools(profile_id)`, `call(profile_id, name, args)`.
- Tú defines los `Protocol` de `SocialData` y `McpGateway` en `lumi_ai/ports.py` en T1, el primer commit, para que CONNECT implemente contra ellos sin esperar. Si CONNECT ya dejó una propuesta distinta en su estado, el orquestador arbitra.
- No llamas a Xpoz, Post for Me, Meta, LinkedIn ni X directamente desde `lumi_ai/`: todo pasa por `SocialData`.

## 7. Qué portas (origen, destino, tests que lo cubren)

| Origen en `lumi/app/` | Destino | Tests de referencia (en `lumi/tests/`) |
| --- | --- | --- |
| `agent/providers.py` | `lumi_ai/providers/` | `test_provider_fallback` (10) |
| `agent/loop.py` | `lumi_ai/agent/{loop,context,gates,streaming}.py` | `test_agent_claim_gate` (15), `test_agent_context` (8), `test_agent_tool_errors` (8), `test_context_budget` (11), `test_coverage_gate` (12), `test_loop_gates` (7), `test_prompt5_acceptance` (8) |
| `agent/turn_class.py`, `services/jev.py`, `services/turn_metrics.py` | `lumi_ai/agent/turn_class.py`, `lumi_ai/evaluation/judge.py` | `test_turn_class` (21), `test_jev_layer` (21), `test_tool_tiers` (18) |
| `agent/prompts.py` | `lumi_ai/agent/prompts.py` (sin Ateh, multiplataforma) | `test_prompt5_acceptance` |
| `tools/registry.py` y `tools/*.py` (excepto `connect.py`, `backfill.py`, `posts.py`, `activity.py`, `analytics.py`, `actions.py` que consultan datos: pasan por puertos) | `lumi_ai/tools/` | `test_registry` (4), `test_user_request_tool` (6), `test_memory` (11) |
| `tools/connect.py` | CONNECT lo reimplementa; tú dejas un puerto `ConnectionLinks.start_connect(profile_id, platform)` | — |
| `services/voice.py`, `voice_corpus.py` | `lumi_ai/style/`, `lumi_ai/rag/voice_corpus.py` | `test_voice` (5), `test_voice_corpus` (5), `test_voice_routes` (4), partes de `test_profile_extract_fixes` (27) sobre `analysis/metrics` |
| `services/chroma.py`, `memory.py`, `framework_corpus.py`, `peer_store.py` | `lumi_ai/rag/`, `apps/intelligence/repos.py` | `test_framework_corpus` (8), `test_peer_store` (7), `test_memory` (11), `test_voice_index_sqlite` (3, se descarta) |
| `services/peer_pipeline.py`, `analysis/*`, `schemas/{peer,niche}.py` | `lumi_ai/competitors/` | `test_peer_extract` (10), `test_peer_winners` (12), `test_peer_synthesize` (8), `test_peer_schemas` (8), `test_niche_schemas` (11), `test_peer_pipeline_wiring` (2) |
| `services/repurpose.py`, `repurpose_flow.py`, `enforcement.py`, `tools/repurpose.py`, `routers/repurpose.py` | `lumi_ai/generation/`, `apps/intelligence/views.py` | `test_repurpose` (11), `test_repurpose_endpoint` (17), `test_enforcement` (7) |
| `routers/voice.py` (Whisper) | `lumi_ai/providers/audio.py`, `apps/intelligence/views.py` | `test_voice_routes` |
| `background/bootstrap.py` | `apps/intelligence/tasks.py` | cubierto por `test_peer_pipeline_wiring` y tests nuevos |

Reglas de port: copia el comportamiento, no la forma. Cada test viejo se reescribe en `lumi_ai/tests/` (o `apps/intelligence/tests/` si toca la base) con el mismo caso y el mismo resultado esperado; los que usaban SQLite se rehacen con Postgres vía `pytest-django`. Cuando un test viejo codifique un defecto (por ejemplo el `strip("`")`), cámbialo y deja nota en `decisiones.tsv`.

## 8. Tareas en orden

### T0. Arranque (15 min)
`git fetch origin && git checkout lumi-orquestador`. Lee `lumi/plan/ContextoTareas.md`, `lumi/AGENTS.md`, `lumi/docs/{agent,tools,services,xpoz_optimization,blueprint-fix,profile_extract_audit}.md`, `system-arch-mds/*.md`. Crea `estado/INTELLIGENCE.md` y el TSV. Línea base: `cd lumi && GROQ_API_KEY=x OPENROUTER_API_KEY=x TYPESAFE_API_KEY=x NEATLOGS_API_KEY=x SECRET_KEY=x uv run pytest -q` (esperado: 418 pasan).

### T1. Esqueleto y puertos (Fase 1, primera hora) — bloquea a CONNECT
1. `uv add chromadb pydantic httpx openai` (lo que falte) y las dependencias de IA que uses; `lumi/lumi_ai/__init__.py`, `ports.py`, `config.py`, `json_utils.py`.
2. `ports.py`: todos los `Protocol` de la sección 5 con dataclasses de entrada y salida (`PostIn`, `PostOut`, `UserInfo`, `SocialDataError` y sus subclases). Documenta cada método con un docstring de una línea.
3. Commit y push inmediatos; reporte al orquestador con la lista de puertos.
Verifica: `uv run python -c "import lumi_ai.ports"`; `rg -n "django" lumi/lumi_ai` sin resultados.

### T2. Proveedores (2 h)
Porta `providers.py` a `lumi_ai/providers/` con: cadena configurable; reintento sin `reasoning_effort` ante 400; enfriamiento de un candidato tras 402/429 (no volver a probarlo en cada turno durante N minutos; configurable); errores tipados; registro de uso (tokens por llamada); `TIER_MODELS` configurable; respeto de `MAX_REQUEST_TOKENS`. Cliente de audio en `audio.py`. neatlogs opcional en `observability.py`. Sonda en `keys.py` para Groq, OpenRouter, OpenLux, Jev, neatlogs: lista de modelos del proveedor y una llamada de 1 token; avisa de modelos configurados que no existan.
Verifica: `uv run pytest lumi_ai/tests/providers -q` (casos de `test_provider_fallback` + 402, 429, cooldown, 400 de `reasoning_effort`); sin keys, `import lumi_ai.providers` no falla.

### T3. Loop del agente y tools (4-6 h, el bloque más grande)
1. Parte `loop.py` (1167 líneas) en `context.py` (ventana, presupuesto de tokens, recorte de contexto de tools), `gates.py` (afirmaciones sin tools, cobertura, escritura pendiente de MCP), `streaming.py` (eventos SSE), `loop.py` (orquestación). Mantén las constantes y los umbrales; muévelos a `AIConfig`.
2. `turn_class.py` y la capa Jev con la cadena de respaldo de la sección 4.
3. `prompts.py`: sin "@AtehOfficial", sin `DEFAULT_NICHE_HANDLES` y sin supuestos de solo-X. El prompt recibe plataforma(s) conectada(s), nicho y perfil de voz resumidos.
4. `tools/registry.py` y las 20 tools con los mismos nombres y parámetros. Las que tocan datos usan puertos. Añade el modo en el que una tool de MCP viene de `McpGateway`. `POST /trends/scan` (ARCHITECT lo expone) llama a la tool por el registro.
5. Cancelación y desconexión: el generador de streaming se cancela limpio y guarda referencia a sus tareas.
Verifica: `uv run pytest lumi_ai/tests/agent lumi_ai/tests/tools -q`; los casos de los 7 archivos de la tabla pasan; un test nuevo recorre un turno completo con proveedor falso que pide dos tools seguidas.

### T4. Pegamento con Django (2-3 h, requiere T4 y T5 de ARCHITECT)
`apps/intelligence/models.py` y migraciones según `SCHEMA.md`; `repos.py` (implementa los puertos con ORM, usando `apps.profiles.services`); `runtime.py` (`run_turn`, `stream_turn`: arma `AIConfig` desde settings, el contexto, llama al loop y persiste con `apps.chat.services`); `tasks.py` (`bootstrap_profile`); `views.py` y `urls.py` para `voice/transcribe` y `repurpose` (DRF, permisos por perfil); sondas registradas en `apps.py` (`ready()`).
Verifica: `uv run pytest apps/intelligence -q` con un proveedor falso; `uv run python manage.py makemigrations --check --dry-run`.

### T5. Perfil de estilo (2-3 h)
Porta `voice.py`: extracción desde posts auténticos (≥5), `reply_style` desde replies, retweets excluidos. Mejoras: (a) JSON robusto con `json_utils.extract_json` + validación pydantic + un reintento de reparación (adiós `strip("`")`); (b) perfil por plataforma opcional (`VoiceProfile.platform`, nulo = general) para que el tono de LinkedIn no contamine el de X; (c) arranque en frío: `answer_style_questions` produce un perfil válido sin posts, marcado `source=questions`, y se reemplaza cuando haya ≥5 posts; (d) "una voz actual por perfil" con transacción y `select_for_update`.
Verifica: `uv run pytest lumi_ai/tests/style apps/intelligence/tests/test_voice.py -q`.

### T6. RAG con ChromaDB, solo vectores (2-3 h)
`rag/vector_store.py`: interfaz `VectorStore` (`upsert(ids, embeddings, metadatas)`, `query(embedding, k, where)`, `delete(ids)`) con Chroma Cloud o local; **sin `documents`**. `embedder.py` y `retrieval.py` (consulta, recupera ids, pide los textos a Postgres). `voice_corpus.py` (ejemplos del usuario), `peer_corpus.py` (posts y frameworks de pares), `memory.py` (notas del agente y resumen continuo en Postgres, reemplazando `memory.md`). `manage.py reindex_vectors [--collection x]` (en `apps/intelligence/management/commands/`) que reconstruye Chroma desde Postgres.
Verifica: un Chroma falso que lanza excepción si recibe `documents=` y los tests pasan con él; `uv run pytest lumi_ai/tests/rag -q`; test de ida y vuelta: borra la colección, `reindex_vectors`, la consulta devuelve los mismos ids. Con Chroma local real (sin key) pasa también un test marcado `live`-local si el modelo ONNX está disponible.

### T7. Análisis de competidores (3-4 h)
Porta el pipeline completo (baseline 28 días, ganadores ≥1,5× mediana propia, etiquetado ciego, lift, síntesis) a `lumi_ai/competitors/` usando `SocialData` y los repos. Decisión pendiente que debes tomar con tests: conectar o descartar `schemas/niche.py` (`niche_registry`, `niche_key = slug:geo_scope`); si lo conectas, `niche_key` va en `NichePreference` y `NicheReport`. Respeta el presupuesto de créditos (`BudgetExceeded` se traduce en estado `insufficient_data` honesto). Limitación honesta: Xpoz cubre X; para LinkedIn y Facebook no hay API oficial de posts públicos de terceros, así que ahí el análisis parte de los posts propios conectados y de posts que el usuario pega (herramienta nueva `analyze_pasted_post(profile_id, platform, text, media_url=None)`). Documéntalo en `docs/AI.md`.
Verifica: `uv run pytest lumi_ai/tests/competitors -q` (casos de `test_peer_*`, `test_niche_schemas`); un test con `SocialData` falso que devuelve 40 posts y verifica ganadores, lift y estado `insufficient_data` cuando hay menos de los necesarios.

### T8. Generación por plataforma (3 h)
`generation/platforms.py` con reglas y límites de X, LinkedIn, Facebook (nueva: tono, largo recomendado, enlaces, hashtags, apertura) más TikTok e Instagram existentes. `generate_post(profile_id, platform, topic, goal, source=None)`: perfil de voz (de la plataforma, o el general) + ejemplos recuperados por RAG + frameworks ganadores del nicho + reglas de plataforma → borrador → `enforcement` → evaluación (T9) → hasta 2 regeneraciones guiadas por la crítica → resultado con borrador, razones y evaluación. Porta `repurpose.py`, `repurpose_flow.py`, `enforcement.py`, `difficulty.py`. Corrige: `repurpose_caption` guarda la solicitud antes de trabajar (que se guarde junto con el intento en una transacción, o con estado `pending` explícito), y el `strip("`")`. Nueva tool `generate_post` registrada; `repurpose_caption` sigue existiendo.
Verifica: `uv run pytest lumi_ai/tests/generation apps/intelligence/tests/test_repurpose_endpoint.py -q`; tests de límites por plataforma (X 280, LinkedIn 3000, Facebook definido por ti con fuente oficial citada en el código), `must_keep_phrases` preservadas.

### T9. Evaluación automática de calidad y estilo (3 h)
`evaluation/`: (a) comprobaciones deterministas (largo, frases obligatorias, patrones prohibidos como guiones largos, enlaces y menciones intactos); (b) `style_score`: similitud de embeddings con el corpus de voz del usuario más una rúbrica con LLM (fidelidad de voz, ajuste a plataforma, gancho, especificidad, sin tics de IA, sin datos inventados), cada criterio con puntaje y razón; (c) juez Jev con la cadena de respaldo; (d) `quality_gate`: umbrales configurables y decisión `pass|regenerate|fail`; (e) persistencia en `GenerationEvaluation`; (f) `manage.py ai_eval --suite golden [--live]`: corre un conjunto dorado (≥20 casos con etiqueta esperada, en `evaluation/golden/`, sintéticos y marcados como tales; la calibración con posts reales de Christian queda como pendiente) con respuestas grabadas, imprime métricas (acuerdo del juez con la etiqueta, tasa de regeneración) y sale con código ≠0 si caen bajo un umbral.
Verifica: `uv run pytest lumi_ai/tests/evaluation -q`; `uv run python manage.py ai_eval --suite golden` pasa sin keys con fixtures grabados.

### T10. Análisis de video multimodal (3-4 h; puede ir en paralelo a T7-T9)
1. `docs/VIDEO_API_COMPARISON.md`: compara con las páginas oficiales de hoy (anota fecha y URL de cada dato) al menos: Google Gemini API (comprensión de video nativa), Twelve Labs (Pegasus 1.5 y Marengo 3.5) y la opción modular (fotogramas + Groq Whisper + modelo de visión vía OpenRouter). Columnas: qué entiende (imagen, audio, texto en pantalla, JSON estructurado), duración máxima, precio por minuto, plan gratis y qué hacen con los datos del plan gratis, límites de tasa, latencia, términos de uso al analizar videos públicos de terceros, estabilidad del SDK, esfuerzo de integración. Datos de partida del orquestador (sin verificar, rehazlos): Gemini ~100 tokens/s a resolución baja y ~300 por defecto, File API 2 GB gratis, el plan gratis puede usar datos para mejorar productos, precios de lista aproximados de $0,0058/min (flash-lite) a $0,028/min (flash) según un cálculo de terceros; Twelve Labs con plan Free (3 GB), Plus $29 y Pro $99, y facturación nueva desde 2026-10-15.
2. Propón **una** opción con razones y costo por video de 60 s, y deja la decisión a Christian en un resumen de 10 líneas al inicio del archivo.
3. Implementa sin esperar: `VideoAnalyzer` (puerto), `VideoAnalysis` (duración, gancho de los primeros 3 s, transcripción, texto en pantalla, número de cortes, ritmo, presencia de subtítulos, llamada a la acción, formato), `fake.py` para tests, y el adaptador del proveedor propuesto detrás de `VIDEO_PROVIDER` y `VIDEO_API_KEY`. Sin `VIDEO_PROVIDER` la función está apagada. Cableado: los posts con video de los competidores pasan por `VideoAnalyzer` y su `VideoAnalysis` entra al etiquetado ciego como campo extra. Persistencia en `VideoAnalysisRecord` con caché por URL del medio y versión de prompt.
4. No actives ni pagues nada: habilitarlo exige la key y la aprobación de Christian. Sondas en `keys.py`.
Verifica: `uv run pytest lumi_ai/tests/video -q` con fixtures grabados; `docs/VIDEO_API_COMPARISON.md` existe con tabla y propuesta; con `VIDEO_PROVIDER` vacío el pipeline de competidores corre igual.

### T11. Sondas y pruebas `live` (1-2 h)
`lumi_ai/keys.py` registra en `apps.core.keys` (ARCHITECT): `groq`, `openrouter`, `openlux`, `typesafe`, `neatlogs`, `chroma`, `video`. Tests `@pytest.mark.live`: viaje completo de tool calling con Groq, OpenRouter con un modelo gratuito (revisa que el modelo exista), Whisper con un audio de 2 s en `fixtures/`, Chroma local, video (se omite sin key). Todos con presupuesto mínimo y un `skipif` si falta la key.
Verifica: sin keys `uv run pytest -m "not live"` pasa; `uv run python manage.py check_keys --only groq,openrouter,typesafe,neatlogs,chroma,openlux,video` muestra `OMITIDA` para lo que falta y no falla.

### T12. Documentación y revisión crítica (2 h)
`docs/AI.md`: diagrama de un turno de agente, proveedores y cadena, RAG (colecciones, ids, reindex), pipeline de competidores, generación, evaluación, video, qué cuesta cada cosa, qué se apaga sin cada key. Pasa `/interrogate` sobre `agent/loop.py`, `evaluation/quality_gate.py` y `rag/vector_store.py`; corrige los hallazgos aceptados.

## 9. Comprobaciones de aceptación (todas deben pasar)

```bash
cd lumi
uv run pytest -m "not live" lumi_ai apps/intelligence -q      # sin keys, sin red
uv run pytest -m "not live" -q                                # toda la suite junta con los otros bots
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py ai_eval --suite golden
uv run python manage.py reindex_vectors && uv run pytest lumi_ai/tests/rag -q
uv run python manage.py check_keys --only groq,openrouter,typesafe,neatlogs,chroma,openlux,video
rg -n "documents=" lumi/lumi_ai/rag                           # sin resultados
rg -n "AtehOfficial|ateh_x_connect|DEFAULT_NICHE_HANDLES" lumi/lumi_ai lumi/apps/intelligence   # sin resultados
rg -n "django" lumi/lumi_ai                                   # sin resultados
```

Con keys reales (solo si Christian ya las puso): `uv run pytest -m live -q` y `check_keys` en `OK` para Groq y OpenRouter. Sin keys, estos dos pasos quedan documentados como pendientes, no como hechos.

Cobertura de paridad: cada uno de los 418 tests viejos de tu zona tiene su equivalente o una razón escrita en `decisiones.tsv` para descartarlo.

## 10. Qué reportar

En cada reporte y en `estado/INTELLIGENCE.md`:

- SHA y rama; tareas T0-T12 hechas, en curso, bloqueadas.
- Salida resumida de los comandos de la sección 9.
- Para cada decisión grande (embeddings, `niche.py`, video): qué elegiste, qué descartaste, por qué y evidencia.
- La propuesta de video en 10 líneas, para que el orquestador se la pase a Christian.
- Riesgos: límites de Groq (~7.000 tokens), cuota de OpenRouter (402 con saldo vacío), modelo ONNX que se descarga, IDs de modelo que ya no existan, calidad del juez con datos sintéticos.
- Qué necesitas de ARCHITECT, CONNECT o Christian (por ejemplo, posts reales de Christian para calibrar la evaluación).
