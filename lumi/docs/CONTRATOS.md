# Contratos de Lumi (backend Django)

Versión 1.0, 2026-10-27. Dueño: LUMI-ARCHITECT. Complementa `docs/SCHEMA.md` (tablas) y `lumi_ai/ports.py` (puertos de IA, versión 1.7).

Este documento fija lo que los otros dos equipos pueden usar sin preguntar: rutas HTTP, firmas de servicios, nombres de migraciones, el registro de keys, las convenciones de tests y los puntos donde el diseño se aparta del plan. Una ruta o función marcada **publicada** ya existe en `lumi-orquestador`. Las demás son contrato: el código llega en la tarea indicada.

## 1. Estado y aceptación

| Pieza | Estado |
| --- | --- |
| `manage.py`, ajustes, `apps.core` (entorno, registro de keys, `check_keys`, `/health`) | publicada |
| `core.models.TimestampedModel`, `core.choices`, `core.fields.EncryptedTextField` | publicada |
| `accounts.0001_initial` (`User`, `AuthToken`), `AUTH_USER_MODEL = "accounts.User"` | publicada |
| `profiles.0001_initial` (11 tablas de la sección 6.3 de `SCHEMA.md`) | publicada |
| `core.0001_initial` y `core.0002_legacy_import_outcome` (`BackgroundJob`, `LegacyImportMap`), `chat.0001_initial` (`ChatMessage`) | publicada |
| Capa de servicios de `profiles` y `chat` (sección 5), `core.jobs` | publicada |
| Rutas de ARCHITECT (sección 3), SSE y tendencias | publicada |
| Importador `import_legacy` (sección 10) | publicada para `profiles` y `chat`. INTELLIGENCE y CONNECT añaden sus tablas (sección 10). |

Protocolo de aceptación: cada equipo responde con un commit que diga `CONTRATO ARCHITECT ACEPTADO <sha>` (el SHA de este archivo) en su `plan/estado/<EQUIPO>.md`, y anota ahí cada punto en que discrepa. Un cambio incompatible en este archivo sube la versión mayor y lo avisa el orquestador.

## 2. Convenciones HTTP

| Tema | Regla |
| --- | --- |
| Prefijo | `/api/v1/`. `/health` queda en la raíz. OpenAPI en `/api/schema/` y `/api/docs/` (`drf-spectacular`): públicas solo con `DEBUG=True`; en producción exigen staff (sesión de `/admin/` o token de un usuario staff). Panel de revisión en `/admin/` (solo staff, solo lectura). |
| Formato | JSON UTF-8. Nombres de campo en `snake_case`. Ids numéricos. Fechas ISO 8601 en UTC (`2026-10-27T14:03:00Z`). |
| Autenticación | Cabecera `Authorization: Token <clave>`. Toda ruta la exige salvo las marcadas "pública". |
| Propiedad | Toda ruta con `profile_id` comprueba que el perfil es del usuario. Si no lo es, responde `404 not_found` (no `403`), para no revelar que existe. La comprueba `IsProfileOwner` en `apps/core/permissions.py`. |
| Paginación | `limit` (por defecto 50, máximo 200) y `before=<id>` (cursor por id descendente). Sin `offset`. |
| Errores | `{"error": {"code": "<codigo>", "message": "<texto>", "details": {}}}`. `details` es opcional. Nunca incluye trazas, SQL ni valores de keys. |
| CORS | `CORS_ALLOWED_ORIGINS` desde el entorno, sin `*`. Por defecto `http://localhost:3010,http://127.0.0.1:3010`. |
| Idempotencia | Los `POST` que crean recursos externos (publicar) aceptan `Idempotency-Key`. |

Catálogo de códigos de error. Los equipos pueden añadir códigos propios con prefijo de dominio (`connections.token_expired`).

| `code` | HTTP | Cuándo |
| --- | --- | --- |
| `validation_error` | 400 | Cuerpo o parámetros inválidos. `details` mapea campo a mensajes. |
| `unauthenticated` | 401 | Falta la clave, es desconocida o caducó. |
| `forbidden` | 403 | Autenticado pero sin permiso (por ejemplo, ruta de administración). |
| `not_found` | 404 | No existe o no es del usuario. |
| `conflict` | 409 | Choca con el estado actual (email ya registrado, trabajo duplicado). |
| `rate_limited` | 429 | Cabecera `Retry-After` en segundos. |
| `upstream_error` | 502 | Falló un proveedor externo. El mensaje no incluye datos sensibles. |
| `not_configured` | 503 | Falta una variable opcional del servicio pedido. `details.env_vars` la nombra. |
| `internal_error` | 500 | Error no previsto. El detalle va al log, no a la respuesta. |
| `method_not_allowed` | 405 | Verbo no admitido en la ruta. |

