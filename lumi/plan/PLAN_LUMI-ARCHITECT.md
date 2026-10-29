# PLAN LUMI-ARCHITECT

Bot: LUMI-ARCHITECT (`fdf7d401-408a-46fc-b3b6-11fff0080f78`). Orquestador: Grok Bot. Plan escrito el 2026-10-27 sobre el commit `cce6ca3` de `main`.

Lee primero `lumi/plan/ContextoTareas.md` (estado, decisiones, fases, bloqueos). Este plan se ejecuta sin preguntar al usuario: si dudas en algo reversible, decide, anótalo en `decisiones.tsv` y sigue.

## 0. Protocolo común (idéntico en los tres planes)

- Una sola rama compartida: `lumi-orquestador`. `git fetch origin && git checkout lumi-orquestador`. Nunca `push --force`, nunca merge a `main`, nunca deploy, nunca abrir PR (el orquestador abre un Draft PR al final).
- Commits en tu ámbito de archivos, en español, formato `[ARCHITECT] área: qué cambió`. Commitea al terminar cada tarea o cambio importante y como mínimo cada hora de trabajo. Antes de cada push: `git pull --rebase origin lumi-orquestador`, corre los tests de tu ámbito y luego `git push origin lumi-orquestador`.
- Conflictos: si el conflicto toca archivos fuera de tu ámbito, no lo resuelvas a ciegas; conserva la versión del dueño y avisa al orquestador. Conflicto en `lumi/uv.lock`: `git checkout --theirs uv.lock && uv lock`, y commitea el resultado. Cualquier bot puede añadir sus dependencias con `uv add` en `pyproject.toml`; nada más de ese archivo.
- Estado propio: `lumi/plan/estado/ARCHITECT.md` (qué terminaste, qué sigue, bloqueos, SHA del último commit verde) y `lumi/plan/estado/ARCHITECT-decisiones.tsv` (una fila por decisión: fecha, qué, por qué, evidencia, resultado; skill `/show-me-your-work`). Actualízalos en cada commit.
- Reporte al orquestador al cambiar de fase y ante cualquier bloqueo, con: fase, SHA, tareas hechas, comandos de verificación que corriste con su resultado, riesgos y qué necesitas de otro bot.
- Skills permitidas: `/architect`, `/tdd`, `/blast-radius`, `/correct`, `/show-me-your-work`, `/figure-it-out`, `/how`, `/why`, `/create-verification-skill`, `/interrogate`. Prohibida `/arena` (consume demasiado). Aplica `/correct` en todo el trabajo de repo y `/unslop` en lo que escribas para personas.
- Seguridad: nunca escribas valores de keys en archivos, commits, logs ni salidas. Los docs solo nombran variables. No uses la box para gastar créditos de Xpoz, X ni ninguna cuota de pago.
- Límite de uso: no pases el límite semanal Premium de Christian. Sin créditos extra ni cargos. Si el límite se llena, detente y reporta.
- Idioma: docs para Christian en español. Código, identificadores y docstrings en inglés (como el repo actual). Con Christian, español.
- No cambies código fuera de tu ámbito (sección 2). Si necesitas un cambio ahí, pídelo al dueño en tu reporte o en su archivo de estado.

## 1. Misión

Dejar la base del backend Django + DRF sobre PostgreSQL con un esquema normalizado y verificable, y los contratos que permiten a LUMI-INTELLIGENCE y LUMI-CONNECT trabajar en paralelo sin pisarse. Portas lo que hoy hace `lumi/app/` (FastAPI + SQLModel + Alembic) conservando toda la funcionalidad, y al final eliminas el código FastAPI. Los tests existentes en `lumi/tests/` son la referencia de comportamiento.

Entregas centrales:

1. Proyecto Django (`lumi/config/`, `lumi/apps/`) que arranca con `docker compose up` y con `manage.py runserver`.
2. Esquema Postgres normalizado (3NF donde tenga sentido), con índices y restricciones, y migraciones Django.
3. Importador de datos del esquema legado con verificación de que no se pierde nada.
4. Autenticación, permisos por usuario, CORS cerrado, errores uniformes, OpenAPI.
5. `manage.py check_keys`, validación de keys obligatorias al arrancar y la política de keys opcionales.
6. Contratos escritos (`lumi/docs/SCHEMA.md`, `lumi/docs/CONTRATOS.md`) para los otros dos bots.
7. Retiro de FastAPI/Alembic/SQLite cuando haya paridad demostrada.

## 2. Ámbito de archivos

Tuyos (puedes crear y editar):

