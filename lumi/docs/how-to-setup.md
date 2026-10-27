# Cómo montar Lumi en local

Todo lo necesario para pasar de `git clone` a una app que funciona. Léelo antes que [`../README.md`](../README.md): el README cubre la arquitectura y el despliegue, y este documento cubre tu máquina.

El backend es Django 5.2 con Django REST framework sobre **PostgreSQL**. No hay SQLite: sin `DATABASE_URL` de PostgreSQL, la app no arranca y el error lo dice.

## Requisitos

| Herramienta | Versión | Para qué |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | la última | Dependencias de Python y entorno virtual (`.python-version` fija **3.12**; uv la instala) |
| PostgreSQL | 16 | Base de datos. Con Docker Compose o con `scripts/dev_postgres.py` (sin Docker) |
| Docker | cualquiera | Solo si usas `docker compose` para Postgres |
| Node.js | 22.18+ | Frontend (Vite / React). Los tests corren `.ts` con el type stripping de Node, activo por defecto desde 22.18; en 22.6 a 22.17 hay que pasar `--experimental-strip-types`, y en Node 20 fallan |
| git | cualquiera | Clonar |

## 1. Clonar

```bash
git clone https://github.com/Ateh-Ugoji/Lumi-agent hackathon
cd hackathon/lumi          # el backend y los documentos viven aquí
```

## 2. PostgreSQL

Con Docker Compose (la opción por defecto):

```bash
docker compose up -d db
```

Eso crea la base `lumi` en `127.0.0.1:5432` con el usuario `lumi` y la clave `lumi_dev`, solo para desarrollo. Si el puerto 5432 está ocupado, cambia `LUMI_DB_PORT`. La `DATABASE_URL` correspondiente es:

```
postgresql://lumi:lumi_dev@localhost:5432/lumi
```

Sin Docker, `uv run python scripts/dev_postgres.py` levanta un PostgreSQL real con pgserver, deja los datos en `lumi/.pgdata` e imprime la URL (`export DATABASE_URL=$(uv run python scripts/dev_postgres.py)`).

## 3. Archivo de entorno

```bash
cp .env.example .env
```

`.env.example` marca cada variable como `[OBLIGATORIA]` u `[opcional]`. Rellena al menos las obligatorias; si falta alguna, el arranque falla y el error las lista todas.

| Obligatoria | Qué es |
|---|---|
| `DATABASE_URL` | URL de PostgreSQL (paso 2) |
| `SECRET_KEY` | Firma de Django. Genera una: `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `TOKEN_ENCRYPTION_KEY` | Clave Fernet que cifra los tokens de OAuth en Postgres. Genera una: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `GROQ_API_KEY` | Proveedor principal de modelos y de voz a texto |

Todo lo demás es opcional: sin su variable, la función se apaga y el arranque avisa con un `WARNING` en lugar de fallar. La lista completa y dónde sacar cada key está en [`API_KEYS.md`](API_KEYS.md).

**No subas `.env` nunca.** Git lo ignora, igual que `*.db`, `.venv/`, `node_modules/`, `__pycache__/`, `*.log`, `.pgdata/` y `staticfiles/`. Comparte las keys por un gestor de contraseñas, no por el repositorio.

## 4. Backend

```bash
uv sync                                    # instala las dependencias en .venv
uv run python manage.py migrate            # crea las tablas
uv run python manage.py createsuperuser    # pide email y contraseña (el email es el usuario)
uv run python manage.py check_keys         # qué servicios están configurados y cuáles responden
```

`check_keys` imprime una fila por servicio: `OK`, `OMITIDA` (opcional y sin key) o `FALLA`. Termina con error si algún servicio da `FALLA`. Con `--only database,groq` revisa solo esos servicios, y con `--json` imprime JSON. Funciona con el entorno vacío, así que sirve para ver qué falta.

### Arrancar el servidor

```bash
npm run dev:backend
# o, sin npm:
DJANGO_SETTINGS_MODULE=config.settings.dev uv run uvicorn config.asgi:application --reload
```

El chat (`POST /api/v1/chat/stream`) responde con SSE, y SSE necesita un servidor **ASGI**. Por eso Lumi corre con uvicorn (`config.asgi:application`), en local y en Railway. El SSE se diseñó y se prueba sobre ASGI; `manage.py runserver` (WSGI) no es el camino soportado para el chat. Un test (`apps/chat/tests/test_asgi_stream.py`) levanta uvicorn de verdad y comprueba que el primer evento llega antes de que termine el turno.

El backend está listo en **http://127.0.0.1:8000** cuando responde `GET /health`. Los estáticos del admin (`/admin/`) los sirve WhiteNoise desde `staticfiles/`; en local con `DEBUG=true` no hace falta nada más.

### Importar datos del Lumi anterior

Si tienes un `lumi.db` del backend FastAPI, impórtalo a PostgreSQL. Necesita `TOKEN_ENCRYPTION_KEY` en el entorno, porque guarda cifradas las filas que fusiona u omite.

```bash
uv run python manage.py import_legacy --sqlite /ruta/a/lumi.db --dry-run   # ejecuta todo y deshace al final
uv run python manage.py import_legacy --sqlite /ruta/a/lumi.db             # importa de verdad
uv run python manage.py import_legacy --sqlite /ruta/a/lumi.db --verify    # no importa: compara origen y destino
```

- `--dry-run` corre toda la importación dentro de una transacción y la deshace, así que muestra los recuentos sin escribir nada.
- `--verify` falla si alguna fila del origen no está importada, fusionada u omitida con su contenido guardado, o si hay una tabla sin importador.
- `--user EMAIL` fija el dueño de los datos (por defecto `importado@lumi.invalid`) y `--memory-md RUTA` añade el `memory.md` legado.
- La importación es idempotente: repetirla no duplica filas.

Los detalles (orden de los importadores, qué significa cada resultado) están en [`DATA_IMPORT.md`](DATA_IMPORT.md).

### Comprobaciones

```bash
uv run ruff check .                              # lint
uv run python manage.py makemigrations --check   # el modelo coincide con las migraciones
uv run pytest -q                                 # toda la suite, sin keys y sin red
```

Los tests usan `config.settings.test` y crean su propia base `test_lumi` en el PostgreSQL de `DATABASE_URL`, así que ese rol necesita permiso para crear bases (el de Docker Compose lo tiene). Los tests marcados `live` llaman a servicios reales: se omiten salvo con `LUMI_RUN_LIVE=1` y las keys en `.env` (`LUMI_RUN_LIVE=1 uv run pytest -m live`). Algunos gastan cuota.

## 4. Frontend

Second terminal:

```bash
cd hackathon/lumi/frontend
npm install
npm run dev
```

UI is at **http://localhost:3010** (port is pinned in `vite.config.ts`). It calls `http://localhost:8000` by default; point it elsewhere with `VITE_API_BASE` if your backend lives on another host.

