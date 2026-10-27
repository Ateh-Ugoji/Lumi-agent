# ContextoTareas: Lumi

Registro de tareas del orquestador (Grok Bot). Cualquier agente que retome este trabajo debe leer este archivo completo y su PLAN antes de actuar, y actualizar lo que le toca al terminar cada tarea.

Última actualización: 2026-10-27 07:15 UTC.

Ubicación: `lumi/plan/` en la rama `lumi-orquestador` (copia de trabajo en `/workspace/lumi-plan/`). Planes por bot en esa misma carpeta: [PLAN_LUMI-ARCHITECT.md](PLAN_LUMI-ARCHITECT.md), [PLAN_LUMI-INTELLIGENCE.md](PLAN_LUMI-INTELLIGENCE.md), [PLAN_LUMI-CONNECT.md](PLAN_LUMI-CONNECT.md). Guías de keys en `lumi/docs/API_KEYS.md` y `lumi/docs/AGENT_KEYS_SETUP.md`.

## 1. Qué es Lumi

Lumi es un agente de IA para mantener presencia en redes sociales sin quemarse creando contenido.

- Personalización: el usuario conecta sus cuentas y la IA aprende su estilo de escritura, su nicho y su audiencia.
- Análisis de competidores: identifica competidores, analiza sus posts con mejor rendimiento y extrae la estructura que les funciona.
- Generación de contenido: crea posts optimizados para X, Facebook y LinkedIn con el contexto que normalmente falta.

Demo objetivo: un usuario conecta una cuenta social, Lumi recupera contenido autorizado de su nicho, la IA analiza posts y videos, aprende patrones y genera un post personalizado que el usuario revisa en React.

## 2. Estado real del repositorio

Medido el 2026-10-27 sobre `origin/main` = `cce6ca3` ("Add complete Lumi source: backend, frontend, alembic, docs, tests", 297 archivos).

- Repo: https://github.com/Ateh-Ugoji/Lumi-agent (público, dueño Ateh-Ugoji; Christian tiene permiso de push). En origen hay `main` y, desde esta entrega, `lumi-orquestador`.
- **Backend legado (FastAPI)** en `lumi/app/`, unas 12.200 líneas: `agent/` (5 archivos), `tools/` (14), `services/` (21), `models/` (15), `routers/` (10), `analysis/` (8), `background/` (4), `schemas/` (3). 23 rutas. Migraciones Alembic: 10 en `lumi/alembic/versions/`. Prototipo en `lumi/mvp/handle_search/`; scripts en `lumi/scripts/`.
- **Tests**: `lumi/tests/`, 40 archivos, 418 pruebas. Con variables ficticias (`GROQ_API_KEY`, `OPENROUTER_API_KEY`, `TYPESAFE_API_KEY`, `NEATLOGS_API_KEY`, `SECRET_KEY`) pasan las 418 en unos 5 s. **Sin esas variables fallan 17 y 3 dan error**, porque `Settings` las exige sin valor por defecto. Nueve archivos de tests usan SQLite; el prototipo `mvp` también lee SQLite.
- **Docs**: `lumi/docs/` (README, agent, background, blueprint-fix, codenamejo-integration, flow-map, frontend-integration, mcp-connectors, models, profile_extract_audit, routers, services, tools, xpoz_optimization) y `system-arch-mds/` en la raíz. Un solo `lumi/AGENTS.md` y un `lumi/CLAUDE.md`. `temp-agents.md`, `_purge_p16.py` y `backend-dev.log` ya no están (se quitaron en `cce6ca3`; existían en `261d01a`).
- **Frontends**: hay dos, React 19 + Vite, y difieren en 25 archivos. `frontend/` en la raíz (53 archivos) tiene voz, motor de revelado y UI del conector de Google. `lumi/frontend/` tiene `formatClock`, reduced-motion, avatar, `scanError`, tarjetas de impresiones/engagement y `VITE_API_BASE`. Los dos instalan, pasan typecheck y compilan en Node 20. Sus pruebas `node --test` sobre `.ts` necesitan Node ≥ 22.6: con `npx -y node@22` pasan 14/14 (raíz) y 11/11 (`lumi/frontend`). En `lumi/frontend`, `npm test` falla además porque su script nombra `tests/revealEngine.test.ts`, que no existe allí. Los dos llevan `package-lock.json` y `pnpm-lock.yaml`.
- **Stack legado**: FastAPI + SQLModel + Alembic, Postgres en Railway con SQLite por defecto, ChromaDB (hoy guarda texto, no solo vectores), Groq (`openai/gpt-oss-120b`, luego `qwen/qwen3.8-27b`) con respaldo en OpenRouter (`meta-llama/llama-3.3-70b-instruct`), OpenLux opcional, juez Jev/TypeSafe, Post for Me, Xpoz, neatlogs, 20 tools de agente, 21 tablas, conectores MCP de Google Drive y Docs, Whisper para voz.
- **Despliegue**: existe `railway.json` y un despliegue en Railway. No desplegamos nada.

