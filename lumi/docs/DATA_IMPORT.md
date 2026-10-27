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
Comando de CONTRATOS §10 (T8):

`python manage.py import_legacy --sqlite PATH [--user EMAIL] [--dry-run] [--memory-md PATH]`

El origen es solo un `lumi.db` de SQLite, que se abre en solo lectura (`mode=ro`). Ensaya siempre sobre una copia.

```bash
cp /workspace/lumi-data/lumi.db /tmp/lumi-copia.db
uv run python manage.py import_legacy --sqlite /tmp/lumi-copia.db --user TU_CORREO --dry-run
uv run python manage.py import_legacy --sqlite /tmp/lumi-copia.db --user TU_CORREO
uv run python manage.py import_legacy --sqlite /tmp/lumi-copia.db --verify   # compara conteos; tiene que salir con código 0
uv run python manage.py reindex_vectors   # regenera los vectores de Chroma desde Postgres
```

- Todos los datos legados son de un solo usuario. `--user` lo crea con contraseña inutilizable si no existe.
- Es repetible: escribe `legacy_import_map` y una segunda ejecución no duplica ni cambia nada.
- Orden: handles, perfiles, posts, métricas, chat, inteligencia, conexiones; cada tabla en una transacción.
- Enums en minúsculas; `alerted_at` y `alert_dismissed` pasan a `alerts`; fechas y métricas desconocidas quedan `NULL` (no 0).
- `--verify` cubre las 21 tablas legadas.
- Los tokens de `mcp_auth_accounts` y `profiles.pfm_account_id` se cifran con `EncryptedTextField` al escribirse y nunca van a logs.
- Un dump de Postgres no está soportado por el contrato; si llega uno, pídelo a ARCHITECT. `LEGACY_DATABASE_URL` de `.env.example` no lo usa este comando.

## 4. Después de importar
- Prueba la app con `seed_demo` desactivado, para que el seed no sobrescriba los datos importados.
- Anota en `lumi/plan/ContextoTareas.md` cuándo se importó, el origen, los conteos por tabla y el resultado de la verificación.


## Opciones del importador y trabajos en segundo plano (actualizado 07:15 UTC)
- `--dry-run`: lee y valida sin escribir nada.
- `--verify`: compara los conteos por tabla y sale con código distinto de 0 si algo difiere. Las filas duplicadas que se fusionan cuentan como fusionadas, no como perdidas.
- `--memory-md PATH`: importa también el archivo de memoria en markdown del agente legado.
- `--user EMAIL`: asigna los datos a ese usuario. Si no se indica, crea un usuario "importado".
- Hoy importa profiles y chat; los importadores de INTELLIGENCE y CONNECT se suman después.
- `LUMI_JOB_DISPATCH`: con `none` (el valor por defecto), los trabajos que crea la importación quedan en `queued` hasta que un worker los procese. Con `eager` se ejecutan en el momento; úsalo solo en desarrollo.
