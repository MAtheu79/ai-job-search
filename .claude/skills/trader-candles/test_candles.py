"""Offline tests for candles.py on hand-built candles.

    python3 -m unittest discover -s .claude/skills/trader-candles -p "test_*.py" -v
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import candles  # noqa: E402

T0 = 1760880600  # 2025-10-19 13:30 UTC, any fixed start works


def bar(i, o, h, l, c, v=1000):
    return {"t": T0 + 300 * i, "o": o, "h": h, "l": l, "c": c, "v": v}


def downtrend(n=6, start=110.0, step=1.0):
    out, p = [], start
    for i in range(n):
        out.append(bar(i, p, p + 0.3, p - step - 0.3, p - step))
        p -= step
    return out


def uptrend(n=6, start=100.0, step=1.0):
    out, p = [], start
    for i in range(n):
        out.append(bar(i, p, p + step + 0.3, p - 0.3, p + step))
        p += step
    return out


def keys(bars):
    last = len(bars) - 1
    return {p["pattern"] for p in candles.detect(bars) if p["index"] == last}


class Single(unittest.TestCase):
    def test_hammer_after_downtrend(self):
        b = downtrend()
        p = b[-1]["c"]
        b.append(bar(len(b), p, p + 0.55, p - 2.0, p + 0.5))
        self.assertIn("hammer", keys(b))

    def test_hanging_man_after_uptrend(self):
        b = uptrend()
        p = b[-1]["c"]
        b.append(bar(len(b), p, p + 0.55, p - 2.0, p + 0.5))
        self.assertIn("hanging_man", keys(b))

    def test_shooting_star_after_uptrend(self):
        b = uptrend()
        p = b[-1]["c"]
        b.append(bar(len(b), p, p + 2.0, p - 0.55, p - 0.5))
        self.assertIn("shooting_star", keys(b))

    def test_inverted_hammer_after_downtrend(self):
        b = downtrend()
        p = b[-1]["c"]
        b.append(bar(len(b), p, p + 2.0, p - 0.05, p + 0.4))
        self.assertIn("inverted_hammer", keys(b))

    def test_doji_and_dragonfly(self):
        b = downtrend()
        p = b[-1]["c"]
        b.append(bar(len(b), p, p + 0.02, p - 2.0, p + 0.01))
        self.assertIn("dragonfly_doji", keys(b))
        b2 = [bar(i, 100, 101, 99, 100.02) for i in range(3)]
        self.assertIn("doji", keys(b2))

    def test_marubozu(self):
        b = [bar(i, 100, 100.6, 99.6, 100.2) for i in range(6)]
        b.append(bar(6, 100, 103.02, 99.99, 103))
        self.assertIn("bullish_marubozu", keys(b))


class Double(unittest.TestCase):
    def test_bullish_engulfing(self):
        b = downtrend()
        p = b[-1]["c"]
        b.append(bar(len(b), p, p + 0.1, p - 1.1, p - 1.0))
        b.append(bar(len(b), p - 1.1, p + 0.6, p - 1.2, p + 0.5))
        self.assertIn("bullish_engulfing", keys(b))

    def test_bearish_engulfing(self):
        b = uptrend()
        p = b[-1]["c"]
        b.append(bar(len(b), p, p + 1.1, p - 0.1, p + 1.0))
        b.append(bar(len(b), p + 1.1, p + 1.2, p - 0.6, p - 0.5))
        self.assertIn("bearish_engulfing", keys(b))

    def test_bullish_harami(self):
        b = downtrend()
        p = b[-1]["c"]
        b.append(bar(len(b), p, p + 0.1, p - 2.1, p - 2.0))
        b.append(bar(len(b), p - 1.4, p - 0.9, p - 1.5, p - 1.0))
        self.assertIn("bullish_harami", keys(b))

    def test_piercing_and_dark_cloud(self):
        b = downtrend()
        p = b[-1]["c"]
        b.append(bar(len(b), p, p + 0.1, p - 2.1, p - 2.0))
        b.append(bar(len(b), p - 2.0, p - 0.4, p - 2.1, p - 0.6))
        self.assertIn("piercing_line", keys(b))
        u = uptrend()
        q = u[-1]["c"]
        u.append(bar(len(u), q, q + 2.1, q - 0.1, q + 2.0))
        u.append(bar(len(u), q + 2.0, q + 2.1, q + 0.4, q + 0.6))
        self.assertIn("dark_cloud_cover", keys(u))


class Triple(unittest.TestCase):
    def test_morning_star(self):
        b = downtrend()
        p = b[-1]["c"]
        b.append(bar(len(b), p, p + 0.1, p - 2.1, p - 2.0))
        b.append(bar(len(b), p - 2.1, p - 1.9, p - 2.5, p - 2.2))
        b.append(bar(len(b), p - 2.1, p - 0.4, p - 2.2, p - 0.5))
        self.assertIn("morning_star", keys(b))

    def test_evening_star(self):
        b = uptrend()
        p = b[-1]["c"]
        b.append(bar(len(b), p, p + 2.1, p - 0.1, p + 2.0))
        b.append(bar(len(b), p + 2.1, p + 2.5, p + 1.9, p + 2.2))
        b.append(bar(len(b), p + 2.1, p + 2.2, p + 0.4, p + 0.5))
        self.assertIn("evening_star", keys(b))

    def test_three_white_soldiers(self):
        b = [bar(i, 100, 100.5, 99.5, 100.1 if i % 2 else 99.9) for i in range(6)]
        b.append(bar(6, 100.0, 101.1, 99.9, 101.0))
        b.append(bar(7, 100.5, 102.1, 100.4, 102.0))
        b.append(bar(8, 101.5, 103.1, 101.4, 103.0))
        self.assertIn("three_white_soldiers", keys(b))

    def test_three_black_crows(self):
        b = [bar(i, 100, 100.5, 99.5, 100.1 if i % 2 else 99.9) for i in range(6)]
        b.append(bar(6, 100.0, 100.1, 98.9, 99.0))
        b.append(bar(7, 99.5, 99.6, 97.9, 98.0))
        b.append(bar(8, 98.5, 98.6, 96.9, 97.0))
        self.assertIn("three_black_crows", keys(b))


class NoNoise(unittest.TestCase):
    def test_hammer_needs_a_downtrend(self):
        b = [bar(i, 100, 100.5, 99.5, 100.1 if i % 2 else 99.9) for i in range(6)]
        b.append(bar(6, 100, 100.55, 98.0, 100.5))
        self.assertNotIn("hammer", keys(b))

    def test_forming_candle_is_ignored(self):
        b = uptrend()
        closed, forming = candles.closed_bars(b, "5m", b[-1]["t"] + 10)
        self.assertEqual(len(closed), len(b) - 1)
        self.assertIs(forming, b[-1])


def chart_json(bars, sym="DEMO"):
    return {"chart": {"result": [{"meta": {"symbol": sym, "dataGranularity": "5m"},
                                   "timestamp": [b["t"] for b in bars],
                                   "indicators": {"quote": [{k: [b[x] for b in bars] for k, x in
                                                             (("open", "o"), ("high", "h"), ("low", "l"),
                                                              ("close", "c"), ("volume", "v"))}]}}],
                      "error": None}}


class Commands(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        b = downtrend()
        p = b[-1]["c"]
        b.append(bar(len(b), p, p + 0.1, p - 1.1, p - 1.0))
        b.append(bar(len(b), p - 1.1, p + 0.6, p - 1.2, p + 0.5))
        self.bars = b
        self.file = os.path.join(self.d, "DEMO.json")
        with open(self.file, "w") as fh:
            json.dump(chart_json(b), fh)
        self.after = candles.label(b[-1]["t"] + 600, "5m")

    def tearDown(self):
        shutil.rmtree(self.d)

    def run_cmd(self, *args):
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = candles.main(list(args))
        return code, buf.getvalue()

    def test_confirm_bullish_exit_0(self):
        code, out = self.run_cmd("confirm", "DEMO", "--offline", self.file, "--now", self.after)
        self.assertEqual(code, 0, out)
        self.assertIn("Envolvente alcista", out)

    def test_scan_writes_json(self):
        dest = os.path.join(self.d, "patterns.json")
        code, out = self.run_cmd("scan", "--tickers", "DEMO", "--interval", "5m", "--offline", self.d,
                                 "--now", self.after, "--write", dest)
        self.assertEqual(code, 0, out)
        with open(dest, encoding="utf-8") as fh:
            doc = json.load(fh)
        self.assertEqual(doc["hits"][0]["symbol"], "DEMO")

    def test_chart_html(self):
        out_html = os.path.join(self.d, "c.html")
        code, out = self.run_cmd("chart", "DEMO", "--offline", self.file, "--now", self.after,
                                 "--out", out_html, "--no-plan")
        self.assertEqual(code, 0, out)
        with open(out_html, encoding="utf-8") as fh:
            page = fh.read()
        self.assertIn("<svg", page)
        self.assertIn("Envolvente alcista", page)


if __name__ == "__main__":
    unittest.main()