### Riesgos y defectos encontrados en el código y los docs

- Sin autenticación y con CORS `*`. Un solo usuario implícito.
- Constantes de un solo usuario escritas en el código: handles de Ateh, `seed.py` que pisa datos, `ateh_x_connect` en `tools/connect.py`, `external_id="lumi_user"` en PFM.
- Estado de OAuth y escrituras pendientes de MCP en memoria del proceso: se rompen con más de un worker.
- Tokens MCP de Google en texto plano en la base.
- Keys expuestas en el pasado (ver `lumi/before-deployment.md`): hay que rotarlas, no reutilizarlas.
- `PFM_JWT_TOKEN` vencido (401). Xpoz: quedan unas 125 consultas gratis con la key 1.
- Modelos de IA con ID escrito en el código y sin verificar; neatlogs es obligatorio hoy.
- Dos frontends que divergen y lockfiles duplicados.
- No hay Docker ni Postgres en la box de trabajo. Para probar con Postgres real se usa `pgserver` (PostgreSQL 16.2 por socket Unix, verificado el 2026-10-27); `docker compose` no se puede probar aquí.
- Los datos de Meta, LinkedIn y X que trajo la investigación de CONNECT no están verificados por el orquestador.

## 3. Decisiones fijas

De Christian:

1. Portar el backend de FastAPI a Django 5.2 LTS + Django REST Framework, conservando toda la funcionalidad. Los tests existentes son la referencia de comportamiento. No queda FastAPI en paralelo.
2. PostgreSQL es la única base de datos en desarrollo, tests y producción (Docker Compose en local). Sin SQLite. `DATABASE_URL` obligatoria; si falta, error claro al arrancar.
3. Normalizar el esquema (3NF donde tenga sentido), corregir N+1, añadir índices y restricciones. Migrar de SQLModel/Alembic a migraciones del ORM de Django sin pérdida de datos, con verificación.
4. ChromaDB guarda solo vectores con referencia a IDs de Postgres.
5. La prioridad máxima es la IA (LUMI-INTELLIGENCE): agente con tool calling (Groq con respaldo en OpenRouter), perfiles de estilo, RAG con ChromaDB, análisis de competidores, video multimodal con API de terceros (comparar y proponer una), generación por plataforma y evaluación automática de calidad y estilo. Se reutiliza lo que funciona en `lumi/app`. Sin respuestas simuladas.
6. Muse (Meta Model API, Muse Spark) no se implementa ahora: solo `lumi/docs/MUSE.md` con contexto completo para un agente futuro.
7. X queda detrás de `X_LIVE_ENABLED=false`; nunca se gastan créditos de X. Facebook solo en modo Development; LinkedIn con `w_member_social`.
8. Christian no tiene ninguna key. Todo debe funcionar al pegar las keys en `lumi/.env`: chequeo de keys obligatorias al arrancar, funciones opcionales desactivadas con aviso, `python manage.py check_keys` con una llamada real mínima por servicio, tests unitarios que pasan sin keys y pruebas con llamadas reales marcadas `live`.
9. Frontend: se fusionan los dos en uno solo en `lumi/frontend/` con todas las funciones de ambos y se borra `frontend/` de la raíz. Christian lo decidió el 2026-10-27 05:19 UTC. El agente en la nube `bc-3bd03218-ab2c-5948-aba9-f4435b428b7a` que iba a hacerlo se canceló a las 05:20 UTC sin cambios; **no se retoma**. Esa fusión es ahora la tarea T2 de LUMI-CONNECT.
10. Skills de pstack permitidas: `/architect`, `/tdd`, `/blast-radius`, `/correct`, `/show-me-your-work`, `/figure-it-out`, `/how`, `/why`, `/create-verification-skill`, `/interrogate`. `/arena` prohibida. Siempre `correct` en repos y `unslop` al escribir.
11. Sin consumo por encima del límite semanal Premium: sin créditos extra ni cargos. Si se llena, se detiene el trabajo.
12. Con Christian se habla en español.

Del orquestador (cambia lo que decía el borrador anterior):

