# ContextoTareas: Lumi

Registro de tareas del orquestador (Grok Bot). Cualquier agente que retome este trabajo debe leer este archivo completo y su PLAN antes de actuar, y actualizar lo que le toca al terminar cada tarea.

Última actualización: 2026-10-27 (ver la sección TRASPASO al final; el cuerpo de arriba llega hasta las 09:10 UTC).

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
16. Política de keys. Obligatorias: `DATABASE_URL`, `SECRET_KEY`, `TOKEN_ENCRYPTION_KEY` (Fernet), `GROQ_API_KEY`. Opcionales con aviso al arrancar: `OPENROUTER_API_KEY` (respaldo), `TYPESAFE_API_KEY`, `NEATLOGS_API_KEY` (pasa de obligatoria a opcional), `PFM_JWT_TOKEN`, `XPOZ_API_KEY`, `XPOZ_API_KEY_2`, `OPENLUX_*`, `CHROMA_*`, `META_APP_ID/SECRET`, `LINKEDIN_CLIENT_ID/SECRET`, `X_CLIENT_ID/SECRET`, `X_LIVE_ENABLED` (false), `VIDEO_PROVIDER` y `VIDEO_API_KEY`, `GOOGLE_OAUTH_*`, `MCP_*`, `FRONTEND_URL` (`PUBLIC_BASE_URL` quedó obsoleta el 27 oct). Detalle en `lumi/docs/API_KEYS.md`. Solo se nombran variables; nunca valores.
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
- [ ] **Conseguir las keys** y pegarlas en `lumi/.env` (nombres y pasos en `lumi/docs/API_KEYS.md`): `GROQ_API_KEY` (obligatoria para probar la IA) y `OPENROUTER_API_KEY` (opcional, de respaldo; pide saldo: con saldo 0 responde 402), `TYPESAFE_API_KEY`, `NEATLOGS_API_KEY`, `PFM_JWT_TOKEN` (el anterior venció), `XPOZ_API_KEY`. Generar `SECRET_KEY` y `TOKEN_ENCRYPTION_KEY` (la guía trae el comando). Rotar cualquier key que haya estado expuesta.
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
- Al crear la app de Post for Me, poner en su panel la URL de retorno `{FRONTEND_URL}/connections/pfm/callback` (cambió el 27 oct con el arreglo del OAuth) (pedido de CONNECT).
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

## INTELLIGENCE en espera, 27 oct 07:47 UTC (`761185f`)
- T0–T12 terminadas. Ports en 1.10. Las sondas y los tests live están escritos y no se corrieron; no se gastó cuota. lumi_ai + apps/intelligence: 640 tests pasan. Ruff y makemigrations limpios.
- T4b: pasarela MCP con `resolve_pending` (`0c07e2e`) y resultado de `connect_account` filtrado por campos permitidos (`5b35885`). CONNECT tiene los SHA para su e2e real.
- Timeout de tools corregido (`761185f`): CancelToken + `@aio` con `atomic()` y una compuerta antes del commit que revierte si se canceló. Hay test con base real. Sin cubrir: escrituras anteriores dentro de la misma tool, llamadas externas y Chroma (se repara con `reindex_vectors`).
- Pendientes de otros. CONNECT: OwnPostSync, ConnectionLinks y que sus escrituras usen `@aio`. ARCHITECT: `.gitignore`, `.env.example` de video, el arranque ASGI sin key y su test de `legacy_import`.
- INTELLIGENCE espera las keys y las 4 decisiones de Christian.

