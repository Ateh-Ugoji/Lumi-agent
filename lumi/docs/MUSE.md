# Muse (Meta Model API)

Este documento es para un agente futuro que integre Muse en Lumi. Hoy no hay código de Muse en el repo, ni variables en `.env.example`, ni sonda en `check_keys`. Todo lo de abajo se leyó el 2026-10-27 en la documentación oficial de Meta (https://dev.meta.ai). Lo que no pude confirmar dice "sin verificar".

## Qué es

"Muse" no aparece en el repo ni en su historia. La lectura más probable es la Meta Model API, la API de inferencia de Meta, que sirve la familia Muse. Confírmalo con Christian antes de construir nada (pregunta 1 al final).

| Modelo | Para qué sirve | Fuente |
|---|---|---|
| `muse-spark-1.3`, `1.2`, `1.1` | Texto y agentes, con razonamiento y herramientas. Entrada de texto, imagen, video, audio y PDF. Salida de texto | https://dev.meta.ai/docs/models |
| `muse-spark-1.3-contributor`, `1.2-contributor` | Los mismos modelos más baratos, a cambio de que Meta use tus datos para entrenar | https://dev.meta.ai/docs/pricing-rate-limits |
| `muse-wonder-1.0` | El modelo más capaz, en preview. Solo modo estándar | https://dev.meta.ai/docs/models |
| `muse-image-1.0` | Genera y edita imágenes | https://dev.meta.ai/docs/image-generation |
| `muse-voice-transcribe-1.0` | Voz a texto | https://dev.meta.ai/docs/overview |
| `sam-3.1` | Segmentación de imagen y video | https://dev.meta.ai/docs/models |

Muse Spark Open y Muse Glimmer son modelos de pesos abiertos para correr en hardware propio. No pasan por la API y no entran en este plan.

## Cómo se accede

- Alta en el sitio de Model API con "Start building". Hace falta ser mayor de 18 años y estar en una región soportada. Se puede entrar con correo, móvil, Facebook, Google o GitHub. Después hay que añadir un método de pago y crear una key. Fuente: https://dev.meta.ai/help/accounts-and-login/sign-up (2026-10-27).
- Key en el panel, pestaña API keys, "Create API key". Se ve una sola vez y empieza con `LLM_`. Fuente: https://dev.meta.ai/docs/authentication.
- URL base `https://api.meta.ai/v1`, cabecera `Authorization: Bearer $MODEL_API_KEY`. Los SDK de OpenAI y Anthropic no leen `MODEL_API_KEY` solos, hay que pasar la key al crear el cliente. Fuente: https://dev.meta.ai/docs/authentication.
- Protocolos: Responses API (la recomendada), Chat Completions y Messages estilo Anthropic. El SDK `openai` funciona cambiando `base_url`. Fuente: https://dev.meta.ai/docs/quickstart.
- Regiones: el acceso depende del país. La política (actualizada el 2026-10-12) lista territorios restringidos, entre ellos China continental con Hong Kong y Macao, Rusia, Irán, Cuba y Corea del Norte. Muse Image no está disponible en India. Muse Wonder no está disponible en Corea del Sur. Fuentes: https://dev.meta.ai/legal/geographic-use-policy y https://dev.meta.ai/docs/models. La política dice que Meta puede cambiar la disponibilidad en cualquier momento, y que ese recurso no garantiza acceso. Comprueba el país de Christian y el de la región de Railway antes de contar con esto.

## Variables de entorno propuestas

Solo nombres. No se añaden al `.env.example` ni a `check_keys` hasta que se decida integrar.

| Variable | Uso |
|---|---|
| `MODEL_API_KEY` | Nombre que usa Meta en sus docs. Alternativa: `META_MODEL_API_KEY`, que se distingue mejor de las otras keys de Lumi |
| `MUSE_BASE_URL` | Por defecto `https://api.meta.ai/v1` |
| `MUSE_TEXT_MODEL` | Por ejemplo `muse-spark-1.3` |
| `MUSE_IMAGE_MODEL` | `muse-image-1.0` |
| `MUSE_MAX_IMAGES_PER_DAY` | Tope de gasto propio. Meta no ofrece un tope duro en lo que leí (sin verificar) |

## Capacidades que importan a Lumi

- Ventana de contexto de 1,048,576 tokens en Spark y Wonder. Fuente: https://dev.meta.ai/docs/overview.
- Llamadas a herramientas, incluidas llamadas en paralelo. Con la Responses API se conserva el razonamiento entre turnos. Fuente: https://dev.meta.ai/docs/tool-calling.
- Salida estructurada con `response_format` de tipo `json_schema` en Chat Completions, o `text.format` en Responses. La decodificación queda restringida al esquema. Los esquemas recursivos devuelven HTTP 400. Fuente: https://dev.meta.ai/docs/structured-output.
- Búsqueda web integrada con la herramienta `web_search`, a $2.50 por 1,000 consultas además de los tokens. Fuente: https://dev.meta.ai/docs/pricing-rate-limits.
- Multimodal: Spark y Wonder reciben imagen, video, audio y PDF y devuelven texto. Muse Image recibe texto e imagen y devuelve imagen. Fuente: https://dev.meta.ai/docs/models.
- Muse Image: endpoints `/v1/images/generations` y `/v1/images/edits`, compatibles con la API de imágenes de OpenAI, y edición por turnos con la Responses API. Parámetros `size` (relación de aspecto, no píxeles exactos), `reasoning_strength` (`high` por defecto, `low` más rápido), `response_format` (`b64_json` por defecto, o `url` firmada y temporal) y `output_format` (`webp`, `png`, `jpeg`). La búsqueda web va integrada y pasar la herramienta `web_search` da error. Fuente: https://dev.meta.ai/docs/image-generation.
- Voz a texto: `POST /v1/asr/transcribe` y `wss://api.meta.ai/v1/asr/realtime`. Fuente: https://dev.meta.ai/docs/overview.
- Video como salida (Muse Video): el anuncio del 2026-07-07 lo menciona, pero no encontré un endpoint en la documentación. Sin verificar. Anuncio: https://ai.meta.com/blog/introducing-muse-image-muse-video-msl/.

## Precios y límites

Pago por uso, sin mínimos. Fuente: https://dev.meta.ai/docs/pricing-rate-limits (2026-10-27).

| Concepto | Precio |
|---|---|
| Muse Spark estándar | entrada $1.25, entrada en caché $0.15, salida $4.25 por millón de tokens |
| Muse Spark contributor | entrada $0.10, caché $0.002, salida $0.20 por millón de tokens |
| Muse Wonder | entrada $4.00, caché $0.20, salida $20.00 por millón de tokens |
| Muse Image | $0.01 por imagen generada. Solo cobran las que salen bien. La búsqueda integrada va incluida |
| Muse Voice Transcribe | $0.18 por hora de audio |
| SAM 3.1 | $2.50 por 1,000 imágenes, $0.20 por 1,000 fotogramas de video |
| Búsqueda web en modelos de texto | $2.50 por 1,000 consultas |

Límites por equipo, no por key: Spark estándar y Wonder 3,000 solicitudes por minuto y 4M tokens por minuto. Los modelos contributor 150 solicitudes por minuto. `muse-image-1.0` 150 solicitudes por minuto. Voz: 256 flujos simultáneos y 16,000 por hora.

Plan gratis: no encontré ninguno ni créditos de bienvenida, y el alta pide un método de pago. Sin verificar. Asume que el primer uso cuesta dinero.

## Términos que afectan a Lumi

- En modo estándar Meta no entrena con tus datos. En modo contributor sí lo hace con los prompts, archivos y respuestas. Lumi procesa publicaciones y datos de cuentas de redes de personas. Usa solo modo estándar, salvo que Christian acepte lo contrario por escrito. Fuente: https://dev.meta.ai/docs/pricing-rate-limits.
- Hay que cumplir la política geográfica también para los usuarios finales de Lumi, no solo para el servidor. Fuente: https://dev.meta.ai/legal/geographic-use-policy.
- No leí los Terms of Service completos ni la política de uso aceptable. Revísalos antes de publicar contenido generado a nombre de un usuario. Sin verificar.

## Dónde encajaría en Lumi

1. Como proveedor de texto más en `lumi_ai/providers/` (INTELLIGENCE). La fábrica ya construye clientes `AsyncOpenAI` con `base_url`, así que Muse entraría con una entrada más en `build_provider_specs`, una constante de URL en `urls.py` y los campos nuevos en `AIConfig`. El orden en la cadena de fallback es una decisión de producto.
2. Como generador de imágenes para las publicaciones. Sería un puerto nuevo en `lumi_ai/ports.py`, por ejemplo `ImageGenerator`, y un cliente propio. Hoy no hay generación de imágenes en Lumi.
3. Como transcripción de voz, alternativa a Groq Whisper. Ya existe `lumi_ai/providers/audio.py`.

En CONNECT no cambia nada: Muse no es una red social ni un conector OAuth. Solo habría que registrar la sonda en `check_keys` y documentar la key en `API_KEYS.md`.

## Plan de integración

1. Christian confirma que "Muse" es la Meta Model API, su país y si acepta el gasto por uso.
2. Christian crea la cuenta, añade el pago y crea una key (pasos en la sección de alta).
3. INTELLIGENCE añade `MODEL_API_KEY` o `META_MODEL_API_KEY` a `AIConfig` y la entrada en `build_provider_specs`. Prueba con `httpx.MockTransport` o un cliente falso, sin red.
4. Si hay imágenes, se define el puerto y un cliente con tope diario (`MUSE_MAX_IMAGES_PER_DAY`), `dry_run` y un contador de coste por ejecución, igual que el presupuesto de Xpoz.
5. Sonda en `check_keys`. Una lectura de la lista de modelos sería gratis, pero no verifiqué que ese endpoint exista (sin verificar). Si no existe, la sonda solo comprueba el formato `LLM_...` y no gasta.
6. Pruebas con marca `live`, una sola llamada corta de texto y una imagen, nunca en bucle.
7. Documentar en `API_KEYS.md` y `CONEXIONES.md`.

## Riesgos

- Coste desde la primera imagen y sin plan gratis que yo haya visto.
- Disponibilidad por país que puede cambiar sin aviso.
- Muse Wonder está en preview y Muse Image limita a 150 solicitudes por minuto.
- El modo contributor envía datos a entrenamiento. No usarlo con datos de usuarios.
- Los nombres y versiones de modelos cambian rápido (Spark ya va en 1.3). Fija la versión en una variable y no en el código.

## Preguntas abiertas para Christian

1. ¿"Muse" es la Meta Model API (Muse Spark, Muse Image)? No hay ninguna otra pista en el repo.
2. ¿Para qué lo quieres: texto del agente, imágenes para publicaciones, voz o varios?
3. ¿Aceptas pagar por uso, y con qué tope mensual?
4. ¿En qué país estás y dónde se despliega Railway?
5. ¿Alguna vez aceptarías el modo contributor? Mi recomendación es que no.