13. **Una sola rama compartida: `lumi-orquestador`** (antes: una rama por bot). Christian lo pidió el 2026-10-27 ("creas 1 solo branch y ahí comiteas todo"). Cada bot commitea en su ámbito de archivos en cada cambio importante y como mínimo cada hora, con `git pull --rebase origin lumi-orquestador` antes de cada push. Nunca `push --force`, nunca merge a `main`, nunca deploy. Al final, el orquestador abre un solo Draft PR de `lumi-orquestador` a `main`.
14. Los ámbitos de archivos no se solapan (secciones 2 de cada PLAN); los contratos entre bots son `docs/SCHEMA.md` y `docs/CONTRATOS.md` (ARCHITECT) y `lumi_ai/ports.py` (INTELLIGENCE). El contrato se aprueba con la línea `CONTRATO ARCHITECT ACEPTADO <sha>` en el estado de cada bot.
15. El código FastAPI solo se borra cuando exista la matriz de paridad completa (T12 de ARCHITECT).
16. Política de keys. Obligatorias: `DATABASE_URL`, `SECRET_KEY`, `TOKEN_ENCRYPTION_KEY` (Fernet), `GROQ_API_KEY`, `OPENROUTER_API_KEY`. Opcionales con aviso al arrancar: `TYPESAFE_API_KEY`, `NEATLOGS_API_KEY` (pasa de obligatoria a opcional), `PFM_JWT_TOKEN`, `XPOZ_API_KEY`, `XPOZ_API_KEY_2`, `OPENLUX_*`, `CHROMA_*`, `META_APP_ID/SECRET`, `LINKEDIN_CLIENT_ID/SECRET`, `X_CLIENT_ID/SECRET`, `X_LIVE_ENABLED` (false), `VIDEO_PROVIDER` y `VIDEO_API_KEY`, `GOOGLE_OAUTH_*`, `MCP_*`, `PUBLIC_BASE_URL`, `FRONTEND_URL`. Detalle en `lumi/docs/API_KEYS.md`. Solo se nombran variables; nunca valores.
17. El agente nunca publica solo: publicar es una acción del usuario confirmada en la interfaz y pasa por los adaptadores de CONNECT.

## 4. Equipo

| Bot | Id | Ámbito | Plan |
| --- | --- | --- | --- |
| Grok Bot (orquestador) | este chat | Coordina, revisa entregas, desbloquea, mantiene este archivo, los PLAN y las guías de keys, abre el Draft PR final y habla con Christian | este archivo |
| LUMI-ARCHITECT | fdf7d401-408a-46fc-b3b6-11fff0080f78 | Proyecto Django + DRF, esquema Postgres normalizado, migraciones, importador del legado, auth, endpoints y chat, Celery, Docker Compose, CI, `check_keys`, retiro del código legado | [PLAN_LUMI-ARCHITECT.md](PLAN_LUMI-ARCHITECT.md) |
| LUMI-INTELLIGENCE | a84a1345-b5b8-4313-8388-58ea71766c79 | `lumi_ai/` (Python puro) y `apps/intelligence/`: agente, proveedores, estilo, competidores, RAG, generación por plataforma, evaluación, video | [PLAN_LUMI-INTELLIGENCE.md](PLAN_LUMI-INTELLIGENCE.md) |
| LUMI-CONNECT | 4c242e68-4666-4132-ab34-da80d3e2bed4 | `apps/connections/`: OAuth y adaptadores (Facebook, LinkedIn, X, Post for Me), Xpoz, ingesta, handles, MCP de Google; frontend único; e2e; `MUSE.md` | [PLAN_LUMI-CONNECT.md](PLAN_LUMI-CONNECT.md) |

Estado de los bots: **ACTIVOS** desde el 2026-10-27 06:00 UTC (los activó Christian).

### Resumen de cada plan

**ARCHITECT.** Entrega el esqueleto Django 5.2 + DRF (OpenAPI con drf-spectacular, CORS, psycopg3, uvicorn) con Postgres obligatorio y `scripts/dev_postgres.py` (pgserver) para la box sin Docker. Publica el contrato (`SCHEMA.md`, `CONTRATOS.md`) en las primeras 2 horas, porque desbloquea a los otros dos. Define el esquema en 3NF (usuario + perfil social, `SocialHandle`, `Post` unificado, `Alert` con restricción única, etc.), la capa de servicios sin N+1 con alerta atómica "una sola vez", port de analytics y spikes, vistas de chat con SSE, importador del SQLite/Postgres legado con `verify_legacy_import`, Celery + poller, `check_keys` y CI. Solo borra `lumi/app/` con la matriz de paridad completa.

**INTELLIGENCE.** Paquete `lumi_ai/` sin dependencia de Django, con `Protocol` como puertos (T1, primera hora, desbloquea a CONNECT). Proveedores Groq → OpenRouter con enfriamiento ante 402/429 y modelos configurables; bucle de agente con tool calling y los límites actuales (6 iteraciones, 6700 tokens por petición, filtros de afirmaciones y cobertura); perfil de estilo por plataforma; RAG con Chroma solo de vectores (`reindex_vectors`); pipeline de competidores X-first (línea base de 28 días, ganadores ≥1.5× la mediana propia, etiquetado a ciegas, lift, síntesis) con `insufficient_data` honesto y análisis de posts pegados para LinkedIn/Facebook; generación por plataforma con regeneración ≤2; evaluación determinista + estilo + juez; comparación de APIs de video y un adaptador apagado por defecto.

