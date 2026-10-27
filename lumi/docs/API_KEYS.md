# API keys de Lumi

Guía para Christian. Lumi funciona en modo completo cuando estas variables están en `lumi/.env`. Copia `lumi/.env.example` a `lumi/.env`, pega los valores y arranca. No hace falta tocar código.

Reglas:

- Si falta una key **obligatoria**, la app no arranca y el error lista todas las que faltan de una vez.
- Si falta una key **opcional**, la función que depende de ella se apaga y el arranque lo avisa en el log con una línea `WARNING` por variable.
- `lumi/.env` nunca se sube al repo. Nunca pegues keys en chats, commits, logs ni PRs. Este archivo solo nombra variables.
- Las keys que se expusieron antes del repo actual (ver `lumi/before-deployment.md`) deben rotarse antes de usarlas.

Columna **Estado**: `real` = la variable ya existe en el código actual (`lumi/app/config.py`, `lumi/.env.example` o `os.environ`). `nueva` = la define el plan; el nombre queda fijo cuando el bot responsable lo escribe en `.env.example`.

## Obligatorias (sin ellas no arranca)

| Variable | Estado | Para qué sirve | Dónde se obtiene |
| --- | --- | --- | --- |
| `DATABASE_URL` | real | PostgreSQL, único motor en dev, tests y producción. Formato Django: `postgresql://usuario:clave@host:5432/lumi` (sin `+asyncpg`). En local la levanta `docker compose up -d db`; el valor de `.env.example` ya apunta ahí | Docker Compose local; Railway u otro Postgres en producción |
| `SECRET_KEY` | real | Firma de sesiones y tokens de Django. Hoy está declarada y no se usa; en Django sí se usa | `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `TOKEN_ENCRYPTION_KEY` | nueva | Clave Fernet que cifra en Postgres los tokens OAuth de redes y de Google | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `GROQ_API_KEY` | real | Modelo de lenguaje principal (`openai/gpt-oss-120b`, con `openai/gpt-oss-20b` para turnos simples) y voz a texto (Whisper) | https://console.groq.com/keys |
| `OPENROUTER_API_KEY` | real | Modelo de respaldo cuando Groq falla o se agota (hoy `meta-llama/llama-3.3-70b-instruct`) | https://openrouter.ai/keys |

## Recomendadas (opcionales, con aviso al arrancar)

Hoy el código exige `TYPESAFE_API_KEY` y `NEATLOGS_API_KEY` al arrancar. El plan los baja a opcionales: sin ellas Lumi funciona, con menos calidad de evaluación y sin trazas.

| Variable | Estado | Qué se apaga si falta | Dónde se obtiene |
| --- | --- | --- | --- |
| `TYPESAFE_API_KEY` | real | El juez Jev (clasificación de turnos, dificultad de reescritura, fidelidad). Cae a un modelo pequeño de Groq y, si tampoco hay, a reglas deterministas | TypeSafe AI |
| `NEATLOGS_API_KEY` | real | Trazas de llamadas al modelo y del loop del agente | neatlogs |

## Datos y redes sociales (opcionales)

| Variable | Estado | Qué se apaga si falta | Dónde se obtiene |
| --- | --- | --- | --- |
| `PFM_JWT_TOKEN` | real | Post for Me: conectar cuentas por su OAuth, traer posts y métricas, publicar. El token que existía está vencido (401) | Post for Me |
| `XPOZ_API_KEY` | real | Escucha social y posts de competidores en X. El plan gratis da 500 créditos únicos (2 por consulta de X) | Xpoz |
| `XPOZ_API_KEY_2` | real (se lee con `os.environ`, fuera de `config.py`) | Segunda key de Xpoz para rotar cuando la primera se agota | Xpoz |
| `META_APP_ID`, `META_APP_SECRET` | nueva | OAuth de Facebook (páginas). En modo Development solo funciona con cuentas con rol en la app | https://developers.facebook.com/apps |
| `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET` | nueva | OAuth de LinkedIn. Con autoservicio solo se publica en el perfil personal (`w_member_social`) | https://www.linkedin.com/developers/apps |
| `X_CLIENT_ID`, `X_CLIENT_SECRET` | nueva | OAuth de X | https://developer.x.com |
| `X_LIVE_ENABLED` | nueva | Interruptor de llamadas reales a X. Por defecto `false`. Cada post en X gasta créditos prepagados; no se activa sin que Christian lo pida | no es una key |
| `PUBLIC_BASE_URL`, `FRONTEND_URL` | nueva | URL pública del backend (para redirect URIs de OAuth) y del frontend (adónde vuelve el usuario tras conectar) | no son keys |

Trámites que ninguna key resuelve (solo Christian):

- Meta: App Review de `pages_manage_posts`, `pages_read_engagement` y `read_insights`, más Business Verification. Mientras no estén aprobados, solo funcionan cuentas con rol en la app (modo Development).
- LinkedIn: solicitar la Community Management API (pide screencast) para páginas de empresa.
- X: decidir si se compran créditos.

Estos datos vienen del reporte de LUMI-CONNECT (`/workspace/lumi-integraciones/research.md`) y no los verificó el orquestador; CONNECT los revalida con las páginas oficiales antes de documentar los pasos finales.

## Opcionales de IA y almacenamiento

| Variable | Estado | Qué se apaga si falta | Dónde se obtiene |
| --- | --- | --- | --- |
| `OPENLUX_API_KEY`, `OPENLUX_MODEL` | real (`OPENLUX_BASE_URL=https://api.openlux.ai/v1` está fijo en código) | Proveedor extra que se prueba antes que Groq. Valor por defecto del modelo: `qwen3.8-27b` | OpenLux |
| `CHROMA_API_KEY`, `CHROMA_TENANT`, `CHROMA_DATABASE` | real | Chroma Cloud. Sin ellas, ChromaDB corre local en `CHROMA_PATH` (por defecto `.chroma`). Chroma guarda solo vectores | https://www.trychroma.com |
| `VIDEO_API_KEY`, `VIDEO_PROVIDER` | nueva | Análisis de video en competidores. Los nombres se confirman cuando LUMI-INTELLIGENCE entregue `lumi/docs/VIDEO_API_COMPARISON.md` y Christian elija proveedor | el proveedor elegido |
| `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI` | real | Conectores MCP de Google Drive y Docs | https://console.cloud.google.com/apis/credentials |
| `MCP_ENABLED`, `MCP_GDRIVE_ENABLED`, `MCP_GDOCS_ENABLED` | real | Interruptores (por defecto `true`) de los conectores MCP | no son keys |
| `MCP_TOOLS_TTL_SECONDS`, `MCP_REFRESH_TIMEOUT_SECONDS`, `MCP_CALL_TIMEOUT_SECONDS` | real | Ajustes de caché y tiempos de MCP (300 / 15 / 60) | no son keys |
| `TURN_CLASS_JEV_ENABLED`, `TURN_CLASS_JEV_TIMEOUT_MS`, `TURN_CLASS_JEV_HIGH`, `TURN_CLASS_JEV_LOW` | real | Etapa 2 del clasificador de turnos con Jev (apagada por defecto) | no son keys |

