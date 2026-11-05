# PLAN LUMI-CONNECT

Bot: LUMI-CONNECT (`4c242e68-4666-4132-ab34-da80d3e2bed4`). Orquestador: Grok Bot. Plan escrito el 2026-10-27 sobre el commit `cce6ca3` de `main`.

Lee primero `lumi/plan/ContextoTareas.md`. Ejecuta este plan sin preguntar al usuario; decide lo reversible, anótalo en `decisiones.tsv` y sigue.

## 0. Protocolo común (idéntico en los tres planes)

- Una sola rama compartida: `lumi-orquestador`. `git fetch origin && git checkout lumi-orquestador`. Nunca `push --force`, nunca merge a `main`, nunca deploy, nunca abrir PR (el orquestador abre un Draft PR al final).
- Commits en tu ámbito de archivos, en español, formato `[CONNECT] área: qué cambió`. Commitea al terminar cada tarea o cambio importante y como mínimo cada hora de trabajo. Antes de cada push: `git pull --rebase origin lumi-orquestador`, corre los tests de tu ámbito y luego `git push origin lumi-orquestador`.
- Conflictos: si el conflicto toca archivos fuera de tu ámbito, no lo resuelvas a ciegas; conserva la versión del dueño y avisa al orquestador. Conflicto en `lumi/uv.lock`: `git checkout --theirs uv.lock && uv lock`, y commitea. Puedes añadir tus dependencias con `uv add`; nada más de `pyproject.toml`.
- Estado propio: `lumi/plan/estado/CONNECT.md` (qué terminaste, qué sigue, bloqueos, SHA del último commit verde) y `lumi/plan/estado/CONNECT-decisiones.tsv` (una fila por decisión: fecha, qué, por qué, evidencia, resultado; skill `/show-me-your-work`). Actualízalos en cada commit.
- Reporte al orquestador al cambiar de fase y ante cualquier bloqueo, con: fase, SHA, tareas hechas, comandos de verificación con resultado, riesgos y qué necesitas de otro bot.
- Skills permitidas: `/architect`, `/tdd`, `/blast-radius`, `/correct`, `/show-me-your-work`, `/figure-it-out`, `/how`, `/why`, `/create-verification-skill`, `/interrogate`. Prohibida `/arena`. Aplica `/correct` en todo el trabajo de repo y `/unslop` en lo que escribas para personas.
- Seguridad: nunca escribas valores de keys ni tokens en archivos, commits, logs ni salidas. Los docs solo nombran variables. Las pruebas con llamadas reales gastan cuota: mínimas, marcadas `live`, y nunca en bucle.
- Límite de uso: no pases el límite semanal Premium de Christian. Sin créditos extra ni cargos. Si el límite se llena, detente y reporta.
- Idioma: docs para Christian en español. Código, identificadores y docstrings en inglés (como el repo actual). Textos de la interfaz: los que ya usa el frontend (inglés) salvo que Christian pida otro idioma. Con Christian, español.
- No cambies código fuera de tu ámbito (sección 2); pide los cambios al dueño.

## 1. Misión

Conectar Lumi con el mundo y con el usuario:

1. **Conexiones**: OAuth 2.0 y adaptadores para Facebook (modo Development), LinkedIn (`w_member_social`) y X (apagado detrás de `X_LIVE_ENABLED=false`, nunca gastar créditos de X). Tokens cifrados en Postgres, con refresco y revocación. Post for Me como proveedor adicional detrás de la misma interfaz.
2. **Datos**: clientes de Post for Me y Xpoz (con presupuesto de créditos), ingesta de posts y métricas, búsqueda de handles.
3. **Frontend**: fusionar los dos frontends en uno solo en `lumi/frontend/` con todas las funciones de ambos, borrar `frontend/` de la raíz, e integrarlo con el backend Django.
4. **E2E**: pruebas de punta a punta del flujo de la demo.
5. **Muse**: no se implementa; solo `lumi/docs/MUSE.md` con todo el contexto para un agente futuro.

Demo objetivo: el usuario entra, conecta una cuenta, Lumi trae contenido autorizado de su nicho, la IA analiza posts y videos, aprende patrones y genera un post personalizado que el usuario revisa en React y, si confirma, publica.

## 2. Ámbito de archivos

Tuyos:

- `lumi/apps/connections/**` (modelos, proveedores, OAuth, publicación, clientes PFM y Xpoz, ingesta, handles, MCP de Google, sondas, vistas, `urls.py`, migraciones, tests)
- `lumi/frontend/**` (el frontend único)
- `frontend/**` de la raíz (solo para leerlo, fusionarlo y al final borrarlo con `git rm -r frontend`)
- `lumi/e2e/**` (pruebas de punta a punta) y `lumi/apps/connections/e2e_settings.py`
- `lumi/docs/MUSE.md`, `lumi/docs/CONEXIONES.md`, `lumi/docs/ADR-CONNECT-*.md`
- Tu bloque `# --- CONNECT ---` en `lumi/.env.example`
- `lumi/plan/estado/CONNECT*.{md,tsv}`