Frontend scripts: `npm run dev` · `npm run build` · `npm run typecheck` · `npm test` (node's built-in runner).

## 5. Comprobar el circuito

1. Abre http://localhost:3010. La aplicación carga.
2. Envía un mensaje en el chat: la respuesta llega por SSE, evento a evento.

## Cambios en el esquema

```bash
uv run python manage.py makemigrations <app> -n describe_el_cambio
uv run python manage.py migrate
uv run python manage.py makemigrations --check   # antes de hacer commit
```

Solo migraciones de Django. Cada tabla, restricción e índice nuevos se documentan en [`SCHEMA.md`](SCHEMA.md).

## Despliegue en Railway

`railway.json` ya lo describe: el build ejecuta `collectstatic` con `config.settings.prod` (sin base de datos ni claves), antes de arrancar se aplica `manage.py migrate --noinput` y el servicio arranca con `uvicorn config.asgi:application`. Las variables obligatorias de la tabla del paso 3 van en el panel de Railway, junto con `ALLOWED_HOSTS`, `CORS_ALLOWED_ORIGINS` y `CSRF_TRUSTED_ORIGINS` con las URLs reales.

## Problemas frecuentes

| Síntoma | Causa y arreglo |
|---|---|
| `Falta la variable de entorno obligatoria DATABASE_URL` | No hay `.env` o la variable está vacía. Mira el paso 2 |
| `connection refused` al migrar | Postgres no está levantado: `docker compose up -d db` |
| Django dice que la clave de cifrado falta o no es válida | `TOKEN_ENCRYPTION_KEY` vacía o no es una clave Fernet. Genera una (paso 3) |
| El chat responde `503 chat.unavailable` | El agente no está disponible, normalmente por una key que falta. Ejecuta `manage.py check_keys` |
| El chat no llega evento a evento | Estás sirviendo con WSGI (`runserver`). Usa uvicorn con `config.asgi:application` |
| `Address already in use` en 8000 o 3010 | Otra copia está corriendo. Busca el proceso con `lsof -i :8000` y ciérralo |
| El frontend no llega a la API | El backend no está arriba, o `VITE_API_BASE` apunta a otro sitio |
| `repository not found` al clonar | Usas la URL antigua. La actual es `Ateh-Ugoji/Lumi-agent` |

## Dónde vive cada cosa

```
lumi/
├── config/         # ajustes de Django (base, dev, prod, test), urls, asgi
├── apps/           # apps de Django: accounts, core, profiles, chat, connections, intelligence
├── lumi_ai/        # motor del agente (proveedores, bucle, RAG, estilo), sin Django
├── legacy/         # backend FastAPI anterior, solo referencia (ver legacy/README.md)
├── frontend/       # interfaz React + Vite
├── docs/           # este archivo, contratos, esquema y notas (docs/README.md es el índice)
├── plan/           # planes y estado de cada bot
├── AGENTS.md       # fuente de verdad de la arquitectura para personas y agentes
└── .env.example    # plantilla de entorno: cópiala a .env
```

El backend FastAPI anterior (`app/`, `alembic/`, `alembic.ini`, sus 5 scripts y sus 422 tests) está en `legacy/`. Es código de referencia: no se despliega, no se mantiene y el `pytest` normal no lo recoge. Para correr sus tests, mira `legacy/README.md`.
