# analizar-video

Resume cualquier vídeo (enlace o archivo) en español, con marcas de tiempo.

## Cómo funciona
1. **Plan A, Gemini:** envía el vídeo a Gemini a través del plugin Watch. Si un modelo está saturado (503) o al límite (429), prueba el siguiente.
2. **Plan B, local:** si fallan todos los modelos, genera hojas de fotogramas con la hora marcada para que Claude (o tú) las lea. El vídeo no sale de tu ordenador.

## Requisitos
- Plugin Watch para Claude Code:
  ```bash
  claude plugin marketplace add bradautomates/claude-video
  claude plugin install watch@claude-video
  ```
- `GEMINI_API_KEY` (gratis en https://aistudio.google.com/apikey), en el entorno o en `~/.config/watch/.env`.
- `ffmpeg` (plan B) y `yt-dlp` (solo para enlaces que no sean de YouTube en el plan B).
- Bash (en Windows: Git Bash o WSL).

## Uso
```bash
./analizar-video.sh "https://www.youtube.com/watch?v=XXXX"
./analizar-video.sh video.mp4 "¿Qué indicador usa y con qué ajustes?"
```

Opciones (variables de entorno):
- `ANALIZAR_SOLO_LOCAL=1`: no sube nada a Google (para vídeos privados).
- `ANALIZAR_MODELOS="gemini-3.8-flash gemini-3.5-flash"`: elige qué modelos probar.
- `ANALIZAR_OUT=/ruta`: carpeta para las hojas de fotogramas (por defecto `/tmp/analizar-video`).

Códigos de salida: `0` respuesta de Gemini, `10` plan B (hojas generadas), `2` archivo no encontrado, `3` fallo al descargar, `4` fallo de ffmpeg.

## Usarlo como skill de Claude Code
Copia la carpeta a `~/.claude/skills/analizar-video/` y Claude la usará cuando le pidas analizar un vídeo.

## Pendiente
- Probar con enlaces de YouTube y en macOS/Windows.
- Límite de hojas en vídeos muy largos.
- Guardar el resumen en un archivo.
- La lista de modelos de Gemini hay que actualizarla con el tiempo.