## Estado 27 oct, 08:10 UTC
- **ARCHITECT** (`17e7d0c`): 1486 tests pasan y 3 se saltan (live). `apps.intelligence.urls` montado, SSE declarado, `post_media.kind` nullable, esquema legado congelado en un fixture, ruta `POST /connections/{provider}/link` en el contrato, códigos de error `<dominio>.<motivo>` vigilados por un test, y causa del test intermitente de `claim_due_polls` arreglada. Paridad con los 418 tests legados: 349 cubiertos, 45 reemplazados, 3 desvíos y 21 sin cubrir (11 de INTELLIGENCE, 10 de CONNECT, ya avisados). `lumi/app/` sigue intacto.
- **Orquestador**: confirmó las filas 24 (`text_truncated` sigue a la última captura) y 25 (solo se guarda una captura cuando cambia alguna métrica, siempre que quede registrada la hora de la última comprobación). `OPENROUTER_API_KEY` pasa a opcional en `API_KEYS.md`, `AGENT_KEYS_SETUP.md` y este archivo; `chat_unavailable` pasa a `chat.unavailable`. `AGENTS.md` no se toca: describe el app legado, donde OpenRouter sí es obligatoria.
- **CONNECT**, revisión de seguridad sobre `9bc2ac6`: sin críticos. Hay 3 altos que está arreglando:
  1. El `state` de OAuth no está atado a la sesión del navegador, así que alguien podría quedarse con la cuenta social de otra persona enviándole un enlace de conexión.
  2. Secretos de Meta en los logs de httpx a nivel INFO.
  3. El presupuesto de Xpoz se reinicia en cada request.
  Además hay 4 medios: la sincronización de PFM se fía de PFM y usa un `external_id` adivinable, un token ilegible bloquea el refresh, la confirmación de escrituras MCP va por lista negra y `?say=` dispara prompts. El arreglo del punto 1 cambia CONTRATOS §11 y lo coordina con ARCHITECT.
- **08:07, OAuth (ARCHITECT y CONNECT):** el diseño acordado es el siguiente. El proveedor redirige a una página del frontend, y esa página hace un POST autenticado con `{code, state}`. El backend acepta solo el `state` del mismo usuario, lo consume de forma atómica y tiene un test que reproduce el ataque. Lleva PKCE y un TTL corto.
  - Esto cambia CONTRATOS §4 y §11: los callbacks dejan de ser públicos, y los `redirect_uri` registrados en cada proveedor pasan a `FRONTEND_URL`.
  - Hasta que esté arreglado, no se abre ninguna conexión social real a usuarios.
  - Cuando se suba el cambio, el orquestador tiene que actualizar las URLs de callback en `API_KEYS.md`, `AGENT_KEYS_SETUP.md` y las decisiones de Christian, incluido el callback de PFM.

## Revisión horaria, 27 oct 2026, 08:10 UTC
- main avanzó a `632217e` (fotos de perfil en el flujo de pensamiento, guardadas en la base). Se fusionó en `lumi-orquestador` sin force-push. Hubo un conflicto: `lumi/frontend/src/api/client.ts` lo borró CONNECT al partir el cliente en módulos. Los dos campos nuevos se pasaron a `api/chat.ts` (`SamplePost.avatar_url`) y `api/trends.ts` (`TrendMatch.author_avatar_url`), y `App.tsx` calcula `activeAvatarUrl` desde `activeProfile`. `tsc --noEmit` limpio.
- Falta portar al backend Django lo que main añadió en el legado: columna `listening_matches.author_avatar_url` (migración alembic `b7f3a91c5d20`), avatar en `services/handle_db.py`, `tools/listening.py`, `routers/trends.py` y `agent/loop.py`, con su test `tests/test_handle_db.py`. Le toca a ARCHITECT (trends) y a CONNECT (handles). Esto suma tests legados al mapa de paridad.
- Últimos commits: ARCHITECT 08:07, INTELLIGENCE 08:08, CONNECT hasta `888b7f4` (subido a las 08:10). CONNECT ya arregló los altos 2 (secretos de Meta fuera de la URL y loggers HTTP a WARNING) y 3 (tope diario de Xpoz por usuario y global desde el ledger), y el medio de PFM (`external_id` aleatorio y verificación local de cada cuenta). Además montó ConnectionLinks y un e2e con el agente real y un modelo simulado por HTTP. Sigue con el alto 1 (`state` de OAuth). Ninguno lleva más de 2 horas sin commits.
- Sigue sin aparecer `/workspace/lumi-data/lumi.db`.

