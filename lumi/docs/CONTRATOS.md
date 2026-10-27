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

**Regla de códigos.** Hay dos niveles y ningún otro:

1. Los códigos genéricos de la tabla siguiente, sin prefijo. Valen para cualquier ruta y el cliente los trata igual en todas.
2. Todo código propio de un dominio lleva el prefijo `<dominio>.<motivo>`, en `snake_case` y con un solo punto (`publish.not_connected`, `chat.unavailable`). El dominio es la función, no la app: `connections`, `publish`, `chat`, `profiles`, `voice`, `job`. Un dominio nuevo se anota en esta lista.

`apps/core/tests/test_error_codes.py` recorre el código y falla si un `ApiError` usa un código fuera de estos dos niveles.

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
| `payload_too_large` | 413 | El cuerpo o el archivo supera el límite de la ruta (audio de `POST /voice/transcribe`). |

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

`/chat` y `/chat/stream` llaman al módulo que nombra `LUMI_CHAT_RUNTIME` (por defecto `apps.intelligence.runtime`) a través de `apps/core/agent_runtime.py`. Si el módulo no existe responden `503 chat.unavailable`. El módulo expone `run_turn`, `stream_turn`, `generate_title(message)` y `scan_trends(...)`. `message` admite hasta 8000 caracteres. Las rutas de chat usan el límite `chat` de 30 por minuto y usuario. `DELETE /chat/history` responde `204` también si no había nada. `POST /trends/scan` responde `502 profiles.scan_failed` si el runtime falla.

### 3.4 Eventos SSE de `/chat/stream`

`Content-Type: text/event-stream`. Cada evento es `data: <json>\n\n`. Cabeceras `Cache-Control: no-cache` y `X-Accel-Buffering: no`. Cada 15 segundos sin eventos se envía el comentario `: ping`. Si el cliente se desconecta, el turno se cancela. El streaming exige un servidor ASGI (`uvicorn config.asgi:application`). Con WSGI la respuesta se acumula entera. `/chat/stream` acepta `Accept: text/event-stream` (y `application/json`); un error antes de empezar el flujo (400, 401, 404, 429) llega como el JSON de error habitual. Las demás rutas de chat siguen sin aceptar `text/event-stream` (`406`).

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
| `GET /connections/{provider}/status`, `DELETE /connections/{provider}` | CONNECT | `provider` en `pfm`, `meta`, `linkedin`, `x`, `google`. El estado trae `provider`, `configured`, `connected`, `stale` y `accounts`, más `details` (objeto opcional con datos del proveedor que no son cuentas; vacío salvo en Google). En Google: `scopes` (lista), `expires_at` (fecha o `null`) y `has_refresh_token` (booleano). Nunca un token. Sin refresh token, la concesión caduca con el access token y el estado sale `stale`. |
| `POST /connections/{provider}/link` (**nuevo**, aceptado) | CONNECT | Enlaza una cuenta ya conectada (una Página de Meta, por ejemplo) a un perfil. Contrato en 4.1. |
| `GET /handles/search`, `GET /handles/saved`, `POST /handles/select`, `GET /handles/stats` | CONNECT | El modelo `SocialHandle` es de ARCHITECT. `stats` devuelve `live_budget` (tope por ejecución, `XPOZ_RUN_CREDIT_BUDGET`) y `live_budget_by_platform`: objeto `{red: tope}` solo para las redes con búsqueda de usuarios en vivo (hoy `x`, `instagram` y `tiktok`). Cada valor es `XPOZ_RUN_CREDIT_BUDGET_<RED>` si existe y, si no, `live_budget`. |
| `POST /publish` | CONNECT | Cuerpo con `attempt_id` o texto, `platform`, `dry_run`. Cabecera `Idempotency-Key`. |
| `POST /voice/transcribe` | INTELLIGENCE | |
| `POST /repurpose` | INTELLIGENCE | |

