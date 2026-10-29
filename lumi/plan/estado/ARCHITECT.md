# Estado de LUMI-ARCHITECT

Rama: `lumi-orquestador`. Registro de decisiones: `ARCHITECT-decisiones.tsv`.

## T0 (hecho)

| Dato | Resultado |
| --- | --- |
| Base de partida | `b4d039a` |
| Tests viejos con 5 variables ficticias | 422 pasan en 5 s |
| Tests viejos sin variables | 17 fallan, 398 pasan, 3 errores (todos por variables que faltan) |
| Base de datos real | No existe `/workspace/lumi-data/lumi.db`. El importador se ensaya solo con datos de ejemplo hasta que llegue. |

## Tareas

| Tarea | Estado | Nota |
| --- | --- | --- |
| T0 | hecha | |
| T1 | hecha | `docker-compose.yml` (Postgres 16, Redis opcional con `--profile celery`), `manage.py check_keys`, ajustes que leen todo de `lumi/.env`, fallo claro sin `DATABASE_URL` o `SECRET_KEY`, SQLite rechazado, opcionales avisan en el arranque. Tests en `apps/core/tests/test_startup_e2e.py` (procesos reales) y uno `live`. El compose no se pudo probar: la box no tiene Docker. |
| T2 | `SCHEMA.md` v2 y `CONTRATOS.md` v1.0 publicados | Aceptados por INTELLIGENCE (0489487) y CONNECT (585bb7a). |
| T3 | hecha en lo de ARCHITECT | `accounts`, `profiles`, `core` y `chat` con migración inicial. Rutas `/auth/*`, `TokenAuthentication`, `IsProfileOwner`, manejador de errores. |
| T4 a T12 | pendientes | Siguiente: `services.py` de perfiles y chat y sus rutas. |

## Cambios que esperan los documentos de keys (los mantiene el orquestador)

| Documento | Cambio |
| --- | --- |
| `API_KEYS.md` | Ids de sondas de `check_keys` y banderas: ver `CONTRATOS.md`. |
| `API_KEYS.md` | `TOKEN_ENCRYPTION_KEY_PREVIOUS`, `XPOZ_LIVE_ENABLED`, `XPOZ_RUN_CREDIT_BUDGET`, `HANDLE_CACHE_TTL_MINUTES`, `LINKEDIN_API_VERSION`, `META_GRAPH_VERSION` ya están en `.env.example`. |
| `API_KEYS.md` | `GOOGLE_OAUTH_REDIRECT_URI` pasa a `{FRONTEND_URL}/connections/google/callback` (página del frontend; el backend ya no recibe al proveedor) y `PUBLIC_BASE_URL` queda obsoleta. |
| `API_KEYS.md` | Variables nuevas del núcleo: `DJANGO_SETTINGS_MODULE`, `DEBUG`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, `REDIS_URL`, `AUTH_TOKEN_TTL_DAYS`, `LEGACY_DATABASE_URL`. |
| `API_KEYS.md` | `MVP_*` y `HANDLE_SEARCH_DB` desaparecen cuando CONNECT absorbe `mvp/`. |
| `AGENT_KEYS_SETUP.md` | El paso 3 usa `scripts/dev_postgres.py` (se entrega en el resto de T1). |
| `how-to-setup.md` | Se actualiza tras el port. |

## Lista de T12 (al borrar `lumi/legacy/`)

- Actualizar `docs/how-to-setup.md`: Postgres obligatorio (la línea 14 aún habla de SQLite), `manage.py`, `check_keys`. CONNECT cubre la parte del frontend.
- [x] Quitar el plugin `lumi_pytest_env` y su `addopts` (hecho: `DJANGO_SETTINGS_MODULE` en `pyproject.toml`, `conftest.py` omite `live` salvo `LUMI_RUN_LIVE=1`).
- Ejecutar `collectstatic` en el build de Railway (estáticos del admin con whitenoise).
- Docker se valida solo como YAML; no hay Docker en la máquina de trabajo.
- No hay Celery beat todavía: `connections.refresh_expiring` se programa cuando exista beat (T9) y se quita el cron de `manage.py refresh_connections`. Hasta entonces sigue en cron.

## Matriz de paridad