El manejador `apps/core/errors.py` traduce las excepciones de DRF y de Django a este formato, también las rutas inexistentes (`404`) y los fallos del servidor (`500`). Para un error de dominio, un servicio lanza `ApiError(code, message, status_code=..., details=...)`. Los `message` están en español y son para mostrar; el cliente decide por `code`, que es estable y no cambia con el idioma del texto.

## 3. Rutas de ARCHITECT

Los cuerpos coinciden con los de FastAPI salvo lo marcado como **cambio**.

### 3.1 Autenticación

| Ruta | Cuerpo | Respuesta |
| --- | --- | --- |
| `POST /auth/register` (pública) | `{email, password, display_name?}` | `201 {token, user}` |
| `POST /auth/login` (pública) | `{email, password, device_name?}` | `200 {token, user}` |
| `POST /auth/logout` | vacío | `204`. Borra solo la clave usada. |
| `GET /auth/me` | | `200 {id, email, display_name}` |

`token` es la clave en claro. Solo aparece en estas respuestas. `password` exige 10 caracteres o más, pasa por los validadores de Django. El login falla con `401 unauthenticated` y el mismo mensaje para email desconocido y contraseña errónea. Límite de intentos: 10 por minuto por IP y por email (`429`).

### 3.2 Perfiles, analytics y alertas

| Ruta | Respuesta |
| --- | --- |
| `GET /profiles` | `{profiles: [{id, name, platform, handle, has_voice_profile, listening_active, timezone, timezone_source}]}` solo los del usuario. `name` es `handle.display_name` o, si está vacío, el handle. |
| `POST /profiles` (**nuevo**) | Cuerpo `{platform, handle}`. `201` con el resumen si crea el perfil y `200` si el usuario ya lo tenía. Crea el handle si falta (`get_or_create_handle`) y el perfil. Lanza `profile.bootstrap` y responde también `job_id`. |
| `POST /profiles/{id}/select` | `{profile_id, name, voice_profile_exists, post_count, listening_active}`. Sin estado en servidor: el cliente guarda la selección. |
| `GET /profiles/{id}/analytics` | Solo lectura. Mismo cuerpo que hoy. **Cambio**: ya no actualiza datos al leerlo. |
| `POST /profiles/{id}/refresh` (**nuevo**) | `202 {job_id}`. Lanza `profile.refresh` (sincroniza posts y métricas, recalcula el baseline). |
| `GET /profiles/{id}/alerts/unread` | `{alerts: [{id, post_id, caption, platform_post_id, alerted_at, kind, velocity: {likes_per_hour, baseline_likes_per_hour}}]}`. **Cambio**: añade `id` y `kind`. Las velocidades salen de `alerts.velocity` y `alerts.baseline_velocity`; si son nulas, `null`. |
| `POST /profiles/{id}/alerts/{alert_id}/dismiss` (**nuevo**) | `204`, o `404`. |
| `GET /profiles/{id}/listening` y `PUT` (**nuevos**) | `{keywords: [str], enabled: bool, interval_minutes: int}`. Respaldan `ListeningStore`. `PUT` reemplaza el conjunto de keywords en una transacción. |
| `GET /jobs/{job_id}` (**nuevo**) | `{id, kind, status, progress, result, error_code, error_message, created_at, started_at, finished_at}`. `status` es `queued`, `running`, `succeeded`, `failed` o `cancelled`. |

Un `profile_id` ya no tiene valor por defecto en ninguna ruta ni cuerpo. El legado aceptaba `profile_id=1`.

### 3.3 Chat

| Ruta | Cuerpo y respuesta |
| --- | --- |
| `POST /chat` | `{profile_id, message}` a `{role, content, tool_calls_made, tool_executions}`. |
| `POST /chat/stream` | Mismo cuerpo. Respuesta SSE, ver 3.4. |
| `GET /chat/history?profile_id=&limit=50&before=` | `{messages: [{id, role, content, created_at}]}` de más antiguo a más nuevo. Solo roles `user` y `assistant`. |
| `DELETE /chat/history?profile_id=` | `204`. |
| `POST /chat/title` | `{message}` a `{title}`. Sin estado. |

`/chat` y `/chat/stream` llaman al módulo que nombra `LUMI_CHAT_RUNTIME` (por defecto `apps.intelligence.runtime`) a través de `apps/core/agent_runtime.py`. Si el módulo no existe responden `503 chat_unavailable`. El módulo expone `run_turn`, `stream_turn`, `generate_title(message)` y `scan_trends(...)`. `message` admite hasta 8000 caracteres. Las rutas de chat usan el límite `chat` de 30 por minuto y usuario. `DELETE /chat/history` responde `204` también si no había nada. `POST /trends/scan` responde `502 scan_failed` si el runtime falla.

### 3.4 Eventos SSE de `/chat/stream`

`Content-Type: text/event-stream`. Cada evento es `data: <json>\n\n`. Cabeceras `Cache-Control: no-cache` y `X-Accel-Buffering: no`. Cada 15 segundos sin eventos se envía el comentario `: ping`. Si el cliente se desconecta, el turno se cancela. El streaming exige un servidor ASGI (`uvicorn config.asgi:application`). Con WSGI la respuesta se acumula entera.

