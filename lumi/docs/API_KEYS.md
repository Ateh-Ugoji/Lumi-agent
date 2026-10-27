# API keys de Lumi

Guía para Christian. Lumi funciona en modo completo cuando estas variables están en `lumi/.env`. Copia `lumi/.env.example` a `lumi/.env`, pega los valores y arranca. No hace falta tocar código.

Reglas:

- Si falta una key **obligatoria**, la app no arranca y el error lista todas las que faltan de una vez.
- Si falta una key **opcional**, la función que depende de ella se apaga y el arranque lo avisa en el log con una línea `WARNING` por variable.
- `lumi/.env` nunca se sube al repo. Nunca pegues keys en chats, commits, logs ni PRs. Este archivo solo nombra variables.
- Las keys que se expusieron antes del repo actual (ver `lumi/before-deployment.md`) deben rotarse antes de usarlas.

Columna **Estado**: `real` = la variable está en `lumi/.env.example` o la lee el código Django/`lumi_ai`. `nueva` = la define el plan y aún no está en el código. Política y registro de sondas: `docs/CONTRATOS.md` §8.

PostgreSQL es el único motor y `DATABASE_URL` es obligatoria. No hay SQLite (salvo la lectura de un `lumi.db` legado en `import_legacy`).

> **Aviso (27 oct 2026):** el token de Post for Me (`PFM_JWT_TOKEN`) está vencido (401) y hay que renovarlo. Xpoz casi no tiene créditos: no actives `XPOZ_LIVE_ENABLED` sin recargar o usar `XPOZ_API_KEY_2`.

> **Dónde viven estas claves.** Hoy el código las lee **solo del entorno** (`lumi/.env` en local, el panel de Railway en producción). La tabla `service_credentials` ya existe para guardar las de la app cifradas, pero todavía no se lee: eso llega en una fase posterior (base primero, entorno de respaldo). Ver `docs/CONEXIONES.md`, sección "Credenciales de la app".

## Obligatorias (sin ellas no arranca)

| Variable | Estado | Para qué sirve | Dónde se obtiene |
| --- | --- | --- | --- |
| `DATABASE_URL` | real | PostgreSQL, único motor en dev, tests y producción. Formato Django: `postgresql://usuario:clave@host:5432/lumi` (sin `+asyncpg`). En local la levanta `docker compose up -d db`; el valor de `.env.example` ya apunta ahí | Docker Compose local; Railway u otro Postgres en producción |
| `SECRET_KEY` | real | Firma de sesiones y tokens de Django. Mínimo 32 caracteres (lo comprueba `check_keys`) | `python -c "import secrets; print(secrets.token_urlsafe(50))"` |
| `TOKEN_ENCRYPTION_KEY` | real | Clave Fernet que cifra en Postgres los tokens OAuth de redes y de Google | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `GROQ_API_KEY` | real | Modelo de lenguaje principal (`openai/gpt-oss-120b`, con `openai/gpt-oss-20b` para turnos simples) y voz a texto (Whisper) | https://console.groq.com/keys |

## Recomendadas (opcionales, con aviso al arrancar)

Son opcionales: sin ellas Lumi funciona, con menos calidad de evaluación y sin trazas.

| Variable | Estado | Qué se apaga si falta | Dónde se obtiene |
| --- | --- | --- | --- |
| `TYPESAFE_API_KEY` | real | El juez Jev (clasificación de turnos, dificultad de reescritura, fidelidad). Cae a un modelo pequeño de Groq y, si tampoco hay, a reglas deterministas | TypeSafe AI |
| `NEATLOGS_API_KEY` | real | Trazas de llamadas al modelo y del loop del agente | neatlogs |
| `OPENROUTER_API_KEY` | real | El respaldo cuando Groq falla o se agota (hoy `meta-llama/llama-3.3-70b-instruct`). Pide saldo: con saldo 0 responde 402 | https://openrouter.ai/keys |

## Datos y redes sociales (opcionales)