Cada fila es un comportamiento donde el backend nuevo difiere del legado a propósito (sección 11 de `docs/CONTRATOS.md`) y el test que lo fija. Lo que se comporta igual lo cubren los tests de cada app; la comparación con los 422 tests legados de `lumi/tests/` está en [`PARIDAD-LEGADO.md`](PARIDAD-LEGADO.md), que genera `apps/core/tests/legacy_parity.py` desde `legacy_parity_map.tsv`. Un test falla si algún test legado queda sin mapa, si un destino no existe o si el informe se desvía.

| Fila | Comportamiento | Legado | Nuevo | Estado | Test |
| --- | --- | --- | --- | --- | --- |
| 1 | Tokens de API | `rest_framework.authtoken` | Tabla `auth_tokens` con hash y caducidad | Aceptada | `apps/accounts/tests/test_models.py::test_token_stores_only_the_hash_and_authenticates` |
| 2 | Alertas repetidas | Avisa de nuevo tras descartar | Único parcial: una `active` por episodio, varias `dismissed` | Aceptada | `apps/profiles/tests/test_models.py::test_alert_only_one_active_per_episode_but_dismissed_can_repeat` |
| 8 | `GET /profiles/{id}/analytics` | Tenía efectos secundarios | Solo lectura; el refresco va en `POST /profiles/{id}/refresh` | Aceptada | `apps/profiles/tests/test_api.py::test_analytics_is_read_only_and_empty_without_posts` |
| 12 | `/admin/` | No existía | Solo staff y solo lectura | Aceptada | `apps/core/tests/test_admin.py::test_the_admin_is_read_only` |
| 13 | `/api/schema/` y `/api/docs/` | Públicas | Públicas solo con `DEBUG`; en producción exigen staff | Aceptada | `apps/core/tests/test_docs_access.py::test_anonymous_is_refused_in_production` |
| 14 | Registro con email repetido | Error de integridad | `409 conflict` | Aceptada, a revisar antes del lanzamiento | `apps/accounts/tests/test_auth_api.py::test_register_rejects_duplicate_email_case_insensitively` |
| 16 | Intentos y evaluaciones | Dos transacciones | Una (`evaluations=`, puertos 1.8) | Retirada | `apps/intelligence/tests/test_repos.py` (casos con `evaluations=`) |
| 18 | Analytics: totales | Suma todas las lecturas de cada post, así que un post leído tres veces cuenta tres | Suma la lectura más reciente de cada post | **Aceptada por el orquestador** | `apps/profiles/tests/test_parity.py::test_row_18_analytics_adds_the_latest_reading_of_each_post_not_every_reading` (más `test_services.py::test_analytics_counts_the_latest_snapshot_of_each_post_once`) |
| 19 | Importador | No existía | Una transacción, ids conservados solo en perfiles, posts y chat, cero pérdida | Aceptada (cero pérdida exigida) | `apps/core/tests/test_legacy_import.py::test_every_legacy_row_is_imported_or_kept_with_its_payload` y `::test_the_duplicate_metric_reading_of_post_12_is_not_lost` |
| 21 | `post_media.kind` | Obligatorio | Admite NULL = tipo desconocido (puertos 1.9), nunca adivinado | Aceptada (orquestador y Christian) | `apps/profiles/tests/test_parity.py::test_row_21_media_of_unknown_type_is_stored_as_null_not_guessed` |
| 24 | `posts.text_truncated` | Una vez marcada, quedaba marcada | Sigue a la última captura, junto con el `caption` | Confirmada (orquestador) | `apps/profiles/tests/test_parity.py::test_row_24_the_truncation_flag_follows_the_latest_fetch_not_a_sticky_one` |
| 25 | Capturas de métricas | Fila nueva cada 6 h y en las marcas de 24 h, 72 h, 7 d y 30 d, aunque no cambie nada | Fila nueva solo si cambia una métrica; cada lectura anota `posts.last_checked_at` | Confirmada (orquestador, con la condición de `last_checked_at`) | `apps/profiles/tests/test_parity.py::test_row_25_a_snapshot_is_appended_only_when_a_metric_changed` |
| 27 | Foto del autor en `/trends/matches` | Columna `listening_matches.author_avatar_url`, copia por coincidencia; si el escaneo no la sabía, queda NULL para siempre | Se lee de `social_handles.avatar_url` del autor (`author_avatar_url`, `null` si no se conoce); sin columna ni migración | Aceptada | `apps/profiles/tests/test_parity.py::test_row_27_the_match_author_picture_is_the_handle_picture_not_a_copy` |

Nota sobre la fila 18: `reach_series` y `saves_series` siguen recorriendo todas las lecturas en orden, como el legado. Solo los totales cambian.

