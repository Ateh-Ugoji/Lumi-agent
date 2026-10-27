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

## Matriz de paridad

Pendiente (se llena antes de T12).

## Notas del esqueleto

| Tema | Detalle |
| --- | --- |
| Pytest y los tests legados | `lumi_pytest_env.py` elige `config.settings.test` solo si `DATABASE_URL` empieza por `postgres`. Los 418 tests legados siguen pasando con una URL SQLite ficticia (verificado). Con una URL Postgres corren los 418 más los de `apps/` (438 en total). Se borra en T12. |
| `.env.example` | `DATABASE_URL` pasa al formato Django. El backend FastAPI viejo ya no arranca con esta plantilla; vale hasta T12 solo para los tests. |
| Arranque | `manage.py` imprime un error limpio si falta `DATABASE_URL` o `SECRET_KEY`. `check_keys`, `help` y `version` corren con el entorno vacío. |