- `lumi/manage.py`, `lumi/config/**`
- `lumi/apps/core/**`, `lumi/apps/accounts/**`, `lumi/apps/profiles/**`, `lumi/apps/chat/**`
- `lumi/pyproject.toml` (dependencias propias; los otros solo añaden las suyas con `uv add`), `lumi/uv.lock`, `lumi/pytest.ini` o la sección de pytest en `pyproject.toml`, configuración de ruff
- `lumi/Dockerfile`, `lumi/docker-compose.yml`, `lumi/.dockerignore`, `lumi/railway.json`, `lumi/scripts/dev_postgres.py`
- `lumi/.env.example` (tú eres el único dueño del archivo; cada bot tiene su bloque entre marcadores `# --- INTELLIGENCE ---` / `# --- CONNECT ---` y puede editar solo su bloque)
- `lumi/docs/SCHEMA.md`, `lumi/docs/CONTRATOS.md`, `lumi/docs/ADR-*.md`, `lumi/docs/MIGRACION_LEGADA.md`
- `lumi/plan/estado/ARCHITECT*.{md,tsv}`
- `.github/workflows/ci.yml` (crearlo; solo CI)
- Al final (T12): borrar `lumi/app/`, `lumi/alembic/`, `lumi/alembic.ini`, `lumi/tests/` (los tests viejos), `lumi/mvp/`, `lumi/_purge_p16.py` si existiera, y `lumi/.agents/` solo si quedó obsoleto (conserva `hooks.json` si sigue sirviendo, sin `where.exe`).

No toques (son de otro bot): `lumi/lumi_ai/**`, `lumi/apps/intelligence/**` (INTELLIGENCE); `lumi/apps/connections/**`, `lumi/frontend/**`, `frontend/**`, `lumi/docs/MUSE.md` (CONNECT); `lumi/plan/ContextoTareas.md`, `lumi/plan/PLAN_*.md`, `lumi/docs/API_KEYS.md`, `lumi/docs/AGENT_KEYS_SETUP.md` (orquestador).

Regla de integración: `config/urls.py` incluye desde el día 1 `apps.accounts.urls`, `apps.profiles.urls`, `apps.chat.urls`, `apps.intelligence.urls` y `apps.connections.urls` (crea un `urls.py` vacío y un `apps.py` mínimo en las apps ajenas solo si aún no existen, con un commit `[ARCHITECT] andamio: ...` que los dueños sobrescriben libremente).

## 3. Estado actual que debes conocer (verificado en `cce6ca3`)

- Backend FastAPI: ~12.200 líneas en `lumi/app/` (agent 5, tools 14, services 21, models 15, routers 10, analysis 8, background 4, schemas 3). 40 archivos de test, 418 tests. Sin keys: 17 fallan y 3 dan error porque `Settings` exige GROQ, OPENROUTER, TYPESAFE, NEATLOGS y SECRET_KEY sin default; con variables ficticias pasan los 418 en ~5 s (`cd lumi && GROQ_API_KEY=x OPENROUTER_API_KEY=x TYPESAFE_API_KEY=x NEATLOGS_API_KEY=x SECRET_KEY=x uv run pytest -q`).
- 9 archivos de test usan SQLite y hay que reescribirlos para Postgres: `test_handle_search_mvp`, `test_handle_search_platforms`, `test_mcp`, `test_peer_pipeline_wiring`, `test_peer_store`, `test_profile_extract_fixes`, `test_repurpose_endpoint`, `test_user_request_tool`, `test_voice_index_sqlite` (este último se descarta: probaba un bug de SQLite).
- 21 tablas (modelos en `lumi/app/models/*.py`): `profiles`, `profile_snapshots`, `profile_baseline`, `posts`, `metric_snapshots`, `own_post_analysis`, `listening_matches`, `user_activity`, `user_search_requests`, `voice_profiles`, `style_answers`, `repurpose_requests`, `repurpose_attempts`, `user_actions`, `poll_config`, `chat_messages`, `turn_classifications`, `mcp_auth_accounts`, `peer_frameworks`, `niche_framework_reports`, `post_taggings`.
- 23 rutas REST en 9 routers (+ `/health`). Ver la tabla de la sección 6.
- No existen Dockerfile ni docker-compose. La box de desarrollo del orquestador no tiene Docker ni Postgres; sí tiene `sudo apt-get`. Verificado el 2026-10-27: `uv run --no-project --with pgserver python -c ...` levanta un PostgreSQL 16.2 real por socket Unix. Úsalo para `scripts/dev_postgres.py` (no es fallback a SQLite: es Postgres).
- Defectos que debes corregir en el port (referencias en el código viejo):
  - `profiles` mezcla usuario y cuenta conectada; `pfm_account_id` es único y NOT NULL; `handle` no es único.
  - `routers/profiles.py:51-52` filtra perfiles a los handles/PFM ids de Ateh; `seed.py` fija la cuenta @AtehOfficial y pisa nombre y handle; `USER_HANDLES`/`USER_PFM_IDS` son constantes muertas.
  - `SECRET_KEY` obligatoria y sin uso; sin autenticación; CORS `*`.
  - N+1: `routers/alerts.py:44-49`, `profiles.py:74-75` (2N+1), `listening.py:71-73` (`check_trending`), `chat.py:113-115` (borrado fila a fila).
  - `GET /profiles/{id}/analytics` tiene efectos secundarios.
  - `listening_matches.alerted_at`/`alert_dismissed` nunca se escriben; "alert once" es leer-comprobar-escribir (no atómico).
  - Enums `ChatRole`/`UserActionType` se guardan en MAYÚSCULAS (nombre, no valor).
  - `style_answers` es solo escritura y no tiene unique (profile_id, question_key).
  - Timestamps `UTCDateTime` sin `server_default`; riesgo de datetime naive/aware en el poller.
  - Estado OAuth `state` y escrituras pendientes de MCP en memoria del proceso (se rompen con varios workers).
  - `hooks.json` usa `where.exe` (solo Windows).
  - `railway.json` (Railpack, `preDeployCommand` alembic, healthcheck `/health`): ajústalo, pero NO se despliega.

