# Estado de LUMI-ARCHITECT

Rama: `lumi-orquestador`. Registro de decisiones: `ARCHITECT-decisiones.tsv`.

## T0 (hecho)

| Dato | Resultado |
| --- | --- |
| Base de partida | `b4d039a` |
| Tests viejos con 5 variables ficticias | 418 pasan en 7,7 s |
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
- Quitar el plugin `lumi_pytest_env` y su `addopts`.
- Ejecutar `collectstatic` en el build de Railway (estáticos del admin con whitenoise).
- Docker se valida solo como YAML; no hay Docker en la máquina de trabajo.

## Matriz de paridad

Cada fila es un comportamiento donde el backend nuevo difiere del legado a propósito (sección 11 de `docs/CONTRATOS.md`) y el test que lo fija. Lo que se comporta igual lo cubren los tests de cada app; esta matriz no sustituye la comparación endpoint por endpoint con los 418 tests legados de `lumi/tests/`, que sigue sin hacerse.

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

Nota sobre la fila 18: `reach_series` y `saves_series` siguen recorriendo todas las lecturas en orden, como el legado. Solo los totales cambian.

## Notas del esqueleto

| Tema | Detalle |
| --- | --- |
| Pytest y los tests legados | `lumi_pytest_env.py` elige `config.settings.test` solo si `DATABASE_URL` empieza por `postgres`. Los 418 tests legados siguen pasando con una URL SQLite ficticia (verificado). Con una URL Postgres corren los 418 más los de `apps/` (438 en total). Se borra en T12. |
| `.env.example` | `DATABASE_URL` pasa al formato Django. El backend FastAPI viejo ya no arranca con esta plantilla; vale hasta T12 solo para los tests. |
| Arranque | `manage.py` imprime un error limpio si falta `DATABASE_URL` o `SECRET_KEY`. `check_keys`, `help` y `version` corren con el entorno vacío. |