## Propuestas para otros equipos (foto del autor, de `632217e`)

- **INTELLIGENCE** (`apps/intelligence`, `lumi_ai`): el escaneo de tendencias debe pasar la foto que conozca al crear el handle del autor, con `services.get_or_create_handle(platform, handle, origin="niche", avatar_url=...)` (solo rellena si está vacía). Además, cada elemento de `viral_posts` del resultado de `scan_trends` puede traer `avatar_url` (cadena, vacía si no se sabe) y `extract_sample_posts` (`lumi_ai/agent/support.py`) debe copiarlo a `sample_posts[].avatar_url` del evento SSE `tool_done`. El frontend ya lo espera (`SamplePost.avatar_url?: string`).
- **CONNECT** (`apps/connections/handles`): al buscar o refrescar un handle, guardar `avatar_url` en `social_handles` por `get_or_create_handle`, igual que hoy. Es lo que sustituye al `lookup` de `handle_db` del legado: no hace falta ninguna tabla nueva.
- **Frontend**: `TrendMatch.author_avatar_url?: string | null` ya está en `api/trends.ts`; `ChronicOnline` usa la foto guardada y unavatar de respaldo.
- **CONNECT, refresco de fotos** (`/handles/search`, ronda 5): `profiles.services.update_handle_avatar(handle_id, url) -> bool` sustituye la foto cuando llega una URL http(s) válida y distinta, e ignora vacíos. `get_or_create_handle` sigue siendo solo de relleno.
- **CONNECT, foto de la cuenta de PFM: hecho** en `3dda0e1` (con `d9ab891`). Llama a `update_profile_avatar(..., username=acc.username)` solo si la fila está `active` y enlazada. Solo refrescan fotos los datos del proveedor (`source="live"`). CONTRATOS 11, fila 28.
- **INTELLIGENCE, 4 huecos de `test_handle_db`: cerrados** en `4971a13` (HandleBook, PORTS 1.12). Paridad: 364 cubiertos, 45 reemplazados, 3 desviaciones, 10 retirados, 0 huecos (422).
- **INTELLIGENCE, códigos de error de trabajos: hecho** en `b92761e`. `profiles.sync_failed` y `voice.learn_failed`; `PENDING_RENAME` quedó vacío y CONTRATOS 3.2 lo refleja.
- **INTELLIGENCE, foto de la fuente: cerrado** con la opción (b), gana la foto guardada, en `f8c50ea` con su prueba. CONTRATOS 11, fila 29.
- **CONNECT, `POST /handles/select`: hecho** en `f843610` (fila 30). Solo `(platform, handle)`, origen `cache`, 400 si el handle no es válido. **Pendiente de CONNECT:** que el frontend mande `platform` y que el serializador lo exija (hoy asume `x`). `selected` queda solo para datos anteriores: se conserva en el CHECK y en el rango, no se migra.

## Ronda 9: revisión de `5257760` y `3c57f88`, y handles elegidos del legado