## 4. Decisiones fijas que aplican a todo

- Django + DRF, sin FastAPI en paralelo. Python 3.12. Gestor `uv`. Django 5.2 LTS salvo que `uv add` demuestre incompatibilidad con DRF o drf-spectacular; registra la elección en `docs/ADR-0001-stack.md`.
- PostgreSQL es la única base (dev, tests, prod). Sin SQLite en ningún camino. `DATABASE_URL` obligatoria; si falta, el arranque falla con un mensaje claro que dice cómo obtenerla. Formato Django (`postgresql://...`, sin `+asyncpg`). Acepta también el URI de `pgserver` (`postgresql://postgres:@/postgres?host=/ruta/socket`); si `dj-database-url` no lo parsea, escribe un parser propio en `apps/core/env.py` y pruébalo.
- ChromaDB guarda solo vectores con ids que referencian filas de Postgres. Postgres es la fuente de verdad del texto. Lo implementa INTELLIGENCE; tú dejas en el esquema las tablas donde ahora vive ese texto.
- Un solo usuario no es suficiente: añade usuarios y propiedad de datos desde el principio.
- ASGI: uvicorn. Las vistas de chat y streaming son vistas async de Django; el resto, DRF.
- Tareas en segundo plano: evalúa Celery + Redis frente a una cola en Postgres (django-tasks) en `docs/ADR-0002-tareas.md` en la tarea T9. Recomendación inicial: Celery + Redis + Celery Beat, porque hay tareas periódicas (poller), reintentos y varios workers; en tests, ejecución síncrona (`CELERY_TASK_ALWAYS_EAGER`). Cualquier estado compartido (OAuth `state`, escrituras pendientes de MCP) va a Postgres o a la caché de Django respaldada por Redis, nunca a memoria del proceso.
- Política de keys (aplícala en `apps/core/keys.py`):
  - Obligatorias: `DATABASE_URL`, `SECRET_KEY`, `TOKEN_ENCRYPTION_KEY`, `GROQ_API_KEY`. `OPENROUTER_API_KEY` es opcional (respaldo de Groq).
  - Opcionales con aviso `WARNING` al arrancar: `TYPESAFE_API_KEY`, `NEATLOGS_API_KEY` (hoy obligatorias; se relajan), `PFM_JWT_TOKEN`, `XPOZ_API_KEY`, `XPOZ_API_KEY_2`, `OPENLUX_*`, `CHROMA_*`, `META_*`, `LINKEDIN_*`, `X_*`, `VIDEO_*`, `GOOGLE_OAUTH_*`.
  - Con `DJANGO_SETTINGS_MODULE=config.settings.test` nada de eso es necesario salvo `DATABASE_URL`.
  - Nombres definitivos en `lumi/docs/API_KEYS.md` (lo mantiene el orquestador; avísale si añades o renombras alguna).

## 5. Estructura objetivo (tu parte)

```
lumi/
  manage.py
  config/{__init__,urls,asgi,wsgi,celery}.py
  config/settings/{base,dev,test,prod}.py
  apps/core/       env.py, keys.py, errors.py, pagination.py, models.py (TimestampedModel),
                   health.py, management/commands/{check_keys,import_legacy,verify_legacy_import,seed_demo}.py
  apps/accounts/   User (login por email), token auth, permisos
  apps/profiles/   SocialProfile, ProfileSnapshot, ProfileBaseline, PollConfig, SocialHandle, Post, MetricSnapshot,
                   Alert, ListeningMatch, services.py (contrato), analytics.py, tasks.py (poller), views/serializers/urls
  apps/chat/       ChatMessage, services.py (contrato), views (chat, stream, history, title), urls
  scripts/dev_postgres.py
  Dockerfile, docker-compose.yml (db, redis, web, worker, beat)
```

## 6. Mapa de rutas (legado → nuevo)

