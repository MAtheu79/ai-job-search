#!/usr/bin/env bash
# Uso: analizar.sh <url-o-ruta> [pregunta]
set -u
SRC="${1:?falta la fuente}"
Q="${2:-Resume el vídeo en español con marcas de tiempo: qué se ve y qué se dice en cada parte, y cuál es el mensaje principal.}"
OUT="${ANALIZAR_OUT:-/tmp/analizar-video}"; mkdir -p "$OUT"
MODELS="${ANALIZAR_MODELOS:-gemini-3.7-flash gemini-3.8-flash gemini-3.6-flash gemini-3.5-flash gemini-flash-latest gemini-3.1-pro-preview}"
WATCH=$(ls -d "$HOME"/.claude/plugins/cache/claude-video/watch/*/skills/watch 2>/dev/null | sort -V | tail -1)

# Plan A: Gemini mediante Watch, rotando modelos
if [ -z "${ANALIZAR_SOLO_LOCAL:-}" ] && [ -n "$WATCH" ]; then
  for m in $MODELS; do
    rep=$(WATCH_GEMINI_MODEL="$m" python3 "$WATCH/scripts/watch.py" "$SRC" --engine gemini --question "$Q" 2>&1)
    if grep -q "## Answer (from Gemini)" <<<"$rep"; then
      sed -n '/^# watch: video report/,$p' <<<"$rep"; exit 0
    fi
    echo "[analizar] $m falló: $(grep -oE 'HTTP [0-9]+: [^.]{0,80}' <<<"$rep" | head -1)" >&2
  done
elif [ -z "$WATCH" ]; then
  echo "[analizar] plugin Watch no encontrado; uso plan B" >&2
fi

# Plan B: hojas de contacto locales
MEDIA="$SRC"
if [[ "$SRC" =~ ^https?:// ]]; then
  command -v yt-dlp >/dev/null || { echo "[analizar] falta yt-dlp para descargar el enlace" >&2; exit 3; }
  yt-dlp -q -f 'mp4/best' -o "$OUT/video.%(ext)s" "$SRC" || exit 3
  MEDIA=$(ls "$OUT"/video.* | head -1)
fi
[ -f "$MEDIA" ] || { echo "[analizar] no existe: $MEDIA" >&2; exit 2; }
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$MEDIA")
FPS=$(python3 -c "d=float('$DUR');print(min(1.0, 60.0/d) if d>0 else 1)")
rm -f "$OUT"/sheet_*.jpg
ffmpeg -loglevel error -y -i "$MEDIA" -vf "fps=$FPS,scale=320:-2,drawtext=text='%{pts\:hms}':x=6:y=6:fontsize=22:fontcolor=yellow:box=1:boxcolor=black@0.6,tile=5x4" "$OUT/sheet_%d.jpg" || exit 4
echo "PLAN_B duracion=${DUR}s fps=$FPS"
ls "$OUT"/sheet_*.jpg | sed 's/^/SHEET: /'
exit 10
