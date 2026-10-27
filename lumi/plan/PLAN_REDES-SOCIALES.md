# PLAN REDES SOCIALES: acciones de Meta y cómo separarlas del resto de servicios

Creado el 27 de octubre de 2026. Complementa `PLAN_LUMI-CONNECT.md` (que ya entregó OAuth, publicar texto y el contrato `SocialProvider`). Aquí se planea lo que viene después: usar más acciones de la API de Meta sin mezclarlas con LinkedIn, X, YouTube ni Post for Me.

Estado: **plan, sin código**. Nada de esto está construido. Cada hecho sobre la API de Meta que no se haya comprobado en este repo dice "sin verificar" y la tarea R1 lo revalida contra la documentación oficial antes de escribir código.

## 0. Protocolo (el mismo de los otros planes)

- Rama única: `lumi-orquestador`. Sin force-push, sin merge a `main`, sin deploy y nada live sin permiso de Christian.
- Cada tarea: responsable, entregable y cómo se verifica. Commits con el prefijo del responsable (`[CONNECT]`, `[ARCHITECT]`, `[INTELLIGENCE]`).
- Antes de tocar código: auditar, mostrar el plan y luego ejecutar (`AGENTS.md`, proceso obligatorio). Todo cambio de esquema, de herramienta o de flujo actualiza en el mismo cambio `AGENTS.md`, `docs/flow-map.md` y `docs/flow-map.html`.
- Las credenciales de la app viven solo en el entorno (decisión del 27 de octubre, `AGENTS.md`, regla de secretos). Ninguna tarea de este plan añade una tabla de credenciales.
- Pruebas sin red: transportes simulados, como `apps/connections/tests/db/test_api.py`. Una llamada real a un proveedor solo con permiso explícito y `LUMI_RUN_LIVE=1`.

## 1. Qué hay hoy (verificado en el código)

| Pieza | Dónde | Qué hace |
|---|---|---|
| Contrato de proveedor | `apps/connections/providers/base.py` (`SocialProvider`, `Capabilities`) | OAuth, `list_accounts`, `fetch_posts`, `fetch_metrics`, `publish` (solo texto y un enlace) |
| Adaptadores | `providers/meta.py`, `linkedin.py`, `x.py` | Uno por proveedor; Post for Me y Xpoz son clientes aparte (`clients/`) |
| Meta hoy | `providers/meta.py` | Conectar Páginas, publicar en `/{página}/feed`, leer posts y métricas **en el adaptador, sin ningún llamador** |
| Enrutado red a proveedor | `publish_api.py:43` (`PROVIDER_FOR_PLATFORM`), `connect_links.py:24-25` (`NATIVE_PROVIDER`, `PFM_PLATFORMS`), `ingest.py:34` (`PFM_PLATFORMS`) | **La misma decisión escrita en tres sitios** |
| Agente | herramientas en `lumi_ai/tools`, `connect_account` y las de lectura | El agente no publica: publicar es solo REST con `confirm` e `Idempotency-Key` |
| Confirmación de escrituras | `mcp_pending_writes` y `resolve_pending` | Patrón de "pedir un sí antes de escribir" ya construido para MCP |

El problema de separación no está en Meta: está en que "qué proveedor sirve a qué red" y "qué sabe hacer cada uno" no tienen un solo dueño.

## 2. Decisiones de diseño

**D1. Se separa por dos ejes.**
1. **Proveedor** (quién tiene la app, las credenciales y la API): `meta`, `linkedin`, `x`, `google` (YouTube), `pfm`. Un adaptador por proveedor, como hoy.
2. **Capacidad** (qué acción): publicar texto, publicar medios, programar, editar y borrar, comentarios, métricas de post, métricas de página, mensajes. Cada capacidad es una interfaz pequeña; un proveedor implementa solo las suyas.

**D2. Meta se parte en superficies, no en un archivo gigante.** Meta no es una API: son varias, con permisos y revisión propios (Páginas, Instagram, Messenger, anuncios, Threads, WhatsApp; el panel de la app de Christian las lista como casos de uso). `providers/meta/` pasa a ser un paquete: `graph.py` (HTTP y OAuth compartidos), `pages.py` (Facebook Páginas) y, si se decide, `instagram.py`. Mensajes, anuncios, Threads y WhatsApp quedan **fuera de alcance** hasta que Christian lo decida (sección 6).

**D3. Una sola tabla de rutas.** Un módulo `providers/routes.py` responde, para cada red, qué proveedores la sirven, en qué orden y con qué capacidades. Sustituye a `PROVIDER_FOR_PLATFORM`, `NATIVE_PROVIDER` y los dos `PFM_PLATFORMS`. Cambiar quién sirve a Instagram pasa a ser una línea, no tres.

**D4. Las capacidades se declaran y se comprueban, no se suponen.** `Capabilities` crece con una bandera por capacidad y un método `supports(action)`. Una acción no soportada responde con el error tipado que ya existe (`UnsupportedOperation`) y el agente lo explica; nunca finge. Un test recorre todos los proveedores y exige que lo declarado coincida con lo implementado.