| Variable | Estado | Qué se apaga si falta | Dónde se obtiene |
| --- | --- | --- | --- |
| `PFM_JWT_TOKEN` | real | Post for Me: conectar cuentas por su OAuth, traer posts y métricas, publicar. El token que existía está vencido (401) | https://app.postforme.dev (ver "Post for Me" abajo) |
| `XPOZ_API_KEY` | real | Escucha social y posts de competidores en X. El plan gratis da 500 créditos únicos (2 por consulta de X) | https://www.xpoz.ai/get-token |
| `XPOZ_API_KEY_2` | real (se lee con `os.environ`, fuera de `config.py`) | Segunda key de Xpoz para rotar cuando la primera se agota | https://www.xpoz.ai/get-token con otra cuenta |
| `META_APP_ID`, `META_APP_SECRET` | real | OAuth de Facebook (páginas). En modo Development solo funciona con cuentas con rol en la app | https://developers.facebook.com/apps |
| `LINKEDIN_CLIENT_ID`, `LINKEDIN_CLIENT_SECRET` | real | OAuth de LinkedIn. Con autoservicio solo se publica en el perfil personal (`w_member_social`) | https://www.linkedin.com/developers/apps |
| `X_CLIENT_ID`, `X_CLIENT_SECRET` | real | OAuth de X | https://console.x.com |
| `X_LIVE_ENABLED` | real | Interruptor de llamadas reales a X. Por defecto `false`. Cada post en X gasta créditos prepagados; no se activa sin que Christian lo pida | no es una key |
| `XPOZ_LIVE_ENABLED` | real | Interruptor de llamadas reales a Xpoz. Por defecto `false`. Cada consulta gasta créditos | no es una key |
| `XPOZ_RUN_CREDIT_BUDGET` | real | Tope de créditos de Xpoz por ejecución. Por defecto `12` (una corrida de Instagram cuesta 12). Opcionales por red: `XPOZ_RUN_CREDIT_BUDGET_X`, `XPOZ_RUN_CREDIT_BUDGET_INSTAGRAM`, `XPOZ_RUN_CREDIT_BUDGET_TIKTOK` y `XPOZ_RUN_CREDIT_BUDGET_REDDIT` | no es una key |
| `HANDLE_DB_ENRICH_LIMIT` | real | Handles nuevos que un escaneo completa con una búsqueda de pago por llamada. Por defecto `6` (2 créditos de Xpoz cada uno). `0` guarda solo los handles | no es una key |
| `HANDLE_CACHE_TTL_MINUTES` | real | Minutos de vigencia de la caché de búsqueda de handles. Por defecto `60`. Sustituye a `MVP_CACHE_TTL_MINUTES` | no es una key |
| `TOKEN_ENCRYPTION_KEY_PREVIOUS` | real | Clave Fernet anterior, solo mientras se rota `TOKEN_ENCRYPTION_KEY`. Vacía en el uso normal | no es una key |
| `LINKEDIN_API_VERSION`, `META_GRAPH_VERSION` | real | Versiones de API que usan los adaptadores. Por defecto `202609` y `v26.0` | no son keys |
| `FRONTEND_URL` | real | URL del frontend, por defecto `http://localhost:3010`. Todas las redirect URIs de OAuth salen de ella: el proveedor vuelve a una página del frontend, y esa página hace un POST autenticado al backend. El hosting tiene que servir `index.html` en `/connections/*`. (`PUBLIC_BASE_URL` es obsoleta: Django ya no la lee) | no es key |

## Ajustes de Django (opcionales, no son keys)

| Variable | Estado | Para qué sirve |
| --- | --- | --- |
| `AUTH_TOKEN_TTL_DAYS` | real | Días de validez de los tokens de API (tabla `auth_tokens`). Por defecto `30` |
| `CORS_ALLOWED_ORIGINS` | real | Orígenes del frontend permitidos. Local: `http://localhost:3010,http://127.0.0.1:3010` |
| `DJANGO_SETTINGS_MODULE`, `DEBUG`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, `LOG_LEVEL`, `REDIS_URL`, `LUMI_ENV_FILE` | real | Ajustes estándar. `LUMI_ENV_FILE` cambia la ruta del `.env` (por defecto `lumi/.env`) |