Las rutas de CONNECT usan el prefijo `/connections/` como fija `docs/CONEXIONES.md`. La ruta de Google del legado (`/mcp/google/*`) desaparece.

### 4.1 `POST /connections/{provider}/link`

Motivo: un login de Meta con varias Páginas guarda todas en `connected_accounts` y no enlaza ninguna al perfil. Sin enlace, `POST /publish` responde `publish.not_connected`. Esta ruta deja al usuario elegir la Página de cada perfil.

| Punto | Decisión |
| --- | --- |
| Estado | **Aceptado** (ARCHITECT, a petición de CONNECT). CONNECT lo implementa. |
| Autenticación | `Authorization: Token <clave>`, como toda ruta no pública. |
| Cuerpo | `{"account_id": "<id>", "profile_id": <int>}`. Los dos son obligatorios. `account_id` es el campo `id` que devuelve `GET /connections/{provider}/status` en cada cuenta (el `external_account_id`, texto), no una clave interna. |
| Proveedores | `pfm`, `meta`, `linkedin` y `x`. `google` no enlaza cuentas a perfiles: `400 connections.unsupported`. Un `provider` desconocido responde igual que las demás rutas de `/connections/`. |
| Permisos | `IsProfileOwner` sobre `profile_id`. Esta clase deja pasar una petición sin `profile_id`, así que la vista debe exigirlo (`400 validation_error` con `details`). |
| Propiedad de la cuenta | La cuenta se busca con `user = request.user`, `provider` y `external_account_id`. Si no existe o es de otro usuario: `404 not_found`, el mismo que un perfil ajeno. Nunca `403`. |
| Efecto | En una sola transacción, con bloqueo de la fila de la cuenta (`select_for_update`): si el perfil ya tenía otra cuenta del mismo `provider`, esa pasa a `social_profile = NULL` (sigue conectada, sin enlace); luego `social_profile` de la cuenta elegida pasa a ser el perfil. El orden evita chocar con el único parcial (`social_profile`, `provider`). Si la cuenta estaba enlazada a otro perfil del usuario, se mueve: ese perfil queda sin cuenta de ese proveedor. |
| Idempotencia | Repetir la misma petición no escribe nada y responde lo mismo (`200`). No hace falta `Idempotency-Key`: el estado final es el mismo con una repetición o con cien. |
| Respuesta `200` | `{"provider": "meta", "profile_id": 7, "account": {...}, "replaced_account_id": null, "moved_from_profile_id": null}`. `account` es el mismo objeto que cada elemento de `accounts` en `status`. `replaced_account_id` es el `id` de la cuenta que dejó el perfil, o `null`. `moved_from_profile_id` es el perfil que perdió la cuenta, o `null`. En una repetición los dos son `null`. Nunca un token. |
| Errores | `400 validation_error` (falta un campo o no es del tipo). `400 connections.unsupported` (proveedor sin enlaces). `404 not_found` (perfil o cuenta no existen o no son del usuario). `409 connections.account_unusable` (la cuenta está en `revoked` o `error`: hay que reconectar antes). `409 connections.platform_mismatch` (la cuenta tiene `platform` y no coincide con la red del perfil; una cuenta con `platform` vacío enlaza con cualquier perfil). `429 rate_limited` con el límite general. |
| Desenlazar | No hay ruta. Enlazar otra cuenta reemplaza la anterior y `DELETE /connections/{provider}?account_id=` desconecta una. Si hace falta desenlazar sin desconectar, se pide como cambio (sección 12). |

CONNECT confirma qué valor de `platform` guarda para una Página de Meta con Instagram: de eso depende cuándo salta `connections.platform_mismatch`. Las pruebas mínimas: enlace feliz, repetición, reemplazo, movimiento entre perfiles, cuenta ajena (404), perfil ajeno (404), `google` (400), cuenta revocada (409) y que `POST /publish` deje de responder `publish.not_connected` tras enlazar.

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

