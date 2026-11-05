# Instrucciones para un agente: activar Lumi con las API keys

Tu tarea es dejar Lumi funcionando con las keys que te dé el usuario. No cambies código salvo que una comprobación falle por un bug; si es un bug, arréglalo en el ámbito de archivos del bot dueño (ver `lumi/plan/ContextoTareas.md`) o repórtalo.

Prerrequisito: el backend Django ya existe (`lumi/manage.py`). Política de keys: `docs/CONTRATOS.md` §8. PostgreSQL es el único motor; `DATABASE_URL` es obligatoria.

Aviso (27 oct 2026): `PFM_JWT_TOKEN` está vencido y hay que pedir uno nuevo a Christian. Xpoz casi no tiene créditos: deja `XPOZ_LIVE_ENABLED=false`.

1. Lee `lumi/docs/API_KEYS.md`: qué hace cada variable y cuáles son obligatorias (`DATABASE_URL`, `SECRET_KEY`, `TOKEN_ENCRYPTION_KEY`, `GROQ_API_KEY`; `OPENROUTER_API_KEY` es opcional).
2. Copia `lumi/.env.example` a `lumi/.env` si no existe. Pega cada key en su variable exacta. Nunca subas `.env` ni pegues keys en chats, commits, logs, PRs o salidas de comandos (no uses `cat .env` ni `env`; usa `check_keys`, que no imprime valores).
3. Levanta Postgres: `docker compose up -d db`.
   Variables que no son keys y que debes revisar en `.env`: `FRONTEND_URL` (de ella salen todas las redirect URIs; `PUBLIC_BASE_URL` es obsoleta), `XPOZ_LIVE_ENABLED`, `XPOZ_RUN_CREDIT_BUDGET` (12 por defecto; opcionales por red: `XPOZ_RUN_CREDIT_BUDGET_X`, `_INSTAGRAM`, `_TIKTOK`, `_REDDIT`), `HANDLE_CACHE_TTL_MINUTES`, `TOKEN_ENCRYPTION_KEY_PREVIOUS`, `LINKEDIN_API_VERSION`, `META_GRAPH_VERSION`, `AUTH_TOKEN_TTL_DAYS`, `CORS_ALLOWED_ORIGINS`. `GOOGLE_OAUTH_REDIRECT_URI` debe ser `{FRONTEND_URL}/connections/google/callback`, y las demás redirect URIs siguen `{FRONTEND_URL}/connections/<provider>/callback` (tabla en `API_KEYS.md`). Los modelos de IA (`GROQ_MODEL_LARGE`, `GROQ_MODEL_SMALL`, `GROQ_MODEL_FALLBACK`, `OPENROUTER_MODEL`, `OPENLUX_MODEL`, `WHISPER_MODEL`) y los tiempos (`PROVIDER_COOLDOWN_SECONDS`, `PROVIDER_COOLDOWN_MAX_SECONDS`, `LLM_TIMEOUT_SECONDS`) tienen valores por defecto en `lumi_ai/config.py`; solo cámbialos si `check_keys` dice que un modelo no existe. El embedder (`onnx-minilm-l6-v2`) no tiene variable.
   - Si no hay Docker (por ejemplo la box del orquestador), usa el helper que entrega LUMI-ARCHITECT: `uv run python scripts/dev_postgres.py`. Arranca un PostgreSQL real con el paquete `pgserver` (verificado el 2026-10-27: PostgreSQL 16.2 en la box) e imprime el `DATABASE_URL` para `.env`. No es un fallback: sigue siendo Postgres, solo cambia cómo se levanta.
4. Aplica el esquema: `uv run python manage.py migrate`.
5. Corre `uv run python manage.py check_keys` (opciones `--only id1,id2` y `--json`; salida 0 = todo bien, 1 = falta una obligatoria o falló un servicio, 2 = id desconocido). Para cada servicio con error, lee el mensaje: key mal copiada, permiso faltante en la consola del proveedor o cuota agotada. Arregla lo que dependa de la configuración y reporta al usuario lo que dependa de él.
6. Tests sin keys (deben pasar todos, también sin red): `uv run pytest` (los `live` se omiten solos salvo que definas `LUMI_RUN_LIVE=1`). Tests con keys reales: `LUMI_RUN_LIVE=1 uv run pytest -m live`. Cuidado: los `live` gastan cuota; los de X siguen apagados mientras `X_LIVE_ENABLED=false`.
7. Arranca backend y frontend (`uv run python manage.py runserver` (en Railway corre bajo ASGI, `config.asgi:application`, que el SSE del chat necesita) y, en `lumi/frontend`, `npm ci && npm run dev`) y recorre el flujo de la demo: conectar una cuenta, traer contenido del nicho, analizar posts (y video si hay `VIDEO_API_KEY`), generar un post y verlo en el frontend.
8. Reporta al usuario, en una lista corta: qué servicios quedaron activos, cuáles siguen apagados y por qué, y qué trámite le falta (por ejemplo, App Review de Meta).

Reglas:

- No actives `X_LIVE_ENABLED` sin que el usuario lo pida: cada post en X cuesta créditos.
- No hagas merge a `main` ni deploy sin aprobación.
- No gastes cuota de Xpoz sin necesidad (2 créditos por consulta de X; el plan gratis tiene 500 en total).
- Para las pruebas del frontend usa Node 22 o superior (`node --test` sobre `.ts` no funciona en Node 20).