## Revisión horaria, 27 oct 2026, 09:10 UTC
- `main` no avanzó desde `632217e`. Rama al día en `90a6180`.
- **ARCHITECT** (último `ca41934`, 08:50): `posts.last_checked_at` (filas 24 y 25 de paridad confirmadas); paridad con estado `retired` y motivo (`niche_schemas`: 1 portado y 10 retirados; legado congelado en 422); CONTRATOS fila 5: `OAuthState.consume` filtra también por `user_id`; `pfm_links` en SCHEMA; topes de Xpoz en `.env.example` (`XPOZ_RUN_CREDIT_BUDGET=12`, topes por red opcionales, `XPOZ_DAILY_CREDIT_CAP_USER=60`, `XPOZ_DAILY_CREDIT_CAP_GLOBAL=300`), con lo que queda resuelto el aviso de CONNECT sobre el valor 10; `claim_due_polls` con CTE `MATERIALIZED` para que `LIMIT ... FOR UPDATE SKIP LOCKED` corra una sola vez. Pendiente: T4 a T12 (`services.py` de perfiles y chat y sus rutas), portar el avatar de autor de main (trends) y actualizar `how-to-setup.md` al final.
- **CONNECT** (último `90a6180`, 08:52): cerró los medios de la revisión de seguridad. Medio 5: un token ilegible ya no bloquea refresh ni status, y hay comando `rotate_tokens`. Medio 6: la confirmación de escrituras MCP pasa a lista blanca de herramientas de solo lectura, con argumentos completos y una escritura viva por perfil. Medio 7: se quitó el efecto `?say=` del frontend. Bajo: `SdkMcpTransport` solo abre sesión hacia hosts permitidos por https. **Sigue abierto el alto 1** (atar el `state` de OAuth a la sesión: callbacks vía página del frontend + POST autenticado, PKCE). Cuando se suba, el orquestador actualiza las URLs de callback en `API_KEYS.md` y `AGENT_KEYS_SETUP.md`. Pendientes en su estado: programar `connections.refresh_expiring` en Celery beat, portar el avatar de main en handles, y que INTELLIGENCE use `build_mcp_gateway()` y `resolve_pending`.
- **INTELLIGENCE** (último `f4a660c`, 08:08): códigos `voice.transcription_*`, `VIDEO_TIMEOUT_SECONDS` en `from_env`, paridad de `test_niche_schemas`. Sigue esperando las keys y las 4 decisiones de Christian (Gemini de pago para video, términos de uso de video de terceros, autorizar tests live, posts reales para calibrar jueces). T10 sigue sin fuente de URLs de medios. Lleva ~1 h sin commits, menos de 2 h.
- Ningún bot lleva más de 2 horas sin commits ni reportó un bloqueo nuevo que el orquestador pueda destrabar. No se escribió a ningún bot.
- Sigue sin aparecer `/workspace/lumi-data/lumi.db` ni un dump.

## 09:20 UTC
- **ARCHITECT** aprobó el arreglo de OAuth de CONNECT (rama `alto1v2`, que se rebasó antes de subir; los commits que entraron son `a2ba0b5`..`3e67db4`; CONNECT dice que pasan 1702 pytest, 55 tests de frontend y 10 e2e). CONNECT lo sube después de rebasar sobre `b0c7051`. Las redirect URIs salen ahora de `{FRONTEND_URL}/connections/<provider>/callback` y `PUBLIC_BASE_URL` es obsoleta (`242791e`). El orquestador ya actualizó `API_KEYS.md` (con una tabla por proveedor), `AGENT_KEYS_SETUP.md` y este archivo. Contrato: se añade `POST /connections/pfm/sync` con throttle, y `GET /pfm/status` ya no escribe (fila 26, `b0c7051`).
- **ARCHITECT**: `posts.last_checked_at` (`660bd1e`). Paridad con los 422 tests legados (main sumó 4): 350 cubiertos, 45 reemplazados, 3 desvíos, 10 retirados y 14 huecos, todos de CONNECT. El pytest por defecto pasa sin keys desde `17b7280`. Fixture de `claim_due_polls` con CTE materializado (`ca41934`).
- **Primera conexión social real**: la decide Christian, y solo cuando el arreglo esté en la rama.
- **Pendiente de portar los avatares de main `632217e`**: `listening_matches.author_avatar_url` y trends le tocan a ARCHITECT; `handle_db` le toca a CONNECT.
- `AGENTS.md:88` y `README.md:119` describen el backend legado y no se tocan.