| `type` | Campos |
| --- | --- |
| `tool_start` | `tool`, `arguments`, `reason` |
| `tool_done` | `tool`, `sample_posts` |
| `done` | `content`, `tool_executions`. Es el último evento. |
| `error` | `error` (mensaje corto, sin trazas). Es el último evento. |

Sin cambios respecto al legado. Los eventos nuevos se añaden con un `type` nuevo y los clientes ignoran los que no conocen.

### 3.5 Tendencias

| Ruta | Cuerpo y respuesta |
| --- | --- |
| `GET /trends/matches?profile_id=&limit=50` | `{matches: [{id, profile_id, platform, platform_post_id, author_handle, caption, platform_url, metrics, discovered_at}]}`. `metrics` sale del último `metric_snapshots` del post. |
| `POST /trends/scan` | `{profile_id, handles?, min_likes?}` a `{profile_id, new_matches_found, viral_posts}`. **Cambio**: `profile_id` es obligatorio y `handles` ya no trae la lista fija `sama, levelsio, ...`; si falta, usa el nicho activo del perfil. `min_likes` por defecto 20. Pasa por el registro de tools de INTELLIGENCE. |

## 4. Rutas reservadas para otros equipos

ARCHITECT monta los `urls.py` de cada app vacíos. El equipo dueño llena el suyo con el mismo prefijo y el mismo formato de errores.

| Ruta | Dueño | Notas |
| --- | --- | --- |
| `POST /connections/{provider}/connect` | CONNECT | Responde JSON `{authorize_url}` y **no** redirige: una navegación del navegador no puede enviar `Authorization`. El frontend hace el `fetch` y luego `window.location = authorize_url`. |
| `GET /connections/{provider}/callback` (pública) | CONNECT | El proveedor redirige aquí. Identifica al usuario por la fila de `oauth_states`, no por cabecera. Responde `302` a `FRONTEND_URL`, nunca JSON. |
| `GET /connections/{provider}/status`, `DELETE /connections/{provider}` | CONNECT | `provider` en `pfm`, `meta`, `linkedin`, `x`, `google`. |
| `GET /handles/search`, `GET /handles/saved`, `POST /handles/select`, `GET /handles/stats` | CONNECT | El modelo `SocialHandle` es de ARCHITECT. |
| `POST /publish` | CONNECT | Cuerpo con `attempt_id` o texto, `platform`, `dry_run`. Cabecera `Idempotency-Key`. |
| `POST /voice/transcribe` | INTELLIGENCE | |
| `POST /repurpose` | INTELLIGENCE | |

Las rutas de CONNECT usan el prefijo `/connections/` como fija `docs/CONEXIONES.md`. La ruta de Google del legado (`/mcp/google/*`) desaparece.

## 5. Capa de servicios

Todos los datos salen como los dataclass de `lumi_ai.ports` o como `TypedDict`, nunca como instancias ORM. Cada función existe en versión síncrona y en versión `a<nombre>` async (con `sync_to_async(thread_sensitive=True)`). Los servicios no comprueban permisos: lo hace la vista (`IsProfileOwner`). Excepción: los que reciben `user_id` filtran por él.

`apps/profiles/services.py`

| Función | Notas |
| --- | --- |
| `get_profile(profile_id, user_id=None) -> ProfileInfo \| None` | Con `user_id`, solo si el perfil es suyo. `connected_platforms` se arma con las cuentas de `connections`, sin importar esa app (consulta por nombre de tabla en un `Protocol` de `profiles`). |
| `list_profiles(user_id) -> list[ProfileInfo]` | |
| `get_or_create_handle(platform, handle, *, origin="live", **datos) -> int` | Devuelve `social_handles.id`. Normaliza a minúsculas sin `@`. Regla `add-if-absent` sobre `origin` (`selected` > `live` > `cache` > `niche`). |
| `list_posts(profile_id, *, platform=None, kinds=None, since=None, limit=50, include_deleted=False) -> list[PostOut]` | `kinds=None` significa solo originales. Más nuevo primero. |
| `get_posts(post_ids) -> list[PostOut]` | |
| `list_activity(profile_id, *, kind=None, limit=50) -> list[ActivityOut]` | Replies y retweets propios. |
| `upsert_posts(handle_id, posts: Sequence[PostIn \| PeerPostIn]) -> UpsertResult` | `UpsertResult(inserted, updated, post_ids)`. Un solo `INSERT ... ON CONFLICT (author_id, platform_post_id) DO UPDATE`. Idempotente. No pisa `published_at` ni métricas con `NULL`. Escribe `metric_snapshots` solo si las métricas cambian. |
| `append_metric_snapshots(post_id, snapshots)` | Inserta. Un conflicto en (`post`, `captured_at`) se ignora. |
| `latest_baseline(profile_id) -> BaselineOut \| None` / `save_baseline(baseline: BaselineOut)` | Solo inserción. |
| `mark_bootstrapped(profile_id) -> bool` | Idempotente: `UPDATE ... WHERE bootstrapped_at IS NULL`. `True` si fue la primera vez. |
| `record_listening_match(profile_id, post_id, score=None) -> bool` | `INSERT ... ON CONFLICT DO NOTHING`. |
| `create_alert_once(profile_id, post_id, kind, *, trigger=None, velocity=None, baseline_velocity=None) -> bool` | SQL crudo `INSERT ... ON CONFLICT (profile_id, post_id, kind) WHERE status = 'active' DO NOTHING RETURNING id`. `True` solo si insertó. Atómico entre procesos. |
| `unread_alerts(profile_id) -> list[AlertOut]` / `dismiss_alert(profile_id, alert_id) -> bool` | |
| `get_listening(profile_id) -> ListeningConfig` / `set_listening(config) -> ListeningConfig` | Keywords en `listening_keywords`, el resto en `poll_configs`. |
| `claim_due_polls(limit=50) -> list[int]` | Un solo `UPDATE ... RETURNING profile_id` (ver `SCHEMA.md` 6.3). Dos workers no reclaman el mismo perfil. |