No toques: `lumi/config/**`, `lumi/apps/{core,accounts,profiles,chat}/**`, `lumi/pyproject.toml` (salvo `uv add`), Docker, CI, `lumi/docs/{SCHEMA,CONTRATOS}.md` (ARCHITECT); `lumi/lumi_ai/**`, `lumi/apps/intelligence/**` (INTELLIGENCE); `lumi/plan/ContextoTareas.md`, `lumi/plan/PLAN_*.md`, `lumi/docs/API_KEYS.md`, `lumi/docs/AGENT_KEYS_SETUP.md` (orquestador). No borres nada de `lumi/app/` (lo retira ARCHITECT al final). Puedes leer `lumi/app/` y `lumi/tests/` todo lo que quieras.

## 3. Estado actual (verificado en `cce6ca3`)

**Backend legado que te toca portar**

- `lumi/app/services/pfm.py`: cliente de Post for Me (httpx). Endpoints usados: `POST /v1/social-accounts/auth-url` (permisos `posts` + `feeds`), `GET /v1/social-accounts/{id}`, `GET /v1/social-account-feeds/{id}`, `POST /v1/social-accounts/{id}/disconnect`; `/v1/social-posts` es de publicación. PFM soporta Instagram, X, LinkedIn, TikTok, Facebook, YouTube, Pinterest, Bluesky y Threads. Límites: 5 req/s y 40 req/min. El token (`PFM_JWT_TOKEN`) que existía está vencido (401). PFM guarda los tokens OAuth; el redirect se configura en su panel. Contiene `classify_post_kind` y `is_authentic_original` (replies a `user_activity`, retweets nunca son voz).
- `lumi/app/routers/pfm.py`: `POST /pfm/connect` (usa `external_id="lumi_user"` fijo) y `GET /pfm/callback` (devuelve JSON en vez de redirigir).
- `lumi/app/services/xpoz.py` (httpx, `https://api.xpoz.ai`): plan gratis con 500 créditos únicos y 2 créditos por consulta de X (~125 consultas con la key 1); `XPOZ_API_KEY` y `XPOZ_API_KEY_2` (esta última se lee con `os.environ`); `USER_LIVE_FIELDS`; el servidor devuelve una página de 20 posts. Docs: `lumi/docs/xpoz_optimization.md` (Paso 0 bloqueante: verificar capacidades de Xpoz antes de construir sobre supuestos; `XPOZ_RUN_CREDIT_BUDGET` está planeada y sin construir).
- `lumi/app/services/ingest.py` (571 líneas): backfill y refresco de posts y métricas desde PFM y Xpoz hacia la base, con ruteo de `posts` y `user_activity`.
- `lumi/mvp/handle_search/server.py` (863 líneas) y `lumi/app/services/handle_db.py` (279): búsqueda de handles con Xpoz, caché y mapeos en Chroma (`handle_cache`, `handle_mappings`). Lee `MVP_CHROMA_*`, `HANDLE_SEARCH_DB` (SQLite `lumi.db`; desaparece), `MVP_XPOZ_LIVE`, `MVP_XPOZ_BUDGET`, `MVP_CACHE_TTL_MINUTES`, `HANDLE_DB_ENRICH_LIMIT`. Rutas: `/handles/{search,saved,select,stats}`.
- MCP de Google Drive y Docs: `lumi/app/services/{mcp.py (554),mcp_connectors.py}`, `routers/mcp_google.py` (`/mcp/google/{connect,callback,status}`), `background/mcp_refresh.py`, `models/mcp_auth_account.py`. Interruptores `MCP_ENABLED`, `MCP_GDRIVE_ENABLED`, `MCP_GDOCS_ENABLED`; credenciales `GOOGLE_OAUTH_CLIENT_ID/SECRET/REDIRECT_URI`. **Los tokens se guardan en texto plano en `mcp_auth_accounts` (modelo con `access_token`, `refresh_token`, `scopes`, `expires_at`).** El `state` de OAuth y las escrituras pendientes viven en memoria del proceso.
- `lumi/app/tools/connect.py`: `connect_account(handle)` fija `ateh_x_connect`.
- `GET /pfm/callback` y `/mcp/google/callback` devuelven JSON: el usuario se queda mirando JSON en el navegador.

**Frontends (dos, divergentes; ambos `npm ci` + typecheck + build OK en Node 20)**