Variables que el código actual lee fuera de `config.py` y que el port debe pasar a la configuración central o eliminar: `MVP_CHROMA_API_KEY`, `MVP_CHROMA_TENANT`, `MVP_CHROMA_DATABASE`, `HANDLE_SEARCH_DB` (apunta a SQLite; desaparece), `MVP_XPOZ_LIVE`, `MVP_XPOZ_BUDGET`, `MVP_CACHE_TTL_MINUTES`, `HANDLE_DB_ENRICH_LIMIT`. Planeada y aún sin construir: `XPOZ_RUN_CREDIT_BUDGET`.

Nombres nuevos que propone el plan de CONNECT para sustituir a los `MVP_*` (aún no existen en el repo; se confirmarán en `docs/CONEXIONES.md`): `XPOZ_LIVE_ENABLED`, `HANDLE_CACHE_TTL_MINUTES`, `TOKEN_ENCRYPTION_KEY_PREVIOUS` (opcional, para rotar la clave de cifrado).

## Comprobar que todo funciona

```bash
cd lumi
cp .env.example .env            # pega las keys en .env
docker compose up -d db         # Postgres local
uv run python manage.py migrate
uv run python manage.py check_keys
uv run python manage.py runserver
```

`check_keys` hace una llamada mínima real a cada servicio configurado y muestra `OK`, `OMITIDA (opcional, falta la variable)` o el error exacto (key mal copiada, permiso faltante, cuota agotada). Nunca imprime el valor de una key. Con `--only groq,xpoz` prueba solo esos servicios; con `--json` da salida para scripts.

`check_keys` y los nombres marcados `nueva` son parte del plan: no existen en el repo hasta que LUMI-ARCHITECT, LUMI-INTELLIGENCE y LUMI-CONNECT los entreguen.
