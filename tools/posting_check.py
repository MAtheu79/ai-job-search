#!/usr/bin/env python3
"""Deterministic helpers for /check-posting: closed-posting signals and repost detection.

Two subcommands, both read-only:

  closed   Scan posting text for "no longer accepting applications" style
           phrases and past deadlines.
             python tools/posting_check.py closed --text-file posting.txt [--today YYYY-MM-DD]

  repost   Look for earlier sightings of the same company + similar title in
           job_scraper/seen_jobs.json and job_search_tracker.csv.
             python tools/posting_check.py repost --company "Acme" --title "Data Scientist" [--url URL]

Both print JSON to stdout. Missing state files are treated as empty, never as errors.
Fetching the posting is deliberately NOT done here: the /check-posting command
fetches it (WebFetch handles JS-heavy portals better) and passes the text in.
"""

import argparse
import csv
import json
import re
import sys
import unicodedata
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SEEN = ROOT / "job_scraper" / "seen_jobs.json"
DEFAULT_TRACKER = ROOT / "job_search_tracker.csv"

# Phrases that, on a posting page, mean the job is closed. Lowercase, accent-folded.
CLOSED_PHRASES = [
    # English
    "no longer accepting applications",
    "this job is no longer available",
    "this position has been filled",
    "this job has expired",
    "this posting has expired",
    "the application deadline has passed",
    "job is closed",
    "position is closed",
    "this vacancy is closed",
    "this vacancy has closed",
    "applications are closed",
    "job not found",
    # Danish
    "stillingen er besat",
    "jobbet er ikke laengere aktivt",
    "annoncen er udlobet",
    "ansogningsfristen er overskredet",
    "stillingsopslaget er udlobet",
    # Spanish
    "ya no acepta solicitudes",
    "esta oferta ha caducado",
    "la oferta ya no esta disponible",
    "el proceso de seleccion ha finalizado",
    # German
    "nicht mehr verfugbar",
    "die stelle ist bereits besetzt",
    "bewerbungsfrist ist abgelaufen",
]

# Deadline cue words followed by a date (same line).
DEADLINE_CUES = r"(?:deadline|apply by|closing date|ansøgningsfrist|ansogningsfrist|frist|fecha l[ií]mite|bewerbungsfrist)"
DATE_PATTERNS = [
    (re.compile(r"(\d{4})-(\d{1,2})-(\d{1,2})"), ("y", "m", "d")),
    (re.compile(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})"), ("d", "m", "y")),
]

TITLE_STOPWORDS = {
    "m", "f", "d", "w", "x", "mwd", "fmd", "all", "genders", "and", "og", "y",
    "the", "a", "an", "of", "for", "to", "in", "til", "de", "la", "el",
}
SENIORITY = {"senior", "junior", "lead", "principal", "staff", "graduate", "trainee", "sr", "jr"}
COMPANY_SUFFIXES = {
    "a/s", "as", "aps", "ivs", "inc", "ltd", "llc", "gmbh", "ag", "ab", "sa", "sl",
    "bv", "nv", "plc", "corp", "co", "group", "holding",
}


def fold(text):
    """Lowercase and strip accents (æ->ae, ø->o, å->a, é->e)."""
    text = text.lower().replace("æ", "ae").replace("ø", "o").replace("å", "a").replace("ß", "ss")
    text = unicodedata.normalize("NFKD", text)
    return "".join(c for c in text if not unicodedata.combining(c))


def normalize_company(name):
    words = re.findall(r"[a-z0-9/]+", fold(name or ""))
    return " ".join(w for w in words if w not in COMPANY_SUFFIXES)


def normalize_title(title):
    words = re.findall(r"[a-z0-9+#]+", fold(title or ""))
    return " ".join(w for w in words if w not in TITLE_STOPWORDS)


