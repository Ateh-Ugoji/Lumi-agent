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
| `PUBLIC_BASE_URL` | `http://localhost:8000` | URL pública del backend. De ella salen las redirect URIs |
| `FRONTEND_URL` | `http://localhost:3010` | Adónde vuelve el usuario tras conectar (`?connected=` o `?error=`) |
| `X_LIVE_ENABLED` | `false` | Interruptor de toda llamada real a X |
| `XPOZ_LIVE_ENABLED` | `false` | Interruptor de las llamadas reales a Xpoz (cada consulta gasta créditos) |
| `XPOZ_RUN_CREDIT_BUDGET` | `10` | Tope de créditos de Xpoz por ejecución. Al llegar se lanza `BudgetExceeded` |
| `HANDLE_CACHE_TTL_MINUTES` | `60` | Vigencia de la caché de búsqueda de handles (sustituye a `MVP_CACHE_TTL_MINUTES`) |
| `TOKEN_ENCRYPTION_KEY_PREVIOUS` | vacío | Clave Fernet anterior, solo mientras se rota |
| `LINKEDIN_API_VERSION` | `202609` | Valor de la cabecera `Linkedin-Version` (formato AAAAMM) |
| `META_GRAPH_VERSION` | `v26.0` | Versión de Graph API |

Los valores por defecto de `XPOZ_RUN_CREDIT_BUDGET`, `HANDLE_CACHE_TTL_MINUTES` y `LINKEDIN_API_VERSION` son decisión mía y no vienen de una fuente oficial.

## Redirect URIs exactas

Formato `{PUBLIC_BASE_URL}/api/v1/connections/<provider>/callback`. Cada consola compara la URI carácter por carácter, así que pega exactamente estas.

| Proveedor | URI en local | URI en producción |
| --- | --- | --- |
| Meta | `http://localhost:8000/api/v1/connections/meta/callback` | `https://<tu-dominio>/api/v1/connections/meta/callback` |
| LinkedIn | exige HTTPS, ver nota | `https://<tu-dominio>/api/v1/connections/linkedin/callback` |
| X | `http://127.0.0.1:8000/api/v1/connections/x/callback` | `https://<tu-dominio>/api/v1/connections/x/callback` |
| Google | `http://localhost:8000/api/v1/connections/google/callback` | `https://<tu-dominio>/api/v1/connections/google/callback` |

Notas.

- X pide `127.0.0.1` y no acepta `localhost` en local. Fuente https://docs.x.com/resources/fundamentals/developer-apps (2026-10-27). Si usas `127.0.0.1` en la consola, `PUBLIC_BASE_URL` debe ser `http://127.0.0.1:8000` durante esa prueba.
- LinkedIn dice "Add the redirect (callback) URL via HTTPS" y que la URL debe ser absoluta, sin `#`, y que los parámetros de consulta se ignoran. Fuente https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow (2026-10-27). Si acepta `http://localhost` queda sin verificar. Para probar en local usa un túnel HTTPS (por ejemplo `cloudflared` o `ngrok`) y pon esa URL en `PUBLIC_BASE_URL`.
- Meta compara la URI contra "Valid OAuth Redirect URIs". Fuente https://developers.facebook.com/docs/facebook-login/guides/advanced/manual-flow (2026-10-27). Que `http://localhost` valga para apps en modo Development está sin verificar en la página oficial.
- Post for Me no usa redirect URI de Lumi. Conecta las cuentas con su propio OAuth y Lumi solo guarda el id de cuenta de PFM.

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

Pendiente. Se llena en T11 con las notas de la integración React y Django.

## Lo construido

Pendiente. Se actualiza en T14 con lo que realmente quedó implementado.