`apps/chat/services.py`: `append_message(profile_id, message: ChatMessageIn) -> int`, `history(profile_id, limit) -> list[ChatMessageOut]` (cumple `ChatStore`), `clear_history(profile_id)`.

`get_posts(post_ids, *, profile_id=None)`: `profile_id` decide la etiqueta de cada `PostOut`. Si el llamador lo pasa, esa es la etiqueta. Si no, se usa el perfil dueño del post con el id más bajo. Un post de un competidor, que ningún perfil posee, sale con `profile_id = 0`.

`apps/core/jobs.py`: `BackgroundJob` y el despacho. `LUMI_JOB_DISPATCH=none` (por defecto) deja el trabajo en `queued` para un worker externo. `eager` lo ejecuta en la misma petición, solo para pruebas y desarrollo. Los tipos `profile.bootstrap` y `profile.refresh` todavía no tienen manejador: INTELLIGENCE o CONNECT registran el suyo con el decorador `@jobs.register(kind)` de `apps.core.jobs`. El manejador recibe un `JobContext` y devuelve un `dict` con el resultado o `None`.

`MatchStore.record_listening_match(profile_id, post_id, score=None) -> bool` (puertos 1.6) lo implementa INTELLIGENCE sobre `profiles.services.record_listening_match`. El post ya tiene que estar guardado con `PeerPostStore.save_peer_posts`; la fila de `listening_matches` es solo el puente (perfil, post). Devuelve `False` si el vínculo ya existía, así que `scan_trends` cuenta solo las coincidencias nuevas.

`RepurposeStore.create_request_with_attempts(..., source_post_id=None)` (puertos 1.7) guarda `repurpose_requests.source_post_id` (FK a `posts`, `SET_NULL`). `generate_post` lo deja en `None` y `repurpose_caption` lo rellena con el `post_id` del post de partida. Condición del puerto: el post tiene que pertenecer al perfil. `repos.py` tiene que comprobarlo (autor del post igual al handle del perfil) y rechazar el resto antes de insertar; una solicitud sin post de origen sigue siendo válida.

Los puertos `ProfileStore`, `PostStore`, `ListeningStore` y `ChatStore` los implementa INTELLIGENCE en `apps/intelligence/repos.py` encima de estas funciones. ARCHITECT no importa `lumi_ai` en ninguna vista salvo `runtime`.

`ChatMessageIn` de `ports.py` no trae `tool_call_id`, que `SCHEMA.md` 6.4 añade a `chat_messages`. Petición a INTELLIGENCE: añadir `tool_call_id: str | None = None` en `ChatMessageIn` y `ChatMessageOut` (cambio aditivo, puertos 1.5). Hasta entonces la columna queda nula.

## 6. Migraciones publicadas

Las apps ajenas declaran `dependencies = [("profiles", "0001_initial")]` (o la que necesiten). Estos nombres no se renombran.

| Migración | Contenido | Estado |
| --- | --- | --- |
| `accounts.0001_initial` | `User`, `AuthToken` (depende de `auth.0012`) | publicada |
| `profiles.0001_initial` | `SocialHandle`, `HandleSnapshot`, `SocialProfile`, `ProfileBaseline`, `PollConfig`, `ListeningKeyword`, `Post`, `PostMedia`, `MetricSnapshot`, `Alert`, `ListeningMatch` | publicada |
| `core.0001_initial` | `BackgroundJob`, `LegacyImportMap` | T3 |
| `chat.0001_initial` | `ChatMessage` | T3 |

Cualquier cambio de esquema posterior va en `0002_*` de la app dueña. Los enums compartidos de `apps/core/choices.py` los cambia ARCHITECT a petición del equipo que los necesite.