Prefijo nuevo `/api/v1/`; `/health` queda en la raíz. Mismas funciones, mismos cuerpos salvo lo indicado. Publica el OpenAPI con `drf-spectacular` en `/api/schema/` y `/api/docs/`.

| Legado | Nuevo | Dueño de la vista |
| --- | --- | --- |
| `POST /chat`, `POST /chat/stream` (SSE), `GET /chat/history`, `DELETE /chat/history`, `POST /chat/title` | `/api/v1/chat`, `/api/v1/chat/stream`, `/api/v1/chat/history`, `/api/v1/chat/title` | ARCHITECT (llama a `apps.intelligence.runtime`) |
| `GET /profiles`, `POST /profiles/{id}/select` | `/api/v1/profiles`, `/api/v1/profiles/{id}/select` | ARCHITECT |
| `GET /profiles/{id}/analytics` (con efectos secundarios) | `GET /api/v1/profiles/{id}/analytics` (solo lectura) + `POST /api/v1/profiles/{id}/refresh` (efectos) | ARCHITECT |
| `GET /profiles/{id}/alerts/unread` | `/api/v1/profiles/{id}/alerts/unread` | ARCHITECT |
| `GET /trends/matches`, `POST /trends/scan` | `/api/v1/trends/matches`, `/api/v1/trends/scan` (pasa por el registro de tools, no lo evita) | ARCHITECT (llama a INTELLIGENCE) |
| `POST /pfm/connect`, `GET /pfm/callback` | `/api/v1/connections/pfm/connect` y `POST /api/v1/connections/pfm/sync` (PFM no manda `state`: la página del frontend llama al sync; `pfm/callback` responde `400 connections.unsupported`) | CONNECT |
| `GET /mcp/google/{connect,callback,status}` | `POST /api/v1/connections/google/connect`, `POST /api/v1/connections/google/callback` (autenticada: la llama la página del frontend con `{state, code}` y el Token del usuario) y `GET /api/v1/connections/google/status`. No hay callback público del backend. | CONNECT |
| `GET /handles/search`, `GET /handles/saved`, `POST /handles/select`, `GET /handles/stats` | `/api/v1/handles/{search,saved,select,stats}` | CONNECT (modelo `SocialHandle` es tuyo) |
| `POST /voice/transcribe` | `/api/v1/voice/transcribe` | INTELLIGENCE |
| `POST /repurpose` | `/api/v1/repurpose` | INTELLIGENCE |
| `GET /health` | `/health` | ARCHITECT |
| (nuevo) | `/api/v1/auth/{register,login,logout,me}` | ARCHITECT |

Los nombres y cuerpos reales los fijas en `docs/CONTRATOS.md` leyendo `lumi/app/routers/*.py` y `lumi/docs/routers.md`.

## 7. Tareas en orden

Cada tarea termina con commit y push. "Verifica" indica el comando que debe pasar antes de marcarla hecha.

### T0. Arranque (15 min)
1. `git fetch origin && git checkout lumi-orquestador`. Lee `lumi/plan/ContextoTareas.md`, `lumi/AGENTS.md`, `lumi/.agents/database.md`, `lumi/.agents/api-endpoints.md`, `lumi/docs/models.md`, `lumi/docs/routers.md`.
2. Crea `lumi/plan/estado/ARCHITECT.md` y `ARCHITECT-decisiones.tsv`.
3. Corre los 418 tests viejos con variables ficticias para fijar la línea base y anota el resultado en el estado.

### T1. Esqueleto Django y entorno (Fase 1, 1-2 h)
1. `uv add django djangorestframework drf-spectacular django-cors-headers "psycopg[binary,pool]" cryptography uvicorn whitenoise celery redis` y de desarrollo `pytest pytest-django pytest-asyncio factory-boy`. Mantén las dependencias del código viejo hasta T12.
2. `lumi/manage.py`, `lumi/config/settings/{base,dev,test,prod}.py`, `lumi/config/urls.py`, `asgi.py`, `wsgi.py`.
3. `apps/core/env.py` (lectura tipada de variables, parser de `DATABASE_URL`), `apps/core/keys.py` (registro `KeySpec(nombre, variables, obligatoria, sonda)`; `validate_required()` lista todas las que faltan de una vez; las apps ajenas registran sus claves y sondas en su `AppConfig.ready()`), `apps/core/health.py` (`GET /health`: base de datos, migraciones al día, versión).
4. `scripts/dev_postgres.py`: levanta Postgres real con `pgserver`, crea la base `lumi`, imprime el `DATABASE_URL`.
5. `Dockerfile`, `docker-compose.yml` (servicios `db` postgres:16 con healthcheck y volumen, `redis`, `web`, `worker`, `beat`), `.env.example` por bloques, `.dockerignore`.
6. `pytest` configurado: `DJANGO_SETTINGS_MODULE=config.settings.test`, marcador `live` (excluido por defecto con `-m "not live"`), `--reuse-db` opcional.
Verifica: `uv run python scripts/dev_postgres.py` imprime una URL; con ella en `DATABASE_URL`, `uv run python manage.py check` y `migrate` pasan; `GET /health` responde 200; sin `DATABASE_URL`, `manage.py runserver` falla con un error que nombra la variable.

