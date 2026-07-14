"""
Scrape the one-year Bible reading plan from:
  https://line.twgbr.org/recoveryversion/oneyear/

Two tracks:
  NT: n001.html – n365.html
  OT: o001.html – o365.html

Output: data/oneyear_plan.json
"""

import json
import os
import re
import time
import requests
from bs4 import BeautifulSoup
from pathlib import Path
from datetime import date, timedelta

BASE = "https://line.twgbr.org/recoveryversion/oneyear/"
# Optional custom CA bundle via env var; defaults to system trust store.
CA = os.environ.get("ONEYEAR_CA_BUNDLE")
OUT = Path(__file__).resolve().parent / "data" / "oneyear_plan.json"
OUT.parent.mkdir(parents=True, exist_ok=True)

SESSION = requests.Session()
if CA:
    SESSION.verify = CA

# ── Chinese numeral → integer ──────────────────────────────────────────────
# 〇 (U+3007) is the ideographic zero used in positional notation for Psalms
# 100+ (e.g. 一〇〇 = 100, 一四五 = 145, 一五〇 = 150).
_ONES = {"零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4,
         "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}

# Single-chapter books have no "第一章" header on their day page, so the parser
# must force chapter 1 rather than inherit the previous day's chapter.
_SINGLE_CHAPTER_BOOKS = {"俄巴底亚书", "腓利门书", "约翰贰书", "约翰叁书", "犹大书"}

# All 66 book names (simplified) as they appear in page titles / <h1> headers.
# Used to detect a mid-page book change (a day can span two books).
_BOOK_NAMES = {
    "马太福音", "马可福音", "路加福音", "约翰福音", "使徒行传", "罗马书", "哥林多前书",
    "哥林多后书", "加拉太书", "以弗所书", "腓立比书", "歌罗西书", "帖撒罗尼迦前书",
    "帖撒罗尼迦后书", "提摩太前书", "提摩太后书", "提多书", "腓利门书", "希伯来书",
    "雅各书", "彼得前书", "彼得后书", "约翰壹书", "约翰贰书", "约翰叁书", "犹大书",
    "启示录", "创世记", "出埃及记", "利未记", "民数记", "申命记", "约书亚记", "士师记",
    "路得记", "撒母耳记上", "撒母耳记下", "列王纪上", "列王纪下", "历代志上", "历代志下",
    "以斯拉记", "尼希米记", "以斯帖记", "约伯记", "诗篇", "箴言", "传道书", "雅歌",
    "以赛亚书", "耶利米书", "耶利米哀歌", "以西结书", "但以理书", "何西阿书", "约珥书",
    "阿摩司书", "俄巴底亚书", "约拿书", "弥迦书", "那鸿书", "哈巴谷书", "西番雅书",
    "哈该书", "撒迦利亚书", "玛拉基书",
}

def cn2int(s: str) -> int:
    """Convert a Chinese chapter/psalm number string to int.

    Handles two notations:
      - multiplicative (十/百): 九十九 → 99
      - positional (with 〇, or bare digit chars): 一〇〇 → 100, 一四五 → 145
    """
    s = s.strip()
    if not s:
        return 0
    # Positional notation: contains 〇, or is a run of digit-chars with no 十/百.
    if "〇" in s or (len(s) >= 2 and "十" not in s and "百" not in s
                    and all(c in _ONES for c in s)):
        try:
            return int("".join(str(_ONES[c]) for c in s))
        except (KeyError, ValueError):
            return 0
    # Handle hundreds: 一百…
    hundreds = 0
    if "百" in s:
        idx = s.index("百")
        h_part = s[:idx]
        hundreds = _ONES.get(h_part, 1) * 100
        s = s[idx + 1:]
        if s.startswith("零"):
            s = s[1:]
    # Handle tens
    tens = 0
    if "十" in s:
        idx = s.index("十")
        t_part = s[:idx]
        tens = _ONES.get(t_part, 1) * 10
        s = s[idx + 1:]
    # Handle ones
    ones = _ONES.get(s, 0) if s else 0
    return hundreds + tens + ones


def _title_book(soup) -> str:
    t = soup.title.string if soup.title else ""
    # Format: "读经一年一遍第001天-马太福音"
    m = re.search(r"[-–](.+)$", t)
    return m.group(1).strip() if m else ""


def parse_page(html: str, prev_chapter: int = None):
    """
    Parse one day's page HTML.

    A single day can span more than one book (e.g. 王上22 → 王下1); the page
    marks the new book with an <h1> heading. We walk the document in order,
    tracking the current book and chapter, and collect an ordered list of
    (book, chapter, verse). Consecutive verses of the same book are grouped
    into "segments".

    Returns dict with:
      segments  : [{book, start_ch, start_v, end_ch, end_v}, ...]
      book      : first book (backward-compat)
      start_ch/start_v : first verse of the day
      end_book  : last book
      end_ch/end_v     : last verse of the day
      key_verse, tomorrow_hint
    prev_chapter: chapter at the end of the previous day, used when a day
                  continues mid-chapter with no chapter header.
    """
    soup = BeautifulSoup(html, "html.parser")
    title_book = _title_book(soup)

    def is_single(bk):
        return bk in _SINGLE_CHAPTER_BOOKS

    current_book = title_book
    single_chapter = is_single(current_book)
    current_ch = 1 if single_chapter else prev_chapter  # may be None
    verses = []  # ordered [(book, ch, v)]

    for elem in soup.find_all(["h1", "b", "sup"]):
        if elem.name == "h1":
            name = elem.get_text(strip=True)
            if name in _BOOK_NAMES and name != current_book:
                current_book = name
                single_chapter = is_single(name)
                current_ch = 1 if single_chapter else None  # new book restarts
        elif elem.name == "b":
            if single_chapter:
                continue
            m = re.match(r"^第(.+?)[章篇]$", elem.get_text(strip=True))
            if m:
                ch = cn2int(m.group(1))
                if ch > 0:
                    current_ch = ch
        elif elem.name == "sup" and not elem.find("a"):
            # Verse numbers may carry a 上/下 split-verse suffix (e.g. "1上").
            m = re.match(r"^(\d+)", elem.get_text(strip=True))
            if m and current_ch is not None:
                v = int(m.group(1))
                if v == 0:  # Psalm titles are verse 0; skip for range tracking
                    continue
                verses.append((current_book, current_ch, v))

    # Group ordered verses into per-book segments
    segments = []
    for bk, ch, v in verses:
        if segments and segments[-1]["book"] == bk:
            segments[-1]["end_ch"] = ch
            segments[-1]["end_v"] = v
        else:
            segments.append({"book": bk, "start_ch": ch, "start_v": v,
                             "end_ch": ch, "end_v": v})

    # Key verse and tomorrow hint (in <b> tags)
    key_verse = ""
    tomorrow_hint = ""
    for b in soup.find_all("b"):
        t = b.get_text(strip=True)
        if t.startswith("重点经节") or t.startswith("重點經節"):
            key_verse = t
        elif t.startswith("明天:") or t.startswith("明天："):
            tomorrow_hint = t

    first = segments[0] if segments else None
    last = segments[-1] if segments else None
    return {
        "segments": segments,
        "book": first["book"] if first else title_book,
        "start_ch": first["start_ch"] if first else None,
        "start_v": first["start_v"] if first else None,
        "end_book": last["book"] if last else None,
        "end_ch": last["end_ch"] if last else None,
        "end_v": last["end_v"] if last else None,
        "key_verse": key_verse,
        "tomorrow_hint": tomorrow_hint,
        "_end_chapter": last["end_ch"] if last else prev_chapter,
    }


def fetch(url: str, retries: int = 4) -> str:
    delay = 2
    for attempt in range(retries):
        try:
            r = SESSION.get(url, timeout=20)
            r.encoding = "utf-8"
            if r.status_code == 200:
                return r.text
        except Exception as e:
            print(f"  Error {url}: {e}")
        if attempt < retries - 1:
            time.sleep(delay)
            delay *= 2
    return ""


def scrape_track(prefix: str, label: str, year: int = 2026):
    """Scrape one track (NT or OT) and return list of 365 dicts."""
    results = []
    current_chapter = None
    start_date = date(year, 1, 1)

    for day in range(1, 366):
        url = f"{BASE}{prefix}{day:03d}.html"
        d = start_date + timedelta(days=day - 1)
        print(f"  [{label}] Day {day:3d} {d}  {url}")

        html = fetch(url)
        if not html:
            print(f"    !! FAILED to fetch day {day}")
            results.append({
                "day": day,
                "date": str(d),
                "track": label,
                "book": None,
                "start_ch": None,
                "start_v": None,
                "end_book": None,
                "end_ch": None,
                "end_v": None,
                "range": None,
                "segments": [],
                "key_verse": "",
                "tomorrow_hint": "",
            })
            continue

        info = parse_page(html, prev_chapter=current_chapter)
        current_chapter = info["_end_chapter"]

        # Format range string (may span two books)
        range_str = None
        for seg in info["segments"]:
            sc, sv, ec, ev = seg["start_ch"], seg["start_v"], seg["end_ch"], seg["end_v"]
            piece = (f"{seg['book']} {sc}:{sv}-{ev}" if sc == ec
                     else f"{seg['book']} {sc}:{sv}-{ec}:{ev}")
            range_str = piece if range_str is None else f"{range_str}；{piece}"

        results.append({
            "day": day,
            "date": str(d),
            "track": label,
            "book": info["book"],
            "start_ch": info["start_ch"],
            "start_v": info["start_v"],
            "end_book": info["end_book"],
            "end_ch": info["end_ch"],
            "end_v": info["end_v"],
            "range": range_str,
            "segments": info["segments"],
            "key_verse": info["key_verse"],
            "tomorrow_hint": info["tomorrow_hint"],
        })

        # small polite delay
        time.sleep(0.1)

    return results


def main():
    print("Scraping NT track (n001–n365)…")
    nt = scrape_track("n", "NT")

    print()
    print("Scraping OT track (o001–o365)…")
    ot = scrape_track("o", "OT")

    # Merge by day
    plan = {}
    for rec in nt:
        day = rec["day"]
        plan[day] = {"day": day, "date": rec["date"], "nt": rec, "ot": None}
    for rec in ot:
        day = rec["day"]
        if day in plan:
            plan[day]["ot"] = rec
        else:
            plan[day] = {"day": day, "date": rec["date"], "nt": None, "ot": rec}

    output = [plan[d] for d in sorted(plan.keys())]
    OUT.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    print(f"\nSaved {len(output)} days → {OUT}")

    # Quick sanity check
    print("\nSample entries:")
    for d in [1, 32, 60, 100, 200, 300, 365]:
        entry = plan.get(d, {})
        nt_r = entry.get("nt", {}) or {}
        ot_r = entry.get("ot", {}) or {}
        print(f"  Day {d:3d}: NT={nt_r.get('range','?')}  OT={ot_r.get('range','?')}")


if __name__ == "__main__":
    main()