| Punto | Resultado |
| --- | --- |
| FK | `user` CASCADE y `handle` CASCADE se quedan. `social_handles` no se borra en ningún código (los importadores fusionan por `handle_normalized`) y las demás tablas derivadas del handle ya usan CASCADE. PROTECT haría imposible borrar un handle con elecciones sin ganar nada. |
| Restricción única | `uq_user_saved_handle` está en la base (`sqlmigrate` y `pg_indexes`). |
| Índices (EXPLAIN, 20 000 handles, 10 000 filas) | (Resuelto: CONNECT quitó `ix_user_saved_recent` en `2b00a07`.) `saved` tarda menos de 1 ms. `ix_user_saved_recent` sí se usaba, pero solo para filtrar por usuario; sin él y sin el índice automático de `user_id` el plan es el mismo con `uq_user_saved_handle`. Ninguna consulta ordena por `created_at`. CONNECT lo quitó en `2b00a07` (migración `0009_user_saved_handles_lighter`). |
| Sin duplicados con `social_profiles` | Los perfiles propios se leen de `social_profiles` por `user_id`; la tabla nueva solo guarda elecciones. |
| N+1 | `saved` hace 2 consultas con 5 y con 50 elegidos. |
| Concurrencia | 12 hilos haciendo `select` del mismo handle: todos 200, una fila en `user_saved_handles`, un handle. |
| Migración | `0008` hacia delante, `migrate connections 0007`, otra vez hacia delante sobre una copia con 20 000 handles y 10 000 filas: sin error. El retroceso borra la tabla (es lo esperable en `CreateModel`); `social_handles` queda intacto. `makemigrations --check`: sin cambios. |
| `3c57f88` | Los códigos son `validation_error`; los mensajes están en español; `details.platform` en select y `details.platforms` en search y saved; sin token 401 `unauthenticated`. `test_error_codes` pasa. Diferencia sin documentar hasta hoy: `platform` de select distingue mayúsculas y espacios (`X`, `x ` dan 400), `platforms` no. Mensaje de select para valor no válido: `"X" no es una elección válida.` (el de DRF, sin la lista de redes). Resuelto por CONNECT en `2b00a07`: `platform` se normaliza igual que `platforms` y los 400 listan las 5 redes. |
| Texto de CONNECT (`/workspace/handles-contract.md`) | Dos errores corregidos al aplicarlo: (1) decía que `platform` no distingue mayúsculas, solo es cierto para `platforms`; (2) citaba un bloque "platform obligatorio" que no existe, ahora cita los cuatro tests por nombre. Tampoco existe una tabla de migraciones en §12 (es "Cómo se pide un cambio"): la migración queda en la fila 31 y en SCHEMA §8. El "(8)" de las pruebas es exacto. |
| Legado | El `lumi.db` no tiene handles guardados ni elegidos (`legacy_schema.sql`): vivían en Chroma `handle_mappings`, global. Por eso `import_legacy` recibe `--handle-mappings PATH` (JSON de esa colección) y escribe `user_saved_handles` del `--user` con `ts` como `created_at`. `--verify` falla si falta alguno. Los perfiles propios del SQLite ya van a `social_profiles`. Sin el archivo no hay nada que importar. |
| Demo | "Los handles existentes no tienen dueño" es aceptable para la demo: `saved` muestra los perfiles propios y se llena al elegir. Con datos del legado hace falta el export de Chroma. |

## Ronda 10: el backend FastAPI viejo pasa a `lumi/legacy/`

| Tema | Detalle |
| --- | --- |
| Qué se movió | `git mv` sin tocar contenido (commit aparte, el historial se conserva): `app/` (85 archivos), `alembic/` (14), `alembic.ini`, `tests/` (40 archivos, 422 tests) y 5 scripts (`classifier_report`, `cleanup_authentic_posts`, `own_report`, `smoke_memory`, `smoke_voice_corpus`). Nada se borró. |
| Qué no se movió | `mvp/` y `scripts/dev_postgres.py`: los usa Django. |
| Pytest | `testpaths = ["apps"]` y `legacy` en `norecursedirs`. El pytest por defecto ya no recoge el legado. `legacy/pytest.ini` y `legacy/conftest.py` propios (con `-p no:django`) dejan correr los 422 a mano, sin Postgres. |
| Ruff | `src = [".", "legacy"]` para que `app` cuente como código propio; el legado se sigue revisando y está limpio. |
| Despliegue | Railpack no tiene forma de excluir carpetas de la subida. El legado no se ejecuta (`startCommand` es `config.asgi:application`) y `test_deploy_config` lo vigila. |
| Congelados | `legacy_regen.py` y el test de fixtures congelados añaden `legacy/` al `sys.path` al importar `app.models`. `import_legacy` nunca importó `app`. |
| Cuentas | Antes: 1883 pasaron, 3 omitidos. Ahora: 1461 + 10 de CONNECT (`2b00a07`) = 1471, 3 omitidos. La diferencia de 422 son los tests legados. `pytest apps lumi_ai`: 2031 (antes 2021 + 10 de CONNECT). |

## Notas del esqueleto

| Tema | Detalle |
| --- | --- |
| Pytest y los tests legados | Sin plugin: `config.settings.test` va fijo en `pyproject.toml` y exige `DATABASE_URL` de PostgreSQL. Los 422 tests legados viven en `lumi/legacy/tests/` (desde R10), con su propio `pytest.ini` y `conftest.py`: corren a mano desde `lumi/legacy`, sin Postgres y con las cinco variables ficticias de `Settings` que pone su conftest. El `pytest` normal no los recoge. Se borran con `lumi/legacy/`. |
| `.env.example` | `DATABASE_URL` pasa al formato Django. El backend FastAPI viejo ya no arranca con esta plantilla; vale hasta T12 solo para los tests. |
| Arranque | `manage.py` imprime un error limpio si falta `DATABASE_URL` o `SECRET_KEY`. `check_keys`, `help` y `version` corren con el entorno vacío. |