**CONNECT.** OAuth 2.0 y adaptadores con interfaz única `SocialProvider` para Facebook (Development), LinkedIn (`w_member_social`), X (apagado; sin llamadas de red) y Post for Me; tokens Fernet en Postgres, estado OAuth en base, refresco y revocación; publicación solo con confirmación e idempotencia; clientes de Xpoz (con presupuesto de créditos) y PFM; ingesta, búsqueda de handles con caché en Postgres y MCP de Google con tokens cifrados. Fusiona los dos frontends en `lumi/frontend/`, lo integra con `/api/v1/` y token auth, corrige los defectos conocidos, escribe pruebas e2e y `lumi/docs/MUSE.md`. Revalida los permisos de Meta, LinkedIn y X con las páginas oficiales.

## 5. Fases, dependencias y tiempos

Los tiempos son estimaciones en horas de trabajo de los bots desde la reactivación (H0), sumando las estimaciones de cada PLAN; el límite semanal Premium puede alargarlos. Se reportan al orquestador al cerrar cada fase.

| Fase | Ventana | Qué ocurre | Depende de | Cierra cuando |
| --- | --- | --- | --- | --- |
| A. Contrato | H0 – H2 | ARCHITECT: esqueleto (T1) y contrato (T2). INTELLIGENCE: puertos (T1). CONNECT: permisos reales (T1) y empieza la fusión del frontend (T2), que no depende del backend. | Señal de Christian | `SCHEMA.md`, `CONTRATOS.md` y `lumi_ai/ports.py` publicados y las tres líneas `CONTRATO ARCHITECT ACEPTADO <sha>` escritas |
| B. Base (en paralelo) | H2 – H14 | ARCHITECT: auth, modelos, servicios, analytics, importador (T3-T8). INTELLIGENCE: proveedores, bucle, estilo, RAG (T2, T3, T5, T6). CONNECT: modelos y cifrado, adaptadores, OAuth, publicación, clientes, handles, MCP (T3-T9). | Fase A | `pytest -m "not live"` en verde por bot, sin keys |
| C. Integración | H14 – H26 | INTELLIGENCE: pegamento Django (T4), competidores, generación, evaluación, video (T7-T10). ARCHITECT: chat/SSE, Celery, `check_keys` (T7, T9, T10). CONNECT: sondas, integración React ↔ Django, e2e (T10-T12). | Fase B; T4 y T5 de ARCHITECT para el pegamento y las FK | Flujo de demo completo con proveedores falsos, desde React |
| D. Cierre | H26 – H34 | `MUSE.md` y limpieza (CONNECT T13-T14); `/interrogate` y `docs/AI.md` (INTELLIGENCE T12); CI y matriz de paridad, luego retiro de `lumi/app` (ARCHITECT T11-T12). Orquestador: revisión, Draft PR y resumen para Christian. | Fase C | Comprobaciones de aceptación de los tres PLAN en verde; Draft PR abierto |

Cruces de dependencia que más pueden frenar:

- CONNECT T3 (modelos) y INTELLIGENCE T4 (pegamento) esperan T4 y T5 de ARCHITECT.
- CONNECT T7-T9 implementan puertos de INTELLIGENCE T1.
- ARCHITECT T12 (borrar `lumi/app`) espera el cierre de los portes de INTELLIGENCE y CONNECT.
- Cualquier prueba `live` espera las keys de Christian.

## 6. Tareas completadas

- [x] Revisar el repo y contrastar el stack descrito por Christian con las docs (primer reporte, 2026-10-27).
- [x] Crear los tres bots y configurar sus perfiles con funciones, skills, prioridades, decisiones fijas y objetivo de la demo.
- [x] Recibir la investigación inicial de LUMI-CONNECT (`/workspace/lumi-integraciones/research.md`). Sin verificar por el orquestador.
- [x] Enviar la primera tarea a los tres bots y pausarlos por orden de Christian (05:05 UTC). Pueden haber dejado trabajo parcial en el chat de cada bot; en el repo solo existe `main`.
- [x] Christian subió el código y el frontend al repo (`cce6ca3`, 2026-10-27).
- [x] Christian decidió fusionar los dos frontends (05:19 UTC). Agente en la nube cancelado a las 05:20 UTC sin cambios.
- [x] Auditar el código real: estructura, tests (418), frontends, riesgos (sección 2). Verificación: comandos ejecutados en un clon de `cce6ca3`.
- [x] Escribir `docs/API_KEYS.md` y `docs/AGENT_KEYS_SETUP.md` con los nombres de variables reales del código. Verificación: contraste con `lumi/app/config.py` y `lumi/.env.example`.
- [x] Escribir los tres PLAN ejecutables (ARCHITECT 276 líneas, INTELLIGENCE 218, CONNECT 233) con misión, ámbito, tareas con rutas, código y tests a reutilizar, contratos, comprobaciones y formato de reporte.
- [x] Reescribir este archivo y subir todo a la rama `lumi-orquestador` (commit y SHA en el reporte que recibió Christian).

