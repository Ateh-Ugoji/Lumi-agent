# Cómo conectar los datos reales a Lumi

Esta guía sirve para cuando llegue la base con datos reales. Hoy esa base es un archivo SQLite, `lumi.db`, del backend FastAPI. Según `how-to-setup.md`, se pasa por un drive o por mensaje directo. Nunca se sube a git: `lumi/.gitignore` ya ignora `*.db`.

## 1. Dónde dejar el archivo
- En la box compartida va en `/workspace/lumi-data/lumi.db`. Esa carpeta está fuera del repo.
- Si llega un dump de Postgres en lugar del archivo, va en `/workspace/lumi-data/legacy.sql` o `/workspace/lumi-data/legacy.dump`.

## 2. Revisar qué trae, sin modificarlo
```bash
sqlite3 -readonly /workspace/lumi-data/lumi.db ".tables"
sqlite3 -readonly /workspace/lumi-data/lumi.db "select name,(select count(*) from pragma_table_info(name)) from sqlite_master where type='table';"
```
Anota en `lumi/plan/estado/ARCHITECT.md` las tablas y el número de filas de cada una. Si la versión de Alembic (`alembic_version`) no es la cabeza actual, primero corre las migraciones sobre una copia del archivo.

## 3. Importarlo al esquema Django en Postgres
`LEGACY_DATABASE_URL` admite dos formas:
- `sqlite:////workspace/lumi-data/lumi.db`, que es el caso normal.
- `postgresql://...`, si llega una base de Postgres.

```bash
export LEGACY_DATABASE_URL=sqlite:////workspace/lumi-data/lumi.db
uv run python manage.py import_legacy --source "$LEGACY_DATABASE_URL" --dry-run
uv run python manage.py import_legacy --source "$LEGACY_DATABASE_URL"
uv run python manage.py verify_legacy_import --source "$LEGACY_DATABASE_URL"   # tiene que salir con código 0
uv run python manage.py reindex_vectors   # vuelve a generar los vectores de Chroma desde Postgres
```
El importador abre el origen en solo lectura y se puede repetir sin duplicar datos. Si un origen no tiene usuarios, crea un usuario llamado "importado".

## 4. Después de importar
- Prueba la app con `seed_demo` desactivado, para que el seed no sobrescriba los datos importados.
- Anota en `lumi/plan/ContextoTareas.md` cuándo se importó, el origen, los conteos por tabla y el resultado de la verificación.
- Si los datos traen tokens de redes sociales en texto plano, cífralos con Fernet al importarlos y no los muestres en ningún log.