### T2. Contratos (Fase 1 cierre, 1-2 h) — bloquea a los otros dos
1. `docs/SCHEMA.md`: esquema final con tabla, columnas, tipos, claves, índices, restricciones, dueño de la app y mapa columna a columna desde el esquema legado (sección 8).
2. `docs/CONTRATOS.md`: (a) rutas y cuerpos de la API (sección 6); (b) firmas de la capa de servicios (sección 9); (c) hooks del registro de keys; (d) convenciones de tests y de fixtures; (e) quién crea qué migración.
3. Commit y reporte al orquestador. LUMI-INTELLIGENCE y LUMI-CONNECT lo aprueban por escrito en sus archivos de estado (`estado/INTELLIGENCE.md`, `estado/CONNECT.md`, línea `CONTRATO ARCHITECT ACEPTADO <sha>`). Si piden cambios, aplícalos antes de T3. No esperes más de 1 h por la aprobación: si no llega, sigue con lo que no cambia el contrato y avisa al orquestador.

### T3. Cuentas y permisos (1 h)
`apps/accounts`: `User` con email único, tokens DRF (`rest_framework.authtoken`), endpoints `/api/v1/auth/*`, clase `IsOwner`/`IsProfileOwner` para recursos por `profile_id`, `CORS_ALLOWED_ORIGINS` desde entorno (sin `*`), manejador de errores uniforme `{"error": {"code", "message"}}` en `apps/core/errors.py`. Comando `seed_demo` que crea un usuario y un perfil genérico desde variables `DEMO_*` o argumentos (sin handles de Ateh).
Verifica: tests de registro, login, acceso denegado a perfil ajeno (403/404), CORS.

### T4. Modelos y migraciones de `profiles` y `chat` (2-3 h)
Implementa `docs/SCHEMA.md`. Usa `TextChoices` en minúsculas, `db_index`/`Meta.indexes` y `constraints` (`UniqueConstraint`, `CheckConstraint`, `UniqueConstraint(condition=...)` para "una voz actual por perfil"), `DateTimeField(auto_now_add)` con zona horaria, FKs con `on_delete` explícito. Migraciones con nombres descriptivos y sin `RunPython` irreversible sin `reverse_code`.
Verifica: `manage.py makemigrations --check --dry-run` limpio; `migrate` desde cero y `migrate apps.profiles zero` OK; tests de restricciones (violaciones levantan `IntegrityError`).

### T5. Capa de servicios (contrato) y consultas sin N+1 (2 h)
`apps/profiles/services.py` y `apps/chat/services.py` con las firmas de la sección 9. Vistas de `profiles`, `alerts`, `trends/matches`, `analytics`, `refresh` con `select_related`/`prefetch_related`/agregaciones. Alerta única con `UPDATE ... WHERE alerted_at IS NULL` atómico. Borrado de historial en una sola consulta.
Verifica: tests con `django_assert_max_num_queries` para cada vista de lista (consulta constante respecto al número de filas); test de concurrencia de "alert once" con dos hilos.

### T6. Port de analytics y spikes (1-2 h)
Porta `lumi/app/services/analytics.py` (282 líneas), `lumi/app/services/metrics.py` (`current_and_baseline_velocity`, `detect_spike`) a `apps/profiles/analytics.py`. Reutiliza `lumi/tests/test_metrics.py` (7 tests) adaptándolo a Django.
Verifica: `uv run pytest apps/profiles -q`.

### T7. Chat (vistas) (2 h)
`apps/chat/views.py`: `POST chat` (JSON), `POST chat/stream` (SSE, vista async, `StreamingHttpResponse`; maneja desconexión del cliente y cancela la tarea; guarda referencia a las tareas), `history`, `title`. Todo llama a `apps.intelligence.runtime.run_turn/stream_turn` (INTELLIGENCE; mientras no exista, un doble de prueba en `apps/chat/tests/fakes.py`). Persistencia de mensajes en `ChatMessage` vía `apps/chat/services.py`.
Verifica: tests con el doble de prueba, incluido el formato de eventos SSE actual (`lumi/docs/routers.md`, `lumi/tests/` de chat si existe).