## 7. Tareas pendientes

Cada tarea: responsable, entregable y cómo se verifica. Los detalles y rutas están en el PLAN del responsable.

### Bloqueos que solo puede resolver Christian

- [ ] **Dar la señal para reactivar los bots.** Los bots no se reactivan solos.
- [ ] **Conseguir las keys** y pegarlas en `lumi/.env` (nombres y pasos en `lumi/docs/API_KEYS.md`): `GROQ_API_KEY` y `OPENROUTER_API_KEY` (obligatorias para probar la IA; OpenRouter pide saldo: con saldo 0 responde 402), `TYPESAFE_API_KEY`, `NEATLOGS_API_KEY`, `PFM_JWT_TOKEN` (el anterior venció), `XPOZ_API_KEY`. Generar `SECRET_KEY` y `TOKEN_ENCRYPTION_KEY` (la guía trae el comando). Rotar cualquier key que haya estado expuesta.
- [ ] **Meta**: crear la app de desarrollador (modo Development), poner `META_APP_ID/SECRET`; para publicar a terceros hace falta App Review y Business Verification.
- [ ] **LinkedIn**: crear la app y activar el producto de autoservicio con `w_member_social`; la Community Management API (páginas de empresa) hay que solicitarla.
- [ ] **X**: decidir si se prueba en vivo (cuesta créditos prepagados). Por defecto no; `X_LIVE_ENABLED=false`.
- [ ] **Video**: aprobar el proveedor que proponga INTELLIGENCE (`docs/VIDEO_API_COMPARISON.md`) y poner su key si quiere activarlo.
- [ ] Decidir si se sigue en `Lumi-agent` o se crea un repo nuevo. Por defecto: la rama `lumi-orquestador` en `Lumi-agent`.

### Fase A: contrato

- [ ] ARCHITECT T1: esqueleto Django, `.env.example`, Docker Compose, `dev_postgres.py`. Verificación: `manage.py check` y `/health` responden con Postgres.
- [ ] ARCHITECT T2: `docs/SCHEMA.md` y `docs/CONTRATOS.md`. Verificación: INTELLIGENCE y CONNECT escriben `CONTRATO ARCHITECT ACEPTADO <sha>` en su estado.
- [ ] INTELLIGENCE T1: `lumi_ai/ports.py` con los `Protocol`. Verificación: CONNECT lo importa y su tipado compila.
- [ ] CONNECT T1: `docs/CONEXIONES.md` con permisos revalidados (fecha y URL por dato).

### Fase B: base

- [ ] ARCHITECT T3-T8: cuentas y permisos, modelos y migraciones, servicios sin N+1, analytics y spikes, chat, importador. Verificación: `pytest -m "not live"`, `makemigrations --check`, `verify_legacy_import` sin diferencias.
- [ ] INTELLIGENCE T2, T3, T5, T6: proveedores, bucle y tools, estilo, RAG de vectores. Verificación: tests con respuestas grabadas, `rg` sin `documents=` ni `AtehOfficial`.
- [ ] CONNECT T2: fusión de frontends y borrado de `frontend/` de la raíz. Verificación: `npm ci && npm run typecheck && npm run build` y las pruebas de Node 22 en verde; checklist de funciones completa en `estado/CONNECT.md`.
- [ ] CONNECT T3-T9: modelos y cifrado, adaptadores, OAuth, publicación, clientes de Xpoz y PFM, handles, MCP. Verificación: `pytest -m "not live" apps/connections`; con X apagado, ninguna petición a hosts de X.

### Fase C: integración

- [ ] INTELLIGENCE T4, T7, T8, T9, T10: pegamento Django, competidores, generación (X, Facebook, LinkedIn), evaluación, video. Verificación: `ai_eval --suite golden`, tests de cada módulo, comparación de video escrita.
- [ ] ARCHITECT T7, T9, T10: chat con SSE, Celery + poller, `check_keys`. Verificación: `manage.py check_keys` sin keys marca lo opcional como omitido y falla claro con lo obligatorio.
- [ ] CONNECT T10-T12: sondas de keys, integración React ↔ Django con auth por token, e2e. Verificación: `test_e2e_api.py` y Playwright (o la nota de por qué no corrió).
- [ ] INTELLIGENCE T11: sondas y pruebas `live` listas. Corren solo cuando Christian ponga las keys.

