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
| T1 | esqueleto publicado, resto en curso | Hecho: `manage.py`, `config/settings/{base,dev,test,prod}`, `apps/core/{env,keys,probes,startup,health}`, `scripts/dev_postgres.py`, `.env.example` por bloques, pytest con marcador `live`, 20 tests. Falta: Docker y compose, comando `check_keys`, `apps.accounts` (T3). `contrib.auth` queda fuera de `INSTALLED_APPS` hasta T3 para no crear tablas bajo un modelo de usuario que se reemplaza. |
| T2 | `SCHEMA.md` publicado; `CONTRATOS.md` en curso | Esperan aprobación de INTELLIGENCE y CONNECT (`CONTRATO ARCHITECT ACEPTADO <sha>`). |
| T3 a T12 | pendientes | |

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
