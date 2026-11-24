#!/usr/bin/env python3
"""Candlestick tools for trader-candles: pattern detection and a candlestick
chart with the trade plan drawn on it. Standard library only. Reads the same
free Yahoo chart JSON as the other trader-* tools. It never places an order.

    python3 candles.py patterns TSLA                     # patterns in today's 5-minute candles
    python3 candles.py patterns TSLA --interval 1d       # daily candles, last ~6 months
    python3 candles.py patterns TSLA --date 2026-10-19 --last 10
    python3 candles.py confirm TSLA --at 10:15           # does the candle at 10:15 confirm a long?
    python3 candles.py scan                              # last closed candle of every trader/watchlist.json hit
    python3 candles.py scan --tickers TSLA,NVDA --interval 1d --write
    python3 candles.py chart TSLA                        # trader/chart-TSLA.html, with trader/plan.json on it

Common flags: --interval 1m|2m|5m|15m|30m|60m|1d|1wk (default 5m; scan
defaults to 1d), --offline FILE|DIR (a saved Yahoo chart JSON, .json or
.json.gz, or a folder of <TICKER>.json), --json, --now "YYYY-MM-DD HH:MM"
(New York time, to replay a day: candles after it are ignored).

Patterns (each needs the trend before it where the textbook does; the trend
is the last 5 closes against their average):
  1 candle   doji, dragonfly doji, gravestone doji, spinning top, hammer,
             hanging man, inverted hammer, shooting star, marubozu
  2 candles  engulfing, harami, piercing line, dark cloud cover, tweezers
  3 candles  morning star, evening star, three white soldiers,
             three black crows, three inside up / down
Strength 1-3 is the textbook reliability, not a probability. A pattern is a
hint about the next few candles, never a guarantee: check it with
/trader-timemachine before you risk money.

Only CLOSED candles count: a candle that is still forming is drawn on the
chart but never read as a pattern.

Exit codes: patterns/scan/chart 0 = ok, 1 = error. confirm 0 = a bullish
pattern confirms, 2 = a bearish pattern warns against the long, 3 = nothing.
"""

import argparse
import datetime
import gzip
import html
import json
import os
import sys
import time
import urllib.error
import urllib.request

UA = "Mozilla/5.0 (compatible; day-trader-skill/2.0; +https://github.com/Jakeschincariol/day-trader-skill)"
HOSTS = ("query2", "query1")
BACKOFF = 5.0
INTERVALS = {"1m": 60, "2m": 120, "5m": 300, "15m": 900, "30m": 1800, "60m": 3600,
             "1d": 86400, "1wk": 7 * 86400}
DEFAULT_RANGE = {"1m": "5d", "2m": "5d", "5m": "5d", "15m": "1mo", "30m": "1mo", "60m": "3mo",
                 "1d": "6mo", "1wk": "2y"}
TREND_BARS = 5
AVG_BARS = 10
NOTE = ("Los patrones de velas son pistas, no señales que ganen solas. "
        "El day trading hace perder dinero a la mayoría de la gente.")


class CandleError(Exception):
    pass


# ---------------------------------------------------------------- time (New York)

def _nth_sunday(year, month, n):
    d = datetime.date(year, month, 1)
    d += datetime.timedelta(days=(6 - d.weekday()) % 7)
    return d + datetime.timedelta(weeks=n - 1)


def eastern_offset(utc):
    """-4 in daylight time, -5 otherwise (US rule since 2007)."""
    y = utc.year
    start = datetime.datetime.combine(_nth_sunday(y, 3, 2), datetime.time(7, 0))
    end = datetime.datetime.combine(_nth_sunday(y, 11, 1), datetime.time(6, 0))
    return -4 if start <= utc.replace(tzinfo=None) < end else -5


def ny(ts):
    utc = datetime.datetime(1970, 1, 1) + datetime.timedelta(seconds=int(ts))
    return utc + datetime.timedelta(hours=eastern_offset(utc))


def ny_to_ts(local):
    for off in (-4, -5):
        utc = local - datetime.timedelta(hours=off)
        if eastern_offset(utc) == off:
            return int((utc - datetime.datetime(1970, 1, 1)).total_seconds())
    return int((local + datetime.timedelta(hours=5) - datetime.datetime(1970, 1, 1)).total_seconds())


def now_ts():
    return int(time.time())


def parse_now(text):
    try:
        return ny_to_ts(datetime.datetime.strptime(text.strip(), "%Y-%m-%d %H:%M"))
    except ValueError:
        raise CandleError('--now wants "YYYY-MM-DD HH:MM" in New York time, not %r' % text)


def intraday(interval):
    return INTERVALS[interval] < 86400


def label(ts, interval):
    d = ny(ts)
    return d.strftime("%Y-%m-%d %H:%M") if intraday(interval) else d.strftime("%Y-%m-%d")


# ---------------------------------------------------------------- data

EXCHANGE_SUFFIXES = {"MC", "L", "DE", "F", "PA", "AS", "MI", "BR", "LS", "SW", "ST", "OL", "CO", "HE", "VI", "IR",
                     "TO", "V", "NE", "MX", "SA", "BA", "SN", "AX", "NZ", "HK", "T", "KS", "KQ", "SS", "SZ", "TW",
                     "SI", "NS", "BO", "JK", "BK", "KL", "TA", "JO", "IS", "WA", "PR", "AT"}


def yahoo_symbol(sym):
    """BRK.B -> BRK-B (a share class), but SAN.MC / VOD.L keep the exchange suffix."""
    sym = sym.upper()
    if "." in sym and sym.rsplit(".", 1)[1] not in EXCHANGE_SUFFIXES:
        return sym.replace(".", "-")
    return sym