Las variables que CONTRATOS §8 añadió a esta guía: `FRONTEND_URL`, `XPOZ_LIVE_ENABLED`, `XPOZ_RUN_CREDIT_BUDGET`, `HANDLE_CACHE_TTL_MINUTES`, `TOKEN_ENCRYPTION_KEY_PREVIOUS`, `LINKEDIN_API_VERSION`, `META_GRAPH_VERSION`, `AUTH_TOKEN_TTL_DAYS`, `CORS_ALLOWED_ORIGINS`.

Trámites que ninguna key resuelve (solo Christian):

- Meta: App Review de `pages_manage_posts`, `pages_read_engagement` y `read_insights`, más Business Verification. Mientras no estén aprobados, solo funcionan cuentas con rol en la app (modo Development). Pasos en "Meta, paso a paso".
- LinkedIn: solicitar la Community Management API (pide screencast) para páginas de empresa. Pasos en "LinkedIn, paso a paso".
- X: decidir si se compran créditos. Mientras tanto `X_LIVE_ENABLED=false`.

Los datos de Meta, LinkedIn, X, Post for Me y Xpoz se revalidaron el 2026-10-27 contra las páginas oficiales. Las fuentes y las diferencias con `research.md` están en `docs/CONEXIONES.md`. Lo que no se pudo comprobar en una página oficial dice "sin verificar".

## Cómo crear cada app

Redirect URIs. Todas siguen el patrón `{FRONTEND_URL}/connections/<provider>/callback` (por defecto `http://localhost:3010`). El callback llega al frontend y no al backend; así el `state` queda atado al usuario con sesión iniciada. Pega la URI sin barra final y sin cambios.

| Proveedor | Redirect URI | Nota |
| --- | --- | --- |
| Meta (Instagram y Facebook, una sola app) | `{FRONTEND_URL}/connections/meta/callback` | |
| LinkedIn | `{FRONTEND_URL}/connections/linkedin/callback` | Exige HTTPS: en local, un túnel en `FRONTEND_URL` |
| X | `{FRONTEND_URL}/connections/x/callback` | En local usa `http://127.0.0.1:3010`, no `localhost` |
| Google | `{FRONTEND_URL}/connections/google/callback` | Lo controla `GOOGLE_OAUTH_REDIRECT_URI` |
| Post for Me | `{FRONTEND_URL}/connections/pfm/callback` | Se pone en el panel de PFM; el código no manda un redirect. Sin verificar con una cuenta real |
| TikTok | no tiene OAuth | Solo lectura vía Xpoz |

El detalle está en `docs/CONEXIONES.md`.

Orden recomendado: Google, Xpoz, Meta, LinkedIn, Post for Me, X. Los dos trámites largos (App Review de Meta y Community Management API de LinkedIn) no bloquean nada de lo anterior, y se pueden dejar para cuando Lumi se abra a otras personas.

### Google (conectores Drive y Docs)

Fuentes https://developers.google.com/identity/protocols/oauth2/web-server y https://support.google.com/cloud/answer/6158849 (2026-10-27).

