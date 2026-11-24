"""Convierte subtítulos .vtt (incluidos los automáticos de YouTube) en texto limpio con marcas [mm:ss]."""
import re
import sys

TIEMPO = re.compile(r"^(\d{2}:)?(\d{2}):(\d{2})\.\d{3} -->")
ETIQUETAS = re.compile(r"<[^>]+>")


def convertir(ruta, cada=15):
    bloques, actual, vistos = [], None, set()
    with open(ruta, encoding="utf-8", errors="replace") as f:
        for linea in f:
            linea = linea.strip()
            m = TIEMPO.match(linea)
            if m:
                h = int((m.group(1) or "0:")[:-1])
                actual = h * 3600 + int(m.group(2)) * 60 + int(m.group(3))
                continue
            if not linea or actual is None or linea.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
                continue
            texto = ETIQUETAS.sub("", linea).strip()
            if not texto or texto in vistos:
                continue
            vistos.add(texto)
            if not bloques or actual - bloques[-1][0] >= cada:
                bloques.append([actual, texto])
            else:
                bloques[-1][1] += " " + texto
    for seg, texto in bloques:
        print(f"[{seg // 60:02d}:{seg % 60:02d}] {texto}")


if __name__ == "__main__":
    convertir(sys.argv[1])