- Raíz `frontend/` (53 archivos: `App.tsx` 1101 líneas, `PromptBar` 1331, `Settings` 676, `AgentThinking` 338). Tiene lo que el otro no: voz (`src/voice/{recorder,speak}.ts`, `src/api/voice.ts`, Whisper de Groq por `/voice/transcribe`), motor de revelado (`src/reveal/{revealEngine,useSmoothText}.ts` y `tests/revealEngine.test.ts`), pestaña Settings → Connectors con estado del conector de Google (`getGoogleConnectorStatus`, `openGoogleConsent`), tipos `HandleSearchResult`/`SavedHandlesResponse`, `sendChatMessage` en `client.ts` y `agent.ts`. `API_BASE` fijo a `http://localhost:8000`.
- `lumi/frontend/` (51 archivos: `App.tsx` 963, `PromptBar` 1174, `Settings` 514, `AgentThinking` 501). Tiene lo que el otro no (`WorkingMark.tsx` se borró a propósito en main `62056d4`, "drop the orb": NO portarlo ni restaurarlo): `formatClock.ts` (+ test), `usePrefersReducedMotion.ts`, avatar de usuario en la barra lateral vía `userProfile` (unavatar.io), `scanError` en `ChronicOnline`, `InsightCards` renombrado (gasto/uso a impresiones/engagement, sin la ficción de kWh y dólares), CSS `edge-dissolve` en `global.css`, `VITE_API_BASE` en `agent.ts` y `client.ts`, tipos `HandleRow`/`HandleSearchResponse` y funciones `searchHandles`/`getSavedHandles`/`selectHandle`. No tiene voz, ni revelado, ni UI del conector de Google.
- Difieren 25 archivos, entre ellos: `package.json`, `App.tsx`, `App.module.css`, `api/agent.ts`, `api/client.ts`, `AgentThinking` (tsx y css), `ChronicOnline`, `InsightCards`, `PromptBar`, `Settings`, `Sidebar`, `styles/global.css`. Ambos tienen `package-lock.json` y `pnpm-lock.yaml` (lockfiles duplicados). Ambos corren en el puerto 3010 (`vite --port 3010`).
- Pruebas del frontend: `node --test` sobre `.ts` exige Node ≥ 22.6; en Node 20 (la box) falla con `ERR_UNKNOWN_FILE_EXTENSION`. Con `npx -y node@22 --test ...` pasan: raíz 14/14, `lumi/frontend` 11/11. En `lumi/frontend`, el script `test` nombra `tests/revealEngine.test.ts`, que no existe allí (solo en la raíz), así que `npm test` falla tal cual.
- Defectos de frontend ya identificados en `lumi/AGENTS.md`: `PromptBar` ignora `busy` (envíos concurrentes y la respuesta cae en otro chat); la heurística `isConnectLink` convierte cualquier enlace con "LinkedIn" en la tarjeta de conectar X; borrar un chat local borra el historial del servidor; el botón "Upgrade" abre un chat nuevo; no se puede cambiar de perfil; código muerto (`ChatBar`, `LoadingDots`, `useSimulatedRun`); ficción en Settings (`alex@lumi.app`, asientos); el bloque `html.light` de tokens es código muerto; `getProfileAnalytics` se llama en cada cambio de vista y nunca se muestra; handles de tendencias fijos `["sama","levelsio","karpathy","paulg","swyx"]`.

**Hechos que debes revalidar con las páginas oficiales (los trajo tu investigación previa y no los verificó el orquestador)**: la investigación previa de la box (`/workspace/lumi-integraciones/research.md`; si no existe en tu entorno, investiga desde cero) dice que Meta exige App Review de `pages_manage_posts`, `pages_read_engagement` y `read_insights` y Business Verification; que LinkedIn exige solicitar la Community Management API (con screencast) para páginas de empresa y que con autoservicio solo existe `w_member_social`; que X cobra créditos por post. Confírmalo hoy (2026-10-27) y anota fecha y URL.

## 4. Decisiones fijas

- OAuth 2.0 con Authorization Code; PKCE donde el proveedor lo exija (X) y recomendable en el resto. Estado de OAuth en Postgres (tabla `OAuthState`), de un solo uso y con expiración, nunca en memoria del proceso.
- Tokens cifrados en reposo con Fernet (`TOKEN_ENCRYPTION_KEY`, obligatoria). Soporta rotación con `MultiFernet` si existe `TOKEN_ENCRYPTION_KEY_PREVIOUS` (opcional, nueva). Nunca se loguean ni se serializan; el serializador de DRF no los expone.
- Interfaz única `SocialProvider` para `meta`, `linkedin`, `x` y `pfm`. PFM guarda sus propios tokens, así que su adaptador solo conserva el id de cuenta de PFM (sin tokens).
- X: `X_LIVE_ENABLED=false` por defecto. Con el interruptor apagado el adaptador no hace ninguna llamada de red a X (ni siquiera el intercambio de código ni la publicación) y devuelve un error tipado `LiveDisabled` con mensaje claro. Construir la URL de autorización es local y se permite para mostrar la UI. Nunca se activa sin que Christian lo pida.
- Facebook en modo Development: solo funcionan cuentas con rol en la app. Documenta que sin App Review no se publica a nadie más.
- LinkedIn con autoservicio: publicar en el perfil personal (`w_member_social`). Leer los posts propios requiere un permiso restringido (`r_member_social`); si no está disponible, el producto lo declara en la UI (estado `limited`) en vez de simular datos.
- Publicar siempre requiere confirmación explícita del usuario (`confirm=true` desde un botón de la UI) y una clave de idempotencia; también existe `dry_run`. El agente no publica solo.
- Muse (Meta Model API, Muse Spark) no se implementa. Solo `lumi/docs/MUSE.md`.
- El frontend es único, en `lumi/frontend/`, con todas las funciones de ambos. Un solo gestor: npm (`package-lock.json`); borra `pnpm-lock.yaml`. La raíz `frontend/` se borra al final de la fusión.
- No hay respuestas simuladas en producción. Los dobles de proveedores viven en `tests/` y en `e2e_settings.py`.

## 5. Estructura objetivo

