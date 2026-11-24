#!/usr/bin/env bash
# Uso: analizar-video.sh <url-o-ruta> [pregunta]
#
# Plan A: Gemini (vía plugin Watch), rotando modelos si alguno está saturado.
# Plan C: solo enlaces. Texto del vídeo sin descargarlo: título, descripción,
#         capítulos y subtítulos (yt-dlp; si falla y hay FIRECRAWL_API_KEY, Firecrawl).
# Plan B: hojas de fotogramas con la hora marcada (ffmpeg).
#
# Salida: 0 = respuesta de Gemini; 10 = hojas de fotogramas (con o sin texto);
#         11 = solo texto (plan C); 2 = archivo no encontrado; 3 = nada disponible; 4 = fallo de ffmpeg.
set -u
SRC="${1:?falta la fuente}"
Q="${2:-Resume el vídeo en español con marcas de tiempo: qué se ve y qué se dice en cada parte, y cuál es el mensaje principal.}"
OUT="${ANALIZAR_OUT:-/tmp/analizar-video}"; mkdir -p "$OUT"
MODELS="${ANALIZAR_MODELOS:-gemini-3.7-flash gemini-3.8-flash gemini-3.6-flash gemini-3.5-flash gemini-flash-latest gemini-3.1-pro-preview}"
WATCH=$(ls -d "$HOME"/.claude/plugins/cache/claude-video/watch/*/skills/watch 2>/dev/null | sort -V | tail -1)
AQUI="$(cd "$(dirname "$0")" && pwd)"
ES_URL=0; [[ "$SRC" =~ ^https?:// ]] && ES_URL=1

# ---------- Plan A: Gemini ----------
if [ -z "${ANALIZAR_SOLO_LOCAL:-}" ] && [ -n "$WATCH" ]; then
  for m in $MODELS; do
    rep=$(WATCH_GEMINI_MODEL="$m" python3 "$WATCH/scripts/watch.py" "$SRC" --engine gemini --question "$Q" 2>&1)
    if grep -q "## Answer (from Gemini)" <<<"$rep"; then
      sed -n '/^# watch: video report/,$p' <<<"$rep"; exit 0
    fi
    echo "[analizar] $m falló: $(grep -oE 'HTTP [0-9]+: [^.]{0,80}' <<<"$rep" | head -1)" >&2
  done
elif [ -z "$WATCH" ]; then
  echo "[analizar] plugin Watch no encontrado; salto Gemini" >&2
fi

# ---------- Plan C: texto del vídeo (solo enlaces) ----------
TEXTO=0
if [ "$ES_URL" = 1 ]; then
  rm -f "$OUT"/subs.* "$OUT"/info.txt
  if command -v yt-dlp >/dev/null && yt-dlp -q --skip-download --no-warnings \
      --write-subs --write-auto-subs --sub-langs "es.*,en.*,orig" --sub-format vtt \
      --print-to-file "TITULO: %(title)s
CANAL: %(channel)s
DURACION: %(duration_string)s
FECHA: %(upload_date)s
DESCRIPCION:
%(description)s" "$OUT/info.txt" \
      -o "$OUT/subs.%(ext)s" "$SRC" 2>/dev/null; then
    echo "PLAN_C fuente=yt-dlp"
    cat "$OUT/info.txt"
    VTT=$(ls "$OUT"/subs.*.vtt 2>/dev/null | head -1)
    if [ -n "$VTT" ]; then
      echo; echo "TRANSCRIPCION ($(basename "$VTT")):"
      python3 -I "$AQUI/vtt_a_texto.py" "$VTT"
    else
      echo; echo "TRANSCRIPCION: no hay subtítulos"
    fi
    TEXTO=1
  elif [ -n "${FIRECRAWL_API_KEY:-}" ]; then
    resp=$(curl -s -X POST https://api.firecrawl.dev/v2/scrape \
      -H "Authorization: Bearer $FIRECRAWL_API_KEY" -H "Content-Type: application/json" \
      -d "$(python3 -c 'import json,sys;print(json.dumps({"url":sys.argv[1],"formats":["markdown"],"onlyMainContent":True}))' "$SRC")")
    md=$(python3 -c 'import json,sys;d=json.load(sys.stdin);print((d.get("data") or {}).get("markdown",""))' <<<"$resp" 2>/dev/null)
    if [ -n "$md" ]; then
      echo "PLAN_C fuente=firecrawl"; echo "$md"; TEXTO=1
    else
      echo "[analizar] Firecrawl no devolvió contenido" >&2
    fi
  else
    echo "[analizar] plan C no disponible (falta yt-dlp o no hay acceso; FIRECRAWL_API_KEY no definida)" >&2
  fi
fi

# ---------- Plan B: hojas de fotogramas ----------
MEDIA="$SRC"
if [ "$ES_URL" = 1 ]; then
  if [ -n "${ANALIZAR_SIN_FOTOGRAMAS:-}" ] || ! command -v yt-dlp >/dev/null \
     || ! yt-dlp -q --no-warnings -f 'mp4/best' -o "$OUT/video.%(ext)s" "$SRC" 2>/dev/null; then
    [ "$TEXTO" = 1 ] && exit 11
    echo "[analizar] no se pudo obtener ni el vídeo ni su texto" >&2; exit 3
  fi
  MEDIA=$(ls "$OUT"/video.* | head -1)
fi
[ -f "$MEDIA" ] || { echo "[analizar] no existe: $MEDIA" >&2; exit 2; }
DUR=$(ffprobe -v error -show_entries format=duration -of csv=p=0 "$MEDIA")
FPS=$(python3 -c "d=float('$DUR');print(min(1.0, 60.0/d) if d>0 else 1)")
rm -f "$OUT"/sheet_*.jpg
ffmpeg -loglevel error -y -i "$MEDIA" -vf "fps=$FPS,scale=320:-2,drawtext=text='%{pts\:hms}':x=6:y=6:fontsize=22:fontcolor=yellow:box=1:boxcolor=black@0.6,tile=5x4" "$OUT/sheet_%d.jpg" || exit 4
echo; echo "PLAN_B duracion=${DUR}s fps=$FPS"
ls "$OUT"/sheet_*.jpg | sed 's/^/SHEET: /'
exit 10