`apps.connections` ya está en `INSTALLED_APPS`. Todavía no tiene `models.py` ni migraciones: las crea CONNECT (T3) con dependencias sobre las dos migraciones publicadas.

## 7. Utilidades compartidas

| Pieza | Uso |
| --- | --- |
| `apps.core.models.TimestampedModel` | Clase abstracta con `created_at` (`db_default=Now()`) y `updated_at`. |
| `apps.core.choices` | `Platform`, `IngestSource`, `PostKind`, `JobStatus`. |
| `apps.core.fields.EncryptedTextField` | `TextField` cifrado con Fernet. Clave `TOKEN_ENCRYPTION_KEY`; para rotar, la clave anterior pasa a `TOKEN_ENCRYPTION_KEY_PREVIOUS` (varias, separadas por coma). `None` y `""` no se cifran. No admite filtros por valor (solo `isnull`). Una clave que no abre el valor lanza `TokenDecryptError` sin incluir el valor. Helpers: `encrypt_value`, `decrypt_value`, `needs_rotation`, `rotate_value`. |
| `apps.core.keys` | Registro de servicios, ver sección 8. |
| `apps.core.permissions.IsProfileOwner` | Comprueba `profile_id` (URL, query o cuerpo, en ese orden) y deja el perfil en `request.profile`. Un id ajeno, inexistente o mal formado da `404`. Úsese junto a `IsAuthenticated` o solo: un anónimo recibe `401`. `get_owned_profile(user, id)` hace la misma comprobación fuera de una vista. |
| `apps.core.errors` | `ApiError`, `exception_handler`, `error_body`. |
| `apps.accounts.authentication.TokenAuthentication` | Autenticación por defecto de DRF. Deja la fila `AuthToken` en `request.auth`. Actualiza `last_used_at` como mucho una vez por hora. |

Formato del cifrado: token Fernet estándar. El cifrado vive solo en `apps.core.fields` (`EncryptedTextField`, `encrypt_value`, `decrypt_value`). `apps/connections/crypto.py` ya no hace falta y CONNECT puede borrarlo. Un test fija el formato con `Fernet` directo, sin depender de `connections`.

## 8. Registro de keys y `check_keys`

Política (fija, ver `AGENTS.md`):

1. Las variables **obligatorias** son `DATABASE_URL`, `SECRET_KEY`, `TOKEN_ENCRYPTION_KEY`, `GROQ_API_KEY` y `OPENROUTER_API_KEY`. Si falta alguna, el arranque falla con un solo error que las lista todas.
2. Las **opcionales** desactivan su servicio y emiten un `WARNING` por variable. La ruta que lo necesita responde `503 not_configured`.
3. Ningún valor aparece en logs, errores, commits ni documentos. Los documentos solo nombran variables.
4. `python manage.py check_keys` hace una llamada mínima real por servicio. Códigos de salida: 0 todo bien, 1 falta una obligatoria o falló un servicio configurado, 2 id desconocido. Opciones `--only id1,id2` y `--json`. Funciona con el entorno vacío (muestra qué falta).

API de registro (`apps/core/keys.py`, publicada):

```python
register(name, probe=None, *, required=False, env_vars=()) -> KeySpec
```

`probe` es una función sin argumentos, síncrona o `async`, que devuelve un `ProbeResult` o un valor equivalente (`status` en `ok`, `skipped`, `error`; `detail`; `warnings`). `run_probe` nunca lanza, limpia del texto cualquier valor de variable configurada y es compatible con `lumi_ai.ports.ProbeResult` y `KeyProbe`. Cada app registra en su `AppConfig.ready()`.

Ids ya registrados: `database`, `secret`, `token_encryption` (ARCHITECT); los de CONNECT en `apps/connections/keys.py` (hoy `meta`, `linkedin` y `x`; los de `pfm`, `xpoz` y `google` los añade CONNECT con el mismo `register`); los de INTELLIGENCE salen de `lumi_ai.keys.build_probes` con el mismo `register`. Cada proveedor tiene **su propia sonda** (una por id), no una sonda por equipo.

Variables que **no** estaban en la documentación de claves y ya están en `.env.example`: `PUBLIC_BASE_URL`, `FRONTEND_URL`, `XPOZ_LIVE_ENABLED`, `XPOZ_RUN_CREDIT_BUDGET`, `HANDLE_CACHE_TTL_MINUTES`, `TOKEN_ENCRYPTION_KEY_PREVIOUS`, `LINKEDIN_API_VERSION`, `META_GRAPH_VERSION`, `AUTH_TOKEN_TTL_DAYS`, `CORS_ALLOWED_ORIGINS`.

Cambios que el orquestador debe copiar a sus documentos (ARCHITECT no los edita): en `API_KEYS.md` y `AGENT_KEYS_SETUP.md`, la lista de las diez variables anteriores; la regla "PostgreSQL es el único motor, `DATABASE_URL` es obligatoria"; y que `GOOGLE_OAUTH_REDIRECT_URI` es `{PUBLIC_BASE_URL}/api/v1/connections/google/callback`. En `DATA_IMPORT.md`, el comando `import_legacy` de la sección 10.

