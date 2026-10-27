# Estado de LUMI-INTELLIGENCE

Rama: `lumi-orquestador`. Última actualización: 2026-10-27 (T3 en curso).

## Línea base (T0)

- `GROQ_API_KEY=x OPENROUTER_API_KEY=x TYPESAFE_API_KEY=x NEATLOGS_API_KEY=x SECRET_KEY=x uv run pytest -q` en `b4d039a`: 418 pasan (7,6 s). Es la referencia de comportamiento del legado.

## Tareas

| Tarea | Estado | Nota |
| --- | --- | --- |
| T0 Arranque | hecha | Línea base de 418 tests; `estado/` creado. |
| T1 Esqueleto y puertos | hecha | `lumi_ai/ports.py` v1.0, `lumi_ai/config.py`, `lumi_ai/json_utils.py`, `lumi_ai/agent/result.py`. `uv run pytest lumi_ai -q`: 25 pasan. |
| T2 Proveedores | hecha | `lumi_ai/providers/{chain,factory,audio,errors,urls}.py`, `lumi_ai/observability.py`, `lumi_ai/keys.py` (`build_probes(config)`: groq, openrouter, openlux, jev, neatlogs, video). `uv run pytest lumi_ai -q`: 64 pasan, 0 se omiten. Las sondas no se ejecutaron contra proveedores reales (sin keys). |
| T3 Loop y tools | en curso | Hecho: `agent/{context,gates,turn_class}.py`, `judge/` (Jev → LLM pequeño), `tools/` (registry sin estado global + 12 tools con puerto). Falta: `agent/prompts.py`, `agent/loop.py`, `agent/streaming.py`, tests de integración con puertos falsos. Las tools de memoria, competidores, voz-extracción, repurpose y tendencias se registran en T5-T8 (traen su servicio). `uv run pytest lumi_ai -q`: 151 pasan, 0 se omiten. |
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

## Bloqueos

Ninguno por ahora.