### Fase D: cierre

- [ ] CONNECT T13: `lumi/docs/MUSE.md` con fuentes y fechas. Verificación: sin código de integración de Muse en el repo.
- [ ] INTELLIGENCE T12: `docs/AI.md` y `/interrogate` sobre las piezas críticas.
- [ ] ARCHITECT T11-T12: CI, matriz de paridad completa y retiro de `lumi/app/`.
- [ ] Todos: `.env.example` con todas las variables, `docs/API_KEYS.md` exacto (el orquestador lo actualiza con los nombres nuevos que reporten los bots).
- [ ] Orquestador: revisar la rama completa, correr toda la suite, abrir **un** Draft PR `lumi-orquestador` → `main` y resumir para Christian lo que falta de su lado.

## 8. Cómo retomar este trabajo

1. Leer este archivo, el PLAN del bot que corresponda y su `lumi/plan/estado/<BOT>.md`.
2. Confirmar con Christian antes de reactivar bots. Los tres siguen en pausa.
3. Para ver el avance: `git fetch origin && git log --oneline origin/lumi-orquestador`. Cada commit empieza con `[ARCHITECT]`, `[INTELLIGENCE]`, `[CONNECT]` u `[ORQUESTADOR]`.
4. Estado de pruebas de la rama: `cd lumi && uv run pytest -m "not live" -q` (necesita Postgres; en la box sin Docker, `uv run python scripts/dev_postgres.py` cuando ARCHITECT lo entregue). El legado se prueba con las 5 variables ficticias de la sección 2.
5. Al terminar cualquier tarea, marcarla con `[x]`, anotar fecha, commit o archivo entregado y cómo se verificó.
6. Cuando los tres reporten el cierre de la fase D, el orquestador abre el Draft PR. Nada se mergea a `main` ni se despliega sin Christian.
7. Los hechos de Meta, LinkedIn, X y los precios de las APIs de video cambian: revalidarlos con las páginas oficiales antes de basarse en ellos.


## Actualización 27 oct 2026, 05:58 UTC: main 62056d4 traído a lumi-orquestador
- El dueño subió a `main` el commit `62056d4`: agrega `lumi/docs/how-to-setup.md` (guía de instalación local del stack FastAPI actual) y quita el orbe de `AgentThinking` (borra `lumi/frontend/src/components/AgentThinking/WorkingMark.tsx`).
- El orquestador lo fusionó en `lumi-orquestador` (merge `0f9bd49`, sin conflictos). Antes de empezar, cada bot hace `git pull --rebase origin lumi-orquestador`. Si `main` vuelve a cambiar, el orquestador lo fusiona en la rama.
- ~~`WorkingMark` NO se porta~~. **Revertido por el dueño a las 07:09 en `main` `ba305aa`**: el orbe `WorkingMark` vuelve y se conserva (ver actualización de 07:15).
- `how-to-setup.md` describe el backend FastAPI y SQLite. Cuando el port a Django esté listo, ARCHITECT lo actualiza (Postgres obligatorio, `manage.py`, `check_keys`) y CONNECT actualiza la parte del frontend.


## Actualización 27 oct 2026, 06:00 UTC: bots activados y datos preparados
- Christian activó a los 3 bots a las 06:00 UTC y vuelve hacia las 12:00 UTC. El orquestador revisa cada hora: fusiona `main` en la rama, actualiza este archivo y hace push.
- Los datos reales son un archivo SQLite `lumi.db` del backend FastAPI. No están en git. Para conectarlos se sigue `lumi/docs/DATA_IMPORT.md`: el archivo se deja en `/workspace/lumi-data/lumi.db` y después se corren `import_legacy`, `verify_legacy_import` y `reindex_vectors`. El importador T8 de ARCHITECT acepta SQLite y Postgres.
- Pendiente de Christian: dejar `lumi.db` en esa ruta, o pasarlo para que el orquestador lo deje ahí.

## Actualización 27 oct 2026, ~06:40 UTC