def title_similarity(a, b):
    na, nb = normalize_title(a), normalize_title(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    # Ignore seniority differences for the token comparison.
    ta = set(na.split()) - SENIORITY
    tb = set(nb.split()) - SENIORITY
    jaccard = len(ta & tb) / len(ta | tb) if ta | tb else 0.0
    return max(SequenceMatcher(None, na, nb).ratio(), jaccard)


def parse_date(value):
    if not value:
        return None
    try:
        return datetime.strptime(value.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None


def find_deadlines(text):
    found = []
    for line in text.splitlines():
        if not re.search(DEADLINE_CUES, line, re.IGNORECASE):
            continue
        for pattern, order in DATE_PATTERNS:
            for match in pattern.finditer(line):
                parts = dict(zip(order, (int(g) for g in match.groups())))
                try:
                    found.append(date(parts["y"], parts["m"], parts["d"]))
                except ValueError:
                    continue
    return sorted(set(found))


def check_closed(text, today):
    folded = fold(text)
    phrases = [p for p in CLOSED_PHRASES if p in folded]
    deadlines = find_deadlines(text)
    past = [d for d in deadlines if d < today]
    upcoming = [d for d in deadlines if d >= today]
    if phrases or (past and not upcoming):
        verdict = "closed"
    elif not text.strip() or len(text.split()) < 40:
        verdict = "unclear"
    else:
        verdict = "open"
    return {
        "verdict": verdict,
        "closed_phrases": phrases,
        "deadlines": [d.isoformat() for d in deadlines],
        "deadline_passed": bool(past and not upcoming),
        "days_to_deadline": (upcoming[0] - today).days if upcoming else None,
        "word_count": len(text.split()),
    }


def load_seen(path):
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    seen = data.get("seen", {}) if isinstance(data, dict) else {}
    return seen if isinstance(seen, dict) else {}


def load_tracker(path):
    try:
        with open(path, newline="", encoding="utf-8") as handle:
            return list(csv.DictReader(handle))
    except FileNotFoundError:
        return []


def check_repost(company, title, url, seen, tracker, threshold=0.8):
    target_company = normalize_company(company)
    matches = []

    for key, entry in seen.items():
        if not isinstance(entry, dict):
            continue
        if normalize_company(entry.get("company", "")) != target_company:
            continue
        score = title_similarity(title, entry.get("title", ""))
        same_url = bool(url) and url in (key, entry.get("url"))
        if score < threshold and not same_url:
            continue
        matches.append({
            "source": "seen_jobs",
            "title": entry.get("title", ""),
            "url": entry.get("url", key),
            "date": entry.get("first_seen", ""),
            "status": entry.get("status", ""),
            "similarity": round(score, 2),
            "same_url": same_url,
        })

    for row in tracker:
        if normalize_company(row.get("company", "")) != target_company:
            continue
        score = title_similarity(title, row.get("role", ""))
        if score < threshold:
            continue
        matches.append({
            "source": "tracker",
            "title": row.get("role", ""),
            "url": row.get("source", ""),
            "date": row.get("date", ""),
            "status": row.get("status", ""),
            "similarity": round(score, 2),
            "same_url": False,
        })

    matches.sort(key=lambda m: m["date"] or "")
    different_url = [m for m in matches if m["source"] == "seen_jobs" and not m["same_url"]]
    dates = [parse_date(m["date"]) for m in matches if parse_date(m["date"])]

    if any(m["source"] == "tracker" for m in matches):
        verdict = "already_applied"
    elif different_url:
        verdict = "likely_repost"
    elif matches:
        verdict = "seen_before"
    else:
        verdict = "new"

    return {
        "verdict": verdict,
        "first_seen": min(dates).isoformat() if dates else None,
        "matches": matches,
    }


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="command", required=True)

    closed = sub.add_parser("closed", help="scan posting text for closed signals")
    closed.add_argument("--text-file", type=Path, required=True)
    closed.add_argument("--today", help="override today's date (YYYY-MM-DD)")

    repost = sub.add_parser("repost", help="look for earlier sightings of the same job")
    repost.add_argument("--company", required=True)
    repost.add_argument("--title", required=True)
    repost.add_argument("--url", default="")
    repost.add_argument("--seen", type=Path, default=DEFAULT_SEEN)
    repost.add_argument("--tracker", type=Path, default=DEFAULT_TRACKER)
    repost.add_argument("--threshold", type=float, default=0.8)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    if args.command == "closed":
        try:
            text = args.text_file.read_text(encoding="utf-8")
        except FileNotFoundError:
            print(f"Error: {args.text_file} not found", file=sys.stderr)
            return 1
        today = parse_date(args.today) if args.today else date.today()
        if today is None:
            print("Error: --today must be YYYY-MM-DD", file=sys.stderr)
            return 1
        result = check_closed(text, today)
    else:
        result = check_repost(
            args.company, args.title, args.url,
            load_seen(args.seen), load_tracker(args.tracker), args.threshold,
        )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