`apps/core/jobs.py`: `BackgroundJob` y el despacho. `LUMI_JOB_DISPATCH=none` (por defecto) deja el trabajo en `queued` para un worker externo. `eager` lo ejecuta en la misma petición, solo para pruebas y desarrollo. `profile.bootstrap` ya tiene manejador (`apps/intelligence/tasks.py`, INTELLIGENCE). `profile.refresh` **sigue pendiente**: sincronizar posts y métricas necesita `apps/connections` (ingesta) y recalcular el baseline, así que no sale solo de los servicios de `profiles`. Mientras no exista, el trabajo queda en `queued` con `LUMI_JOB_DISPATCH=none`, y `run_job` lo termina en `failed` con `job.no_handler`. Dos tests lo documentan (`apps/profiles/tests/test_api.py`). Quien lo escriba lo registra con `@jobs.register("profile.refresh")` de `apps.core.jobs`. El manejador recibe un `JobContext` y devuelve un `dict` con el resultado o `None`.

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
| `profiles.0002_post_media_kind_nullable` | `post_media.kind` admite NULL y `ck_post_media_kind` pasa a `kind IS NULL OR kind IN ('image','video','gif')` | publicada |
| `core.0001_initial` | `BackgroundJob`, `LegacyImportMap` | T3 |
| `chat.0001_initial` | `ChatMessage` | T3 |
| `connections.0001` a `0005` | `0001_initial` (cuentas, estados OAuth, publicaciones, caché y libro de créditos), `0002_account_details_and_state_profile`, `0003_publish_job_attempt_fk`, `0004_mcp_pending_writes`, `0005_provider_google` (añade `google` al CHECK `ck_connected_accounts_provider`) | publicadas (CONNECT) |

Cualquier cambio de esquema posterior va en `0002_*` de la app dueña. Los enums compartidos de `apps/core/choices.py` los cambia ARCHITECT a petición del equipo que los necesite.

`apps.connections` ya está en `INSTALLED_APPS` y tiene sus modelos y migraciones (CONNECT).

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

1. Las variables **obligatorias** son `DATABASE_URL`, `SECRET_KEY`, `TOKEN_ENCRYPTION_KEY` y `GROQ_API_KEY`. Si falta alguna, el arranque falla con un solo error que las lista todas. `OPENROUTER_API_KEY` es opcional (respaldo de Groq), igual que en `.env.example` y en `check_keys`.
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
| Ajustes | `DJANGO_SETTINGS_MODULE = "config.settings.test"` en `[tool.pytest.ini_options]` de `pyproject.toml`. El plugin `lumi_pytest_env` y su `addopts` se retiraron en T12. |
| Sin Postgres | `DATABASE_URL` es obligatoria y debe ser PostgreSQL: sin ella, los ajustes fallan con un mensaje claro (ya no se omiten tests). Los tests de `lumi/tests/` (legado FastAPI) siguen necesitando las variables ficticias de su `Settings` mientras exista `lumi/app/`. |
| Marca `live` | Un test que llama a un servicio real lleva `@pytest.mark.live`. Se recogen siempre y `conftest.py` (raíz) los omite salvo con `LUMI_RUN_LIVE=1`; además cada test se omite si falta su key. Para correrlos: `LUMI_RUN_LIVE=1 uv run pytest -m live` con las keys en `lumi/.env`. `uv run pytest` a secas pasa sin keys ni red. |
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
| CONNECT | `mcp_auth_accounts` y las `connected_accounts` de pfm. Lee `profiles.pfm_account_id` del legado por su cuenta, usa `profile_targets(ctx)` y guarda el valor en `connected_accounts.external_account_id` **en claro** (fila 20 de la sección 11). Un id que empieza por `demo-` no crea cuenta. |

## 11. Desviaciones y choques con el plan o con otros equipos

