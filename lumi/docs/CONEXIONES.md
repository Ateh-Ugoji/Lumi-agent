# Conexiones con redes sociales

Autor LUMI-CONNECT. Datos revalidados el 2026-10-27 contra las páginas oficiales. Cada hecho lleva su URL. Lo que no pude comprobar en una página oficial dice "sin verificar". Los pasos para crear cada app están en `docs/API_KEYS.md`, sección "Cómo crear cada app". Aquí van el diseño, las tablas por proveedor y el orden de trabajo.

## Reglas de diseño

- Un solo contrato, `SocialProvider`, con cuatro proveedores: `meta`, `linkedin`, `x` y `pfm`.
- OAuth 2.0 con código de autorización. PKCE siempre que el proveedor lo acepta, y obligatorio en X.
- El `state` de OAuth vive en PostgreSQL (`OAuthState`), se usa una sola vez y caduca. Nunca en memoria del proceso.
- Los tokens se cifran con Fernet (`TOKEN_ENCRYPTION_KEY`). Para rotar la clave, la anterior va en `TOKEN_ENCRYPTION_KEY_PREVIOUS` y se descifra con `MultiFernet`.
- Publicar exige `confirm=true`, una clave de idempotencia y soporta `dry_run`. El agente nunca publica por su cuenta.
- X queda detrás de `X_LIVE_ENABLED=false`. Con el interruptor apagado el adaptador no hace ninguna llamada de red, ni siquiera el canje del código, y devuelve `LiveDisabled`. Construir la URL de autorización es un cálculo local y sí se permite.
- Errores tipados: `BudgetExceeded`, `ProviderUnavailable`, `RateLimited`, `ProviderAuthError`, `LiveDisabled`.

## Variables nuevas que introduce CONNECT

El orquestador debe copiarlas a `API_KEYS.md` y ARCHITECT a `.env.example`.

| Variable | Valor por defecto | Para qué sirve |
| --- | --- | --- |
| `FRONTEND_URL` | `http://localhost:3010` | Del frontend salen las redirect URIs: el proveedor devuelve al usuario a una página de esta app |
| `X_LIVE_ENABLED` | `false` | Interruptor de toda llamada real a X |
| `XPOZ_LIVE_ENABLED` | `false` | Interruptor de las llamadas reales a Xpoz (cada consulta gasta créditos) |
| `XPOZ_DAILY_CREDIT_CAP_USER` | `60` | Créditos de Xpoz que un usuario puede gastar en 24 h. Se lee de `xpoz_credit_ledger`, así que aguanta reinicios y varios procesos. `0` bloquea el gasto |
| `XPOZ_DAILY_CREDIT_CAP_GLOBAL` | `300` | Lo mismo para todos los usuarios juntos |
| `XPOZ_RUN_CREDIT_BUDGET` | `12` | Tope de créditos de Xpoz por ejecución. Al llegar se lanza `BudgetExceeded`. 12 alcanza para una búsqueda de Instagram (12 créditos) |
| `XPOZ_RUN_CREDIT_BUDGET_<RED>` | sin definir | Tope propio de una red (`X`, `INSTAGRAM`, `TIKTOK`, `REDDIT`). Una red con tope propio no gasta del compartido. `0` la deshabilita |
| `HANDLE_CACHE_TTL_MINUTES` | `60` | Vigencia de la caché de búsqueda de handles (sustituye a `MVP_CACHE_TTL_MINUTES`) |
| `HANDLE_DB_ENRICH_LIMIT` | `6` | Handles nuevos que un escaneo completa con una búsqueda de pago (2 créditos cada uno) por llamada. `0` guarda solo los handles |
| `TOKEN_ENCRYPTION_KEY_PREVIOUS` | vacío | Clave Fernet anterior, solo mientras se rota |
| `LINKEDIN_API_VERSION` | `202609` | Valor de la cabecera `Linkedin-Version` (formato AAAAMM) |
| `META_GRAPH_VERSION` | `v26.0` | Versión de Graph API |

Los valores por defecto de `XPOZ_RUN_CREDIT_BUDGET`, `HANDLE_CACHE_TTL_MINUTES`, `HANDLE_DB_ENRICH_LIMIT` y `LINKEDIN_API_VERSION` son decisión mía y no vienen de una fuente oficial.

## Redirect URIs exactas

Formato `{FRONTEND_URL}/connections/<provider>/callback`. **Es una página del frontend, no una ruta del backend.** El proveedor redirige ahí, la página lee `code` y `state` y los envía con el Token del usuario a `POST /api/v1/connections/<provider>/callback`. Cada consola compara la URI carácter por carácter, así que pega exactamente estas.

| Proveedor | URI en local | URI en producción |
| --- | --- | --- |
| Meta | `http://localhost:3010/connections/meta/callback` | `https://<tu-frontend>/connections/meta/callback` |
| LinkedIn | exige HTTPS, ver nota | `https://<tu-frontend>/connections/linkedin/callback` |
| X | `http://127.0.0.1:3010/connections/x/callback` | `https://<tu-frontend>/connections/x/callback` |
| Google | `http://localhost:3010/connections/google/callback` | `https://<tu-frontend>/connections/google/callback` |
| Post for Me | `http://localhost:3010/connections/pfm/callback` | `https://<tu-frontend>/connections/pfm/callback` |

Post for Me no tiene consola de redirect URI de OAuth. Esa URL va en su panel como "redirect URL" (ver más abajo). Si cambias `FRONTEND_URL`, cambia las cinco URIs a la vez. El hosting del frontend debe devolver `index.html` para `/connections/*` (en Vite ya lo hace).

Notas.

- X pide `127.0.0.1` y no acepta `localhost` en local. Fuente https://docs.x.com/resources/fundamentals/developer-apps (2026-10-27). Si usas `127.0.0.1` en la consola, abre el frontend y pon `FRONTEND_URL` en `http://127.0.0.1:3010` durante esa prueba.
- LinkedIn dice "Add the redirect (callback) URL via HTTPS" y que la URL debe ser absoluta, sin `#`, y que los parámetros de consulta se ignoran. Fuente https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow (2026-10-27). Si acepta `http://localhost` queda sin verificar. Para probar en local usa un túnel HTTPS (por ejemplo `cloudflared` o `ngrok`) y pon esa URL en `FRONTEND_URL`.
- Meta compara la URI contra "Valid OAuth Redirect URIs". Fuente https://developers.facebook.com/docs/facebook-login/guides/advanced/manual-flow (2026-10-27). Que `http://localhost` valga para apps en modo Development está sin verificar en la página oficial.
- Post for Me conecta las cuentas con su propio OAuth y Lumi solo guarda el id de cuenta de PFM.