```
lumi/apps/connections/
  models.py            ConnectedAccount, OAuthState, PublishJob, McpAuthAccount, HandleSearchCache
  crypto.py            Fernet / MultiFernet, EncryptedTextField
  providers/           base.py (SocialProvider, errores tipados), meta.py, linkedin.py, x.py, pfm.py, registry.py
  oauth.py             flujo, PKCE, estado en Postgres
  publishing.py        PublishJob, idempotencia, dry_run
  clients/             pfm.py (límite 5/s y 40/min), xpoz.py (presupuesto, rotación de keys), http.py (reintentos, timeouts)
  socialdata.py        implementa el puerto SocialData de lumi_ai
  ingest.py            sync_profile(profile_id), backfill_profile_posts, classify_post_kind, is_authentic_original
  handles/             search.py, cache.py (Postgres), views
  mcp/                 gateway.py (puerto McpGateway), connectors.py, google.py, refresh.py
  keys.py              sondas para check_keys
  views.py, serializers.py, urls.py, tasks.py (refresco de tokens), apps.py, migrations/, tests/, e2e_settings.py
lumi/frontend/         el frontend fusionado
lumi/e2e/              Playwright (o la alternativa documentada en T11)
```

## 6. Contratos con los otros bots

Con ARCHITECT:

- Te da: `User`, `SocialProfile`, `SocialHandle`, `Post`, `MetricSnapshot` y `apps/profiles/services.py` (`upsert_posts`, `get_or_create_handle`, `append_metric_snapshots`...), auth por token DRF (`Authorization: Token <token>`), CORS por `CORS_ALLOWED_ORIGINS` (debe incluir `http://localhost:3010`), el registro de keys (`apps.core.keys.register`), Docker y `.env.example`. Rutas con prefijo `/api/v1/` (mapa en su plan, sección 6).
- Tú le das: `apps.connections.ingest.sync_profile(profile_id)` (lo llama el poller), rutas `/api/v1/connections/*`, `/api/v1/handles/*`, `/api/v1/publish`, sondas de keys y el frontend ya apuntado a `/api/v1/`.
- Rutas nuevas tuyas que ARCHITECT debe incluir en `config/urls.py` (ya incluye `apps.connections.urls`): `GET /api/v1/connections`, `POST /api/v1/connections/<provider>/start`, `GET /api/v1/connections/<provider>/callback`, `POST /api/v1/connections/<id>/disconnect`, `POST /api/v1/connections/<id>/refresh`, `POST /api/v1/publish`, y las heredadas `connections/pfm/{connect,callback}`, `connections/google/{connect,callback,status}`, `handles/{search,saved,select,stats}`.
- Aprobación de contrato: cuando ARCHITECT publique `CONTRATOS.md`, escribe en `estado/CONNECT.md` la línea `CONTRATO ARCHITECT ACEPTADO <sha>` o la lista de cambios pedidos, en 1 hora como máximo.
- Migraciones: las tuyas declaran dependencia de la migración de `profiles` que ARCHITECT publique en CONTRATOS.md.

Con INTELLIGENCE:

- Define en `lumi_ai/ports.py` (T1 de INTELLIGENCE, primera hora) los `Protocol` `SocialData`, `McpGateway` y `ConnectionLinks`. Tú los implementas en `apps/connections/socialdata.py`, `mcp/gateway.py` y `connect_links.py`. Mientras no existan, trabaja contra las firmas de su plan: `fetch_user_posts(platform, handle, since, limit)`, `search_posts(platform, query, limit)`, `get_user(platform, handle)`, `search_users(platform, query, limit)`; `McpGateway.list_tools(profile_id)`, `call(profile_id, name, args)`; `ConnectionLinks.start_connect(profile_id, platform)`.
- Errores tipados que INTELLIGENCE espera: `BudgetExceeded`, `ProviderUnavailable`, `RateLimited`, `ProviderAuthError`, `LiveDisabled`.
- Presupuesto de créditos de Xpoz por ejecución: `XPOZ_RUN_CREDIT_BUDGET`; a partir de ahí `BudgetExceeded`.
- El frontend consume los eventos SSE de `/api/v1/chat/stream` y la forma de `TurnResult` que fije INTELLIGENCE; no los reinventes.

## 7. Tareas en orden

### T0. Arranque (15 min)
`git fetch origin && git checkout lumi-orquestador`. Lee `lumi/plan/ContextoTareas.md`, `lumi/AGENTS.md`, `lumi/docs/{frontend-integration,mcp-connectors,xpoz_optimization,services,routers}.md`, `/workspace/lumi-integraciones/research.md`. Crea `estado/CONNECT.md` y el TSV. Línea base de tests con variables ficticias: `cd lumi && GROQ_API_KEY=x OPENROUTER_API_KEY=x TYPESAFE_API_KEY=x NEATLOGS_API_KEY=x SECRET_KEY=x uv run pytest -q` (esperado: 418 pasan).