## Revisión horaria, 27 oct 2026, 10:10 UTC
- `main` no avanzó desde `632217e`. Rama al día en `d1aa288`.
- **CONNECT** (último `d1aa288`, 10:07): **el alto 1 de OAuth ya está en la rama** (`a2ba0b5`, `c5bf3e0`, `25d3eb6`, `d6dcc30`, `3e67db4`): el callback público no intercambia el código, la página del frontend hace `POST /complete` con el Token del dueño del `state`, `user_id` obligatorio al consumir, `state_expired` alcanzable, y test con un mutante que acepta un `state` ajeno. Después: guardia autouse que deja los tests de connections sin red (`9db3bba`), conserva el refresh token rotado de X si falla el guardado (`fa4d9d2`), `POST /connections/{provider}/link` con selector de Página (`d544c76`), e2e que desconecta todas las Páginas de Facebook (`509432b`), y `HandleDirectory` reemplaza `handle_db` con avatares por `get_or_create_handle` (solo rellena): 6 de 10 huecos de `handle_db` cubiertos (`d1aa288`). Pendiente: T11 frontend, T12, T14, 4 huecos de `handle_db`, `refresh_expiring` en Celery beat.
- **ARCHITECT** (último `9fd5c17`, 09:37; el commit del avatar es `67ad108`): `author_avatar_url` se lee de `social_handles.avatar_url`, sin columna ni migración (decisión R3); quitado `PUBLIC_BASE_URL` de los settings; tests sin keys con `conftest.py` raíz. Pendiente: T4 a T12 (`services.py` de perfiles y chat y sus rutas) y `how-to-setup.md` al final.
- **INTELLIGENCE** (último `f4a660c`, 08:08): lleva ~2 h sin commits. Espera las keys y las 4 decisiones de Christian, y T10 sigue sin fuente de URLs de medios. Hay trabajo que no depende de Christian: según el estado de CONNECT, INTELLIGENCE aún no llama a `build_mcp_gateway()` ni a `resolve_pending`, y CONNECT pidió que sus escrituras usen `@aio`. Se pide al padre que se lo indique.
- Con el alto 1 en la rama, la primera conexión social real ya la puede decidir Christian (necesita sus keys de proveedores).
- Sigue sin aparecer `/workspace/lumi-data/lumi.db` ni un dump.

## Revisión horaria, 27 oct 2026, 11:01 UTC
- `main` no avanzó desde `632217e`. Rama al día en `cc789ce`.
- **INTELLIGENCE** volvió a trabajar (último `e28371e`, 10:18): T4 (pegamento Django) hecha salvo `OwnPostSync`; `wiring.get_wiring()` crea la pasarela MCP y el bucle llama a `resolve_pending` antes de cada turno (`0c07e2e`); `connect_account` cableada y escrituras MCP bajo `@aio`/`CancelToken` (`d7543e0`); avatares de autor solo si la fuente los trae (`af4e1d5`, puertos 1.11). Bloqueos sin cambio: T10 vídeo sin fuente de URLs de medios, e Instagram cuesta 12 créditos de Xpoz con `XPOZ_RUN_CREDIT_BUDGET`=10.
- **CONNECT** (último `cc789ce`, 11:01): T11 frontend hecha (Playwright 11/11, node 58/58, tsc limpio); pasadas de ingest con paridad (`bea2d97`); runtime con `connect_account` y la pasarela MCP (`6c4717f`); `DjangoOwnPostSync` con escrituras bajo `@aio` (`fc9271e`), que desbloquea `backfill_posts` de INTELLIGENCE; el stream del chat pide solo `text/event-stream` (`2404169`). Pendiente: T12, T14, huecos restantes de `handle_db`, `refresh_expiring` en Celery beat.
- **ARCHITECT** (último `9fd5c17`, 09:37, ~1 h 25 min): sin commits nuevos. Pendiente: T4 a T12 (`services.py` de perfiles y chat y rutas), copiar las variables nuevas de CONNECT a `.env.example`, y `how-to-setup.md` al final. Si a las 12:00 sigue sin commits, se le escribe.
- Sigue sin aparecer `/workspace/lumi-data/lumi.db` ni un dump. Nadie fue avisado en esta revisión.

