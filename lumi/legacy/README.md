# Código legado (FastAPI)

Esta carpeta guarda el backend anterior de Lumi, hecho con FastAPI, SQLModel y Alembic. Es **solo código de referencia**: no se despliega, no se mantiene y no se debe importar desde el backend nuevo. El backend es Django (`lumi/apps/`, `lumi/config/`, `lumi/manage.py`) y el motor del agente es `lumi/lumi_ai/`.

Se movió con `git mv`, así que `git log --follow` sigue el historial de cada archivo.

## Qué hay

| Carpeta | Contenido |
| --- | --- |
| `app/` | La aplicación FastAPI (modelos, routers, agente, servicios, tareas de fondo) |
| `alembic/`, `alembic.ini` | Las migraciones del esquema viejo |
| `scripts/` | Los 5 scripts que importan `app.*`: `classifier_report.py`, `cleanup_authentic_posts.py`, `own_report.py`, `smoke_memory.py`, `smoke_voice_corpus.py` |
| `tests/` | Los 422 tests viejos |
| `pytest.ini`, `conftest.py` | Configuración propia de esos tests |

`lumi/scripts/dev_postgres.py` no importa `app`, así que se quedó en `lumi/scripts/`. La carpeta `lumi/mvp/` tampoco se movió: un test viejo la importa.

## Cómo correr los tests viejos

Desde `lumi/legacy`:

```bash
cd lumi/legacy
env -u DATABASE_URL -u DJANGO_SETTINGS_MODULE uv run pytest -q
```

- No necesitan Postgres: usan SQLite en archivos temporales y `pytest.ini` desactiva `pytest-django`. No hace falta `DATABASE_URL`.
- `app.config.Settings` pide cinco variables sin valor por defecto (`GROQ_API_KEY`, `OPENROUTER_API_KEY`, `TYPESAFE_API_KEY`, `NEATLOGS_API_KEY`, `SECRET_KEY`). No las pongas: `conftest.py` pone un valor ficticio a cada una que falte y no llama a ningún servicio. Una variable que sí esté definida gana.
- Resultado esperado: `422 passed`. Al final puede salir un `--- Logging error ---` de la librería de logs; no es un fallo.
- También funcionan desde `lumi/` con `uv run pytest legacy/tests`.
- Los tests marcados `live` se omiten salvo `LUMI_RUN_LIVE=1`.

El `pytest` normal de `lumi/` no los recoge (`testpaths = ["apps"]` y `norecursedirs` incluye `legacy`).

## Qué no hacer

- No lo despliegues. `railway.json` arranca `config.asgi:application`, no `app.main`. Railpack sube todo el directorio, pero nada de `legacy/` se ejecuta.
- No lo uses para el backend nuevo. `import_legacy` lee un `lumi.db` con SQL puro y no importa `app`. Los modelos viejos solo los usa `apps/core/tests/legacy_regen.py`, que agrega esta carpeta al `sys.path` para reconstruir los archivos de prueba congelados.
- Los archivos de datos viejos (`memory.md`, el índice local) ahora se resolverían bajo `lumi/legacy/`, no bajo `lumi/`.