## Meta (Facebook Pages)

| Tema | Dato | Fuente (2026-10-27) |
| --- | --- | --- |
| Flujo | Código de autorización por redirección. `state` obligatorio contra CSRF | https://developers.facebook.com/docs/facebook-login/guides/advanced/manual-flow |
| Autorización | `https://www.facebook.com/v26.0/dialog/oauth?client_id&redirect_uri&state&scope` | misma página |
| Token | `GET https://graph.facebook.com/v26.0/oauth/access_token`. El canje del código ocurre en el servidor porque lleva el secreto | misma página |
| Scopes | `pages_show_list`, `pages_read_engagement`, `pages_manage_posts`, `read_insights` | https://developers.facebook.com/docs/permissions |
| Duración | El token de usuario nuevo dura horas. Se canjea por uno de unos 60 días con `grant_type=fb_exchange_token`. El token de página sacado de un token de usuario de larga duración no tiene fecha de caducidad | https://developers.facebook.com/docs/facebook-login/guides/access-tokens/get-long-lived |
| Refresco | No hay refresh token. Se repite el canje largo o se vuelve a pedir login. Con token de página de larga duración no hace falta | misma página |
| Revocación | `DELETE /{user-id}/permissions` en Graph API. Sin verificar en la documentación de hoy | sin verificar |
| Publicar | `POST /{page-id}/feed` con `message` y el token de página. Hace falta tarea `CREATE_CONTENT` en la página y los permisos `pages_manage_posts`, `pages_read_engagement`, `pages_show_list` | https://developers.facebook.com/docs/pages-api/getting-started |
| Listar páginas | `GET /{user-id}/accounts` devuelve `id`, `name`, `access_token` y `tasks` de cada página | misma página |
| Leer posts | `GET /{page-id}/posts` con `pages_read_engagement` | https://developers.facebook.com/documentation/pages-api/posts |
| Métricas | `GET /{post-id}/insights` con `read_insights`. El changelog de v25.0 retira las métricas `*_impressions_*` y manda usar `post_total_media_view_unique`, `post_media_view`, `page_total_media_view_unique` y `page_media_view` | https://developers.facebook.com/docs/graph-api/changelog/version25.0 |
| Límites | Con token de página rigen los límites BUC, que dependen del endpoint | https://developers.facebook.com/docs/graph-api/overview/rate-limiting |
| Modo Development | Solo se piden permisos a usuarios con rol en la app (administrador, desarrollador, tester). No hace falta App Review. Los posts de prueba solo los ven esos usuarios | https://developers.facebook.com/docs/development/build-and-test/app-modes |
| Modo Live | Permite pedir permisos a cualquiera, pero solo los aprobados en App Review | misma página |
| Exige revisión | App Review para usuarios sin rol. Business Verification para acceso avanzado de apps que sirven a otros negocios | https://developers.facebook.com/docs/resp-plat-initiatives/individual-processes/app-review y https://developers.facebook.com/docs/development/release/business-verification |
| Hoy en desarrollo | Todo lo anterior funciona con Christian como administrador de la app y de la página. Lumi lo marca como cuenta de prueba | deducido de las dos páginas anteriores |