### Tareas programadas hasta que exista Celery (T9)

Celery todavía no está configurado (no hay `config/celery.py`, ni broker en los ajustes). Hasta T9, la renovación de tokens de `connections` se programa con **cron** y el comando de gestión de CONNECT, que hace lo mismo que la tarea `connections.refresh_expiring`:

```
*/30 * * * * cd /ruta/a/lumi && uv run python manage.py refresh_connections
```

Renueva los tokens que caducan en menos de 7 días e imprime solo recuentos, nunca tokens. Es idempotente, así que ejecutarlo más a menudo no hace daño. En T9, ARCHITECT añadirá `config/celery.py` con la entrada de beat para `connections.refresh_expiring` y se quitará la línea de cron; el comando queda como respaldo manual.

## 9. Tests

| Tema | Regla |
| --- | --- |
| Motor | `pytest-django` contra PostgreSQL real. Sin SQLite. `uv run python scripts/dev_postgres.py` levanta uno local y imprime su `DATABASE_URL`; `docker compose` es la alternativa. |
| Ajustes | `config.settings.test`, elegidos por el plugin `lumi_pytest_env` (en `pyproject.toml`, `addopts = -p lumi_pytest_env`). Se retira en T12, cuando desaparezcan los tests de FastAPI. |
| Sin Postgres | Los tests de `apps/` se omiten con un motivo claro cuando `DATABASE_URL` no es una URL de PostgreSQL. Con `LUMI_REQUIRE_DJANGO_TESTS=1` (para CI) dejan de omitirse y la ejecución se aborta con ese motivo. Este era el origen de los dos tests de `apps/core` que fallaban en el árbol de CONNECT: con una `DATABASE_URL` de SQLite o vacía, Django no se configuraba. |
| Marca `live` | Un test que llama a un servicio real lleva `@pytest.mark.live`. Se excluyen por defecto (`-m 'not live'`). Para correrlos: `LUMI_RUN_LIVE=1 uv run pytest -m live` con las keys en `lumi/.env`. Sin keys el resto pasa. |
| Fixtures | `django_db`, `settings` de `pytest-django`. Los tests no dependen del orden: no comparten estado en memoria y el registro de keys se aísla con `monkeypatch.setattr(keys, "_REGISTRY", {})`. |
| Restricciones | Cada `UNIQUE` y `CHECK` de `SCHEMA.md` tiene un test que espera `IntegrityError` (`apps/profiles/tests/test_models.py` es la plantilla). |
| Migraciones | `makemigrations --check` y `migrate <app> zero` seguido de `migrate` deben pasar. |
| Concurrencia | `create_alert_once`, `claim_due_polls` y el consumo de `oauth_states` se prueban con dos conexiones (`transaction=True`). |

## 10. Importador `import_legacy` (T8)

`python manage.py import_legacy --sqlite PATH [--user EMAIL] [--dry-run] [--memory-md PATH] [--verify]`

| Punto | Regla |
| --- | --- |
| Entrada | Un `lumi.db` de SQLite del sistema anterior. Es el único uso de SQLite que queda. Se abre solo lectura (`mode=ro`) y el archivo no cambia. Una tabla que falta se trata como vacía. No había un `lumi.db` real en `/workspace/lumi-data/`: los tests usan una base sintética construida con los modelos legados (`apps/core/tests/legacy_db.py`, que carga `legacy_schema.sql` y `legacy_rows.sql`; `legacy_regen.py` los regenera mientras exista `lumi/app/`). |
| Usuario | Todos los datos legados son de un solo usuario. `--user` lo crea con contraseña inutilizable si no existe. Sin `--user` se usa `importado@lumi.invalid`. |
| Transacción | **Una sola transacción para todo** (cambio respecto a "cada tabla en una transacción"), con un savepoint por importador. Un error deja la base como estaba. `--dry-run` corre todo y revierte al final. |
| Repetible | Cada fila legada queda en `legacy_import_map` con un `outcome`: `imported` (pasó a una fila nueva), `merged` (otra fila ya la cubría) o `skipped` (no se pudo importar; `target_table = "(omitida)"`, `target_pk = 0`). Una segunda ejecución no duplica ni cambia nada y cuenta las filas como "ya importadas". |
| Cero pérdida | Regla del orquestador: toda fila legada termina importada, fusionada con su contenido guardado u omitida con su contenido guardado. Las filas `merged` y `skipped` guardan la fila legada completa en `legacy_import_map.payload` (JSON cifrado con Fernet; un `CHECK` impide guardar una sin él). Las `imported` lo llevan solo cuando el importador cambió algo (métrica negativa a `NULL`, `kind` desconocido, intervalo de sondeo recortado, hijo de escucha que reutiliza un post). Por eso importar necesita `TOKEN_ENCRYPTION_KEY`. |
| Ids | Se conservan solo en `social_profiles`, `posts` y `chat_messages`. El resto recibe ids nuevos y el mapa guarda la relación. Es una excepción a la regla general de `SCHEMA.md` 10. Tras insertar con id explícito se ajusta la secuencia. Si un id pedido ya lo usa una fila ajena, el comando falla con `ImportConflict` y no importa nada. |
| Fusiones | Mismo handle normalizado en dos perfiles: sobrevive el de id más bajo y sus hijos pasan a él. Duplicados de `profile_snapshots` por (handle, `captured_at`) y de `metric_snapshots` por (post, `captured_at`): gana el id legado mayor. `user_activity` que repite un post: gana la fila de `posts`. `listening_matches` reutiliza el post existente y fusiona el par (perfil, post) repetido. |
| Reglas | Enums en minúsculas. `alerted_at` y `alert_dismissed` pasan a `alerts` (`spike` en posts, `niche_match` en escucha) y `dismissed_at` queda `NULL`. Fechas sin zona se leen como UTC. Fechas ilegibles quedan `NULL`. Métricas ausentes o negativas quedan `NULL`, no 0. Un `kind` desconocido pasa a `original`. Plataformas o handles no válidos se omiten con aviso (y la fila queda guardada). |
| Verificación | `--verify` compara, por cada tabla de `LEGACY_TABLES` (21), las filas del legado con las `source_pk` distintas del mapa. Cuenta cada fila como importada, fusionada u omitida y exige que las dos últimas tengan su contenido. Estados `ok`, `difiere` y `sin importador`. Falla si alguna tabla con filas no cuadra. |
| Secretos | Ni los tokens ni `pfm_account_id` salen en logs ni en el informe. |