### T8. Importador legado y verificación sin pérdida (2-3 h)
1. `docs/MIGRACION_LEGADA.md`: mapa tabla/columna legado → nuevo (de SCHEMA.md), transformaciones (enums en MAYÚSCULAS a minúsculas, `profiles` a `User`+`SocialProfile`, handles a `SocialHandle`, payloads JSON a tablas hijas) y qué datos no se migran y por qué.
2. `manage.py import_legacy --source $LEGACY_DATABASE_URL [--dry-run]`: lee el origen legado en solo lectura. Acepta SQLite (`sqlite:////ruta/lumi.db`, el caso real: los datos poblados existen como archivo `lumi.db`; ver `lumi/docs/DATA_IMPORT.md`) y Postgres (`postgresql://`, con psycopg), escribe en el esquema nuevo en una transacción por tabla, es idempotente (se puede repetir) y soporta orígenes sin usuarios creando un usuario "importado".
3. `manage.py verify_legacy_import --source ...`: por tabla compara conteos y una suma de verificación determinista por columnas mapeadas; sale con código distinto de 0 si algo difiere. Imprime una tabla.
4. Prueba automática: genera el DDL legado con `alembic upgrade head --sql` (o `pg_dump -s`; guárdalo en `apps/core/tests/fixtures/legacy_schema.sql`), carga filas de ejemplo en una base temporal (un `lumi.db` SQLite de prueba y también un Postgres), importa, verifica y repite para comprobar idempotencia. Hazlo mientras `alembic/` siga en el repo.
Verifica: `uv run pytest apps/core/tests/test_import_legacy.py -q` pasa; `verify_legacy_import` devuelve 0 sobre los datos de ejemplo.

### T9. Tareas en segundo plano (1-2 h)
1. `docs/ADR-0002-tareas.md` con la comparación y la decisión.
2. `config/celery.py`, `apps/profiles/tasks.py`: el poller de `lumi/app/background/poller.py` como tarea periódica (cada tick: ingest de perfiles, spikes, alertas, bootstrap). Llama a `apps.connections.ingest.sync_profile(profile_id)` (CONNECT) y `apps.intelligence.tasks.bootstrap_profile(profile_id)` (INTELLIGENCE); mientras no existan, dobles de prueba. Corrige el riesgo datetime naive/aware y la cooldown por perfil.
Verifica: test del poller con `CELERY_TASK_ALWAYS_EAGER`; `docker compose config` válido (si hay Docker) o `python -c "import yaml; yaml.safe_load(open('docker-compose.yml'))"`.

### T10. `check_keys` y política de keys (1-2 h)
`manage.py check_keys [--only a,b] [--json]`: itera el registro, hace la llamada mínima real de cada sonda, imprime `OK`/`OMITIDA`/error exacto, nunca imprime valores. Sondas propias: base de datos, `SECRET_KEY` y `TOKEN_ENCRYPTION_KEY` (cifra y descifra un valor de prueba), Redis. Las demás las registran INTELLIGENCE y CONNECT; en T10 verifica que aparecen.
Verifica: tests con sondas simuladas (sin red); `uv run python manage.py check_keys` con un `.env` vacío imprime todas las obligatorias faltantes juntas y sale con código 1.

### T11. CI y calidad (1 h)
`.github/workflows/ci.yml`: Postgres como servicio, `uv sync`, `ruff check`, `pytest -m "not live"`. Sin secretos. `ruff format --check`. Hook de pre-commit multiplataforma si conservas `hooks.json`.

### T12. Retiro del código legado (al final, solo con paridad)
Condiciones: (a) los tests portados de los tres bots pasan; (b) `verify_legacy_import` devuelve 0; (c) la matriz de paridad (sección 10) está completa y firmada en `estado/ARCHITECT.md`. Entonces: borra `lumi/app/`, `lumi/alembic/`, `lumi/alembic.ini`, `lumi/tests/` viejos, `lumi/mvp/`, dependencias `fastapi sqlmodel alembic aiosqlite asyncpg` de `pyproject.toml`; actualiza `railway.json` (comando de arranque Django/uvicorn, `preDeployCommand: python manage.py migrate`, healthcheck `/health`; no despliegues). Coordina con el orquestador antes de borrar y confirma que los otros bots ya no importan nada de `app.`.
Verifica: `rg -n "from app\.|import app\b|fastapi|sqlmodel|alembic|sqlite" lumi --glob '!lumi/plan/**' --glob '!lumi/docs/**'` sin resultados (aparte de menciones en docs históricos).

## 8. Esquema: reglas y propuesta de partida

Tú decides el diseño final y lo documentas en `SCHEMA.md`. Restricciones: sin pérdida de datos; los tests de comportamiento siguen en verde; el contrato (sección 9) no cambia sin avisar. Propuesta de partida, basada en defectos reales:

1. `profiles` se divide: `accounts.User` (identidad) y `profiles.SocialProfile` (`user` FK, `platform`, `handle` normalizado, `display_name`, `external_account_id`, `provider` `pfm|native`, `timezone`, `timezone_source`). Unicidad: (`user`, `platform`, `handle_normalized`). La conexión OAuth vive en `connections.ConnectedAccount` (CONNECT), 1:1 opcional con `SocialProfile`.
2. Handles como texto repetido (`listening_matches.author_handle`, `post_taggings.handle`, `user_search_requests.handle`, `handle_mappings` en Chroma) pasan a `SocialHandle` (`platform`, `handle_normalized`, `display_name`, `avatar_url`, `follower_count`, `source`, `last_seen_at`; único por plataforma+handle). Es la tabla `social_handles` planeada en `lumi/docs/xpoz_optimization.md`.
3. `post_taggings.post_id` es un string sin FK (posts de pares que hoy solo viven en Chroma). Crea una sola tabla `Post` con `author` FK a `SocialHandle` y `kind` (`original|reply|retweet|quote`); el post propio es el que tiene `author` igual al handle del perfil. Los posts de pares dejan de vivir solo en Chroma.
4. `listening_matches` duplica texto y métricas de posts. Pasa a ser una tabla puente `ListeningMatch(profile, post, discovered_at, score)` sin copiar caption ni métricas (las métricas están en `MetricSnapshot`).
5. `posts.alerted_at/alert_dismissed` y los campos nunca escritos de `listening_matches` pasan a `Alert(profile, post, kind, created_at, dismissed_at)` con `UniqueConstraint(profile, post, kind)` y índice parcial de no leídas.
6. `own_post_analysis` y `post_taggings` tienen la misma forma (post, versión de prompt, estado, análisis JSON): unifícalas en `PostTagging(post FK, prompt_version, status, analysis JSONB, ...)` con único (`post`, `prompt_version`). Esta tabla es de INTELLIGENCE (app `intelligence`), pero tú defines su FK a `Post` en SCHEMA.md.
7. `peer_frameworks.payload` y `niche_framework_reports.payload` (JSON duplicado): `NicheReport` + `Framework` (FK al reporte, nombre, descripción, evidencia, lift). `payload` JSONB solo para la salida cruda validada del modelo. Tablas de INTELLIGENCE; tú fijas las claves en SCHEMA.md.
8. `voice_profiles.example_post_ids` (JSON sin FK) a M2M `VoiceProfileExample`; `UniqueConstraint(profile, is_current)` condicional (`is_current = true`). Reemplaza el "voltear antes de insertar con flush" por una transacción con `select_for_update`.
9. `style_answers`: único (`profile`, `question_key`) con upsert, y enumera quién lo lee (hoy nadie).
10. `poll_config` pasa a `OneToOneField(SocialProfile)`; `profile_baseline` con índice (`profile`, `computed_at` desc) y método `latest()`.
11. `chat_messages`: `TextChoices` para `role` en minúsculas, índice (`profile`, `id`), `tool_calls` JSONB con su forma documentada; evalúa `ToolExecution` como tabla hija si hay consultas por herramienta. `turn_classifications` con FK a `ChatMessage` y JSONB solo para `jev_probs` y `timings`.
12. `metric_snapshots`: único (`post`, `captured_at`) e índice descendente (el hook `include_object` de Alembic que lo salta en SQLite desaparece); añade `bookmarks` y `quotes` si Xpoz los entrega (ver `docs/xpoz_optimization.md`).
13. Enums de columnas con valores libres (plataformas, estados, `kind_source`, `route_label`) a `TextChoices` con `CheckConstraint`.
14. Todos los timestamps con zona horaria; `created_at`/`updated_at` heredados de `TimestampedModel`.
15. `mcp_auth_accounts`: el modelo es de CONNECT (hoy guarda los tokens en texto plano; deben ir cifrados con `TOKEN_ENCRYPTION_KEY`). Reserva el nombre en SCHEMA.md.
16. `agent_memory`/`memory.md`: tabla `MemoryNote` (INTELLIGENCE) y `ProfileMemorySummary` 1:1 por perfil reemplazan el archivo `memory.md` (hoy ignorado por git).

Para cada cambio: documenta la forma antigua, la nueva y la transformación del importador.

## 9. Contrato de servicios que debes publicar (firmas mínimas, ajústalas en CONTRATOS.md)

`apps/profiles/services.py` (síncronas con variantes async `a*` o `sync_to_async` explícito; los datos salen como `dataclass` o `TypedDict`, no como instancias ORM):

- `get_profile(profile_id, user_id=None)`, `list_profiles(user_id)`, `select_profile(user_id, profile_id)`
- `list_posts(profile_id, *, kind=None, since=None, limit=50, include_deleted=False)`
- `upsert_posts(profile_id, posts: list[PostIn]) -> UpsertResult` (idempotente por plataforma+id externo)
- `append_metric_snapshots(post_id, snapshots)`, `latest_baseline(profile_id)`, `save_baseline(profile_id, ...)`
- `get_or_create_handle(platform, handle, **datos) -> SocialHandle`
- `record_listening_match(profile_id, post_id, score)`, `create_alert_once(profile_id, post_id, kind) -> bool`, `unread_alerts(profile_id)`, `dismiss_alert(alert_id)`
- `get_poll_config(profile_id)`, `set_poll_config(...)`