Requisitos de App Review que la documentación pide antes de enviar (https://developers.facebook.com/docs/resp-plat-initiatives/individual-processes/app-review/submission-guide).

- Icono de 1024x1024 y URL de política de privacidad en Settings > Basic.
- Al menos una llamada exitosa por cada permiso pedido, hecha en los 30 días previos al envío. El botón "Request advanced access" queda gris hasta que el sistema registra la llamada, y eso tarda hasta 2 días.
- Un screencast por permiso, a 1080p o más, sin audio, que muestre el login y el uso del permiso.
- Instrucciones para que el revisor entre a la app. Si no puede probarla, se rechaza todo el envío.

## LinkedIn

| Tema | Dato | Fuente (2026-10-27) |
| --- | --- | --- |
| Flujo | Código de autorización de 3 patas | https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow |
| Autorización | `https://www.linkedin.com/oauth/v2/authorization` | misma página |
| Token | `POST https://www.linkedin.com/oauth/v2/accessToken`. El código dura 30 minutos | misma página |
| Scopes por autoservicio | `openid profile email` (producto "Sign in with LinkedIn using OpenID Connect") y `w_member_social` (producto "Share on LinkedIn") | https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access |
| Duración | Todo token de acceso dura 60 días (`expires_in` 5184000) | misma página de flujo |
| Refresco | Solo con refresh token programático y solo para socios aprobados. Sin eso el usuario repite el consentimiento. Si cambian los scopes de la app, todos deben reconectar | https://learn.microsoft.com/en-us/linkedin/shared/authentication/programmatic-refresh-tokens |
| Revocación | `POST https://www.linkedin.com/oauth/v2/revoke`. Sin verificar en las páginas de hoy | sin verificar |
| Publicar en perfil | `POST https://api.linkedin.com/rest/posts` con `author` `urn:li:person:{id}`, cabeceras `Linkedin-Version: AAAAMM` y `X-Restli-Protocol-Version: 2.0.0`, scope `w_member_social` | https://learn.microsoft.com/en-us/linkedin/marketing/community-management/shares/posts-api?view=li-lms-2026-09 |
| Identidad | `GET https://api.linkedin.com/v2/userinfo` devuelve el `sub` que forma el URN. Sin verificar en las páginas de hoy | sin verificar |
| Leer posts | Exige `r_member_social`, restringido a usuarios aprobados. Sin él, la cuenta queda `limited` y Lumi no lee posts ni métricas | misma página de Posts API |
| Páginas de empresa | `w_organization_social`, `r_organization_social` y las métricas de la página exigen el producto Community Management API | https://learn.microsoft.com/en-us/linkedin/marketing/increasing-access |
| Límites | Tope diario por app y por miembro, con reinicio a medianoche UTC. Exceso devuelve 429 | https://learn.microsoft.com/en-us/linkedin/shared/api-guide/concepts/rate-limits |
| Límites con Community Management en Development | 500 llamadas por app y por día, 100 por miembro y por día, sin `BATCH_GET`, sin webhooks | https://learn.microsoft.com/en-us/linkedin/marketing/increasing-access |
| Versionado | La versión de marketing 202511 se retira el 2026-11-16. La documentación de Posts API de hoy está en `li-lms-2026-09` | https://learn.microsoft.com/en-us/linkedin/marketing/community-management/community-management-overview |
| Hoy en desarrollo | Publicar en el perfil personal de Christian funciona sin revisión. Leer posts y publicar en páginas no | deducido de lo anterior |

## X

| Tema | Dato | Fuente (2026-10-27) |
| --- | --- | --- |
| Flujo | Código de autorización con PKCE (`S256`) | https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code |
| Autorización | `https://x.com/i/oauth2/authorize` | misma página |
| Token | `POST https://api.x.com/2/oauth2/token`. El código de autorización caduca a los 30 segundos de recibirse | misma página |
| Scopes | `tweet.read tweet.write users.read offline.access media.write` | misma página |
| Duración | El token de acceso dura 2 horas. Con `offline.access` se recibe refresh token | misma página |
| Refresco | `grant_type=refresh_token` al mismo endpoint de token | misma página |
| Revocación | `POST https://api.x.com/2/oauth2/revoke`. Sin verificar en la documentación de hoy | sin verificar |
| Tipo de app | "Web App" (cliente confidencial) entrega `client_secret`. Las callbacks deben coincidir exactamente | https://docs.x.com/resources/fundamentals/developer-apps |
| Precio | Pago por uso con créditos prepagados. Crear post $0.015. Crear post con URL $0.20. Leer post $0.005 por recurso. Leer usuario $0.010. Lecturas propias $0.001 por recurso. Tope de 3 millones de lecturas de posts al mes | https://docs.x.com/x-api/getting-started/pricing |
| Plan gratis | No hay. Hay un bono de $20 al guardar una tarjeta y hacer la primera compra de créditos. No se usa. La consola permite fijar un tope de gasto por ciclo | misma página |
| Límites | Los límites de ventana de 15 minutos por endpoint están en la tabla oficial. Los de escritura quedan sin verificar | https://docs.x.com/x-api/fundamentals/rate-limits |
| Hoy | Apagado. Con `X_LIVE_ENABLED=false` no sale ni una petición hacia hosts de X, y un test lo comprueba | decisión de Christian |

Un enlace en el texto cuesta trece veces más que un post sin enlace. Antes de publicar en X, el borrador debe avisar si lleva URL.

## Post for Me (PFM)

| Tema | Dato | Fuente (2026-10-27) |
| --- | --- | --- |
| API base | `https://api.postforme.dev`. Referencia en https://api.postforme.dev/docs | https://api.postforme.dev/docs |
| Autenticación | Clave de API como `Authorization: Bearer`. Se saca de la cuenta de Post for Me | misma página |
| Conectar cuenta | `POST /v1/social-accounts/auth-url` devuelve la URL a la que se redirige al usuario. PFM guarda los tokens | misma página |
| Publicar | `POST /v1/social-posts`. Los medios se suben con `POST /v1/media/create-upload-url` y un `PUT` a la URL firmada | misma página |
| Lectura | `/v1/social-account-feeds/{id}` y `/v1/social-post-results`. Hay métricas por post | misma página |
| Precio | $10 al mes, hasta 1,000 posts exitosos, cuentas ilimitadas. Se pueden usar credenciales propias de cada red o las de PFM | https://www.postforme.dev/pricing |
| Límites | 5 peticiones por segundo y 40 por minuto, según `lumi/AGENTS.md`. Sin verificar en la documentación pública de hoy | sin verificar |
| Hoy | El `PFM_JWT_TOKEN` anterior está vencido (401). Hace falta una clave nueva | `lumi/docs/API_KEYS.md` |

## Xpoz (lectura de X sin la API de X)

| Tema | Dato | Fuente (2026-10-27) |
| --- | --- | --- |
| Autenticación | Clave de acceso en `XPOZ_API_KEY`. Se saca en https://www.xpoz.ai/get-token | https://docs.xpoz.ai/authentication |
| Créditos | 500 gratis, una sola vez, sin renovación. Al agotarse, el plan gratis se detiene | https://docs.xpoz.ai/pricing |
| Coste por búsqueda | Twitter/X 2 créditos, Reddit 2, TikTok 5, Instagram 12. Una búsqueda devuelve hasta 300 resultados. Cada página extra cuenta como búsqueda nueva | misma página |
| Gratis | Las herramientas de cuenta y de seguimiento (`getAccountDetails`, `getCreditsUsageHistory`, `getTrackedItems`...) no gastan créditos | misma página |
| Planes de pago | Pro $20 al mes con 7,500 créditos. Max $200 al mes con 120,000 | misma página |

Con 500 créditos y 2 por consulta de X caben 250 consultas por key. El plan del orquestador cuenta unas 125 con la key 1, porque parte de los créditos ya se usó. Por eso `XPOZ_LIVE_ENABLED=false` y `XPOZ_RUN_CREDIT_BUDGET` frenan el gasto. `getAccountDetails` es gratis y sirve para leer el saldo antes de cada ejecución.

## Diferencias con `research.md`

- Meta. La página de Pages API dice que `GET /{user-id}/accounts` con un token de usuario de corta duración devuelve un token de página de corta duración. El token de página sin caducidad solo sale de un token de usuario de larga duración. `research.md` lo daba por sentado. El adaptador canjea primero el token de usuario.
- Meta. Access Verification ya no se exige ("no longer required", https://developers.facebook.com/docs/development/release/access-verification). Business Verification sí sigue vigente para acceso avanzado.
- Meta. `read_insights` y `pages_manage_posts` dependen de `pages_read_engagement` y `pages_show_list`. Hay que pedir los cuatro juntos.
- Meta. El flujo de creación ahora es por casos de uso. El caso "Manage everything on your Page" agrega `pages_show_list`, `business_management` y `public_profile` como obligatorios, y deja `pages_manage_posts`, `pages_read_engagement` y `read_insights` como opcionales que hay que añadir a mano.
- LinkedIn. El código de autorización dura 30 minutos y el de X 30 segundos. El canje de X no puede esperar.
- LinkedIn. La versión 202511 se retira el 2026-11-16. `research.md` no lo recogía. El valor por defecto de `LINKEDIN_API_VERSION` es 202609.
- LinkedIn. Community Management API en nivel Development limita a 500 llamadas por día por app y 100 por miembro, y bloquea `BATCH_GET`. Tiene 12 meses para pasar a Standard.
- X. Confirmado todo lo de `research.md`. Añado que el código caduca a los 30 segundos y que en local hay que usar `127.0.0.1`.
- Xpoz. Confirmado, y la página oficial añade que las herramientas de cuenta son gratis.

## Orden de trabajo para Christian

Los pasos completos y los enlaces están en `docs/API_KEYS.md`. Este es el orden recomendado, del más barato al más caro de conseguir.

1. Generar `SECRET_KEY` y `TOKEN_ENCRYPTION_KEY` y pegarlas en `lumi/.env`. Cero costo.
2. Google (Drive y Docs por MCP). Cliente OAuth tipo "Web application" en Google Cloud. Cero costo.
3. Xpoz. Cuenta gratis y `XPOZ_API_KEY`. Hay 500 créditos y no se renuevan.
4. Meta. App nueva, caso de uso de Páginas, Christian como administrador, `META_APP_ID` y `META_APP_SECRET`. Cero costo, y funciona de inmediato para su propia página.
5. LinkedIn. App ligada a una página de empresa, productos "Share on LinkedIn" y "Sign in with LinkedIn using OpenID Connect". Cero costo, publica en su perfil.
6. Post for Me. Cuenta de $10 al mes y `PFM_JWT_TOKEN`. Es el camino más corto para publicar en X, Facebook y LinkedIn sin pasar por las revisiones.
7. X. App en la consola de desarrolladores y `X_CLIENT_ID` con `X_CLIENT_SECRET`. Se pegan, pero `X_LIVE_ENABLED` se queda en `false` hasta que Christian decida comprar créditos.
8. Más adelante. Meta App Review con Business Verification y Community Management API de LinkedIn, para abrir Lumi a terceros.

## Frontend

El frontend vive en `lumi/frontend` (Vite, React 19, puerto 3010) y habla solo con `/api/v1`. No queda ninguna llamada al backend viejo: la voz (`POST /voice/transcribe`) y el conector de Google (`/connections/google/*`) pasan por el mismo cliente.

### Cómo está armado

- `src/api/http.ts` es el único cliente. Pone `Authorization: Token <key>`, entiende `{"error":{"code","message","details"}}` y abre el stream del chat. Para el stream pide solo `text/event-stream`: la vista del chat lo acepta (`EventStreamRenderer`) y sus errores previos al stream salen en JSON.
- `src/auth/` guarda el token y muestra el login o el registro antes de la app (`AuthGate` en `main.tsx`). Un 401 limpia el token y vuelve al login.
- `src/api/connections.ts` pide `POST /connections/{provider}/connect`, abre `authorize_url` y, al volver a `/connections/{provider}/callback` lee `code`, `state` o `error` de la consulta, reemplaza la URL por `/` al instante y llama a `POST /connections/{provider}/callback` con el Token del usuario; luego muestra el aviso. Si el usuario canceló, envía `{state, error}` para quemar el state. Con Post for Me lee `isSuccess` y llama a `POST /connections/pfm/sync`, porque PFM no trae `state` y esa llamada es la que lee y guarda las cuentas. Leer el estado (`GET`) nunca llama a PFM ni escribe.
- El panel de conexiones solo lee con `GET .../status`. El botón «Actualizar» de PFM llama a `POST /connections/pfm/sync`; el de los demás proveedores vuelve a leer el estado.
- Se quitó el parámetro `?say=` que enviaba un turno de chat al abrir `/?say=...` (MEDIO 7 de la revisión de seguridad). Cualquier enlace podía hacer que el usuario enviara un prompt sin querer. Un e2e comprueba que la URL ya no envía nada.
- Los códigos de error del callback llegan con prefijo (`connections.access_denied`). El mapa de mensajes acepta también la forma sin prefijo que lista CONTRATOS.
- Publicación: el borrador se revisa con `dry_run`, y la publicación real exige pulsar dos veces (iniciar y confirmar). Cada intento lleva su `Idempotency-Key`.
- Ningún token de proveedor llega al navegador. Las pruebas lo comprueban en el DOM.

### Cómo se prueba

Unitarias del cliente (Node 22):

```
cd lumi/frontend && npx -y node@22 --test tests/*.test.ts
```

Recorrido real en el navegador, con Django, Vite y proveedores simulados. No necesita ninguna clave y no sale a internet:

```
cd lumi
export DATABASE_URL=$(uv run python scripts/dev_postgres.py --test)   # Postgres local
cd e2e && npm install && npx playwright test
```

Playwright abre el Chrome del equipo (`channel: "chrome"`), levanta `e2e/server.py` en el puerto 8000 y Vite en el 3010. El servidor e2e borra y recrea la base `lumi_e2e` en cada arranque y reconstruye el entorno desde cero, así que una clave de tu shell nunca llega a un proveedor. `e2e/sim.py` simula Meta y Post for Me con las respuestas grabadas de `tests/fixtures`, y las pantallas de consentimiento se contestan con redirecciones a la página de callback del frontend, como hacen los proveedores. Por defecto el chat usa el agente real (`E2E_AGENT=real`); con `E2E_AGENT=fake` vuelve el doble anterior (`FakeRuntime`).

Qué es real y qué es un doble en el agente real, sin gastar nada:

- Real: `apps.intelligence.runtime`, `get_wiring()`, el bucle del agente, el registro de herramientas, el cliente `openai` sobre un socket HTTP, `ToolExecution.as_dict` con su `result`, la herramienta `connect_account` sobre `DjangoConnectionLinks`, el embebedor ONNX (en caché local) y Chroma en un directorio temporal.
- Doble: el modelo de lenguaje. `e2e/llm_double.py` es un servidor compatible con OpenAI en el puerto 8099 (`E2E_LLM_PORT`). `lumi_ai.providers.factory.GROQ_BASE_URL` apunta a él y `GROQ_API_KEY` es un valor falso que solo enciende el proveedor. Decide con una regla fija: si el último mensaje pide conectar, llama a `connect_account`; con el resultado de la herramienta responde con el enlace. `GET /_calls` lista lo que recibió.
- Doble: Meta y Post for Me, como antes (`e2e/sim.py`).
- `connect_account` ya viene cableada en `apps.intelligence.wiring` (`ToolDeps(links=DjangoConnectionLinks())`); el e2e usa el registro real sin costura propia.

Los nueve pasos: registro, perfil, estado de los proveedores, conectar Facebook, conectar Post for Me, cancelar en el proveedor, un turno de chat (con Facebook ya conectado la herramienta lo dice; tras desconectar entrega la tarjeta de conexión), publicar (previsualizar, confirmar) y desconectar con cierre y reingreso de sesión. El mismo recorrido sin navegador está en `apps/connections/tests/db/test_e2e_api.py` y corre con `pytest`.

### Qué hace Christian

1. Poner las claves de cada proveedor en `lumi/.env` (orden de la sección anterior). No hay que tocar el frontend.
2. `VITE_API_BASE` solo hace falta si el backend no está en `http://localhost:8000/api/v1`.
3. Para desarrollar: `npm run dev:backend` y `npm run dev:frontend` desde `lumi/`. El backend usa uvicorn (ASGI) porque el stream del chat no funciona bien con `runserver`.
4. En `FRONTEND_URL` va la URL del frontend (`http://localhost:3010`). Los redirect URI de cada app registran la del frontend: `{FRONTEND_URL}/connections/<proveedor>/callback`. `PUBLIC_BASE_URL` ya no se usa y se puede borrar del `.env`.

### Huecos conocidos

- Un login de Meta con varias Páginas guarda todas, pero no enlaza ninguna al perfil. Sin enlace, `POST /publish` contesta `publish.not_connected`. Hace falta una ruta para elegir la Página del perfil (cambio de contrato pendiente de ARCHITECT).
- `ToolExecution.as_dict` no envía el `result` de `connect_account`, así que la tarjeta de conexión del chat solo se marca con el agente de prueba. Con el agente real el enlace se ve como un enlace de texto.
- `/repurpose` y `/voice/transcribe` están en `apps/intelligence/urls.py` pero no están montadas en `config/urls.py`. Hasta entonces la voz responde 404.
- `ChatStreamView` no declara un renderer `text/event-stream`.
- Las pruebas de navegador no cubren X, LinkedIn ni Google conectados, porque esos proveedores no tienen simulación todavía.

## Lo construido

Estado al 2026-10-27. Todo vive en `lumi/apps/connections/`. El núcleo funciona sin Django ni red. Solo `apps.py`, `models.py`, `stores.py` y `keys.py` tocan a Django o a `apps.core`, y `tests/test_boundaries.py` lo vigila.

| Pieza | Archivo | Qué hace |
| --- | --- | --- |
| Configuración | `config.py` | Lee las variables de entorno, valida formatos y excluye los secretos del `repr`. |
| Cifrado | `apps/core/fields.py` (ARCHITECT) | `EncryptedTextField` con Fernet y rotación: `TOKEN_ENCRYPTION_KEY` cifra, `TOKEN_ENCRYPTION_KEY_PREVIOUS` solo descifra. Los tokens de `ConnectedAccount`, `OAuthState` y `McpAuthAccount` usan ese campo. |
| Modelos | `models.py`, `migrations/0001_initial.py` | `ConnectedAccount`, `OAuthState`, `PublishJob`, `McpAuthAccount`, `HandleSearchCache`, `HandleSearchCacheEntry`, `XpozCreditLedger`. Las reglas viven en la base: UNIQUE, CHECK y FK. |
| Almacenes | `stores.py` | Implementaciones Django de los puertos puros. `OAuthState.consume` es un único `UPDATE ... RETURNING`. `PublishJob` es el libro de idempotencia. |
| Cliente HTTP | `http.py` | Transporte inyectable, lista de hosts permitidos, sin redirecciones, errores tipados sin URL ni cuerpo. Escrituras sin reintento. |
| OAuth | `oauth.py` | `state` de un solo uso con caducidad de 10 minutos, PKCE solo para X, destino posterior validado, el `state` solo lo consume el usuario que lo empezó (un solo `UPDATE ... WHERE user_id`). |
| Proveedores | `providers/{meta,linkedin,x}.py` | Contrato común `SocialProvider`. X queda apagado con `X_LIVE_ENABLED=false`: cero peticiones. |
| Publicación | `publishing.py` | `confirm` obligatorio, clave de idempotencia, un fallo ambiguo queda como `unknown` y no se reintenta solo. |
| Claves | `keys.py`, `apps.py` | Registra `meta`, `linkedin` y `x` en `check_keys`. Meta se sonda con un token de app (gratis). X nunca se sonda. |

Los errores tipados vienen de `lumi_ai.ports` (dueño: INTELLIGENCE) y se reexportan desde `errors.py`.

Las respuestas de prueba (`tests/fixtures/*.json`) están **escritas a mano** a partir de las formas documentadas, no capturadas de llamadas reales. Cuando haya apps reales, hay que grabar respuestas verdaderas y comparar. Las pruebas con marca `live` (Meta y LinkedIn) se saltan sin `LUMI_RUN_LIVE=1` y sin su variable. No existe prueba `live` de X y no debe existir.

### Dependencias abiertas

- `publish_jobs.attempt_id` es un `bigint` nulo sin FK. La `0002` añade la FK cuando INTELLIGENCE publique `repurpose_attempts`. Es una desviación temporal de SCHEMA §8.
- `stores.py` escribe handles con `apps.profiles.services.get_or_create_handle` (ya publicado).
- `PublishJob.external_url` y `HandleSearchCacheEntry.rank` son columnas que añadí a SCHEMA §8 para poder repetir una respuesta y conservar el orden. Falta que ARCHITECT las refleje en `docs/SCHEMA.md`.
- Las rutas de conexiones están montadas en `config/urls.py` (`api/v1/`).
- `0002` añade `platform`, `display_name` y `handle` a `connected_accounts` (PFM necesita saber la red de cada cuenta) y `social_profile_id` a `oauth_states` (para enlazar la cuenta al perfil que se indicó en `connect`). Hay que reflejarlo en SCHEMA §8.

### Rutas de conexión (T5)

Todas bajo `/api/v1/connections/{provider}`, con `provider` en `pfm|meta|linkedin|x`. `google` responde 501 hasta T9.

| Ruta | Qué hace |
| --- | --- |
| `POST .../connect` | Cuerpo opcional `profile_id`, `redirect_after`, `platform` (solo PFM). Responde `{"authorize_url"}`. Sin llaves de la app responde 503 `not_configured` con `details.env_vars`. X apagado responde 409 `connections.live_disabled`. |
| `POST .../callback` | Autenticada con el Token. Cuerpo `{state, code}` o `{state, error}`. Termina la autorización solo si el `state` lo empezó el usuario del Token. Si lo empezó otro usuario responde 409 `connections.state_mismatch` y **no** consume el state, así que su dueño aún puede usarlo. Un state desconocido, usado o caducado responde 400 `connections.state_invalid` o `state_expired`. `error` o falta de `code` queman el state del propio usuario (400 `connections.access_denied` o `state_invalid`). En PFM responde 400 `connections.unsupported`. Devuelve `{provider, connected, accounts, redirect_after}` con `Cache-Control: no-store`. |
| `GET .../status` | Solo lectura: `configured`, `connected`, `stale` y la lista de cuentas sin tokens, tal como están guardadas. No llama al proveedor y no escribe (una cuenta con tokens ilegibles se muestra como `error` sin guardarlo). |
| `POST /connections/pfm/sync` | Autenticada, sin cuerpo, con límite de 12 por minuto y usuario (429). Lee `GET /v1/social-accounts?external_id=<id de pfm_links>`, descarta lo que PFM archive bajo otro id, guarda cada cuenta con `_lock_account` y marca como revocadas las que ya no aparecen. Si PFM falla conserva lo guardado y responde `stale: true`. Sin enlace en `pfm_links` no llama a PFM. Devuelve el mismo cuerpo que `GET .../status`. |
| `DELETE .../{provider}` | Revoca en el proveedor (si falla, borra igual) y borra las filas con sus tokens. `?account_id=` limita a una cuenta. |

Códigos de error del callback: `connections.state_invalid`, `connections.state_expired`, `connections.state_mismatch`, `connections.access_denied`, `connections.account_taken`, `connections.no_accounts`, `connections.pfm_failed`, `connections.provider_rejected`, `upstream_error`, `internal_error`.

Decisiones:

- Meta guarda una fila por Página, con el token de la Página y sin vencimiento. Solo se enlaza a un perfil si la concesión trae una única cuenta.
- PFM guarda el id de cuenta de PFM y deja los tokens vacíos, porque PFM conserva los suyos. Usa `external_id = lumi-user-<id>`: PFM rechaza una cuenta que ya tiene otro `external_id`, así que dos usuarios de Lumi no pueden compartir una cuenta de red social. La redirección de PFM no trae `state` de Lumi: la página del frontend llama a `POST /connections/pfm/sync` justo después y esa llamada lee y guarda las cuentas.
- La URL de retorno de PFM se configura en su panel (`FRONTEND_URL/connections/pfm/callback`). `redirect_url_override` existe en la API pero no se usa. Sin verificar contra una cuenta real.
- Riesgo residual de PFM: como no hay `state`, quien abra el enlace de autorización de PFM de otra persona conecta su red social al `external_id` de esa persona. El `external_id` es aleatorio por usuario (`pfm_links`) y la interfaz muestra el handle conectado para que el usuario lo reconozca. Cerrarlo del todo necesita que PFM acepte un `state` propio.
- Renovación: `accounts.refresh_due()` (cola `connections.refresh_expiring` en `tasks.py` y comando `refresh_connections`). Renueva lo que vence en 7 días. Bloquea la fila durante la llamada porque X rota el refresh token. X apagado no envía nada. Falta que ARCHITECT programe la tarea en Celery beat.
- Sin verificar: `DELETE /me/permissions` de Meta con un token de Página (se guarda el token de Página, no el de usuario).

## Google (Drive y Docs por MCP) y límites de publicación

Google no es un `SocialProvider`. `GoogleOAuth` cumple el protocolo `OAuthProvider` y reutiliza `OAuthFlow`. Hay un solo permiso por usuario, guardado en `McpAuthAccount(user, "google")` con tokens cifrados. La ruta `/connections/google/status` añade `details` (`scopes`, `expires_at`, `has_refresh_token`), un campo nuevo y opcional que ARCHITECT debe anotar en CONTRATOS. El campo `details` vale `{}` para los demás proveedores.

`apps.connections.mcp_gateway.build_mcp_gateway()` devuelve el puerto `McpGateway`. El runtime de INTELLIGENCE lo inyecta y ejecuta `resolve_pending(profile_id, user_message)` antes de cada turno (0c07e2e). Las escrituras (crear, editar, borrar) quedan aparcadas en `mcp_pending_writes` (migración 0004, una por perfil) y solo se ejecutan tras un sí corto y claro. Cualquier otro mensaje las cancela. Sin `GOOGLE_OAUTH_CLIENT_ID` y `GOOGLE_OAUTH_CLIENT_SECRET`, `connect` responde 503 con la lista de variables. La sonda `google` de `check_keys` envía un código inválido: `invalid_grant` significa que el cliente es válido.

Sin verificar contra el servicio real: el servidor MCP de Google, el consentimiento y el refresco solo se probaron con servidores simulados en loopback.

Los límites de longitud al publicar salen de `lumi_ai.generation.platforms` (`SocialProvider.validate_draft`), la misma fuente que usa el generador: X 280, LinkedIn 3000, Facebook 63.206 (no oficial), Instagram 2200 con máximo 5 hashtags, TikTok 2200 en unidades UTF-16. Ya no hay tabla local.

## Importador del legado (T8)

`apps/connections/legacy_import.py` registra dos importadores en `import_legacy` (orden 200 y 210, rango CONNECT de CONTRATOS §10).

- `mcp_auth_accounts`: cada fila pasa a `McpAuthAccount` del usuario importado. Los tokens se cifran al guardar. Los permisos (`scopes`) pasan de texto separado por espacios a lista. Una fila sin token se omite con aviso.
- `profiles.pfm_account_id`: crea una `ConnectedAccount` con proveedor `pfm`, ligada al perfil que sobrevive (`profile_targets`). Un id vacío o que empieza por `demo-` no crea cuenta. Si dos perfiles legados se fusionaron, solo el primero conserva la cuenta y el otro deja un aviso.
- El id de PFM queda en `external_account_id` en claro, no cifrado. Es la clave única con la que se llama a PFM y no es un token (PFM guarda las credenciales). Cifrarlo obligaría a duplicarlo en otra columna. Si ARCHITECT prefiere cifrarlo, hace falta un cambio de modelo.
- Ni los tokens ni los ids salen en avisos, en el informe ni en logs. Una segunda ejecución no cambia nada.

## Medios de los posts (propuesta, 2026-10-27)

Hoy `ingest.py` no rellena `PostIn.media`, porque ninguna de las dos fuentes da un tipo fiable. La investigación de las especificaciones públicas (solo lectura, sin llamadas con clave):

| Fuente | Qué devuelve | Fuente de la afirmación |
| --- | --- | --- |
| PFM `GET /v1/social-account-feeds/{id}` con `expand=metrics` | `PlatformPostDto.media`: lista de medios del post propio. El esquema declara cada elemento como un arreglo sin forma (`items: {type: array}`), así que el contenido real queda **sin verificar** | https://api.postforme.dev/docs/json |
| PFM `GET /v1/social-post-results` | `SocialPostResultDto.media`: lista de `SocialPostMediaDto` (`url`, `thumbnail_url`, `alt_text`). Solo existe para posts que se publicaron por PFM | misma página |
| Xpoz, posts de un usuario en X (`/api/data/twitter/posts/users/{username}/live`) | Campo `mediaUrls`, que `USER_LIVE_FIELDS` ya pide. Sin tipo | https://api.xpoz.ai/openapi.json |
| Xpoz, posts de un usuario en Instagram (`/api/data/instagram/posts/users/{identifier}/live`) | Campos `mediaType`, `imageUrl`, `videoUrl`, `audioOnlyUrl`. Con tipo | misma página |
| Xpoz, posts de un usuario en TikTok (`/api/data/tiktok/posts/users/{identifier}/live`) | Campos `videoThumbnail`, `videoUrl`, `duration` | misma página |

Costo. Los campos son parte de la misma consulta (`fields=`): Xpoz cobra por consulta y las filas son gratis, según https://www.xpoz.ai/pricing (X y Reddit 2 créditos, TikTok 5, Instagram 12). Pedir los campos de medios no añade una llamada. Que no cuesten más por campo es lo que dice la tarifa, pero **sin verificar** con una consulta real.

Propuesta concreta para `PostIn.media`:

1. Posts propios (PFM): el cliente ya lee el feed (con `expand=metrics` opcional). Leer `media` de cada elemento no añade ninguna llamada. Mapear solo cuando el elemento trae `url` y un tipo reconocible. Si el contenido real resulta un arreglo anidado, se deja vacío y se avisa.
2. Posts de pares en Instagram y TikTok (Xpoz): hoy el cliente solo lee posts de X (`user_posts_page`). Cuando se añada la lectura de Instagram y TikTok, pedir `imageUrl`, `videoUrl`, `mediaType` (Instagram) y `videoThumbnail`, `videoUrl` (TikTok) en la misma consulta. Costo extra por los campos: 0 créditos. El tipo sale de `mediaType` en Instagram. En TikTok todo es vídeo.
3. X: `mediaUrls` llega sin tipo. Decidido: se guarda con `kind=None` (desconocido, nunca `image`). Implementado en `ingest.xpoz_media`.
4. Si INTELLIGENCE necesita el medio de un post concreto que no llegó, una segunda llamada por post (`/posts/{id}/live`) cuesta lo mismo que una consulta (2 créditos en X, 12 en Instagram, 5 en TikTok). No se recomienda como ruta normal.
5. Alternativa sin costo: que el usuario pegue el enlace del medio en el chat y que INTELLIGENCE lo use como `MediaRef` de esa petición.

CONNECT puede implementar el punto 1 y, para X, el mapeo de `mediaUrls` en el siguiente cambio si ARCHITECT confirma que `MediaRef.kind` admite el valor de cada tipo.

## Tope diario de Xpoz y límites de ritmo (revisión de seguridad, ALTO 3)

`XPOZ_RUN_CREDIT_BUDGET` solo acota una ejecución: cada petición y cada turno de chat crean un cliente nuevo con el contador a cero. El tope real vive en `DjangoCreditLedger.ensure_room`, que suma `xpoz_credit_ledger` de las últimas 24 horas antes de cada llamada de pago. Si pasa el tope del usuario o el global, lanza `BudgetExceeded` y no sale ninguna petición. La búsqueda de handles lo traduce a `reason=budget_exhausted` y sigue respondiendo con lo que hay en caché.

Dos llamadas simultáneas pueden pasar la comprobación a la vez, así que el exceso máximo es una llamada por petición concurrente. Por eso `GET /handles/search` admite 30 por minuto y usuario, y `POST /publish` 10 por minuto y usuario (`apps/connections/throttles.py`).

`GET /handles/stats` devuelve también `daily_cap_user` y `daily_cap_global`. Las dos variables nuevas hay que copiarlas a `.env.example` (no es de CONNECT).

## Confirmación de escrituras MCP (revisión de seguridad, MEDIO 6)

Antes, una herramienta pedía confirmación si su nombre tenía un verbo de escritura. Eso fallaba con nombres sin verbo: `copy_file` del Drive MCP duplica archivos y corría sin preguntar. Ahora es una lista blanca. Cada `MCPConnector` declara `read_only_tools` y solo esas herramientas corren a la primera. Todo lo demás, incluida una herramienta que el servidor añada mañana, queda aparcado hasta un "sí".

- Drive: `search_files`, `read_file_content`, `download_file_content`, `get_file_metadata`, `get_file_permissions`, `list_recent_files`.
- Docs: `read_doc`. `update_doc` pide confirmación.
- La coincidencia es exacta: ni mayúsculas, ni prefijos, ni espacios. Un conector sin lista pide confirmación en todo.
- Los nombres salen de la referencia oficial de Google (Drive y Docs MCP, en vista previa para desarrolladores). Si Google añade una lectura, se añade a la lista a mano.

El usuario ve la herramienta y todos los argumentos completos, sin recortar. Una escritura cuyos argumentos pasen de 20.000 caracteres no se aparca, porque nadie podría leerla entera.

Cada escritura aparcada lleva un `confirmation_id` (hash de perfil, herramienta y argumentos). Mientras haya una escritura viva esperando, otra distinta se rechaza con "NOT parked" y el modelo recibe el id de la que espera. Así el "sí" del usuario solo puede referirse a la escritura que el modelo acaba de describir, y una segunda petición del mismo turno no puede sustituirla. La misma escritura repetida se acepta, y una caducada se reemplaza. El resultado tras confirmar cita el `confirmation_id` que se ejecutó.

Límite que sigue en pie: el "sí" lo interpreta el servidor sobre el siguiente mensaje del usuario, y qué describió el modelo no se puede comprobar. Atar la confirmación a un botón de la interfaz con el id requeriría cambiar el puerto `resolve_pending` (INTELLIGENCE, `lumi_ai/ports.py`).

## Directorio de handles (sustituye a `handle_db`)

`apps/connections/handles/directory.py` (`HandleDirectory`) recoge lo que un escaneo aprende y deja una foto reutilizable. No hay tabla nueva: todo va a `social_handles` por `apps.profiles.services.get_or_create_handle`.

- `remember_scanned(handles, origin="niche")`: guarda las cuentas que un escaneo escuchó. Completa con una búsqueda de pago (solo coincidencia EXACTA de usuario) los handles que la tabla no conoce, hasta `HANDLE_DB_ENRICH_LIMIT` por llamada. Si la tabla no se puede leer no guarda ni gasta créditos.
- `remember(handles, origin="niche")`: guarda a los autores que el escaneo se encontró, sin gastar créditos. Devuelve cuántos eran nuevos.
- `pictures(handles)`: `{handle en minúsculas: Picture}` solo para quien tiene foto. Nunca lanza.
- Regla de ARCHITECT: `get_or_create_handle` solo rellena lo que está vacío y no baja el origen. El refresco de una foto vieja usa `update_handle_avatar` (solo pisa con una URL http(s) válida y distinta; `""`/`None` no hacen nada). Se llama con las filas que el proveedor devolvió en esa llamada (`source="live"`): la búsqueda en vivo de `/handles/search` y las filas vivas que guarda `HandleDirectory`. Una fila `cache` (autores de posts) y la fila de `/handles/select` (viene del cliente) solo rellenan, nunca repintan una foto pública.
- Foto de la cuenta conectada (CONTRATOS §11, fila 28): `sync_pfm_accounts`, tras `row.save()` y solo si la fila está `active` y enlazada a un perfil, llama a `update_profile_avatar(row.social_profile_id, acc.profile_photo_url, username=acc.username)`. El servicio exige que `username` sea el handle del perfil: sin esa comprobación una cuenta mal enlazada cambiaría la foto pública de otro handle. Corre en la petición de sincronización, no en una herramienta, así que no lleva `@aio`.
- Quien llama: `scan_trends` y `search_frameworks` de INTELLIGENCE (4971a13, a través del puerto `HandleBook` y `apps/intelligence/repos/handles.py`) alimentan `HandleDirectory` y reutilizan sus fotos. `lumi_ai/**` no es mío.

## Pasadas de ingesta (borrados sospechosos)

`apps/connections/passes.py` (puro) decide si un post desapareció. `DjangoPassStore` (en `stores.py`) lo guarda en la tabla `ingest_passes`.

- `is_second_miss`: un post se marca como borrado sospechoso solo si faltó en dos pasadas COMPLETAS seguidas, estaba dentro de la ventana de 30 días (`DELETION_WINDOW`) y se había visto antes.
- `pass_reached_window`: una pasada que no llegó hasta el borde de la ventana no cuenta como cobertura.
- `finalize_pass`: aplica lo anterior, sella `last_seen_at` de lo visto y marca o limpia las banderas en una sola transacción. Una pasada interrumpida se registra pero nunca cuenta como pasada previa.
- Diferencias con el legado: la pasada previa es la última COMPLETA (antes cualquiera), y un post marcado que reaparece se limpia.
- Quien la llama: `DjangoOwnPostSync` (`own_post_sync.py`, puerto `OwnPostSync`). Lee el feed de la cuenta Post for Me del perfil (hasta 100 posts y 10 páginas), guarda con `upsert_posts`, renumera cada hilo con `rethread_conversation` y cierra la pasada con `finalize_pass`. Todas las escrituras van con `@aio`: si el tool `backfill_posts` expira, lo que aún no se guardó no se guarda. Un feed vacío se guarda pero no cuenta como pasada completa (un corte de servicio se vería igual). `upsert_posts` borra la marca `is_deleted_suspect` de todo post que el feed devuelve, así que la rama `clear` de `finalize_pass` queda sin efecto detrás de ese guardado. INTELLIGENCE la usa en `wiring.py` (0377f2d): el tool `backfill_posts` la llama con el `CancelToken` del turno, y `profile.bootstrap` (antes de indexar) y `profile.refresh` (`POST /profiles/{id}/refresh`, ya registrado) corren la misma sincronización. No existe una tarea `post_sync`.
