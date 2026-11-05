# Análisis de video: comparación de APIs y propuesta (T10)

Fecha de la investigación: **2026-10-27**. Cada dato lleva la URL oficial de donde salió; lo que no pude verificar en una
página oficial está marcado **(sin verificar)**. Quien decide es Christian: nada de esto está activo ni cuesta nada hasta
que pegue `VIDEO_PROVIDER` y `VIDEO_API_KEY` en `lumi/.env`.

## Propuesta en 10 líneas (para decidir)

1. **Propongo Gemini API con `gemini-3.5-flash-lite`**, con una key de **plan de pago** (Cloud Billing activado).
2. Entiende imagen + audio + texto en pantalla en una sola llamada y devuelve JSON estructurado (`responseMimeType=application/json`).
3. Costo por video de 60 s: **≈ $0.008–0.013** (≈ $0.002 de entrada si se baja la resolución). Ver cálculo abajo.
4. Alternativa más barata: modular (ffmpeg + Whisper en Groq + visión en OpenRouter), ≈ $0.002–0.004 por 60 s, pero hay que construir y mantener cortes, ritmo y OCR nosotros.
5. Twelve Labs descartado por ahora: ≈ $0.029/min solo vía sobrecosto (solo plan Pro), y sus términos dan licencia de entrenamiento sobre los datos salvo opt-out.
6. **No usar el plan gratis de Gemini**: Google dice que en el plan gratis el contenido se usa para mejorar sus productos; en el de pago, no.
7. Riesgo: `generateContent` aparece como "Legacy" en la documentación de video; el adaptador es un solo archivo (`lumi_ai/video/gemini.py`) para migrarlo a la API Interactions sin tocar el resto.
8. Riesgo: los límites de tasa (RPM/RPD) solo se ven dentro de AI Studio; las cifras públicas que encontré son de terceros **(sin verificar)**.
9. Riesgo legal: no encontré cláusula de Google sobre analizar videos públicos de terceros; los términos de cada red (X, Instagram, TikTok) sobre descargar sus videos tampoco están revisados. Es decisión tuya.
10. Antes de activar: probar con ~5 videos reales (`manage.py check_keys --only video` no gasta; `analyze_video` sí gasta unos centavos) y revisar la calidad. Tope por corrida: `VIDEO_MAX_PER_RUN=5`.

**Estado de la implementación:** hecha y probada con respuestas grabadas (sin keys). Con `VIDEO_PROVIDER` vacío el pipeline de
competidores funciona exactamente igual que antes (hay un test que lo prueba).

## Tabla comparativa