Cómo añade tablas otro equipo: crear `apps/<app>/legacy_import.py` y llamar a `register(Importer(name, tables, order, run))` (de `apps.core.legacy_import`). El comando descubre el módulo solo. Rangos de `order`: `profiles` 10 a 79, `chat` 80 a 99, INTELLIGENCE 100 a 199, CONNECT 200 a 299. `run(ctx)` recibe un `ImportContext` con `table(name)` (filas legadas), `mapped`, `is_done`, `remember`, `merge`, `skip`, `warn`, `flush` y `cache`. `skip(tabla, fila_o_id, motivo)` y `merge(tabla, fila, tabla_nueva, pk_nueva, motivo)` guardan la fila completa (con un id suelto, `skip` la vuelve a leer). `remember(..., outcome=, row=)` exige `row` si el resultado no es `imported`. `ctx.memory_md` trae el texto de `--memory-md`. `apps.profiles.legacy_import.profile_targets(ctx)` da, por id legado de perfil, el par `(social_profile_id, handle_id)`.

Pendiente de otros equipos, sin importador hoy (el `--verify` los marca `sin importador` si tienen filas):

| Dueño | Tablas |
| --- | --- |
| INTELLIGENCE | `user_search_requests`, `turn_classifications`, `voice_profiles`, `style_answers`, `own_post_analysis`, `post_taggings`, `peer_frameworks`, `niche_framework_reports`, `repurpose_requests`, `repurpose_attempts`, `user_actions` y el texto de `--memory-md` |
| CONNECT | `mcp_auth_accounts` y las `connected_accounts` de pfm. Lee `profiles.pfm_account_id` del legado por su cuenta, usa `profile_targets(ctx)` y cifra el valor con `EncryptedTextField`. Un id que empieza por `demo-` no crea cuenta. |

## 11. Desviaciones y choques con el plan o con otros equipos