### T1. Revalidar permisos y escribir `docs/CONEXIONES.md` (Fase 1, 1 h)
Con las páginas oficiales de hoy (Meta for Developers: Facebook Login, Pages API, App Review y modo Development; LinkedIn: Authorization Code Flow, Posts API, versionado de API, productos disponibles por autoservicio; X: OAuth 2.0 con PKCE, escritura de posts y precios actuales; Post for Me: API y límites), escribe `docs/CONEXIONES.md`: tabla por proveedor (flujo, scopes, endpoints de autorización, token, refresco, revocación, publicación, lectura de posts y métricas, límites, qué exige revisión, qué funciona hoy en modo desarrollo), redirect URIs exactas (`{PUBLIC_BASE_URL}/api/v1/connections/<provider>/callback`) y los pasos, numerados y con enlaces, que Christian debe seguir para crear cada app y qué pegar en `.env` (variables en `docs/API_KEYS.md`). Cada dato lleva fecha y URL. Lo que no puedas verificar, márcalo "sin verificar". Avisa al orquestador de los nombres de variables nuevos que decidas (`PUBLIC_BASE_URL`, `FRONTEND_URL`, `XPOZ_LIVE_ENABLED`, `HANDLE_CACHE_TTL_MINUTES`, `TOKEN_ENCRYPTION_KEY_PREVIOUS`) para que los incluya en `API_KEYS.md`; ARCHITECT los pone en `.env.example`.

### T2. Fusión de los dos frontends (empieza ya, no depende del backend; 4-6 h)
Objetivo: un solo `lumi/frontend/` con todas las funciones de ambos; la raíz `frontend/` se borra al final.
1. Base: el frontend de la raíz (tiene más funciones). Trabaja en `lumi/frontend/` así: guarda una copia de referencia del actual (`git show cce6ca3:lumi/frontend/<ruta>` siempre da el original), reemplaza `lumi/frontend/` por el contenido de `frontend/` (con `git mv`/`git rm`) y porta encima las mejoras de `lumi/frontend`.
2. Conserva de la raíz: voz (`src/voice/*`, `src/api/voice.ts`), motor de revelado (`src/reveal/*` y su test), pestaña Settings → Connectors con el estado de Google, `sendChatMessage`.
3. Porta de `lumi/frontend`: `formatClock.ts` y `tests/formatClock.test.ts`, `usePrefersReducedMotion.ts`, avatar de usuario en `Sidebar` (`userProfile`, unavatar.io), `scanError` en `ChronicOnline`, `InsightCards` con impresiones/engagement, CSS `edge-dissolve` en `styles/global.css`, `VITE_API_BASE`, y las cuatro funciones de handles.
4. Archivos que difieren (25): resuélvelos uno a uno con `diff -u frontend/<f> lumi/frontend/<f>` (o contra `git show cce6ca3:lumi/frontend/<f>`). Para cada uno decide qué conserva cada lado; anota la decisión en `decisiones.tsv`. Unifica los tipos de handles (`HandleSearchResult`/`HandleRow`, `SavedHandlesResponse`/`HandleSearchResponse`) en un solo juego y un solo módulo `api/handles.ts`.
5. Un solo `package.json`: scripts `dev` (`vite --port 3010`), `build`, `typecheck`, `test` con todos los tests (`formatDuration`, `scriptPlayer`, `revealEngine`, `formatClock`). Una sola lista de dependencias (la unión). Un solo lockfile: borra `pnpm-lock.yaml`; regenera `package-lock.json` con `npm install`. Pruebas en Node ≥ 22.6: añade `"engines": {"node": ">=22.6"}`, `.nvmrc` con `22` y un script que pase `--experimental-strip-types` si hace falta; si prefieres Vitest (funciona en Node 20 y 22), decídelo en `docs/ADR-CONNECT-frontend-tests.md`. Con `npx -y node@22` ya pasaron 14/14 y 11/11.
6. Lista de funciones que deben existir al cerrar (checklist en `estado/CONNECT.md`, cada una con la ruta del archivo): voz (grabar, transcribir, hablar), revelado suave de texto, conector de Google en Settings, `formatClock`, reduced-motion, avatar, `scanError`, tarjetas de impresiones/engagement, disolución de bordes, búsqueda y guardado de handles, `sendChatMessage`, `AgentThinking`, `ChronicOnline`, `PromptBar`.
7. Cuando el checklist esté completo y las comprobaciones pasen, `git rm -r frontend` y commit `[CONNECT] frontend: fusión en lumi/frontend y borrado del frontend de la raíz`.
Verifica (en `lumi/frontend`): `npm ci && npm run typecheck && npm run build && npx -y node@22 --test tests/*.test.ts` sin errores; `ls frontend` en la raíz no existe; `ls lumi/frontend/pnpm-lock.yaml` no existe; `rg -n "localhost:8000" lumi/frontend/src` solo en el valor por defecto de `VITE_API_BASE`.

### T3. Modelos, cifrado y estado OAuth (2 h; requiere T4 de ARCHITECT para las FK)
`models.py`: `ConnectedAccount` (user FK, `social_profile` FK nulo, `provider`, `external_account_id`, `access_token` y `refresh_token` cifrados, `expires_at`, `scopes`, `status` `active|expired|revoked|limited|error`, `last_refreshed_at`, `last_error`), `OAuthState` (`state` único, `user`, `provider`, `code_verifier`, `redirect_after`, `expires_at`), `PublishJob` (perfil, plataforma, texto, estado, `external_post_id`, `error`, `idempotency_key` único, `dry_run`), `McpAuthAccount` (cifrado), `HandleSearchCache`. `crypto.py` con `EncryptedTextField` (Fernet; `MultiFernet` si hay clave previa). Migraciones.
Verifica: `uv run pytest apps/connections/tests/test_crypto.py -q` (ida y vuelta, rotación de clave, el valor en la base no contiene el texto plano: consulta SQL directa), `makemigrations --check --dry-run`.