| | **Gemini API** (propuesta) | **Twelve Labs** (Pegasus 1.5/1.6, Marengo) | **Modular** (ffmpeg + Groq Whisper + visión OpenRouter) |
|---|---|---|---|
| Qué entiende | Imagen, audio y texto en pantalla; salida JSON. Muestrea 1 fotograma/s y el audio a 32 tokens/s. [video-understanding](https://ai.google.dev/gemini-api/docs/generate-content/video-understanding) (act. 2026-10-13) | Pegasus: preguntas y JSON sobre el video (imagen + audio). Marengo: embeddings para búsqueda. [analyze](https://docs.twelvelabs.io/api-reference/analyze-videos/analyze.mdx) (2026-10-27) | Audio: transcripción exacta (Whisper). Imagen: solo los cuadros que extraemos; cortes y ritmo los calculamos nosotros con ffmpeg. [speech-to-text](https://console.groq.com/docs/speech-to-text) (2026-10-27) |
| Duración máx. | Contexto de 1M tokens: ≈ 57 min por defecto (290 tokens/s) y ≈ 2.8 h a resolución baja (98 tokens/s) **(cálculo mío, no cifra de la página)**. Para nosotros: tope por tamaño `VIDEO_MAX_MB` (20 MB por defecto). | Sync: 1 s a 1 h; async: hasta 2 h. URL pública ≤ 4 GB, subida local ≤ 200 MB. [analyze](https://docs.twelvelabs.io/api-reference/analyze-videos/analyze.mdx) (2026-10-27) | Sin límite propio; Groq limita el tamaño del audio por archivo **(cifra sin verificar hoy)** |
| Precio por minuto | 3.5 Flash-Lite: $0.30 / $2.50 por M tokens (entrada / salida). 3.8 Flash: $0.75 / $3.75 hasta 2026-12-31 y luego $1.50 / $7.50. [pricing](https://ai.google.dev/gemini-api/docs/pricing) (2026-10-27) | Pegasus 1.6 entrada de video: $1.75/h ≈ **$0.029/min**, y solo como sobrecosto del plan Pro (apagado por defecto). [overage](https://www.twelvelabs.io/overage) (2026-10-27) | Whisper turbo: $0.04/h (≈ $0.0007/min, mínimo facturable 10 s). [speech-to-text](https://console.groq.com/docs/speech-to-text). Visión: modelo de OpenRouter, ≈ $0.001–0.003 por 60 s **(estimado, depende del modelo)** |
| Plan gratis y qué hacen con tus datos | Existe, con límites bajos. **En el plan gratis el contenido se usa para mejorar productos; en el de pago, no.** [pricing](https://ai.google.dev/gemini-api/docs/pricing) (2026-10-27) | Free: 3 GB. Plus $29, Pro $99. Los términos dan licencia para usar tus datos para prestar, entrenar y mejorar el servicio **salvo opt-out en la cuenta**. [terms §4(a)](https://www.twelvelabs.io/legal/terms-of-use) (2026-10-27) | Groq: ver sus términos para cada plan **(sin verificar)**. Los modelos gratis de OpenRouter no son aptos para datos de terceros |
| Límites de tasa | Solo visibles en AI Studio. Terceros (2026-10-21, **sin verificar**): 3.8 Flash gratis 5 RPM / 20 RPD; 3.5 Flash-Lite gratis 10–15 RPM / 500 RPD | No verificado en página oficial | Whisper en Groq: según plan; el muro de ≈ 7000 tokens de Groq no afecta al audio |
| Latencia | Segundos a decenas de segundos por video corto **(no medida: sin key)** | Sync hasta 1 h (en la práctica segundos–minutos) **(no medida)** | Suma de 3 pasos (descarga, ffmpeg, Whisper, visión) **(no medida)** |
| Términos al analizar videos públicos de terceros | No hay cláusula específica en las páginas de precios/uso; hay que revisar los [términos de la API](https://ai.google.dev/gemini-api/terms) **(sin verificar)**. YouTube: solo videos públicos, en preview | Exige derechos legales sobre el contenido (§4(a)) | Igual que cualquier descarga: depende de los términos de cada red, no del proveedor |
| Estabilidad del SDK | El SDK está migrando a la API Interactions; `generateContent` figura como "Legacy". Por eso usamos REST con httpx, sin SDK | Hay SDK propio; versiones de modelo cambian (1.5 → 1.6) | Estable (cada pieza es simple), pero son tres integraciones |
| Esfuerzo de integración | **Bajo**: un POST. Hecho. | Medio: tareas asíncronas, índices y cuotas por plan | **Alto**: ffmpeg en el servidor, extracción de cuadros, detección de cortes, OCR |

### Cálculo del costo de un video de 60 s (Gemini)

- Entrada: 60 fotogramas × 258 tokens (resolución por defecto) = 15 480, más audio 60 × 32 = 1 920, más el prompt ≈ 600 → **≈ 18 000 tokens**. A resolución baja serían 66 tokens por fotograma → ≈ 6 500 tokens. [video-understanding](https://ai.google.dev/gemini-api/docs/generate-content/video-understanding)
- Salida: el JSON ocupa ≈ 300 tokens, pero con "thinking" se asumen **1 000–3 000**.
- **3.5 Flash-Lite**: entrada 18 000 × $0.30/M = $0.0054; salida 1–3 k × $2.50/M = $0.0025–0.0075 → **≈ $0.008–0.013**.
- **3.8 Flash**: 18 000 × $0.75/M = $0.0135 + 1–3 k × $3.75/M = $0.004–0.011 → **≈ $0.017–0.025** hasta 2026-12-31 y ≈ el doble desde 2027-01-01.
- **Twelve Labs**: 1 min × $1.75/60 = **≈ $0.029** (solo como sobrecosto del plan Pro).
- **Modular**: $0.0007 (Whisper) + visión ≈ $0.001–0.003 = **≈ $0.002–0.004**.

Con `VIDEO_MAX_PER_RUN=5`, una corrida de competidores cuesta como máximo ≈ 5 × $0.013 = **$0.065** con Flash-Lite, y los videos ya
analizados no se cobran otra vez (caché por URL de media y versión del prompt).

## Datos que contradicen lo que traía el orquestador, o entre páginas oficiales

- **Twelve Labs "nuevo billing desde 2026-10-15"**: la página de precios que leí dice que el nuevo esquema empieza el **2027-01-04**. Revisar antes de decidir.
- **Límite de URL externa en Gemini**: una página dice 15 MB y la de Interactions dice 100 MB. Por eso descargamos el video nosotros (≤ `VIDEO_MAX_MB`) y lo mandamos en línea, salvo links de YouTube. [file-input-methods](https://ai.google.dev/gemini-api/docs/generate-content/file-input-methods)
- **Tokens por segundo**: la página oficial da 66 / 258 tokens por fotograma + 32/s de audio, es decir ≈ 100 y ≈ 300 tokens/s: coincide con lo que traía el orquestador.
- **File API de 2 GB gratis**: confirmado (20 GB de pago) en la misma página; no lo usamos porque limitamos a 20 MB.
- **Precios de 3.8 Flash**: duplican el 2027-01-01. Flash-Lite no tiene aviso de cambio.
- **Id del modelo**: `gemini-3.5-flash-lite` existe en la lista oficial (act. 2026-10-22, https://ai.google.dev/gemini-api/docs/models). Hay modelos más nuevos (3.8 Flash, 4 Argon); se cambia con `VIDEO_MODEL`.

## Qué se implementó (sin activar)

- Puerto `VideoAnalyzer` / `VideoAnalysis` (`lumi_ai/ports.py`) y puerto de caché `VideoAnalysisStore` (PORTS_VERSION 1.10).
- Adaptador Gemini (`lumi_ai/video/gemini.py`), descarga segura (`fetch.py`: solo http(s), solo IPs públicas también tras redirecciones, tope de bytes, tipo de contenido de video).
- `fake.py` (solo tests; la fábrica nunca lo construye).
- Caché en `video_analysis_records` por (media, proveedor, versión del prompt); un fallo se guarda con su motivo y nunca reemplaza un éxito.
- El pipeline de competidores analiza los videos de los posts que va a etiquetar y pasa la lectura como campo extra al etiquetado ciego (sin vistas ni URL).
  Se lee un video por post como máximo, con tope `VIDEO_MAX_PER_RUN`; lo que se omite o falla sale en `video_notes`, nunca en silencio.
- Tool `analyze_video(url)` para un link que el usuario pegó; no existe en el registro mientras el video esté apagado.
- Probe `video` en `check_keys`: consulta `GET /models/{VIDEO_MODEL}` (gratis, no analiza nada).

## Variables de entorno

```
VIDEO_PROVIDER=            # vacío = apagado. Valor soportado: gemini
VIDEO_API_KEY=             # key de Google AI Studio con facturación activada
VIDEO_MODEL=gemini-3.5-flash-lite
VIDEO_MAX_MB=20            # videos más grandes se omiten (no se recortan)
VIDEO_MAX_PER_RUN=5        # análisis nuevos por corrida del pipeline
```

## Qué falta y quién lo decide

- **Christian**: elegir proveedor, crear la key de pago, aprobar el gasto, y revisar los términos de X/Instagram/TikTok y de Google para videos de terceros.
- **CONNECT**: entregar `PostIn.media` con URL de video descargable (los de X vienen sin tipo: `kind=None`; se aceptan solo si la URL parece de video). Las URL firmadas de CDN caducan: hay que analizarlas pronto tras traerlas.
- **ARCHITECT**: `post_media.kind` es NOT NULL y `MediaRef.kind` puede ser `None`; hasta que cambie, los videos sin tipo no llegan a la tabla y por tanto no se cachean (se vuelven a analizar y se cobran de nuevo).