**D5. Las herramientas del agente no conocen a Meta.** Reciben `platform` y la acción (`list_comments`, `reply_comment`, `read_page_metrics`...). La tabla de rutas decide quién la atiende. Así YouTube o LinkedIn entran sin tocar el agente.

**D6. Escribir es siempre en dos tiempos.** Toda acción que cambia algo público (publicar medios, programar, editar, borrar, responder un comentario) reutiliza `dry_run` más `confirm` más `Idempotency-Key`, y por el agente pasa por el patrón de escritura pendiente de MCP: el agente propone, el usuario confirma. Los límites de ritmo por usuario siguen el patrón de `throttles.py`.

**D7. Los permisos siguen a las capacidades activas.** Hoy `SCOPES` de Meta es una constante. Pasa a calcularse según las capacidades encendidas por bandera de entorno (`META_<CAPACIDAD>_ENABLED`, apagadas por defecto salvo las que ya funcionan, como el patrón de `X_LIVE_ENABLED`). Una cuenta ya conectada guarda sus `scopes`: si una capacidad nueva pide más, la cuenta pasa a "necesita reconectar" y no a fallar en silencio.

## 3. Mapa de acciones de Meta

La columna "API de Meta" es conocimiento general y está **sin verificar**: R1 la revalida con URL oficial y fecha antes de construir.

| Acción | Estado hoy | Permiso (sin verificar) | Fase |
|---|---|---|---|
| Conectar Páginas, publicar texto con enlace | Hecho | `pages_show_list`, `pages_manage_posts` | Hecho |
| Leer posts de la Página | En el adaptador, sin llamador | `pages_read_engagement` | R3 |
| Métricas de cada post | En el adaptador, sin llamador | `read_insights` | R3 |
| Métricas de la Página (seguidores, alcance) | No | `read_insights` | R3 |
| Publicar fotos, videos y reels | No | `pages_manage_posts` | R4 |
| Programar un post | No | `pages_manage_posts` | R4 |
| Editar y borrar posts | No | `pages_manage_posts` | R4 |
| Leer comentarios | No | `pages_read_user_content` | R5 |
| Responder, ocultar o borrar comentarios | No | `pages_manage_engagement` | R5 |
| Ajustes de la Página y webhooks | No | `pages_manage_metadata` | Fuera por ahora |
| Mensajes de Messenger | No | `pages_messaging` | Fuera por ahora |
| Instagram profesional vinculado | No (hoy solo por Post for Me) | permisos de Instagram | R7, decisión |
| Anuncios, Threads, WhatsApp | No | otras APIs | Fuera por ahora |

Con la app en modo Development y tu rol, estos permisos funcionan sobre tu propia Página sin App Review. Para otros usuarios hace falta acceso avanzado (screencast y verificación del negocio), ver `docs/API_KEYS.md`.

## 4. Tareas en orden

### R0. Decisiones y contrato (ARCHITECT, 1 h)
Resolver las preguntas de la sección 6 con Christian y actualizar `docs/CONTRATOS.md` (las capacidades y la tabla de rutas) y `docs/CONEXIONES.md`.
- **Entregable:** contrato escrito y decisiones en `plan/decisions.tsv`.
- **Verificación:** CONNECT e INTELLIGENCE escriben `CONTRATO REDES ACEPTADO <sha>` en su estado.

### R1. Revalidar la API de Meta (CONNECT, 1-2 h)
Comprobar contra páginas oficiales cada fila de la sección 3: endpoint, permiso, si exige App Review, límites. Cada dato con su URL y fecha, o "sin verificar".
- **Entregable:** sección nueva en `docs/CONEXIONES.md`.
- **Verificación:** ninguna fila de la sección 3 queda con "sin verificar" sin motivo escrito.

### R2. Refactor sin cambiar comportamiento (CONNECT, 3-4 h)
Crear `providers/routes.py` y reemplazar los tres sitios duplicados. Partir `providers/meta.py` en el paquete `providers/meta/` (`graph.py`, `pages.py`). Extender `Capabilities` con las banderas y `supports()`.
- **Entregable:** el mismo comportamiento, un solo dueño del enrutado.
- **Verificación:** `pytest apps/connections` sigue en verde sin tocar los tests existentes; un test nuevo exige que cada proveedor declare solo lo que implementa; `rg "PROVIDER_FOR_PLATFORM|NATIVE_PROVIDER"` no encuentra definiciones duplicadas.

### R3. Leer: posts y métricas de Facebook (CONNECT, 3 h)
Conectar `fetch_posts` y `fetch_metrics` de Meta a la ingesta de posts propios (hoy solo Post for Me) y añadir métricas de la Página. Así las analíticas, la voz y el agente funcionan con Facebook sin Post for Me.
- **Entregable:** una cuenta de Facebook conectada llena `posts` y `metric_snapshots`.
- **Verificación:** tests con transporte simulado; las reglas de borrados sospechosos de `ingest_passes` se cumplen igual; ninguna petición real en los tests.