## Revisión horaria, 27 oct 2026, 12:08 UTC

- `origin/main` sigue en `632217e` (ya incluido en la rama). Rama en `2b6a277`. No hay `/workspace/lumi-data/lumi.db` ni dump.
- **ARCHITECT** activo (no estaba parado: sus commits de 11:07 a 12:01 no llevan la etiqueta `[ARCHITECT]`). Hecho: refresco de fotos `update_handle_avatar`/`update_profile_avatar` y `HANDLE_DB_ENRICH_LIMIT` (`2bc9965`); contratos filas 28 a 31 (`a8f1d20`, `38fa20d`, `eeb6826`, `2b6a277`); revisión ronda 9 de `5257760`/`3c57f88` (FK, índices, concurrencia, migración `0008`); `import_legacy --handle-mappings PATH` importa los handles elegidos del legado a `user_saved_handles` y `--verify` falla si falta alguno (`1f9897f`). Pendiente: T4 a T12 de su plan (`services.py` de perfiles y chat), lista de T12 al borrar `lumi/app/`.
- **CONNECT** activo (último 11:49). Hecho: fotos de handles y de la cuenta PFM (`3dda0e1`, `d9ab891`); `/handles/select` guarda solo `(platform, handle)` con origen `cache` (`f843610`), el frontend manda `platform` (`fe683e4`); `/handles/saved` es la lista propia del usuario en `user_saved_handles`, migración `0008` (`5257760`); `platform` obligatorio en select y `platforms` en search y saved, 400 `validation_error` (`3c57f88`). Pendiente: T12, T14; sugerencias de ARCHITECT: quitar `ix_user_saved_recent` y `db_index=False` en `user`, y normalizar `platform` igual que `platforms` (hoy `X` o `x ` dan 400).
- **INTELLIGENCE** activo (último 11:20). Hecho: `DjangoOwnPostSync` cableado (`backfill_posts`, `profile.bootstrap`, `profile.refresh`, `0377f2d`); `HandleBook` (PORTS 1.12) y paridad del legado con 0 huecos (364 cubiertos, `4971a13`); pruebas HTTP de `/voice/transcribe` (`4f997e4`); `JobError` con prefijo de dominio (`b92761e`); gana la foto guardada en `social_handles` (`f8c50ea`). Sigue esperando keys y decisiones de Christian.
- Dato nuevo para Christian: los handles elegidos del legado no están en `lumi.db`, vivían en la colección Chroma `handle_mappings`. Para importarlos hace falta, además del `lumi.db`, un export JSON de esa colección (`import_legacy --handle-mappings`). Sin él la demo funciona: `saved` muestra los perfiles propios y se llena al elegir.
- Ningún bot lleva más de 2 h sin commits ni reportó un bloqueo nuevo; no se escribió a ninguno.

## TRASPASO, 27 oct 2026, 13:05 UTC: todo apagado
Christian pidió apagar todo para que otro agente siga. Los 3 bots (ARCHITECT, INTELLIGENCE, CONNECT) están detenidos y la rutina horaria del orquestador está borrada. La rama es `lumi-orquestador`. Reglas que siguen vigentes: sin force-push, sin merge a main, sin deploy y nada live sin permiso de Christian.

**Estado**
- Migración a Django/DRF + PostgreSQL completa. Paridad con el legado: 0 huecos (364 cubiertos, 45 reemplazados, 3 desvíos, 10 retirados).
- El backend viejo se movió a `lumi/legacy/` por decisión de Christian (12:50 UTC), en `7fff124`, `c3821c0` y `845a612`. Los tests viejos se corren a mano según `lumi/legacy/README.md`.
- Tests sin keys: el pytest por defecto da 1471 pasan; `apps lumi_ai` da 2031 pasan y 9 se saltan; frontend 62/62; e2e 11/11 (reportado por CONNECT).
- Seguridad: los hallazgos altos y medios están cerrados, incluido OAuth con callback al frontend y POST autenticado. Las redirect URIs son `{FRONTEND_URL}/connections/<provider>/callback`.
- El registro de decisiones en inglés está en `lumi/plan/decisions.tsv`. Ver en sus filas 55 a 70 los avisos de verificación.