| N.º | Tema | Decisión | Quién lo decide si discrepa |
| --- | --- | --- | --- |
| 1 | Tokens de API | Tabla propia `auth_tokens` con hash, caducidad y un token por dispositivo, en lugar de `rest_framework.authtoken`. El contrato HTTP es el mismo. **Aceptado por el orquestador.** | Orquestador |
| 2 | `alerts` | Único parcial (solo una alerta `active` por perfil, post y tipo), en lugar del único completo del plan. Permite avisar de nuevo tras descartar. **Aceptado por el orquestador.** | Orquestador |
| 3 | `profiles.pfm_account_id` | No existe en `social_profiles`: vive en `connections.connected_accounts`. | CONNECT |
| 4 | `PublishJob.status` | CONNECT lo pide con valores `pending`, `done`, `failed`, `unknown` y una columna `fingerprint` `char(64)`. **Aceptado.** `SCHEMA.md` 8 queda actualizado. `idempotency_key` sigue siendo único por perfil. Los valores de `status` no usan `JobStatus` (otra máquina de estados: `unknown` significa "no se sabe si el proveedor publicó"). | CONNECT |
| 5 | `OAuthState.consume` | CONNECT lo implementa como un solo `UPDATE ... SET consumed_at = now() WHERE state = %s AND provider = %s AND user_id = %s AND consumed_at IS NULL AND expires_at > now() RETURNING ...`. El `user_id` es el del Token que llama y es obligatorio: sin él, cualquier usuario autenticado podría consumir el state de otro. Si no hay fila y existe un state vivo de otro usuario, CONNECT responde 409 `connections.state_mismatch` sin consumirlo. Ya es el contrato de `SCHEMA.md` 8. ARCHITECT no escribe ese código. | CONNECT |
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
| 16 | Evaluaciones y transacción | **Retirada.** INTELLIGENCE la cerró en `85a2cff` (puertos 1.8): `create_request_with_attempts(..., evaluations=)` guarda intentos y evaluaciones en un solo `atomic()`, así que la fila 2 de `SCHEMA.md` se cumple tal como está escrita. Un error en una evaluación hace fallar toda la llamada: no quedan intentos sin evaluación. Nota: en `85a2cff` la constante `PORTS_VERSION` sigue en `"1.7"`; falta el aumento a 1.8 (lo hace INTELLIGENCE). | INTELLIGENCE |
| 17 | `niche_reports.origin` | **Aceptado.** `varchar(24)` en lugar de `varchar(20)`: `legacy_peer_frameworks` tiene 22 caracteres. `SCHEMA.md` queda corregido. | INTELLIGENCE |
| 18 | Analytics | **Aceptado por el orquestador.** Los totales suman la lectura más reciente de cada post. El código legado sumaba todas las lecturas y contaba un post varias veces. Las series (`reach_series`, `saves_series`) siguen usando todas las lecturas. Está en la matriz de paridad (`plan/estado/ARCHITECT.md`) con test. | Orquestador |
| 19 | Importador | **Aceptado**: todo en una transacción (un savepoint por importador) e ids conservados solo en perfiles, posts y chat (sección 10). **Rechazado** perder la lectura de métricas duplicada: cero pérdida verificable; `legacy_import_map` guarda `outcome` y el `payload` de cada fila fusionada u omitida (`SCHEMA.md` 10). | Orquestador |
| 20 | `connected_accounts.external_account_id` de PFM | **Aceptado.** Va en texto plano, no cifrado. Es el identificador con el que se llama a PFM y la clave del único (`provider`, `external_account_id`), no una credencial: PFM guarda las credenciales. Cifrarlo impediría la restricción única y la búsqueda. Corrige cualquier texto anterior de ARCHITECT que dijera que se cifraba. Los tokens (`access_token`, `refresh_token`) siguen cifrados. | CONNECT |
| 21 | `post_media.kind` | **Aceptada** (orquestador y Christian). Antes era obligatorio (`image`, `video`, `gif`). Ahora admite NULL = tipo desconocido (puertos 1.9, `MediaRef.kind` puede ser `None`). No se adivina por la URL. Un tipo inválido sigue rechazado por el CHECK. `lumi.db` no guarda medios, así que el importador no crea ninguno. | ARCHITECT, INTELLIGENCE |
| 22 | Códigos de error | **Aceptada** (a petición de CONNECT). Dos niveles: los genéricos de la sección 2 sin prefijo y todo código de un dominio como `<dominio>.<motivo>`. Ya era la práctica de CONNECT (`connections.*`, `publish.*`) y de `job.*`; no hay cambio en sus rutas. Cambian `chat_unavailable` a `chat.unavailable` y `scan_failed` a `profiles.scan_failed` (ARCHITECT, hecho), y `transcription_failed` y `transcription_unavailable` a `voice.*` (INTELLIGENCE, pendiente; `test_error_codes.py` lo vigila). `payload_too_large` pasa al catálogo genérico (413). | ARCHITECT, CONNECT, INTELLIGENCE |
| 23 | `POST /connections/{provider}/link` | **Aceptada** (a petición de CONNECT). Ruta nueva con contrato en 4.1. No cambia ninguna tabla: usa `connected_accounts.social_profile` y su único parcial. | CONNECT |
| 24 | `posts.text_truncated` | **Confirmada** (orquestador) como desvío del legado. El legado la dejaba pegada: una vez marcada, una nueva captura no la bajaba. Aquí la marca describe el texto guardado: cada captura la reescribe junto con el `caption`, así que un texto completo la baja y uno cortado la sube. Motivo: el legado no tenía forma de traer el texto entero y la marca pegada era el único freno; ahora el `caption` también se sustituye. | ARCHITECT |
| 25 | Política de capturas de métricas | **Confirmada** (orquestador) como desvío del legado, con una condición: aunque no se guarde captura, el post anota cuándo se leyó (`posts.last_checked_at`, `profiles.0003`). Se añade una fila a `metric_snapshots` solo cuando cambia alguna métrica (los valores nulos arrastran el último conocido). El legado además añadía una fila cada 6 horas con las métricas iguales y al cruzar las marcas de 24 h, 72 h, 7 d y 30 d. `milestone_bucket` y `should_insert_snapshot` no se portan. Motivo: `age_hours` ya no es columna (se deriva) y las filas sin cambio no aportan a la velocidad ni a la línea de tiempo. `policy.final_metrics` sí se porta. La marca va en el post y no en la última captura porque una lectura sin cambios no crea captura: la última captura solo diría cuándo cambió algo, no cuándo se miró. Con la marca en el post, el análisis distingue un post sin cambios de uno que nadie releyó (`last_checked_at` nulo o viejo). | ARCHITECT |
| 26 | `POST /connections/pfm/sync` | **Aceptada** por ARCHITECT (a petición de CONNECT); el orquestador está avisado. Ruta nueva: PFM no manda `state` ni `code`, así que no hay nada que consumir en un callback y el frontend llama a esta ruta al volver. Contrato en la sección 4. `GET /connections/pfm/status` pasa a ser de solo lectura: ni llama a PFM ni escribe (antes sincronizaba y podía poner cuentas en cuarentena). La ruta usa `pfm_links` (`SCHEMA.md` 8) para saber qué `external_id` preguntar, tiene un límite de 12 por minuto y usuario (`429 rate_limited`), guarda cada cuenta bajo `_lock_account` y, si PFM falla, responde `200` con `stale: true` y lo guardado. Los códigos de error siguen la fila 22 (`<dominio>.<motivo>`); los genéricos (`unauthenticated`, `rate_limited`) van sin prefijo. No cambia ninguna tabla. | CONNECT |

## 12. Cómo se pide un cambio

1. El equipo que lo necesita lo anota en su `plan/estado/<EQUIPO>.md`, con la tabla o ruta y el motivo.
2. ARCHITECT lo responde en `plan/estado/ARCHITECT.md` y, si lo acepta, lo publica como `0002_*` o como versión menor de este documento, con su SHA.
3. Un cambio que rompe a otro equipo lo decide el orquestador.