| N.º | Tema | Decisión | Quién lo decide si discrepa |
| --- | --- | --- | --- |
| 1 | Tokens de API | Tabla propia `auth_tokens` con hash, caducidad y un token por dispositivo, en lugar de `rest_framework.authtoken`. El contrato HTTP es el mismo. **Aceptado por el orquestador.** | Orquestador |
| 2 | `alerts` | Único parcial (solo una alerta `active` por perfil, post y tipo), en lugar del único completo del plan. Permite avisar de nuevo tras descartar. **Aceptado por el orquestador.** | Orquestador |
| 3 | `profiles.pfm_account_id` | No existe en `social_profiles`: vive en `connections.connected_accounts`. | CONNECT |
| 4 | `PublishJob.status` | CONNECT lo pide con valores `pending`, `done`, `failed`, `unknown` y una columna `fingerprint` `char(64)`. **Aceptado.** `SCHEMA.md` 8 queda actualizado. `idempotency_key` sigue siendo único por perfil. Los valores de `status` no usan `JobStatus` (otra máquina de estados: `unknown` significa "no se sabe si el proveedor publicó"). | CONNECT |
| 5 | `OAuthState.consume` | CONNECT lo implementa como un solo `UPDATE ... SET consumed_at = now() WHERE state = %s AND consumed_at IS NULL AND expires_at > now() RETURNING ...`. Ya es el contrato de `SCHEMA.md` 8. ARCHITECT no escribe ese código. | CONNECT |
| 6 | `EncryptedTextField` | Vive en `apps/core/fields.py`, no en `apps/connections/crypto.py` como planeaba CONNECT. Formato compatible. `TokenCipher` puede seguir existiendo. | CONNECT |
| 7 | Rutas de OAuth | `connect` responde JSON y los `callback` son públicos (ver sección 4). | CONNECT |
| 8 | `GET /profiles/{id}/analytics` | Pierde sus efectos secundarios, que pasan a `POST /profiles/{id}/refresh`. | Frontend |
| 9 | Índices | Django limita el nombre de un índice a 30 caracteres (comprobación `models.E034`). `SCHEMA.md` describe los índices por columnas, no por nombre. Los nombres reales (`ix_`, `uq_`, `ck_`) están en las migraciones. | ARCHITECT |
| 10 | `User.email` | `unique=True` más `CHECK (email = lower(email))`, en lugar del único sobre `Lower(email)` de `SCHEMA.md` v2: Django exige `unique` en `USERNAME_FIELD`. El efecto es el mismo. | ARCHITECT |
| 11 | `tool_call_id` | Falta en `ChatMessageIn` y `ChatMessageOut` de `ports.py` (sección 5). | INTELLIGENCE |
| 12 | `contrib.admin`, `sessions` | **Añadidos a petición del orquestador** (d64718e). `/admin/` es solo staff y solo lectura. Todo modelo se registra con `SafeModelAdmin` (`apps/core/admin.py`): no oculta ni muestra nunca un `EncryptedTextField` y la comprobación `lumi.E001` falla el arranque si un admin lo expone. Se ocultan también `password` y `key_hash`. La API sigue siendo solo por token; la sesión solo sirve para `/admin/` y la documentación. | Orquestador |
| 13 | Documentación OpenAPI | **Decidido.** `/api/schema/` y `/api/docs/` son públicas solo con `DEBUG=True`; en producción exigen staff (`IsStaffOrDebug`). | Orquestador |
| 14 | Registro duplicado | **Aceptado.** `POST /auth/register` con un email ya usado responde `409 conflict`. Revela que el email existe (enumeración de cuentas); el límite de 10 por minuto acota el sondeo. **A revisar antes del lanzamiento**: alternativa, responder igual y avisar por email. | Orquestador |
| 15 | Mensajes de error | **Aceptado.** Los `message` van en español; el cliente decide por `code`. | Orquestador |
| 16 | Evaluaciones y transacción | **Pendiente de aceptación.** `GenerationFlow` llama primero a `create_request_with_attempts` y después a `EvalStore.save_evaluation` una vez por intento, cada llamada en su propia transacción. Es una desviación de la fila 2 de `SCHEMA.md` ("una transacción"): el puerto devuelve los `attempt_id` solo después de crear los intentos. Un fallo en el segundo paso deja intentos sin evaluación (el flujo lo registra en `warnings`, no en un error). No puede quedar una evaluación huérfana y `generation_evaluations.attempt_id` sigue siendo obligatoria. **Opción preferida (cambio de puerto, la decide INTELLIGENCE):** el glue de Django no puede envolver las dos llamadas en un `transaction.atomic()`, porque entre ellas hay un `await` en el flujo y Django no admite transacciones que cruzan `await` (cada `sync_to_async` abre y cierra la suya). Sí se puede dentro de una sola función síncrona: `create_request_with_attempts(..., evaluations=...)` recibe las evaluaciones ya calculadas por `attempt_no`, inserta los intentos con `INSERT ... RETURNING id` y las evaluaciones con esos ids, todo en un `atomic()`. Con eso la fila 2 se cumple tal como está escrita. | INTELLIGENCE |
| 17 | `niche_reports.origin` | **Aceptado.** `varchar(24)` en lugar de `varchar(20)`: `legacy_peer_frameworks` tiene 22 caracteres. `SCHEMA.md` queda corregido. | INTELLIGENCE |
| 18 | Analytics | El puerto suma la lectura más reciente de cada post. El código legado sumaba todas las lecturas y contaba un post varias veces. | Frontend |
| 19 | Importador | **Aceptado**: todo en una transacción (un savepoint por importador) e ids conservados solo en perfiles, posts y chat (sección 10). **Rechazado** perder la lectura de métricas duplicada: cero pérdida verificable; `legacy_import_map` guarda `outcome` y el `payload` de cada fila fusionada u omitida (`SCHEMA.md` 10). | Orquestador |

## 12. Cómo se pide un cambio

1. El equipo que lo necesita lo anota en su `plan/estado/<EQUIPO>.md`, con la tabla o ruta y el motivo.
2. ARCHITECT lo responde en `plan/estado/ARCHITECT.md` y, si lo acepta, lo publica como `0002_*` o como versión menor de este documento, con su SHA.
3. Un cambio que rompe a otro equipo lo decide el orquestador.