`apps/chat/services.py`: `append_message(profile_id, role, content, ...)`, `history(profile_id, limit)`, `clear_history(profile_id)`, `set_title(...)`.

Lo que consumes de los otros (los definen ellos; usa dobles hasta que existan):

- INTELLIGENCE: `apps.intelligence.runtime.run_turn(profile_id, message) -> TurnResult`, `stream_turn(profile_id, message) -> AsyncIterator[SSEEvent]`, `apps.intelligence.tasks.bootstrap_profile(profile_id)`, `apps.intelligence.services.scan_trends(profile_id, ...)`.
- CONNECT: `apps.connections.ingest.sync_profile(profile_id)`, `apps.connections.keys` (sondas), vistas propias.

## 10. Matriz de paridad (obligatoria antes de T12)

Crea en `estado/ARCHITECT.md` una tabla con una fila por cada una de las 23 rutas, las 21 tablas y las 20 tools nativas (la lista de tools está en `lumi/docs/tools.md`): columna legado, columna nuevo, test que lo demuestra, estado. No marques una fila sin test que pase.

## 11. Código y tests existentes que reutilizas

- Modelos de referencia: `lumi/app/models/*.py` (15 archivos). Migraciones: `lumi/alembic/versions/` (10; sirven de historia, no se portan una a una).
- `lumi/app/services/analytics.py`, `lumi/app/services/metrics.py`, `lumi/app/background/poller.py`, `lumi/app/routers/{alerts,chat,profiles,trends}.py`, `lumi/app/main.py` (lifespan, `/health`), `lumi/app/database.py`, `lumi/app/config.py`.
- Tests: `lumi/tests/test_metrics.py` (7). Los otros tests de tu zona se escriben nuevos (autenticación, restricciones, consultas sin N+1, importador, `check_keys`, rutas).
- Los helpers de fixtures de SQLite de los tests viejos no se reutilizan: usa `pytest-django` con Postgres.

## 12. Dependencias con los otros bots

- INTELLIGENCE necesita de ti (T2): `SCHEMA.md` y `CONTRATOS.md`; (T4) los modelos de `profiles`/`chat`; (T5) `services.py`; (T10) el registro de keys. Te da: `runtime.py`, `bootstrap_profile`, `scan_trends`, sondas de IA, modelos de su app con FK a `Post` y `SocialProfile`.
- CONNECT necesita de ti: `User`, `SocialProfile`, `SocialHandle`, `Post`, `services.upsert_posts`, CORS/auth, `.env.example`, Docker. Te da: `ingest.sync_profile`, `ConnectedAccount`, sondas, vistas de conexiones y handles, frontend ya apuntado a `/api/v1/`.
- Orden de migraciones: las apps ajenas declaran `dependencies = [("profiles", "<última migración publicada>")]`. Publica en CONTRATOS.md el nombre de cada migración que otros referencian y no las renombres después.

## 13. Comprobaciones de aceptación (todas deben pasar para cerrar tu fase)

```bash
cd lumi
uv run python scripts/dev_postgres.py                      # imprime DATABASE_URL de un Postgres real (o: docker compose up -d db)
uv run python manage.py check --deploy --settings=config.settings.prod   # solo advertencias esperadas, sin errores
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py migrate && uv run python manage.py migrate profiles zero && uv run python manage.py migrate
uv run python manage.py check_keys --only database,secret,token_encryption
uv run pytest -m "not live" apps/core apps/accounts apps/profiles apps/chat -q
uv run pytest -m "not live" -q                              # toda la suite, sin keys, sin red
uv run python manage.py verify_legacy_import --source "$LEGACY_DATABASE_URL"   # sobre la base de ejemplo; código 0
uv run ruff check . && uv run ruff format --check .
```

Y: el arranque sin `DATABASE_URL` falla con error claro; `rg -n "sqlite" lumi --glob '!lumi/plan/**' --glob '!lumi/docs/**'` no devuelve nada tras T12; `uv run pytest` no necesita ninguna key.

## 14. Qué reportar

En cada reporte al orquestador y en `estado/ARCHITECT.md`:

- SHA del último commit verde y rama.
- Tareas T0-T12 hechas, en curso, bloqueadas.
- Salida resumida de los comandos de la sección 13 que corriste (aprobados y fallidos).
- Decisiones nuevas (ADR y filas de `decisiones.tsv`) y cualquier cambio del contrato.
- Riesgos: pérdida de datos posible en el importador, consultas lentas, migraciones que otro bot referencia.
- Qué necesitas de INTELLIGENCE, CONNECT o de Christian (por ejemplo, el archivo `lumi.db` real en `/workspace/lumi-data/lumi.db` para ensayar el importador; sin él, solo corres la prueba con datos de ejemplo).