def _open_url(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", "replace")


def yahoo_get(path):
    last = "no answer"
    for host in HOSTS:
        url = "https://%s.finance.yahoo.com%s" % (host, path)
        for attempt in (0, 1):
            try:
                return _open_url(url)
            except urllib.error.HTTPError as e:
                code = e.code
                body = None
                try:
                    if code == 404:
                        body = e.read().decode("utf-8", "replace")
                except Exception:
                    body = None
                finally:
                    e.close()
                if code == 404:
                    if body:
                        return body
                    raise CandleError("Yahoo has no chart at %s (HTTP 404)" % url.split("?")[0])
                last = "HTTP %d" % code
                if code == 429 and attempt == 0:
                    time.sleep(BACKOFF)
                    continue
                if code == 429 or code >= 500:
                    break
                raise CandleError("Yahoo answered HTTP %d for %s" % (code, url.split("?")[0]))
            except urllib.error.URLError as e:
                last = "could not connect: %s" % (e.reason,)
                break
            except OSError as e:
                last = "network error: %s" % (e,)
                break
    raise CandleError("Yahoo did not answer (%s on query2 and query1): wait a minute and try again" % last)


def parse_chart(text, sym):
    try:
        data = json.loads(text)
        res = data["chart"]["result"]
    except (ValueError, KeyError, TypeError):
        raise CandleError("Yahoo returned something unexpected for %s" % sym)
    if not res:
        err = (data.get("chart") or {}).get("error") or {}
        raise CandleError("Yahoo has no data for %s: %s" % (sym, err.get("description") or "unknown ticker"))
    r = res[0] or {}
    meta = r.get("meta") or {}
    q = ((r.get("indicators") or {}).get("quote") or [{}])[0] or {}

    def at(key, i):
        arr = q.get(key) or []
        return arr[i] if i < len(arr) else None

    bars = []
    for i, t in enumerate(r.get("timestamp") or []):
        c = at("close", i)
        if t is None or c is None:
            continue
        o, h, lo = at("open", i), at("high", i), at("low", i)
        o = float(c if o is None else o)
        h = float(c if h is None else h)
        lo = float(c if lo is None else lo)
        bars.append({"t": int(t), "o": o, "h": max(h, o, c), "l": min(lo, o, c), "c": float(c),
                     "v": int(at("volume", i) or 0)})
    return {"symbol": str(meta.get("symbol") or sym).upper(), "meta": meta, "bars": bars}


def read_text(path):
    if path.endswith(".gz"):
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            return fh.read()
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def offline_file(path, sym):
    if os.path.isdir(path):
        for name in (sym, yahoo_symbol(sym)):
            for ext in (".json", ".json.gz"):
                p = os.path.join(path, name + ext)
                if os.path.exists(p):
                    return p
        raise CandleError("no offline file for %s in %s (want %s.json)" % (sym, path, sym))
    if not os.path.exists(path):
        raise CandleError("no offline file %s" % path)
    return path


def get_chart(sym, interval, rng=None, offline=None):
    sym = sym.upper()
    if interval not in INTERVALS:
        raise CandleError("--interval wants one of %s" % ", ".join(INTERVALS))
    if offline:
        f = offline_file(offline, sym)
        try:
            text = read_text(f)
        except (OSError, ValueError) as e:
            raise CandleError("could not read %s: %s" % (f, e))
    else:
        text = yahoo_get("/v8/finance/chart/%s?range=%s&interval=%s"
                         % (yahoo_symbol(sym), rng or DEFAULT_RANGE[interval], interval))
    ch = parse_chart(text, sym)
    gran = {"1h": "60m"}.get(ch["meta"].get("dataGranularity"), ch["meta"].get("dataGranularity"))
    if offline and gran and gran in INTERVALS and gran != interval:
        interval = gran          # a saved file knows its own candle size
    elif gran and gran != interval:
        raise CandleError("%s has %s candles, not %s" % (sym, gran, interval))
    ch["interval"] = interval
    ch["crypto"] = str(ch["meta"].get("instrumentType") or "").upper() == "CRYPTOCURRENCY"
    return ch


def closed_bars(bars, interval, now, round_the_clock=False):
    """Split into closed candles and the one still forming (if any). Crypto
    trades 24/7, so its candles simply close after their own length."""
    step = INTERVALS[interval]
    if not intraday(interval) and not round_the_clock:
        # a daily candle is closed once its session is over (4:00 p.m. New York)
        out, forming = [], None
        for b in bars:
            d = ny(b["t"]).date()
            close_ts = ny_to_ts(datetime.datetime.combine(d, datetime.time(16, 0)))
            if interval == "1wk":
                close_ts += 4 * 86400
            if close_ts <= now:
                out.append(b)
            elif b["t"] <= now:
                forming = b
        return out, forming
    out = [b for b in bars if b["t"] + step <= now]
    forming = next((b for b in bars if b["t"] <= now < b["t"] + step), None)
    return out, forming


# ---------------------------------------------------------------- patterns

def _geo(b):
    body = abs(b["c"] - b["o"])
    rng = b["h"] - b["l"]
    return {"body": body, "range": rng, "upper": b["h"] - max(b["o"], b["c"]),
            "lower": min(b["o"], b["c"]) - b["l"], "green": b["c"] > b["o"], "red": b["c"] < b["o"],
            "top": max(b["o"], b["c"]), "bottom": min(b["o"], b["c"]), "mid": (b["o"] + b["c"]) / 2.0}


def trend_before(bars, i):
    """'up', 'down' or None for the candles that end just before index i."""
    if i < TREND_BARS:
        return None
    closes = [b["c"] for b in bars[i - TREND_BARS:i]]
    avg = sum(closes) / len(closes)
    last, first = closes[-1], closes[0]
    if last < avg and last < first:
        return "down"
    if last > avg and last > first:
        return "up"
    return None


def avg_body(bars, i):
    seg = bars[max(0, i - AVG_BARS):i] or bars[:1]
    return sum(abs(b["c"] - b["o"]) for b in seg) / len(seg)


PATTERNS = {
    # key: (English, Spanish, direction, candles, strength)
    "doji": ("Doji", "Doji", "neutral", 1, 1),
    "dragonfly_doji": ("Dragonfly doji", "Doji libélula", "bullish", 1, 1),
    "gravestone_doji": ("Gravestone doji", "Doji lápida", "bearish", 1, 1),
    "spinning_top": ("Spinning top", "Peonza", "neutral", 1, 1),
    "hammer": ("Hammer", "Martillo", "bullish", 1, 2),
    "hanging_man": ("Hanging man", "Hombre colgado", "bearish", 1, 1),
    "inverted_hammer": ("Inverted hammer", "Martillo invertido", "bullish", 1, 1),
    "shooting_star": ("Shooting star", "Estrella fugaz", "bearish", 1, 2),
    "bullish_marubozu": ("Bullish marubozu", "Marubozu alcista", "bullish", 1, 1),
    "bearish_marubozu": ("Bearish marubozu", "Marubozu bajista", "bearish", 1, 1),
    "bullish_engulfing": ("Bullish engulfing", "Envolvente alcista", "bullish", 2, 2),
    "bearish_engulfing": ("Bearish engulfing", "Envolvente bajista", "bearish", 2, 2),
    "bullish_harami": ("Bullish harami", "Harami alcista", "bullish", 2, 1),
    "bearish_harami": ("Bearish harami", "Harami bajista", "bearish", 2, 1),
    "piercing_line": ("Piercing line", "Línea penetrante", "bullish", 2, 2),
    "dark_cloud_cover": ("Dark cloud cover", "Cubierta de nube oscura", "bearish", 2, 2),
    "tweezer_bottom": ("Tweezer bottom", "Pinzas de suelo", "bullish", 2, 1),
    "tweezer_top": ("Tweezer top", "Pinzas de techo", "bearish", 2, 1),
    "morning_star": ("Morning star", "Estrella de la mañana", "bullish", 3, 3),
    "evening_star": ("Evening star", "Estrella de la tarde", "bearish", 3, 3),
    "three_white_soldiers": ("Three white soldiers", "Tres soldados blancos", "bullish", 3, 3),
    "three_black_crows": ("Three black crows", "Tres cuervos negros", "bearish", 3, 3),
    "three_inside_up": ("Three inside up", "Tres por dentro alcista", "bullish", 3, 2),
    "three_inside_down": ("Three inside down", "Tres por dentro bajista", "bearish", 3, 2),
}


def _single(b, g, trend, ab):
    out = []
    if g["range"] <= 0:
        return out
    r = g["range"]
    if g["body"] <= 0.1 * r:
        if g["upper"] <= 0.1 * r and g["lower"] >= 0.6 * r:
            out.append("dragonfly_doji" if trend == "down" else "doji")
        elif g["lower"] <= 0.1 * r and g["upper"] >= 0.6 * r:
            out.append("gravestone_doji" if trend == "up" else "doji")
        else:
            out.append("doji")
        return out
    small_upper = g["upper"] <= max(0.1 * r, 0.5 * g["body"])
    small_lower = g["lower"] <= max(0.1 * r, 0.5 * g["body"])
    if g["lower"] >= 2 * g["body"] and small_upper:
        if trend == "down":
            out.append("hammer")
        elif trend == "up":
            out.append("hanging_man")
    elif g["upper"] >= 2 * g["body"] and small_lower:
        if trend == "down":
            out.append("inverted_hammer")
        elif trend == "up":
            out.append("shooting_star")
    elif g["body"] >= 0.9 * r and g["body"] >= ab:
        out.append("bullish_marubozu" if g["green"] else "bearish_marubozu")
    elif g["body"] <= 0.3 * r and g["upper"] > g["body"] and g["lower"] > g["body"]:
        out.append("spinning_top")
    return out


def _double(p, gp, b, g, trend, ab):
    out = []
    tol = 0.001 * b["c"]
    if gp["red"] and g["green"] and trend == "down":
        if b["o"] <= p["c"] + tol and b["c"] >= p["o"] and g["body"] > gp["body"]:
            out.append("bullish_engulfing")
        elif gp["body"] >= ab and g["top"] <= gp["top"] and g["bottom"] >= gp["bottom"] and g["body"] < 0.5 * gp["body"]:
            out.append("bullish_harami")
        elif gp["body"] >= ab and b["o"] <= p["c"] + tol and gp["mid"] < b["c"] < p["o"]:
            out.append("piercing_line")
        if abs(p["l"] - b["l"]) <= tol and "bullish_engulfing" not in out:
            out.append("tweezer_bottom")
    if gp["green"] and g["red"] and trend == "up":
        if b["o"] >= p["c"] - tol and b["c"] <= p["o"] and g["body"] > gp["body"]:
            out.append("bearish_engulfing")
        elif gp["body"] >= ab and g["top"] <= gp["top"] and g["bottom"] >= gp["bottom"] and g["body"] < 0.5 * gp["body"]:
            out.append("bearish_harami")
        elif gp["body"] >= ab and b["o"] >= p["c"] - tol and p["o"] < b["c"] < gp["mid"]:
            out.append("dark_cloud_cover")
        if abs(p["h"] - b["h"]) <= tol and "bearish_engulfing" not in out:
            out.append("tweezer_top")
    return out


def _triple(a, ga, b, gb, c, gc, trend, ab):
    out = []
    if trend == "down" and ga["red"] and ga["body"] >= ab and gb["body"] <= 0.5 * ga["body"] \
            and gb["top"] <= ga["mid"] and gc["green"] and c["c"] > ga["mid"]:
        out.append("morning_star")
    if trend == "up" and ga["green"] and ga["body"] >= ab and gb["body"] <= 0.5 * ga["body"] \
            and gb["bottom"] >= ga["mid"] and gc["red"] and c["c"] < ga["mid"]:
        out.append("evening_star")
    trio = ((a, ga), (b, gb), (c, gc))
    if all(g["green"] and g["body"] >= 0.6 * ab and g["upper"] <= 0.3 * g["body"] for _, g in trio) \
            and a["c"] < b["c"] < c["c"] and ga["bottom"] <= b["o"] <= ga["top"] and gb["bottom"] <= c["o"] <= gb["top"] \
            and trend != "up":
        out.append("three_white_soldiers")
    if all(g["red"] and g["body"] >= 0.6 * ab and g["lower"] <= 0.3 * g["body"] for _, g in trio) \
            and a["c"] > b["c"] > c["c"] and ga["bottom"] <= b["o"] <= ga["top"] and gb["bottom"] <= c["o"] <= gb["top"] \
            and trend != "down":
        out.append("three_black_crows")
    if trend == "down" and ga["red"] and ga["body"] >= ab and gb["green"] and gb["top"] <= ga["top"] \
            and gb["bottom"] >= ga["bottom"] and gb["body"] < 0.5 * ga["body"] and gc["green"] and c["c"] > a["o"]:
        out.append("three_inside_up")
    if trend == "up" and ga["green"] and ga["body"] >= ab and gb["red"] and gb["top"] <= ga["top"] \
            and gb["bottom"] >= ga["bottom"] and gb["body"] < 0.5 * ga["body"] and gc["red"] and c["c"] < a["o"]:
        out.append("three_inside_down")
    return out


def detect(bars, interval="5m"):
    """Every pattern that completes on each closed candle. Returns a list of
    dicts, oldest first. bars must be closed candles only."""
    found = []
    geos = [_geo(b) for b in bars]
    for i, b in enumerate(bars):
        ab = avg_body(bars, i) or 1e-9
        keys = _single(b, geos[i], trend_before(bars, i), ab)
        if i >= 1:
            keys += _double(bars[i - 1], geos[i - 1], b, geos[i], trend_before(bars, i - 1), avg_body(bars, i - 1) or 1e-9)
        if i >= 2:
            keys += _triple(bars[i - 2], geos[i - 2], bars[i - 1], geos[i - 1], b, geos[i],
                            trend_before(bars, i - 2), avg_body(bars, i - 2) or 1e-9)
        for k in keys:
            en, es, direction, n, strength = PATTERNS[k]
            found.append({"pattern": k, "name": en, "nombre": es, "direction": direction, "candles": n,
                          "strength": strength, "index": i, "start_index": i - n + 1, "t": b["t"],
                          "time": label(b["t"], interval), "close": round(b["c"], 4)})
    return found


# ---------------------------------------------------------------- selection

def session_slice(bars, interval, day=None, round_the_clock=False):
    """Indexes [lo, hi) of the candles to SHOW: one New York session for
    intraday candles (the given day or the latest), everything for daily."""
    if not bars:
        return 0, 0
    if not intraday(interval):
        return 0, len(bars)
    if round_the_clock and day is None:          # crypto: the last 24 hours, not a New York session
        start = bars[-1]["t"] - 86400 + INTERVALS[interval]
        return next(i for i, b in enumerate(bars) if b["t"] >= start), len(bars)
    want = day or ny(bars[-1]["t"]).date()
    idx = [i for i, b in enumerate(bars) if ny(b["t"]).date() == want]
    if not idx:
        raise CandleError("no %s candles on %s in this chart" % (interval, want))
    return idx[0], idx[-1] + 1


def load(a, sym):
    now = parse_now(a.now) if a.now else now_ts()
    ch = get_chart(sym, a.interval, getattr(a, "range", None), a.offline)
    bars = [b for b in ch["bars"] if b["t"] <= now]
    closed, forming = closed_bars(bars, ch["interval"], now, ch.get("crypto"))
    if not closed and not forming:
        raise CandleError("no candles for %s before %s" % (sym, label(now, "5m")))
    return ch, closed, forming, now


def parse_day(text):
    if not text:
        return None
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        raise CandleError("--date wants YYYY-MM-DD, not %r" % text)


ARROW = {"bullish": "▲", "bearish": "▼", "neutral": "•"}


def line(p):
    return "  %s %-16s %-26s %-22s %s  fuerza %d/3  cierre %.2f" % (
        ARROW[p["direction"]], p["time"], p["nombre"], "(" + p["name"] + ")", p["direction"],
        p["strength"], p["close"])


# ---------------------------------------------------------------- commands

def cmd_patterns(a):
    ch, closed, forming, now = load(a, a.symbol)
    lo, hi = session_slice(closed, ch["interval"], parse_day(a.date), ch.get("crypto"))
    found = [p for p in detect(closed, ch["interval"]) if lo <= p["index"] < hi]
    if a.direction:
        found = [p for p in found if p["direction"] == a.direction]
    if a.last:
        found = found[-a.last:]
    if a.json:
        print(json.dumps({"symbol": ch["symbol"], "interval": ch["interval"], "candles": hi - lo,
                          "forming": label(forming["t"], ch["interval"]) if forming else None,
                          "patterns": found, "note": NOTE}, indent=2, ensure_ascii=False))
        return 0
    span = "%s → %s" % (label(closed[lo]["t"], ch["interval"]), label(closed[hi - 1]["t"], ch["interval"])) if hi > lo else "-"
    print("%s, velas de %s, %d velas cerradas (%s)%s" % (
        ch["symbol"], ch["interval"], hi - lo, span,
        ", la de %s aún se está formando y no cuenta" % label(forming["t"], ch["interval"]) if forming else ""))
    if not found:
        print("  ningún patrón de velas")
    for p in found:
        print(line(p))
    bull = sum(1 for p in found if p["direction"] == "bullish")
    bear = sum(1 for p in found if p["direction"] == "bearish")
    print("%d alcistas, %d bajistas, %d neutros. %s" % (bull, bear, len(found) - bull - bear, NOTE))
    return 0


def cmd_confirm(a):
    ch, closed, forming, now = load(a, a.symbol)
    if not closed:
        raise CandleError("no closed candle yet for %s" % a.symbol)
    target_i = len(closed) - 1
    if a.at:
        try:
            hh, mm = [int(x) for x in a.at.split(":")]
        except ValueError:
            raise CandleError("--at wants HH:MM, not %r" % a.at)
        day = parse_day(a.date) or ny(closed[-1]["t"]).date()
        at_ts = ny_to_ts(datetime.datetime.combine(day, datetime.time(hh, mm)))
        step = INTERVALS[ch["interval"]]
        cands = [i for i, b in enumerate(closed) if b["t"] + step <= at_ts]
        if not cands:
            raise CandleError("no %s candle closed by %s on %s" % (ch["interval"], a.at, day))
        target_i = cands[-1]
    found = [p for p in detect(closed[:target_i + 1], ch["interval"])
             if p["index"] >= target_i - a.lookback + 1]
    bull = [p for p in found if p["direction"] == "bullish"]
    bear = [p for p in found if p["direction"] == "bearish"]
    verdict = "bullish" if bull and not bear else "bearish" if bear and not bull else \
        "mixed" if bull and bear else "none"
    res = {"symbol": ch["symbol"], "interval": ch["interval"],
           "candle": label(closed[target_i]["t"], ch["interval"]), "lookback": a.lookback,
           "verdict": verdict, "patterns": found, "note": NOTE}
    if a.json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        words = {"bullish": "CONFIRMA el largo: hay patrón alcista",
                 "bearish": "AVISA en contra del largo: hay patrón bajista",
                 "mixed": "MIXTO: hay patrones alcistas y bajistas a la vez",
                 "none": "SIN PATRÓN: las velas no dicen nada claro"}
        closes_at = label(closed[target_i]["t"] + INTERVALS[ch["interval"]], ch["interval"]) \
            if intraday(ch["interval"]) else res["candle"]
        print("%s, vela de %s de las %s (cierra %s, mirando %d vela%s): %s" % (
            ch["symbol"], ch["interval"], res["candle"], closes_at, a.lookback,
            "" if a.lookback == 1 else "s", words[verdict]))
        for p in found:
            print(line(p))
    return {"bullish": 0, "bearish": 2, "mixed": 2, "none": 3}[verdict]


def read_watchlist(path):
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        raise CandleError("no %s: run /trader-scanner first or pass --tickers" % path)
    except ValueError:
        raise CandleError("%s is not valid JSON" % path)
    items = doc.get("hits", []) if isinstance(doc, dict) else doc
    syms = []
    for h in items or []:
        s = h.get("symbol") if isinstance(h, dict) else h
        if s and str(s).upper() not in syms:
            syms.append(str(s).upper())
    return syms


def write_json(path, doc):
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def cmd_scan(a):
    syms = [s.strip().upper() for s in a.tickers.split(",") if s.strip()] if a.tickers else read_watchlist(a.watchlist)
    if not syms:
        raise CandleError("no tickers to scan")
    hits, errors = [], []
    for n, sym in enumerate(syms):
        if n and not a.offline:
            time.sleep(a.pause)
        try:
            ch, closed, forming, now = load(a, sym)
        except CandleError as e:
            errors.append({"symbol": sym, "error": str(e)})
            continue
        if not closed:
            continue
        last = len(closed) - 1
        found = [p for p in detect(closed, ch["interval"]) if p["index"] > last - a.lookback]
        if a.direction:
            found = [p for p in found if p["direction"] == a.direction]
        if found:
            hits.append({"symbol": ch["symbol"], "price": round(closed[-1]["c"], 2),
                         "candle": label(closed[-1]["t"], ch["interval"]), "patterns": found})
    order = {"bullish": 0, "bearish": 1, "neutral": 2}
    hits.sort(key=lambda h: (min(order[p["direction"]] for p in h["patterns"]),
                             -max(p["strength"] for p in h["patterns"]), h["symbol"]))
    doc = {"created_by": "trader-candles", "interval": a.interval, "lookback": a.lookback,
           "scanned": len(syms), "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "hits": hits, "errors": errors, "note": NOTE}
    if a.write:
        write_json(a.write, doc)
    if a.json:
        print(json.dumps(doc, indent=2, ensure_ascii=False))
        return 0
    print("Escaneadas %d acciones en velas de %s (última%s %d vela%s cerrada%s): %d con patrón" % (
        len(syms), a.interval, "s" if a.lookback > 1 else "", a.lookback, "s" if a.lookback > 1 else "",
        "s" if a.lookback > 1 else "", len(hits)))
    for h in hits:
        print("%s  %.2f  (%s)" % (h["symbol"], h["price"], h["candle"]))
        for p in h["patterns"]:
            print(line(p))
    for e in errors:
        print("  ! %s: %s" % (e["symbol"], e["error"]))
    if a.write:
        print("Guardado en %s" % a.write)
    print(NOTE)
    return 0


# ---------------------------------------------------------------- chart

def read_plan(path, sym):
    if not path or not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            plan = json.load(fh)
    except (OSError, ValueError):
        return None
    if str(plan.get("symbol") or "").upper() != sym.upper():
        return None
    return plan


def _fmt(x):
    return ("%.2f" % x) if x >= 1 else ("%.4f" % x)


def render_html(sym, interval, bars, forming, patterns, plan, title_extra=""):
    shown = bars + ([forming] if forming else [])
    n = len(shown)
    if not n:
        raise CandleError("nothing to draw")
    W_C = max(8, min(48, 1080 // n))                     # px per candle: fill ~1100px, scroll when long
    left, right, top = 10, 70, 24
    ph, gap, vh, bottom = 420, 14, 90, 28
    width = left + right + n * W_C
    height = top + ph + gap + vh + bottom
    levels = []
    if plan:
        for key, cls, text in (("entry", "lv-entry", "Entrada"), ("stop", "lv-stop", "Stop"),
                               ("target", "lv-target", "Objetivo")):
            if isinstance(plan.get(key), (int, float)):
                levels.append((float(plan[key]), cls, text))
    orr = (plan or {}).get("opening_range") or None
    lows = [b["l"] for b in shown] + [lv[0] for lv in levels]
    highs = [b["h"] for b in shown] + [lv[0] for lv in levels]
    if orr:
        lows.append(float(orr["low"]))
        highs.append(float(orr["high"]))
    lo_p, hi_p = min(lows), max(highs)
    pad = (hi_p - lo_p) * 0.06 or hi_p * 0.01 or 1
    lo_p, hi_p = lo_p - pad, hi_p + pad
    vmax = max(b["v"] for b in shown) or 1

    def y(p):
        return top + (hi_p - p) / (hi_p - lo_p) * ph

    def x(i):
        return left + i * W_C + W_C / 2.0

    s = []
    # grid + price labels
    for k in range(6):
        p = lo_p + (hi_p - lo_p) * k / 5.0
        s.append('<line class="grid" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/>' % (left, width - right, y(p), y(p)))
        s.append('<text class="axis" x="%d" y="%.1f">%s</text>' % (width - right + 6, y(p) + 4, _fmt(p)))
    # time labels
    last_lab = None
    for i, b in enumerate(shown):
        d = ny(b["t"])
        if intraday(interval):
            every = 2 if n > 200 else 1
            lab = d.strftime("%H:%M") if i == 0 or (d.minute == 0 and d.hour % every == 0) else None
        else:
            key = (d.year, d.month)
            lab = d.strftime("%b %Y") if key != last_lab else None
            last_lab = key
        if lab:
            s.append('<line class="grid" x1="%.1f" x2="%.1f" y1="%d" y2="%d"/>' % (x(i), x(i), top, top + ph))
            s.append('<text class="axis" x="%.1f" y="%d" text-anchor="middle">%s</text>' % (x(i), height - 8, lab))
    # opening range band
    if orr and intraday(interval):
        y1, y2 = y(float(orr["high"])), y(float(orr["low"]))
        s.append('<rect class="orband" x="%d" y="%.1f" width="%d" height="%.1f"/>' % (left, y1, n * W_C, y2 - y1))
        s.append('<text class="lvtext" x="%d" y="%.1f">Rango de apertura %s–%s</text>' % (
            left + 4, y2 - 6, _fmt(float(orr["low"])), _fmt(float(orr["high"]))))
    # flat-by line
    if plan and plan.get("flat_by") and intraday(interval):
        try:
            fh_, fm_ = [int(v) for v in str(plan["flat_by"]).split(":")]
            for i, b in enumerate(shown):
                d = ny(b["t"])
                if (d.hour, d.minute) >= (fh_, fm_):
                    s.append('<line class="lv-flat" x1="%.1f" x2="%.1f" y1="%d" y2="%d"/>' % (
                        x(i) - W_C / 2.0, x(i) - W_C / 2.0, top, top + ph))
                    s.append('<text class="lvtext" x="%.1f" y="%d">cerrar %s</text>' % (
                        x(i) - W_C / 2.0 + 3, top + 12, plan["flat_by"]))
                    break
        except ValueError:
            pass
    # candles + volume
    bw = max(2, W_C * 0.62)
    for i, b in enumerate(shown):
        up = b["c"] >= b["o"]
        cls = "up" if up else "dn"
        if forming is not None and i == n - 1:
            cls += " forming"
        tip = "%s  A %s  M %s  m %s  C %s  Vol %s" % (label(b["t"], interval), _fmt(b["o"]), _fmt(b["h"]),
                                                       _fmt(b["l"]), _fmt(b["c"]), "{:,}".format(b["v"]))
        if forming is not None and i == n - 1:
            tip += "  (formándose)"
        body_top, body_bot = y(max(b["o"], b["c"])), y(min(b["o"], b["c"]))
        s.append('<g class="%s"><title>%s</title>'
                 '<line class="wick" x1="%.1f" x2="%.1f" y1="%.1f" y2="%.1f"/>'
                 '<rect class="body" x="%.1f" y="%.1f" width="%.1f" height="%.1f"/>'
                 '<rect class="vol" x="%.1f" y="%.1f" width="%.1f" height="%.1f"/></g>' % (
                     cls, html.escape(tip), x(i), x(i), y(b["h"]), y(b["l"]),
                     x(i) - bw / 2, body_top, bw, max(1.0, body_bot - body_top),
                     x(i) - bw / 2, top + ph + gap + vh * (1 - b["v"] / float(vmax)), bw,
                     max(0.5, vh * b["v"] / float(vmax))))
    # plan levels
    for p, cls, text in levels:
        s.append('<line class="%s" x1="%d" x2="%d" y1="%.1f" y2="%.1f"/>' % (cls, left, width - right, y(p), y(p)))
        s.append('<text class="lvtext %s-t" x="%d" y="%.1f" text-anchor="end">%s %s</text>' % (
            cls, width - right - 4, y(p) - 4, text, _fmt(p)))
    # pattern markers
    stack = {}
    for pt in patterns:
        i = pt["index"]
        b = shown[i]
        k = stack.get((i, pt["direction"]), 0)
        stack[(i, pt["direction"])] = k + 1
        tip = "%s (%s), %s, fuerza %d/3, %d vela%s" % (pt["nombre"], pt["name"], pt["time"], pt["strength"],
                                                       pt["candles"], "" if pt["candles"] == 1 else "s")
        if pt["direction"] == "bullish":
            yy = y(b["l"]) + 12 + k * 11
            shape = '<path class="mk-bull" d="M%.1f %.1f l5 8 h-10 z"/>' % (x(i), yy - 6)
        elif pt["direction"] == "bearish":
            yy = y(b["h"]) - 12 - k * 11
            shape = '<path class="mk-bear" d="M%.1f %.1f l5 -8 h-10 z"/>' % (x(i), yy + 6)
        else:
            yy = y(b["h"]) - 10 - k * 9
            shape = '<circle class="mk-neu" cx="%.1f" cy="%.1f" r="3"/>' % (x(i), yy)
        s.append('<g class="mk"><title>%s</title>%s</g>' % (html.escape(tip), shape))
    s.append('<text class="axis" x="%d" y="%d">Volumen</text>' % (left, top + ph + gap + 10))

    svg = '<svg viewBox="0 0 %d %d" width="%d" height="%d" role="img" aria-label="Gráfico de velas de %s">%s</svg>' % (
        width, height, width, height, html.escape(sym), "".join(s))

    rows = []
    for pt in reversed(patterns):
        rows.append("<tr><td>%s</td><td class='%s'>%s %s</td><td>%s</td><td>%s</td><td>%d/3</td><td>%s</td></tr>" % (
            html.escape(pt["time"]), pt["direction"], ARROW[pt["direction"]], html.escape(pt["nombre"]),
            html.escape(pt["name"]), {"bullish": "alcista", "bearish": "bajista", "neutral": "neutro"}[pt["direction"]],
            pt["strength"], _fmt(pt["close"])))
    table = ("<table><thead><tr><th>Vela</th><th>Patrón</th><th>Inglés</th><th>Sentido</th><th>Fuerza</th>"
             "<th>Cierre</th></tr></thead><tbody>%s</tbody></table>" % "".join(rows)) if rows else \
        "<p class='muted'>Ningún patrón de velas en este tramo.</p>"
    plan_txt = ""
    if plan:
        bits = []
        for key, text in (("entry", "Entrada"), ("stop", "Stop"), ("target", "Objetivo")):
            if isinstance(plan.get(key), (int, float)):
                bits.append("%s <b>%s</b>" % (text, _fmt(float(plan[key]))))
        if plan.get("risk_per_share"):
            bits.append("riesgo %s por acción" % _fmt(float(plan["risk_per_share"])))
        if plan.get("flat_by"):
            bits.append("cerrar antes de las %s" % html.escape(str(plan["flat_by"])))
        plan_txt = "<p>Plan (%s): %s.</p>" % (html.escape(str(plan.get("date") or "")), ", ".join(bits))
    bull = sum(1 for p in patterns if p["direction"] == "bullish")
    bear = sum(1 for p in patterns if p["direction"] == "bearish")
    span = "%s → %s" % (label(shown[0]["t"], interval), label(shown[-1]["t"], interval))
    return """<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Velas %(sym)s</title>
<style>
:root{--bg:#ffffff;--fg:#1d2330;--muted:#677084;--grid:#e6e9ef;--up:#12915a;--dn:#d4373b;--entry:#2563eb;--stop:#d4373b;--target:#12915a;--band:rgba(37,99,235,.08);--card:#f6f7f9}
@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){--bg:#11141a;--fg:#e7eaf0;--muted:#9aa3b5;--grid:#232834;--up:#2fbf7f;--dn:#f0575b;--entry:#5b8cff;--stop:#f0575b;--target:#2fbf7f;--band:rgba(91,140,255,.12);--card:#181c24}}
:root[data-theme="dark"]{--bg:#11141a;--fg:#e7eaf0;--muted:#9aa3b5;--grid:#232834;--up:#2fbf7f;--dn:#f0575b;--entry:#5b8cff;--stop:#f0575b;--target:#2fbf7f;--band:rgba(91,140,255,.12);--card:#181c24}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1200px;margin:0 auto;padding:20px 16px 40px}
h1{font-size:22px;margin:0 0 4px}.muted{color:var(--muted)}
.chart{overflow-x:auto;background:var(--card);border-radius:10px;padding:8px;margin:14px 0}
svg{display:block;font:11px system-ui,sans-serif}
.grid{stroke:var(--grid);stroke-width:1}.axis{fill:var(--muted)}
.up .body,.up .wick{fill:var(--up);stroke:var(--up)}.dn .body,.dn .wick{fill:var(--dn);stroke:var(--dn)}
.wick{stroke-width:1}.vol{opacity:.35}.up .vol{fill:var(--up)}.dn .vol{fill:var(--dn)}
.forming{opacity:.45}
.orband{fill:var(--band)}
.lv-entry{stroke:var(--entry);stroke-width:1.5}.lv-stop{stroke:var(--stop);stroke-width:1.5;stroke-dasharray:6 4}
.lv-target{stroke:var(--target);stroke-width:1.5;stroke-dasharray:6 4}.lv-flat{stroke:var(--muted);stroke-dasharray:3 3}
.lvtext{fill:var(--muted);font-weight:600}.lv-entry-t{fill:var(--entry)}.lv-stop-t{fill:var(--stop)}.lv-target-t{fill:var(--target)}
.mk-bull{fill:var(--up)}.mk-bear{fill:var(--dn)}.mk-neu{fill:var(--muted)}
table{border-collapse:collapse;width:100%%;font-size:14px}th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--grid)}
td.bullish{color:var(--up)}td.bearish{color:var(--dn)}
.legend span{margin-right:14px;white-space:nowrap}
</style></head><body><main>
<h1>%(sym)s · velas de %(interval)s</h1>
<p class="muted">%(span)s · %(n)d velas · %(bull)d patrones alcistas, %(bear)d bajistas, %(neu)d neutros%(extra)s</p>
%(plan)s
<p class="legend muted"><span style="color:var(--up)">▲ alcista</span><span style="color:var(--dn)">▼ bajista</span><span>• neutro</span><span>Pasa el ratón por una vela o un marcador para ver el detalle.</span></p>
<div class="chart">%(svg)s</div>
<h2 style="font-size:17px">Patrones detectados</h2>
%(table)s
<p class="muted" style="margin-top:18px">%(note)s Datos gratuitos de Yahoo, con retraso. Solo cuentan velas cerradas.</p>
</main></body></html>
""" % {"sym": html.escape(sym), "interval": html.escape(interval), "span": html.escape(span), "n": n,
       "bull": bull, "bear": bear, "neu": len(patterns) - bull - bear, "plan": plan_txt, "svg": svg,
       "table": table, "note": html.escape(NOTE), "extra": html.escape(title_extra)}


def cmd_chart(a):
    ch, closed, forming, now = load(a, a.symbol)
    plan = None if a.no_plan else read_plan(a.plan, ch["symbol"])
    day = parse_day(a.date)
    if day is None and plan and plan.get("date") and intraday(ch["interval"]):
        try:
            d = datetime.date.fromisoformat(str(plan["date"]))
            if any(ny(b["t"]).date() == d for b in closed):
                day = d
        except ValueError:
            pass
    if closed:
        lo, hi = session_slice(closed, ch["interval"], day, ch.get("crypto"))
    else:
        lo = hi = 0
    if not intraday(ch["interval"]) and a.bars:
        lo = max(0, hi - a.bars)
    if plan and intraday(ch["interval"]) and closed and hi > lo and str(plan.get("date")) != ny(closed[lo]["t"]).date().isoformat():
        plan = None                     # the plan is for another day
    all_pat = detect(closed, ch["interval"])
    pats = [dict(p, index=p["index"] - lo) for p in all_pat if lo <= p["index"] < hi]
    show_forming = forming if (forming and hi == len(closed)) else None
    out = a.out or os.path.join("trader", "chart-%s.html" % ch["symbol"])
    doc = render_html(ch["symbol"], ch["interval"], closed[lo:hi], show_forming, pats, plan)
    d = os.path.dirname(out)
    if d:
        os.makedirs(d, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        fh.write(doc)
    if a.json:
        print(json.dumps({"symbol": ch["symbol"], "interval": ch["interval"], "file": out, "candles": hi - lo,
                          "plan": bool(plan), "patterns": pats}, indent=2, ensure_ascii=False))
    else:
        print("Gráfico de velas de %s (%s, %d velas%s, %d patrones) guardado en %s" % (
            ch["symbol"], ch["interval"], hi - lo, ", con el plan dibujado" if plan else "", len(pats), out))
    return 0


# ---------------------------------------------------------------- main

def main(argv=None):
    ap = argparse.ArgumentParser(description="Candlestick patterns and charts for the trader-* skills.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, interval="5m"):
        p.add_argument("--interval", default=interval, choices=list(INTERVALS))
        p.add_argument("--range", help="Yahoo range (default depends on the interval: %s)" % DEFAULT_RANGE)
        p.add_argument("--offline", help="saved Yahoo chart JSON (.json/.json.gz) or a folder of <TICKER>.json")
        p.add_argument("--now", help='"YYYY-MM-DD HH:MM" New York time: ignore candles after it')
        p.add_argument("--json", action="store_true")

    p = sub.add_parser("patterns", help="every pattern in one session (intraday) or the whole range (daily)")
    p.add_argument("symbol")
    common(p)
    p.add_argument("--date", help="YYYY-MM-DD session to read (intraday; default the latest)")
    p.add_argument("--last", type=int, help="only the last N patterns")
    p.add_argument("--direction", choices=["bullish", "bearish", "neutral"])
    p.set_defaults(fn=cmd_patterns)

    p = sub.add_parser("confirm", help="does the latest candle (or the one at --at) confirm a long?")
    p.add_argument("symbol")
    common(p)
    p.add_argument("--at", help="HH:MM New York: the candle that closed by then (e.g. the entry bar)")
    p.add_argument("--date", help="YYYY-MM-DD for --at (default the latest session)")
    p.add_argument("--lookback", type=int, default=1, help="patterns completing in the last N candles (default 1)")
    p.set_defaults(fn=cmd_confirm)

    p = sub.add_parser("scan", help="patterns on the last closed candle of many tickers")
    common(p, interval="1d")
    p.add_argument("--tickers", help="comma-separated; default the hits in --watchlist")
    p.add_argument("--watchlist", default="trader/watchlist.json")
    p.add_argument("--lookback", type=int, default=1)
    p.add_argument("--direction", choices=["bullish", "bearish", "neutral"])
    p.add_argument("--pause", type=float, default=0.4, help="seconds between Yahoo requests (default 0.4)")
    p.add_argument("--write", nargs="?", const="trader/patterns.json", metavar="PATH",
                   help="save the result (default trader/patterns.json)")
    p.set_defaults(fn=cmd_scan)

    p = sub.add_parser("chart", help="write an HTML candlestick chart with the patterns and the plan")
    p.add_argument("symbol")
    common(p)
    p.add_argument("--date", help="YYYY-MM-DD session to draw (intraday; default the plan's day or the latest)")
    p.add_argument("--plan", default="trader/plan.json")
    p.add_argument("--no-plan", action="store_true")
    p.add_argument("--bars", type=int, default=130, help="daily/weekly: draw the last N candles (default 130)")
    p.add_argument("--out", help="default trader/chart-<TICKER>.html")
    p.set_defaults(fn=cmd_chart)

    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except CandleError as e:
        print("error: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