1. Entra en https://console.cloud.google.com y crea un proyecto, o elige uno.
2. Abre la API Library, busca "Google Drive API" y pulsa Enable. Repite con "Google Docs API".
3. Configura la pantalla de consentimiento en Google Auth Platform. Las secciones se llaman Branding, Audience y Data Access (https://support.google.com/cloud/answer/6158849). Mientras la app esté en modo de prueba, añade tu correo como usuario de prueba en Audience. El nombre exacto de ese botón no lo pude comprobar, sin verificar en la consola.
4. Abre la página Clients de Google Auth Platform y pulsa Create Client.
5. Elige el tipo "Web application".
6. En "Authorized redirect URIs" pega `http://localhost:3010/connections/google/callback`. Para producción añade la misma ruta con tu dominio HTTPS.
7. Pulsa Create. Copia el ID de cliente a `GOOGLE_OAUTH_CLIENT_ID` y el secreto a `GOOGLE_OAUTH_CLIENT_SECRET`. Pon la misma URI del paso 6 en `GOOGLE_OAUTH_REDIRECT_URI`.
8. `GOOGLE_OAUTH_REDIRECT_URI` es `{FRONTEND_URL}/connections/google/callback`, que es su valor por defecto en `.env.example` (CONTRATOS §4). La ruta vieja `/mcp/google/callback` es del backend FastAPI; regístrala también solo mientras ese backend siga en uso.

### Xpoz (escucha de competidores en X)

Fuentes https://docs.xpoz.ai/authentication y https://docs.xpoz.ai/pricing (2026-10-27).

1. Crea una cuenta en https://www.xpoz.ai.
2. Abre https://www.xpoz.ai/get-token y copia la clave de acceso a `XPOZ_API_KEY`.
3. El plan gratis da 500 créditos una sola vez y no se renuevan. Una consulta de X cuesta 2. Lumi arranca con `XPOZ_LIVE_ENABLED=false` y `XPOZ_RUN_CREDIT_BUDGET=12`. Cambia a `true` solo cuando quieras gastar créditos.
4. Para una segunda cuenta con otros 500 créditos repite los pasos y guarda la clave en `XPOZ_API_KEY_2`.
5. Las herramientas de cuenta, como leer el saldo, no gastan créditos.

### Meta, paso a paso (Facebook Pages)

Fuentes en `docs/CONEXIONES.md`, sección Meta (2026-10-27).

Modo Development, sin revisión. Sirve para publicar en tus propias páginas.

1. Entra en https://developers.facebook.com con tu cuenta de Facebook y acepta ser desarrollador. Para publicar necesitas ser administrador de una Página de Facebook, o crear una en https://www.facebook.com/pages/create.
2. Abre https://developers.facebook.com/apps/creation/ (https://developers.facebook.com/docs/development/create-an-app). Escribe el nombre de la app y tu correo.
3. Elige el caso de uso "Manage everything on your Page". Los casos de uso no se pueden quitar después. Agrega como opcionales `pages_read_engagement`, `pages_manage_posts`, `pages_manage_metadata` y `read_insights`.
4. Cuando pregunte por el portfolio de negocio, elige "I don't want to connect a business portfolio yet" o el que ya tengas. Se puede conectar después. El texto exacto del botón está sin verificar.
5. Sigue las pantallas Requirements y Overview y pulsa "Go to dashboard".
6. En Settings > Basic copia App ID a `META_APP_ID` y App Secret a `META_APP_SECRET`. El secreto pide tu contraseña para mostrarse.
7. Añade la redirect URI. La documentación pide registrarla en Facebook Login > Settings > Client OAuth Settings > Valid OAuth Redirect URIs (https://developers.facebook.com/docs/facebook-login/guides/advanced/manual-flow). Pega `http://localhost:3010/connections/meta/callback`. En apps nuevas con casos de uso, la ruta del menú puede cambiar, sin verificar en la consola.
8. Deja la app en modo Development (https://developers.facebook.com/docs/development/build-and-test/app-modes). En ese modo solo entran personas con rol en la app: administrador, desarrollador o tester (https://developers.facebook.com/docs/development/build-and-test/app-roles). Añade a cada tester en App roles > Roles.
9. Ten en cuenta el límite de un máximo de 15 apps sin verificar por desarrollador.
10. Prueba con `uv run python manage.py check_keys --only meta`.

Para abrir Lumi a personas sin rol (App Review), solo cuando quieras lanzarlo.

1. Pon la app en Live solo después de que App Review apruebe los permisos. Los posts de prueba se vuelven visibles al pasar a Live (https://developers.facebook.com/docs/development/build-and-test/app-modes).
2. En Settings > Basic completa icono de 1024x1024, URL de política de privacidad, categoría, contacto principal y el propósito de la app ("Yourself or your own business" o "Clients").
3. Haz Business Verification. Es obligatoria para acceso avanzado (https://developers.facebook.com/docs/development/release/business-verification). En Settings > Basic > Verification pulsa Start Verification y conecta tu negocio. La verificación en sí se hace en Business Manager, por un administrador del negocio. Prepara el nombre legal, dirección y documentos que pida Meta.
4. Haz al menos una llamada exitosa por cada permiso, en los 30 días previos. Meta tarda hasta 2 días en registrarla, y hasta entonces el botón "Request advanced access" sale gris. Publicar un borrador desde Lumi en tu página genera esas llamadas.
5. Graba un screencast por permiso, a 1080p o más, sin audio y con la interfaz en inglés, donde se vea el login y cómo la app usa el permiso.
6. Abre App Review > Permissions and Features y pulsa "Request advanced access" en `pages_manage_posts`, `pages_read_engagement`, `pages_show_list` y `read_insights`. Los dos últimos y `pages_read_engagement` son dependencias de `pages_manage_posts` (https://developers.facebook.com/docs/permissions).
7. Responde las preguntas de manejo de datos y deja instrucciones de prueba para el revisor, con un usuario de prueba y una página. Sin eso rechazan el envío (https://developers.facebook.com/docs/resp-plat-initiatives/individual-processes/app-review/submission-guide).
8. Access Verification ya no se exige (https://developers.facebook.com/docs/development/release/access-verification).

### LinkedIn, paso a paso

Fuentes en `docs/CONEXIONES.md`, sección LinkedIn (2026-10-27). Los pasos 1 a 5 vienen de guías de terceros (socialift.uz, docs.unified.to e inkling.host) porque la documentación oficial no los detalla. Están sin verificar en la consola. Los productos y scopes sí son oficiales (https://learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access).

Perfil personal, autoservicio.

1. LinkedIn exige una página de empresa para crear la app. Si no tienes una, crea una en https://www.linkedin.com/company/setup/new/.
2. Crea la app en https://www.linkedin.com/developers/apps/new. Escribe nombre, elige la página de empresa, pega la URL de tu política de privacidad y sube el logo.
3. Pide al administrador de la página que verifique la app. En la pestaña Settings pulsa Verify > Generate URL (la URL vale 30 días) y envíasela al administrador.
4. En la pestaña Products solicita "Share on LinkedIn" y "Sign In with LinkedIn using OpenID Connect". Ambos son de autoservicio. Con ellos obtienes los scopes `w_member_social` y `openid profile email`.
5. En la pestaña Auth, en "Authorized redirect URLs for your app", pega la URL HTTPS de callback (`https://<tu-dominio-o-túnel-del-frontend>/connections/linkedin/callback`). LinkedIn pide HTTPS (https://learn.microsoft.com/en-us/linkedin/shared/authentication/authorization-code-flow). En local usa un túnel.
6. En la misma pestaña copia Client ID a `LINKEDIN_CLIENT_ID` y Primary Client Secret a `LINKEDIN_CLIENT_SECRET`.
7. Deja `LINKEDIN_API_VERSION=202609`. La versión 202511 se retira el 2026-11-16.
8. Prueba con `uv run python manage.py check_keys --only linkedin`. La comprobación valida formato y endpoint, sin canjear códigos.

Con esto Lumi publica en tu perfil personal. Sin `r_member_social` no puede leer tus posts ni sus métricas, y la cuenta queda marcada `limited`.

Páginas de empresa y métricas, con Community Management API.

1. Abre la pestaña Products de tu app y solicita "Community Management API". Si tu app ya tiene Advertising API, LinkedIn pide crear una app nueva con la misma página y solicitar primero el nivel Development. Después se pide Standard en la app que ya existía (https://learn.microsoft.com/en-us/linkedin/marketing/increasing-access).
2. Completa el formulario de acceso con tu caso de uso. Graba un screencast de cada caso de uso para el nivel Standard.
3. Con Development tienes 500 llamadas por día por app y 100 por miembro, sin `BATCH_GET` ni webhooks, y 12 meses para pedir Standard (https://learn.microsoft.com/en-us/linkedin/marketing/community-management/community-management-overview).
4. Al aprobarse, LinkedIn concede scopes como `r_organization_social`, `w_organization_social`, `rw_organization_admin`, `r_organization_followers` y `r_member_postAnalytics`.
5. Los usuarios deben volver a conectar su cuenta para recibir los scopes nuevos.

### Post for Me

Fuentes https://www.postforme.dev/pricing y https://api.postforme.dev/docs (2026-10-27).

1. Crea una cuenta en https://app.postforme.dev.
2. El plan cuesta $10 al mes por hasta 1,000 posts exitosos y cuentas ilimitadas. El token anterior está vencido, así que hace falta una clave nueva.
3. Genera una clave de API en el panel y pégala en `PFM_JWT_TOKEN`. Se envía como `Authorization: Bearer`.
4. Para cada red que Post for Me deba publicar, conecta la cuenta desde el panel o desde Lumi (`POST /v1/social-accounts/auth-url`). Post for Me guarda los tokens, y Lumi solo guarda el id de la cuenta.
5. Los límites de 5 peticiones por segundo y 40 por minuto vienen de `lumi/AGENTS.md`. Están sin verificar en la documentación pública.
6. Prueba con `uv run python manage.py check_keys --only pfm`.

### X

Fuentes https://docs.x.com/x-api/getting-started/getting-access, https://docs.x.com/resources/fundamentals/developer-apps, https://docs.x.com/fundamentals/authentication/oauth-2-0/authorization-code y https://docs.x.com/x-api/getting-started/pricing (2026-10-27).

No hagas el paso 5 hasta decidir gastar. Los pasos 1 a 4 no cuestan.

1. Entra en https://console.x.com con la cuenta de X y acepta el Developer Agreement.
2. Crea una app. Elige el tipo "Web App" (cliente confidencial), que entrega `client_secret`.
3. En la configuración de OAuth 2.0 pega la callback `http://127.0.0.1:3010/connections/x/callback`. X pide `127.0.0.1` y no acepta `localhost`. Para producción añade la URL HTTPS. Marca los permisos de lectura y escritura. Los scopes que pide Lumi son `tweet.read tweet.write users.read offline.access media.write`.
4. Copia Client ID a `X_CLIENT_ID` y Client Secret a `X_CLIENT_SECRET`. El secreto se muestra una sola vez. Deja `X_LIVE_ENABLED=false`.
5. Para activar X compra créditos en la consola y fija un tope de gasto por ciclo antes de cargar nada. Un post cuesta $0.015, uno con enlace $0.20 y leer un post $0.005. Hay un bono de $20 al guardar tarjeta y comprar créditos. Después cambia `X_LIVE_ENABLED=true`.
6. El código de autorización de X caduca a los 30 segundos. Lumi lo canjea de inmediato.

## Opcionales de IA y almacenamiento

| Variable | Estado | Qué se apaga si falta | Dónde se obtiene |
| --- | --- | --- | --- |
| `OPENLUX_API_KEY`, `OPENLUX_MODEL` | real (`OPENLUX_BASE_URL=https://api.openlux.ai/v1` está fijo en código) | Proveedor extra que se prueba antes que Groq. Valor por defecto del modelo: `qwen3.8-27b` | OpenLux |
| `CHROMA_API_KEY`, `CHROMA_TENANT`, `CHROMA_DATABASE` | real | Chroma Cloud. Sin ellas, ChromaDB corre local en `CHROMA_PATH` (por defecto `.chroma`). Chroma guarda solo vectores | https://www.trychroma.com |
| `VIDEO_API_KEY`, `VIDEO_PROVIDER` | nueva | Análisis de video en competidores. Los nombres se confirman cuando LUMI-INTELLIGENCE entregue `lumi/docs/VIDEO_API_COMPARISON.md` y Christian elija proveedor | el proveedor elegido |
| `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_REDIRECT_URI` | real | Conectores MCP de Google Drive y Docs | https://console.cloud.google.com/apis/credentials |
| `MCP_ENABLED`, `MCP_GDRIVE_ENABLED`, `MCP_GDOCS_ENABLED` | real | Interruptores (por defecto `true`) de los conectores MCP | no son keys |
| `MCP_TOOLS_TTL_SECONDS`, `MCP_REFRESH_TIMEOUT_SECONDS`, `MCP_CALL_TIMEOUT_SECONDS` | real | Ajustes de caché y tiempos de MCP (300 / 15 / 60) | no son keys |
| `TURN_CLASS_JEV_ENABLED`, `TURN_CLASS_JEV_TIMEOUT_MS`, `TURN_CLASS_JEV_HIGH`, `TURN_CLASS_JEV_LOW` | real | Etapa 2 del clasificador de turnos con Jev (apagada por defecto; `1500` ms, `0.7`, `0.4`) | no son keys |

## Modelos y proveedores de IA (opcionales, no son keys)

Salen de `lumi/lumi_ai/config.py` (`AIConfig`). El nombre de la variable es el campo en mayúsculas; Django los pasa a `AIConfig.from_mapping`. `check_keys` valida los ids de modelo contra el catálogo real de cada proveedor. Los valores por defecto son los del código anterior y no están verificados contra los catálogos de hoy.

| Variable | Por defecto | Para qué sirve |
| --- | --- | --- |
| `GROQ_MODEL_LARGE` | `openai/gpt-oss-120b` | Modelo principal de Groq |
| `GROQ_MODEL_SMALL` | `openai/gpt-oss-20b` | Turnos simples y juez de respaldo |
| `GROQ_MODEL_FALLBACK` | `qwen/qwen3.8-27b` | Segundo modelo de Groq si el grande falla |
| `OPENROUTER_MODEL` | `meta-llama/llama-3.3-70b-instruct` | Modelo de respaldo en OpenRouter |
| `OPENLUX_MODEL` | `qwen3.8-27b` | Modelo del relay OpenLux |
| `WHISPER_MODEL` | `whisper-large-v3-turbo` | Voz a texto en Groq |
| `PROVIDER_COOLDOWN_SECONDS` | `300` | Descanso de un proveedor tras un 401/402/403/429 |
| `PROVIDER_COOLDOWN_MAX_SECONDS` | `900` | Tope del descanso cuando el proveedor manda `Retry-After` |
| `LLM_TIMEOUT_SECONDS` | `60` | Tiempo máximo de una llamada al modelo |

Embedder: `onnx-minilm-l6-v2` (384 dimensiones), fijo en `lumi_ai/rag/embedder.py`; **no tiene variable**. Se descarga una vez (unos 79 MB) a `~/.cache/chroma`. Cada colección de Chroma guarda el nombre del embedder; si cambia, hay que correr `manage.py reindex_vectors`.

Variables que el código actual lee fuera de `config.py` y que el port debe pasar a la configuración central o eliminar: `MVP_CHROMA_API_KEY`, `MVP_CHROMA_TENANT`, `MVP_CHROMA_DATABASE`, `HANDLE_SEARCH_DB` (apunta a SQLite; desaparece), `MVP_XPOZ_LIVE`, `MVP_XPOZ_BUDGET`, `MVP_CACHE_TTL_MINUTES`, `HANDLE_DB_ENRICH_LIMIT`. `XPOZ_RUN_CREDIT_BUDGET` es nueva y se documenta arriba.

Nombres nuevos de CONNECT para sustituir a los `MVP_*`: `XPOZ_LIVE_ENABLED`, `HANDLE_CACHE_TTL_MINUTES`, `TOKEN_ENCRYPTION_KEY_PREVIOUS`. Ya están en las tablas de arriba, y ARCHITECT debe copiarlos a `.env.example`.

## Comprobar que todo funciona

```bash
cd lumi
cp .env.example .env            # pega las keys en .env
docker compose up -d db         # Postgres local
uv run python manage.py migrate
uv run python manage.py check_keys
uv run python manage.py runserver
```

`check_keys` (`apps/core/management/commands/check_keys.py`) hace una llamada mínima real a cada servicio configurado y muestra `OK`, `OMITIDA` (opcional, falta la variable) o `FALLA` con el error (key mal copiada, permiso faltante, cuota agotada). Nunca imprime el valor de una key y funciona con el entorno vacío.

- `--only id1,id2`: solo esos servicios. Ids: `database`, `secret`, `token_encryption`, `groq`, `openrouter`, `openlux`, `meta`, `linkedin`, `x` y los demás que registren INTELLIGENCE y CONNECT (`pfm`, `xpoz`, `google` cuando CONNECT los añada).
- `--json`: salida para scripts.
- Código de salida: `0` todo bien; `1` falta una obligatoria o falló un servicio configurado; `2` id desconocido.


## Variables de configuración que no son keys (actualizado 07:15 UTC)
| Variable | Por defecto | Para qué sirve |
|---|---|---|
| `LUMI_CHAT_RUNTIME` | `apps.intelligence.runtime` | Módulo de IA que atiende `/chat` y `/chat/stream`. Si no existe, el chat responde `503 chat.unavailable`. |
| `LUMI_JOB_DISPATCH` | `none` | `none` deja los trabajos en cola para un worker; `eager` los ejecuta en la misma petición (solo en desarrollo). |

Para entrar a `/admin/` primero crea un superusuario: `uv run python manage.py createsuperuser`.