- **ARCHITECT:** fase 1 cerrada (SCHEMA v2, CONTRATOS v1.0, `manage.py`, migraciones de `accounts` y `profiles`, `EncryptedTextField`; 619 tests pasan). Decisiones aceptadas por el orquestador: tabla propia `auth_tokens` y único parcial en `alerts`; `contrib.admin` se agrega solo para staff.
- **INTELLIGENCE:** T0–T3 hechas (`lumi_ai`, ports 1.2, 197 tests). T4 espera a ARCHITECT; ahora va con T5 y T6.
- **CONNECT:** fase 1 cerrada (frontend fusionado, `MUSE.md`); capa de adaptadores lista (139 tests). T3 espera las migraciones y CONTRATOS.
- **Pendientes de Christian:** las 5 preguntas de `MUSE.md`, renovar el token de Post for Me (`PFM_JWT_TOKEN`, vencido) y los créditos de Xpoz (casi agotados).
- **Orquestador:** `API_KEYS.md`, `AGENT_KEYS_SETUP.md` y `DATA_IMPORT.md` alineados a CONTRATOS §8 y §10 y a `.env.example`. Faltan en `.env.example` (INTELLIGENCE debe añadirlas): `GROQ_MODEL_LARGE`, `GROQ_MODEL_SMALL`, `GROQ_MODEL_FALLBACK`, `OPENROUTER_MODEL`, `WHISPER_MODEL`, `PROVIDER_COOLDOWN_SECONDS`, `PROVIDER_COOLDOWN_MAX_SECONDS`, `LLM_TIMEOUT_SECONDS`. Revisión de secretos en el historial: sin secretos reales.

## Actualización 27 oct 2026, 07:15 UTC (revisión horaria)

- **`main` avanzó a `ba305aa`** (dueño, "Revert AgentThinking to the orb version; light up social logos on account steps"): restaura `lumi/frontend/src/components/AgentThinking/WorkingMark.tsx` (el orbe) y su CSS, y en `App.tsx` marca como pasos `social` las tools que recorren la cuenta (`extract_voice_profile`, `get_posts`, `get_user_activity`, `get_analytics`, `check_trending`, `backfill_posts`). El orquestador lo fusionó en `lumi-orquestador` sin conflictos. **Nueva regla: el orbe `WorkingMark` se queda; nadie lo borra.** CONNECT: al integrar React con Django, conservar ese mapeo de pasos `social`.
- **ARCHITECT** (último commit 07:05, `39999e5`): T1 cerrada (docker compose, tests de arranque reales, `check_keys` live). Rutas `/auth`, `TokenAuthentication`, `IsProfileOwner`; admin solo staff y de solo lectura; OpenAPI pública solo con DEBUG; servicios de perfiles, handles, posts, alertas y escucha con sus rutas; registro de jobs en segundo plano; chat con rutas y SSE con cancelación; trends (matches y scan por el runtime); rutas de `connections` montadas en `api/v1/`; CONTRATOS con puertos 1.7. Pendiente: resto de T4 a T12 (importador, Celery, CI, matriz de paridad). Sin bloqueos.
- **INTELLIGENCE** (último commit 07:03, `397cd1d`): T0 a T3 hechas; T4 (pegamento Django) en curso con modelos y migración `0001` de `apps/intelligence` (crea `repurpose_attempts`); sondas en `check_keys`; T5 a T7 (estilo, RAG de vectores, competidores) hechas en `lumi_ai`; T8 generación y T9 evaluación hechas en `lumi_ai` (26 casos dorados SINTÉTICOS, `manage.py ai_eval`), falta el guardado real en T4. Puertos 1.7. Pendiente: T10 a T12. **Bloqueos:** (1) T10 vídeo sin fuente de URLs de medios: ni PFM ni Xpoz rellenan `PostIn.media`; opciones: que CONNECT obtenga las URLs con otra llamada del proveedor o que el usuario pegue el enlace; mientras tanto T10 trabaja solo con URL explícita. (2) Instagram cuesta 12 créditos de Xpoz y `XPOZ_RUN_CREDIT_BUDGET` vale 10; el tope vive en el adaptador de CONNECT (subirlo a 12 o hacerlo por plataforma).
- **CONNECT** (último commit 06:56, `d0b5a45`): T3 modelos hecho (+ `0002` con la FK a `repurpose_attempts`); T5 rutas de conexión (connect, callback, status, DELETE, renovación) hechas y ya montadas por ARCHITECT; T7 clientes PFM y Xpoz sin red; T8 `/handles/search`, `saved`, `select`, `stats`; T6 `POST /api/v1/publish` con `Idempotency-Key`. Pendiente: T4, T9 (MCP Google), T10 a T12, T14. La sección "Bloqueos" de `estado/CONNECT.md` está desactualizada (CONTRATOS y migraciones ya existen).
- **Datos:** `/workspace/lumi-data/lumi.db` todavía no existe.
- **Orquestador:** los bots siguen activos (commits cada pocos minutos). Para destrabar dentro de los planes, recomendación: CONNECT decide el presupuesto de Xpoz por plataforma (Instagram ≥ 12) y propone a INTELLIGENCE la fuente de URLs de vídeo. Ninguno de los dos bloqueos necesita a Christian ahora.
- **Siguen pendientes de Christian:** las 5 preguntas de `MUSE.md`, renovar `PFM_JWT_TOKEN`, créditos de Xpoz, las keys y dejar `lumi.db`.