### T4. Interfaz de proveedores y adaptadores (3-4 h)
`providers/base.py`: `SocialProvider` (`build_authorize_url`, `exchange_code`, `refresh`, `revoke`, `get_account`, `fetch_posts`, `fetch_metrics`, `publish`, `capabilities`). Errores tipados. Adaptadores `meta.py` (Facebook Pages: Graph API, token de página, publicar en página), `linkedin.py` (`w_member_social`, publicar en el perfil personal con la Posts API y la cabecera de versión; marca `limited` para lectura), `x.py` (PKCE; todo detrás de `X_LIVE_ENABLED`), `pfm.py` (envoltura del cliente de PFM). Cada uno con un transporte `httpx` inyectable para tests.
Verifica: `uv run pytest apps/connections/tests/providers -q`: por proveedor, URL de autorización con scopes y `state` correctos, intercambio de código, refresco, revocación, publicación, errores 401/403/429 mapeados a errores tipados, todo con respuestas grabadas o `httpx.MockTransport`. Test específico: con `X_LIVE_ENABLED=false` el transporte falso **no recibe ninguna petición** hacia hosts de X (el test falla si hay alguna).

### T5. Vistas OAuth, refresco y revocación (2-3 h)
`oauth.py`, `views.py`, `serializers.py`, `urls.py`: rutas de la sección 6. El `callback` valida y consume `state` de forma atómica, guarda tokens cifrados, vincula o crea `SocialProfile` con `apps.profiles.services`, programa el primer `sync_profile` y **redirige a `FRONTEND_URL`** con `?connected=<provider>` o `?error=<codigo>` (no devuelve JSON). `tasks.py`: refresco periódico de tokens próximos a vencer, con marca `expired`/`error` y mensaje cuando falla. `disconnect` revoca en el proveedor y borra los tokens. Ningún serializer expone tokens.
Verifica: `uv run pytest apps/connections/tests/test_oauth_views.py -q`: estado reutilizado o vencido rechazado, redirección correcta, usuario A no ve ni desconecta cuentas del usuario B, ningún token en las respuestas ni en los logs (captura de logs en el test).

### T6. Publicación (1-2 h)
`publishing.py` y `POST /api/v1/publish`: exige `confirm=true`, `idempotency_key`, límites de la plataforma (consulta `lumi_ai.generation.platforms` cuando INTELLIGENCE la publique; mientras tanto límites propios en una tabla local), `dry_run` que valida permisos y largo sin publicar. X apagada devuelve `LiveDisabled`. Repetir la misma clave devuelve el mismo `PublishJob` sin republicar.
Verifica: `uv run pytest apps/connections/tests/test_publish.py -q` (idempotencia, `dry_run`, X apagada, error del proveedor deja `PublishJob` en `failed` con el motivo).

### T7. Clientes de datos: Post for Me y Xpoz, ingesta (3-4 h)
Porta `services/pfm.py` a `clients/pfm.py` con limitador 5/s y 40/min, `ProviderAuthError` ante 401 (token vencido), reintentos con espera y tiempo máximo. Porta `services/xpoz.py` a `clients/xpoz.py` con presupuesto por ejecución (`XPOZ_RUN_CREDIT_BUDGET`), rotación `XPOZ_API_KEY`/`XPOZ_API_KEY_2` desde la configuración central, contador de créditos gastados por ejecución y `BudgetExceeded`. Implementa `socialdata.py` (puerto `SocialData`). Porta `ingest.py` a `ingest.py` usando `apps.profiles.services.upsert_posts`; conserva el ruteo de `posts` y `user_activity` y `classify_post_kind`/`is_authentic_original`. Resuelve el Paso 0 de `docs/xpoz_optimization.md`: escribe `docs/xpoz_capabilities.md` con lo que Xpoz realmente devuelve, **sin gastar créditos reales** (usa solo respuestas grabadas existentes o la documentación del proveedor; si necesitas una llamada real, máximo una, con `XPOZ_API_KEY` y solo si Christian ya puso la key).
Verifica: `uv run pytest apps/connections/tests/{test_pfm,test_xpoz,test_ingest}.py -q`; `test_post_filter` (7), `test_xpoz`, `test_xpoz_resilience` (6) y la parte de ingesta de `test_profile_extract_fixes` portados; un test de que `BudgetExceeded` corta una ejecución en el crédito exacto.

### T8. Búsqueda de handles (2 h)
Porta `mvp/handle_search/server.py` y `services/handle_db.py` a `handles/`: caché en Postgres (`HandleSearchCache`, TTL `HANDLE_CACHE_TTL_MINUTES`) en lugar de Chroma; mapeos a `SocialHandle` (ARCHITECT) en lugar de `handle_mappings`; presupuesto (`XPOZ_RUN_CREDIT_BUDGET`) y interruptor (`XPOZ_LIVE_ENABLED`) en lugar de `MVP_XPOZ_BUDGET`/`MVP_XPOZ_LIVE`. Rutas `/api/v1/handles/{search,saved,select,stats}` con permisos por usuario. Elimina toda lectura de SQLite y las variables `MVP_*`.
Verifica: `uv run pytest apps/connections/tests/handles -q` (equivalentes de `test_handle_search_mvp` 29, `test_handle_search_platforms` 14, `test_handle_db` 12, `test_handles_router` 7); `rg -n "sqlite|MVP_" lumi/apps/connections` sin resultados.