### R4. Publicar medios, programar, editar y borrar (CONNECT, 4-6 h)
Ampliar `PublishDraft` con medios, y añadir las interfaces de programar y de editar y borrar. Todo con `dry_run`, `confirm` e idempotencia.
- **Entregable:** rutas REST y botón en Publish; banderas `META_MEDIA_ENABLED`, `META_MANAGE_POSTS_ENABLED` apagadas por defecto.
- **Verificación:** con la bandera apagada la acción responde error tipado y no sale ninguna petición; con ella encendida, solo con transporte simulado; permiso explícito de Christian antes de cualquier prueba real.

### R5. Comentarios (CONNECT, 4 h)
Interfaz de comentarios (listar, responder, ocultar, borrar) para Meta, y bandera `META_COMMENTS_ENABLED`. Las escrituras exigen confirmación.
- **Entregable:** rutas y límite de ritmo por usuario.
- **Verificación:** el test de matriz de capacidades incluye comentarios; responder sin `confirm` falla.

### R6. Capa del agente, sin saber de Meta (INTELLIGENCE, 4-6 h)
Herramientas por acción que reciben `platform` (D5), con respuesta tipada cuando la red no la soporta, y reglas del prompt que obliguen a decir la verdad sobre lo que no se puede (como la regla 14 sobre escaneos). Las escrituras pasan por el patrón de escritura pendiente (D6).
- **Entregable:** herramientas registradas y un caso nuevo en la evaluación `golden` por acción.
- **Verificación:** `ai_eval --suite golden`; con una red que no soporta la acción, el agente lo dice y no inventa un resultado. **Ojo con el presupuesto de tokens:** cada herramienta nueva suma al prompt (hoy ~3.600 tokens de herramientas contra el tope de 8.000 por minuto de Groq); medir antes y después y filtrar por clase de turno.

### R7. El resto de servicios (CONNECT, por servicio)
- **LinkedIn:** paridad con las interfaces nuevas. Leer posts exige `r_member_social`, restringido (ver `docs/CONEXIONES.md`): declara `can_read_posts=False` y el agente lo explica.
- **YouTube:** proveedor nuevo `youtube` sobre el cliente OAuth de Google (`GOOGLE_OAUTH_CLIENT_ID` y `GOOGLE_OAUTH_CLIENT_SECRET`, otros permisos). Hoy `google` solo cubre Drive y Docs por MCP; YouTube es un adaptador aparte con sus propias capacidades (subir video, listar, métricas). Sin R2 no se empieza.
- **Instagram:** decisión de la sección 6: por Meta directo (`instagram.py`) o solo por Post for Me.
- **Verificación:** el test de matriz de capacidades incluye al proveedor nuevo.

### R8. Cierre (ARCHITECT)
Actualizar `AGENTS.md`, `flow-map.md`, `flow-map.html`, `SCHEMA.md` (si cambió algo), `API_KEYS.md` (variables nuevas) y `.env.example`. Revisión de seguridad de las rutas de escritura nuevas.
- **Verificación:** suite completa en verde (salvo los fallos conocidos de Windows) y `ruff` limpio.

## 5. Dependencias

R0 y R1 primero y en paralelo. R2 antes que todo lo demás. R3 puede ir ya después de R2 y es la que da valor más rápido. R4 y R5 son independientes entre sí. R6 espera a la acción que envuelva. R7 espera a R2 y a la decisión de Instagram.

## 6. Decisiones que necesito de Christian

1. **¿Qué se construye primero?** Recomendación: R3 (leer), porque desbloquea analíticas y agente con Facebook sin pagar nada; después comentarios (R5) y medios (R4).
2. **Instagram:** ¿directo por la API de Meta o solo por Post for Me? Recomendación: solo Post for Me por ahora; Instagram directo es otra superficie con su propia revisión.
3. **Messenger, anuncios, Threads, WhatsApp:** ¿fuera de alcance? Recomendación: sí, hasta que haya un caso de uso concreto.
4. **YouTube:** ¿cuándo? Recomendación: después de R2, como proveedor nuevo y sin tocar el agente.
5. **Banderas por defecto:** ¿las escrituras nuevas arrancan apagadas? Recomendación: sí, todas apagadas, como `X_LIVE_ENABLED`.

## 7. Riesgos

- **Presupuesto de tokens.** Más herramientas empujan el prompt contra el tope de Groq; ya hubo 503 por eso. R6 mide y filtra.
- **App Review.** Solo se necesita para abrir la app a usuarios sin rol. No bloquea el desarrollo con la cuenta de Christian.
- **Datos de la API sin verificar.** Los permisos de la sección 3 vienen de conocimiento general. R1 los revalida.
- **Escrituras públicas.** Publicar, borrar o responder son visibles. Por eso D6 y banderas apagadas por defecto.
- **Cuentas ya conectadas** con menos permisos: pasan a "necesita reconectar" (D7), no a fallar.