**Pendiente**
- **Christian:**
  - Keys en `lumi/.env`: `GROQ_API_KEY`, `SECRET_KEY` y `TOKEN_ENCRYPTION_KEY`; recomendadas `TYPESAFE_API_KEY` y `OPENROUTER_API_KEY`.
  - Autorizar los tests live.
  - `lumi.db` y el export de Chroma `handle_mappings`.
  - Gemini de pago para video y los términos de cada red.
  - PFM (token y callback), créditos de Xpoz, verificación de Meta y acceso de LinkedIn.
  - Las 5 preguntas de MUSE.md.
  - Posts reales para calibrar a los jueces.
  - La primera conexión real.
  - El 409 del registro.
- **Técnico:**
  - Actualizar las rutas viejas en `CLAUDE.md`, `CONTRIBUTING.md`, `.agents/*.md`, `docs/flow-map.*`, `docs/blueprint-fix.md`, `docs/mcp-connectors.md`, `docs/xpoz_optimization.md` y `docs/tools.md`.
  - ~~`how-to-setup.md` pide Node 20+~~ (hecho: ahora dice 22.18+).
  - ~~Corregir los SHA mal citados en este archivo~~ (hecho).
  - Revisión de seguridad externa antes de tener usuarios reales.
  - Nunca se corrieron docker compose ni la importación con datos reales.


## Continuación por Claude Code, 27 oct 2026, 14:25 UTC
Se retoma desde TRASPASO en Windows 11 (Node 22.13, Python 3.12 vía uv). Reglas de rama sin cambios.

**Hecho**
- Rutas viejas repuntadas a `legacy/` en `CLAUDE.md`, `CONTRIBUTING.md`, `.agents/*.md`, `docs/flow-map.*`, `blueprint-fix.md`, `mcp-connectors.md`, `xpoz_optimization.md` y `tools.md` (123 líneas). `CLAUDE.md` lleva ahora un aviso de que describe el backend anterior.
- `how-to-setup.md`: Node 22.18+. SHA corregidos en este archivo. `CONNECT.md`: presupuesto Xpoz 12.

**Línea base en Windows (medida, sin keys, Postgres de pgserver)**
- pytest: 1462 pasan, 3 se saltan, 9 fallan (el traspaso decía 1471 pasan). Los 9 son del entorno Windows, no de lógica: 8 de `test_startup_e2e.py` y `test_collectstatic.py` lanzan `manage.py` con un entorno vacío sin `SYSTEMROOT` (asyncio no carga) y con salida en cp1252 sin decodificar; `test_sse.py::test_a_quiet_turn_gets_pings` usa un ping de 10 ms y el reloj de Windows no llega a esa resolución. No se corrigieron; en Linux deberían pasar.
- `pgserver` en Windows no trae la carpeta `timezone/` y Postgres rechaza `TimeZone=UTC`. Arreglo local: copiar `.venv/Lib/site-packages/tzdata/zoneinfo` a `.venv/Lib/site-packages/pgserver/pginstall/share/postgresql/timezone`. El puerto de pgserver cambia en cada arranque, hay que actualizar `DATABASE_URL`.
- Un `.env` copiado del `.env.example` viejo trae `GOOGLE_OAUTH_REDIRECT_URI` obsoleto y rompe `test_google_api`; hay que partir del `.env.example` de esta rama.
- Frontend: `npm test` falla en Node 22.13 (sin type stripping por defecto); con `node --experimental-strip-types --test` hace falta repetir la corrida.
- Docker Desktop está instalado pero apagado, así que `docker compose` sigue sin probarse.

**Siguiente**: probar `docker compose` con Docker encendido, levantar Django y el frontend con placeholders, y afinar el mapa de paridad (270 de 364 tests mapeados a archivo entero).