### T9. MCP de Google con tokens cifrados (2 h)
Porta `services/mcp.py`, `mcp_connectors.py`, `routers/mcp_google.py`, `background/mcp_refresh.py` y `models/mcp_auth_account.py` a `mcp/`: tokens en `McpAuthAccount` cifrado, estado OAuth en `OAuthState`, escrituras pendientes en base (no en memoria), `/api/v1/connections/google/{connect,callback,status}` con redirección al frontend. Implementa el puerto `McpGateway`. Sin `GOOGLE_OAUTH_CLIENT_ID`, el conector no aporta tools y `connect` responde 503 con un mensaje honesto (como hoy).
Verifica: `uv run pytest apps/connections/tests/mcp -q` (equivalentes de `test_mcp` 20 y `test_mcp_google_router` 9).

### T10. Sondas de keys (1 h)
`keys.py` registra en `apps.core.keys` (ARCHITECT), con llamada mínima real que no gasta dinero ni créditos: `pfm` (una lectura de cuentas), `meta` (token de aplicación con ID y secreto: gratis), `google` (un intercambio de código inválido distingue cliente inválido de código inválido), `linkedin` (sin llamada gratuita de validación: comprueba formato y que el endpoint de autorización responde; dilo en la salida), `x` (con `X_LIVE_ENABLED=false` se omite con el motivo y no toca la red), `xpoz` (por defecto no gasta: comprueba formato y, si Xpoz tiene un endpoint gratuito de créditos o de cuenta, úsalo; si no, solo con `--spend`).
Verifica: `uv run pytest apps/connections/tests/test_keys.py -q`; `uv run python manage.py check_keys --only pfm,xpoz,meta,linkedin,x,google` sin keys muestra `OMITIDA` en todas y sale sin error.

### T11. Integración React ↔ Django (3-4 h; requiere T3-T5 de ARCHITECT)
1. `lumi/frontend/src/api/`: un cliente único con `VITE_API_BASE` (por defecto `http://localhost:8000/api/v1`), cabecera `Authorization: Token <token>`, manejo de 401 (vuelta al login), errores `{"error": {"code","message"}}`.
2. Pantallas de autenticación (registro, login, logout) y token en `localStorage`.
3. Selección y cambio de perfil (hoy no se puede), lista de cuentas conectadas y botón de conectar por proveedor en Settings → Connectors (Facebook, LinkedIn, X con aviso "apagado", Post for Me, Google). El retorno `?connected=` o `?error=` muestra el estado.
4. Flujo de generación y publicación: ver el borrador y su evaluación (`GenerationEvaluation` de INTELLIGENCE), editar, `dry_run` y botón Publicar con confirmación.
5. Arregla los defectos de la sección 3: `PromptBar` respeta `busy`, `isConnectLink` deja de adivinar por texto (el servidor marca el tipo de enlace de conexión), borrar un chat local no borra el servidor (o lo pide explícitamente), "Upgrade" no abre chat nuevo, borra código muerto (`ChatBar`, `LoadingDots`, `useSimulatedRun`), quita la ficción de Settings (`alex@lumi.app`, asientos) mostrando datos reales del usuario, borra el bloque `html.light`, usa `getProfileAnalytics` o deja de llamarlo, y los handles de tendencias salen del perfil, no de una lista fija.
6. Antes de tocar el frontend, léelo con `/how`. Escribe tus notas en `docs/CONEXIONES.md`, sección "Frontend" (`docs/frontend-integration.md` es del repo y no es tuyo).
Verifica: `npm run typecheck && npm run build && npx -y node@22 --test tests/*.test.ts` limpios; `rg -n "ChatBar|LoadingDots|useSimulatedRun|alex@lumi.app|html.light" lumi/frontend/src` sin resultados.

### T12. Pruebas de punta a punta (3 h)
Dos capas:
1. API (Python, siempre): `apps/connections/tests/test_e2e_api.py` recorre el flujo completo con el cliente de pruebas de Django y proveedores falsos: registro, login, conectar Facebook (callback falso), `sync_profile` trae posts, chat con proveedor de IA falso que llama una tool, generación con evaluación, `dry_run` de publicación, desconexión.
2. Navegador (Playwright, `lumi/e2e/`): backend con `uv run python scripts/dev_postgres.py` (ARCHITECT) + `manage.py migrate` + `seed_demo`, ajustes `apps/connections/e2e_settings.py` (importa `config.settings.test` y cambia solo los proveedores por dobles grabados; nunca se usa en producción), frontend con `npm run build && npx vite preview`. Flujos: login, conectar cuenta (proveedor falso, vuelta con `?connected=`), un turno de chat con revelado de texto, generar y evaluar un post, `dry_run` y publicar, estado del conector de Google. Si Playwright no puede ejecutarse en la box (navegadores o librerías del sistema), documéntalo, usa el navegador de la box para una pasada manual con capturas y deja el resto en la capa 1; no lo des por hecho.
Verifica: `uv run pytest apps/connections/tests/test_e2e_api.py -q`; `cd lumi/e2e && npx playwright test` (o la nota de por qué no corrió).