## Pendientes nuevos de Christian (27 oct 2026, 07:15 UTC)
- Al crear la app de Post for Me, poner en su panel la URL de retorno `PUBLIC_BASE_URL/api/v1/connections/pfm/callback` (pedido de CONNECT).
- Antes del lanzamiento, decidir si el registro con un email repetido sigue respondiendo 409 o si responde igual que un registro nuevo y avisa por email (CONTRATOS §11, pedido de ARCHITECT). Por ahora queda el 409, con límite de 10 por minuto.
- Cuando haya keys, aportar posts reales aceptados y rechazados para calibrar los umbrales de los jueces (Jev y la rúbrica de T9, pedido de INTELLIGENCE).
- Para crear un superusuario en `/admin/`: `uv run python manage.py createsuperuser`.
- Nota de modelos: `qwen/qwen3.8-27b` está en Preview en Groq y puede retirarse sin aviso. Los modelos gpt-oss-120b, gpt-oss-20b y whisper-large-v3-turbo están en Production (según INTELLIGENCE).

## Decisión pendiente de Christian: el MVP legado (27 oct 2026, 07:35 UTC)
ARCHITECT verificó que ningún archivo de INTELLIGENCE ni de CONNECT importa `app.*`. Lo único que sigue usándolo es el MVP legado de Ateh Ugoji: `lumi/alembic/env.py`, 5 scripts (classifier_report, cleanup_authentic_posts, own_report, smoke_memory, smoke_voice_corpus), unos 39 archivos de test en `lumi/tests/` (418 tests), `AGENTS.md` y `before-deployment.md`. Si se borra `lumi/app/`, todo eso se va con él. Las opciones son:
- (a) Borrarlo todo junto, con la paridad cubierta por los tests de Django.
- (b) Moverlo a `lumi/legacy/` como referencia, fuera de la suite de tests.
- (c) Esperar.
El orquestador eligió (c) mientras Christian decide. Entretanto, ARCHITECT completa la matriz de paridad contra los 418 tests legados y congela en un fixture el esquema de `legacy_regen.py`. No se borra ni se mueve nada.
- Restricción (07:40 UTC): INTELLIGENCE y CONNECT confirmaron que su código no importa `app.*`. Pero el frontend todavía llama a rutas del FastAPI viejo en la pantalla de voz y en el conector de Google, y CONNECT las pasa a `/api/v1` en su T11. Lo que decida Christian se aplica recién cuando T11 esté cerrada.

## Estado 27 oct 2026, 07:45 UTC
- CONNECT terminó T0 a T14 (HEAD `82f29c3`). El e2e con Playwright da 9/9 con proveedores simulados y un runtime de chat falso, y pytest da 1555 pasan. La voz y Google ya van por `/api/v1`. Le queda la revisión de seguridad de OAuth y del e2e, y diagnosticar 2 tests intermitentes. Pendientes anotados: elegir Página cuando hay varias en Meta (ruta `link` pedida a ARCHITECT), publicar en Instagram y TikTok, y un tope diario de Xpoz.
- INTELLIGENCE terminó T0 a T10 y T12 (HEAD `9bc2ac6`; 626 tests; `docs/AI.md`, `docs/VIDEO_API_COMPARISON.md`). T11 (los live) está escrita y sin correr. Le queda T4b (runtime con MCP) y corregir el riesgo de que el timeout de una tool permita confirmar una escritura del ORM.
- ARCHITECT tiene que montar `apps.intelligence.urls`: hoy `/repurpose` y `/voice/transcribe` dan 404. También tiene que corregir 2 tests suyos: el arranque ASGI exige `GROQ_API_KEY` sin key en los tests, y un test de `legacy_import` quedó desfasado.

### Decisiones de Christian (INTELLIGENCE)
1. ¿Se aprueba Gemini de pago (`gemini-3.5-flash-lite`) para analizar video? Cuesta unos $0.008–0.013 por video de 60 s, con un tope de `VIDEO_MAX_PER_RUN=5`. Hace falta una key de plan de pago, porque el plan gratis usa el contenido para entrenar.
2. Revisar los términos de Google, X, Instagram y TikTok sobre analizar videos de terceros.
3. Pegar `GROQ_API_KEY` y `TYPESAFE_API_KEY` (y `OPENROUTER_API_KEY` si se quiere) en `lumi/.env`, y autorizar los tests live y `ai_eval --live`, que gastan cuota.
4. Pasar posts reales aceptados y rechazados para calibrar los umbrales de los jueces.
