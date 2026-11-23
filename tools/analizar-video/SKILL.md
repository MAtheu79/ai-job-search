---
name: analizar-video
description: Analiza un vídeo (enlace o archivo local) y devuelve en español un resumen con marcas de tiempo. Usa el plugin Watch con Gemini, rota entre modelos de Gemini si alguno está saturado (503/429) y, si todos fallan, cae a hojas de contacto de fotogramas leídas por Claude (incluidos subtítulos incrustados). Úsalo cuando el usuario pida resumir, analizar, ver o explicar un vídeo, o pregunte "qué pasa en este vídeo".
allowed-tools: Bash, Read
---

# analizar-video

## Requisitos
- Plugin Watch instalado (`claude plugin marketplace add bradautomates/claude-video` y `claude plugin install watch@claude-video`).
- `GEMINI_API_KEY` en el entorno o en `~/.config/watch/.env`.
- `ffmpeg`/`ffprobe` para el plan B. `yt-dlp` solo para enlaces que no sean de YouTube en el plan B.

## Flujo
1. Separa la fuente (URL o ruta) de la pregunta del usuario. Si no hay pregunta, usa:
   "Resume el vídeo en español con marcas de tiempo: qué se ve y qué se dice en cada parte, y cuál es el mensaje principal."
2. Ejecuta:
   ```bash
   bash "${SKILL_DIR}/analizar-video.sh" "<fuente>" "<pregunta>"
   ```
3. Interpreta la salida:
   - **Exit 0, informe con `## Answer (from Gemini)`**: transmite la respuesta de Gemini con sus marcas de tiempo, aclarando que la vio Gemini.
   - **Exit 10, `PLAN_B` con rutas `SHEET:`**: Gemini no estaba disponible. Lee cada hoja con Read (cada celda lleva su marca de tiempo en amarillo). Si hay subtítulos incrustados, tradúcelos: suelen ser la narración. Indica al usuario que el resumen sale de los fotogramas y que el audio no se escuchó.
   - **Otro exit**: informa del error tal cual y ofrece reintentar más tarde.
4. Formato de respuesta (español):
   - Una línea con qué es el vídeo (duración, formato y tema).
   - Una tabla `| Tiempo | Qué se ve | Qué se dice |`.
   - **Mensaje principal** en una o dos frases.
   - Si el contenido hace promesas (dinero, salud, resultados), añade una advertencia breve y objetiva.

## Notas
- No subas a Gemini vídeos que el usuario diga que son privados. En ese caso usa directamente `ANALIZAR_SOLO_LOCAL=1`.
- `ANALIZAR_MODELOS="m1 m2 ..."` sustituye la lista de modelos que se prueban.
- Los archivos temporales van a `$ANALIZAR_OUT` (por defecto `/tmp/analizar-video`).