### T13. `lumi/docs/MUSE.md` (1-2 h; puede ir en cualquier hueco)
Documento autocontenido para un agente futuro. Investiga con fuentes oficiales de Meta (anota fecha y URL de cada dato) y escribe: qué es Muse Spark y la Meta Model API; cómo se accede (registro, límites, regiones), autenticación (tipo de key o OAuth) y variables de entorno propuestas (nombres nuevos, por ejemplo `META_MODEL_API_KEY`); modelos disponibles, ventana de contexto, tool calling y salida estructurada, multimodalidad (¿imagen, video?); precios y plan gratis; términos de uso relevantes; dónde encajaría en Lumi (como un candidato más de `lumi_ai.providers` o como generador de contenido; qué puertos y archivos tocaría); un plan de integración paso a paso con pruebas y riesgos; preguntas abiertas para Christian. Lo que no puedas confirmar, márcalo "sin verificar". **No escribas código de integración, no añadas variables al `.env.example` ni al registro de keys.**
Verifica: el archivo existe, cada dato tiene fecha y fuente, y `rg -n "muse" lumi --glob '!lumi/docs/MUSE.md' --glob '!lumi/plan/**' --glob '!lumi/docs/API_KEYS.md' -i` no muestra código nuevo de integración.

### T14. Limpieza final (30 min)
Sin `frontend/` en la raíz, un solo lockfile, `.gitignore` de `lumi/frontend` (`node_modules`, `dist`). `docs/CONEXIONES.md` actualizado con lo realmente construido y los pasos de Christian. Reporte final.

## 8. Código y tests existentes que reutilizas

| Origen en `lumi/app/` o `lumi/mvp/` | Destino | Tests de referencia (en `lumi/tests/`) |
| --- | --- | --- |
| `services/pfm.py` | `clients/pfm.py`, `ingest.py` (clasificación) | `test_post_filter` (7) |
| `services/xpoz.py` | `clients/xpoz.py` | `test_xpoz` (1), `test_xpoz_resilience` (6) |
| `services/ingest.py` | `ingest.py` | partes de `test_profile_extract_fixes` (27) |
| `mvp/handle_search/server.py`, `services/handle_db.py`, `routers/handles.py` | `handles/` | `test_handle_search_mvp` (29), `test_handle_search_platforms` (14), `test_handle_db` (12), `test_handles_router` (7) |
| `services/mcp.py`, `mcp_connectors.py`, `routers/mcp_google.py`, `background/mcp_refresh.py`, `models/mcp_auth_account.py` | `mcp/` | `test_mcp` (20), `test_mcp_google_router` (9) |
| `routers/pfm.py`, `tools/connect.py` | `views.py`, `connect_links.py` | — (tests nuevos) |
| `frontend/` (raíz) y `lumi/frontend/` | `lumi/frontend/` | `frontend/tests/*.test.ts` (14), `lumi/frontend/tests/*.test.ts` (11) |

Reglas de port: copia el comportamiento, no la forma. Cada test viejo se reescribe con el mismo caso y el mismo resultado esperado; los que usaban SQLite se rehacen con Postgres vía `pytest-django`. Si un test viejo codifica un defecto (por ejemplo, el callback que devuelve JSON), cámbialo y deja nota en `decisiones.tsv`.

## 9. Comprobaciones de aceptación (todas deben pasar)

```bash
cd lumi
uv run pytest -m "not live" apps/connections -q                 # sin keys, sin red
uv run pytest -m "not live" -q                                  # toda la suite junta con los otros bots
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py check_keys --only pfm,xpoz,meta,linkedin,x,google
rg -n "sqlite|MVP_|AtehOfficial|ateh_x_connect|lumi_user" apps/connections frontend/src   # sin resultados
rg -n "access_token|refresh_token" apps/connections --glob '!**/tests/**' --glob '!**/migrations/**'   # solo en modelos cifrados, crypto y clientes; nunca en logs ni serializers
(cd frontend && npm ci && npm run typecheck && npm run build && npx -y node@22 --test tests/*.test.ts)
test ! -d ../frontend && test ! -f frontend/pnpm-lock.yaml    # sin frontend en la raíz y un solo lockfile
(cd e2e && npx playwright test)                                 # o la nota documentada
```

Todas las órdenes parten de `lumi/`; el frontend vive en `lumi/frontend/`. Con keys y apps reales, `check_keys` debe mostrar `OK` para lo configurado; si no hay keys, queda como pendiente documentado, no como hecho. Ninguna prueba toca X ni gasta créditos de Xpoz.

## 10. Qué reportar

En cada reporte y en `estado/CONNECT.md`:

- SHA y rama; tareas T0-T14 hechas, en curso, bloqueadas.
- Salida resumida de los comandos de la sección 9.
- La checklist de funciones del frontend con la ruta de cada una, y el resultado de las pruebas de Node.
- Hechos de Meta/LinkedIn/X revalidados (con fecha y URL) y diferencias con `research.md`.
- Los pasos que Christian debe hacer en las consolas de Meta, LinkedIn, X, Post for Me, Xpoz y Google, en orden (los mismos de `docs/CONEXIONES.md`).
- Riesgos: token de PFM vencido, créditos de Xpoz casi agotados (~125 consultas con la key 1), App Review de Meta, límites de LinkedIn sin Community Management API, X apagado, Playwright que no corra en la box.
- Qué necesitas de ARCHITECT, INTELLIGENCE o Christian.
