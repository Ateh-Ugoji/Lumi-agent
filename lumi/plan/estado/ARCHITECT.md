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
| `API_KEYS.md` | `GOOGLE_OAUTH_REDIRECT_URI` pasa a `/api/v1/connections/google/callback`. |
| `API_KEYS.md` | Variables nuevas del núcleo: `DJANGO_SETTINGS_MODULE`, `DEBUG`, `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS`, `CSRF_TRUSTED_ORIGINS`, `REDIS_URL`, `AUTH_TOKEN_TTL_DAYS`, `LEGACY_DATABASE_URL`. |
| `API_KEYS.md` | `MVP_*` y `HANDLE_SEARCH_DB` desaparecen cuando CONNECT absorbe `mvp/`. |
| `AGENT_KEYS_SETUP.md` | El paso 3 usa `scripts/dev_postgres.py` (se entrega en el resto de T1). |
| `how-to-setup.md` | Se actualiza tras el port. |

## Lista de T12 (al borrar `lumi/app/`)

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

Nota sobre la fila 18: `reach_series` y `saves_series` siguen recorriendo todas las lecturas en orden, como el legado. Solo los totales cambian.

## Notas del esqueleto

| Tema | Detalle |
| --- | --- |
| Pytest y los tests legados | Sin plugin: `config.settings.test` va fijo en `pyproject.toml` y exige `DATABASE_URL` de PostgreSQL. Los 422 tests legados siguen pasando con Postgres más las cinco variables ficticias de `Settings`; con una URL SQLite ficticia ya no corren. Se borran con `lumi/app/`. |
| `.env.example` | `DATABASE_URL` pasa al formato Django. El backend FastAPI viejo ya no arranca con esta plantilla; vale hasta T12 solo para los tests. |
| Arranque | `manage.py` imprime un error limpio si falta `DATABASE_URL` o `SECRET_KEY`. `check_keys`, `help` y `version` corren con el entorno vacío. |
