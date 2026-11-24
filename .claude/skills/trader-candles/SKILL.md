---
name: trader-candles
description: >-
  Candlestick Reader. Draws a candlestick chart of any stock (1-minute to
  weekly candles, with volume) as a self-contained HTML page with the trade
  plan on it (opening range, entry, stop, target, flat-by time), and detects
  24 classic candlestick patterns on CLOSED candles only, each with its trend
  context and a 1-3 strength: doji (plain, dragonfly, gravestone), spinning
  top, hammer, hanging man, inverted hammer, shooting star, marubozu,
  engulfing, harami, piercing line, dark cloud cover, tweezers, morning and
  evening star, three white soldiers, three black crows, three inside up and
  down. Confirms (or warns against) an entry from the candle that just
  closed, and scans a whole watchlist for fresh patterns. Free Yahoo data.
  Never places an order. Use when the user says "velas", "gráfico de velas",
  "candlestick", "candle chart", "show me the chart", "patrones de velas",
  "is that a hammer", "any engulfing", "doji", "morning star", "what do the
  candles say", "confirm the entry with the candles", "scan for candle
  patterns", or after /trader-entry triggers and before /trader-exit, or
  after /trader-exit to see the plan on the chart.
argument-hint: "[patterns|confirm|scan|chart] [TICKER] [--interval 5m|1d]"
---

# trader-candles: Candlestick Reader

Reads the stock the way a chart reader does: one candle at a time. It draws
the candles with the plan on top, names the patterns the textbooks name, and
says whether the candle that just closed backs the long or warns against it.
A pattern is a hint about the next few candles, never a guarantee, and day
trading loses most people money. Answer in the user's language (the tool
prints in Spanish; pattern names come in Spanish and English).

`${CLAUDE_SKILL_DIR}` below is this skill's folder (where this SKILL.md lives).

```bash
python3 "${CLAUDE_SKILL_DIR}/candles.py" chart TSLA                   # trader/chart-TSLA.html, plan drawn if trader/plan.json is TSLA's
python3 "${CLAUDE_SKILL_DIR}/candles.py" chart TSLA --interval 1d     # last 130 daily candles
python3 "${CLAUDE_SKILL_DIR}/candles.py" patterns TSLA                # every pattern in today's 5-minute candles
python3 "${CLAUDE_SKILL_DIR}/candles.py" patterns TSLA --interval 1d --last 10
python3 "${CLAUDE_SKILL_DIR}/candles.py" confirm TSLA                 # the candle that just closed
python3 "${CLAUDE_SKILL_DIR}/candles.py" confirm TSLA --at 10:15 --lookback 2   # the entry bar and the one before
python3 "${CLAUDE_SKILL_DIR}/candles.py" scan                         # daily candles of every trader/watchlist.json hit
python3 "${CLAUDE_SKILL_DIR}/candles.py" scan --tickers TSLA,NVDA,AMD --direction bullish --write
```

Common flags: `--interval 1m|2m|5m|15m|30m|60m|1d|1wk` (default 5m; `scan`
defaults to 1d), `--date YYYY-MM-DD` (which intraday session), `--json`,
`--offline FILE|DIR` (a saved Yahoo chart JSON, `.json` or `.json.gz`, or a
folder of `<TICKER>.json`), `--now "YYYY-MM-DD HH:MM"` (New York time; candles
after it are ignored, to replay a day).

## Where it fits

```
scanner -> news -> entry -> [candles confirm] -> exit -> [candles chart] -> timemachine -> budget -> risk -> broker
scanner -> [candles scan]   (a second filter on the watchlist: which setups also have a candle signal)
```

- After `/trader-entry` triggers: run `confirm TICKER --at <entry time>
  --lookback 2`. Exit 0 = a bullish pattern backs the entry, 2 = a bearish
  (or mixed) pattern warns against it, 3 = the candles say nothing. A
  warning is information for the user, not a veto: say it plainly and let
  them decide. It never replaces `/trader-risk`.
- After `/trader-exit` writes `trader/plan.json`: run `chart TICKER` and
  show the user the page (in a cloud session, send the HTML file with the
  file-sending tool so it renders). The plan is only drawn when its symbol
  and date match the candles shown.
- `scan --write` writes `trader/patterns.json` (`hits[]` with `symbol`,
  `price`, `candle`, `patterns[]`), bullish first, strongest first.

## Reading the output

Each pattern line: arrow (▲ bullish, ▼ bearish, • neutral), the candle's New
York time (the candle's START time; `confirm` also prints when it closes),
the Spanish and English names, direction, strength 1-3 (textbook
reliability, not a probability) and the close.

Rules the tool applies, so you can explain them:
- Only closed candles count. A candle still forming is drawn faded on the
  chart and never read.
- Reversal patterns need the trend before them: the last 5 closes against
  their average. A hammer only counts after a fall (the same shape after a
  rise is a hanging man); a shooting star only after a rise.
- The first candles of a session take their trend from the previous
  session's candles (the default intraday range is 5 days for that reason).
- Neutral patterns (doji, spinning top) mean indecision. They are context,
  never a reason to enter.

## What to tell the user

- Lead with the verdict, then the pattern(s), then one line of caution.
  Example: "La vela de las 10:10 cierra con un martillo tras la caída:
  confirma el largo (fuerza 2/3). Aun así, es una pista, no una garantía:
  pásalo por la máquina del tiempo antes de arriesgar dinero."
- If the user asks whether a pattern "works", point them to
  `/trader-timemachine`, which replays the setup on real history. Do not
  quote win rates for candle patterns from memory.
- Free Yahoo data is delayed. If Yahoo is unreachable (a network policy, a
  rate limit), say so and offer `--offline` with a saved chart file.

## Limits

Long and short patterns are both detected, but the rest of the pack only
plans longs, so a bearish pattern is a warning, not a short signal. Data is
free and delayed. Not financial advice.
