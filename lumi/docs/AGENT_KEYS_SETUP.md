# Instrucciones para un agente: activar Lumi con las API keys

Tu tarea es dejar Lumi funcionando con las keys que te dé el usuario. No cambies código salvo que una comprobación falle por un bug; si es un bug, arréglalo en el ámbito de archivos del bot dueño (ver `lumi/plan/ContextoTareas.md`) o repórtalo.

Prerrequisito: el backend ya es Django (existe `lumi/manage.py`). Mientras exista `lumi/app/` (FastAPI), esto aún no aplica.

1. Lee `lumi/docs/API_KEYS.md`: qué hace cada variable y cuáles son obligatorias (`DATABASE_URL`, `SECRET_KEY`, `TOKEN_ENCRYPTION_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`).
2. Copia `lumi/.env.example` a `lumi/.env` si no existe. Pega cada key en su variable exacta. Nunca subas `.env` ni pegues keys en chats, commits, logs, PRs o salidas de comandos (no uses `cat .env` ni `env`; usa `check_keys`, que no imprime valores).
3. Levanta Postgres: `docker compose up -d db`.
   - Si no hay Docker (por ejemplo la box del orquestador), usa el helper que entrega LUMI-ARCHITECT: `uv run python scripts/dev_postgres.py`. Arranca un PostgreSQL real con el paquete `pgserver` (verificado el 2026-10-27: PostgreSQL 16.2 en la box) e imprime el `DATABASE_URL` para `.env`. No es un fallback: sigue siendo Postgres, solo cambia cómo se levanta.
4. Aplica el esquema: `uv run python manage.py migrate`.
5. Corre `uv run python manage.py check_keys`. Para cada servicio con error, lee el mensaje: key mal copiada, permiso faltante en la consola del proveedor o cuota agotada. Arregla lo que dependa de la configuración y reporta al usuario lo que dependa de él.
6. Tests sin keys (deben pasar todos, también sin red): `uv run pytest` (por defecto excluye `live`). Tests con keys reales: `uv run pytest -m live`. Cuidado: los `live` gastan cuota; los de X siguen apagados mientras `X_LIVE_ENABLED=false`.
7. Arranca backend y frontend (`uv run python manage.py runserver` y, en `lumi/frontend`, `npm ci && npm run dev`) y recorre el flujo de la demo: conectar una cuenta, traer contenido del nicho, analizar posts (y video si hay `VIDEO_API_KEY`), generar un post y verlo en el frontend.
8. Reporta al usuario, en una lista corta: qué servicios quedaron activos, cuáles siguen apagados y por qué, y qué trámite le falta (por ejemplo, App Review de Meta).

Reglas:

- No actives `X_LIVE_ENABLED` sin que el usuario lo pida: cada post en X cuesta créditos.
- No hagas merge a `main` ni deploy sin aprobación.
- No gastes cuota de Xpoz sin necesidad (2 créditos por consulta de X; el plan gratis tiene 500 en total).
- Para las pruebas del frontend usa Node 22 o superior (`node --test` sobre `.ts` no funciona en Node 20).
