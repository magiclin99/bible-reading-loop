"""
build_site_data.py

Turn data/oneyear_plan.json + verses/*.md into the static data the website
loads:

  site/data/index.json         lightweight list of 364 days (date + NT/OT refs)
  site/data/day-001.json ..    per-day bundle with full verse text + footnotes
  site/data/day-364.json

Run:  python build_site_data.py
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PLAN = ROOT / "data" / "oneyear_plan.json"
# The recovery-version verse source (verses/{書卷簡稱}/*.md) is NOT committed to
# this repo (~122MB / 31k files). To regenerate docs/data you must copy it in
# from the source project. The built output in docs/data/ is what the site uses.
VERSES = ROOT / "verses"
OUT = ROOT / "docs" / "data"
OUT.mkdir(parents=True, exist_ok=True)

# simplified full name (from plan) -> traditional abbreviation (verse dir name)
BOOK_ABBR = {
    "马太福音": "太", "马可福音": "可", "路加福音": "路", "约翰福音": "約", "使徒行传": "徒",
    "罗马书": "羅", "哥林多前书": "林前", "哥林多后书": "林後", "加拉太书": "加", "以弗所书": "弗",
    "腓立比书": "腓", "歌罗西书": "西", "帖撒罗尼迦前书": "帖前", "帖撒罗尼迦后书": "帖後",
    "提摩太前书": "提前", "提摩太后书": "提後", "提多书": "多", "腓利门书": "門", "希伯来书": "來",
    "雅各书": "雅", "彼得前书": "彼前", "彼得后书": "彼後", "约翰壹书": "約壹", "约翰贰书": "約貳",
    "约翰叁书": "約參", "犹大书": "猶", "启示录": "啟",
    "创世记": "創", "出埃及记": "出", "利未记": "利", "民数记": "民", "申命记": "申", "约书亚记": "書",
    "士师记": "士", "路得记": "得", "撒母耳记上": "撒上", "撒母耳记下": "撒下", "列王纪上": "王上",
    "列王纪下": "王下", "历代志上": "代上", "历代志下": "代下", "以斯拉记": "拉", "尼希米记": "尼",
    "以斯帖记": "斯", "约伯记": "伯", "诗篇": "詩", "箴言": "箴", "传道书": "傳", "雅歌": "歌",
    "以赛亚书": "賽", "耶利米书": "耶", "耶利米哀歌": "哀", "以西结书": "結", "但以理书": "但",
    "何西阿书": "何", "约珥书": "珥", "阿摩司书": "摩", "俄巴底亚书": "俄", "约拿书": "拿",
    "弥迦书": "彌", "那鸿书": "鴻", "哈巴谷书": "哈", "西番雅书": "番", "哈该书": "該",
    "撒迦利亚书": "亞", "玛拉基书": "瑪",
}

# traditional abbreviation -> traditional full name (for display)
ABBR_FULL = {
    "太": "馬太福音", "可": "馬可福音", "路": "路加福音", "約": "約翰福音", "徒": "使徒行傳",
    "羅": "羅馬書", "林前": "哥林多前書", "林後": "哥林多後書", "加": "加拉太書", "弗": "以弗所書",
    "腓": "腓立比書", "西": "歌羅西書", "帖前": "帖撒羅尼迦前書", "帖後": "帖撒羅尼迦後書",
    "提前": "提摩太前書", "提後": "提摩太後書", "多": "提多書", "門": "腓利門書", "來": "希伯來書",
    "雅": "雅各書", "彼前": "彼得前書", "彼後": "彼得後書", "約壹": "約翰壹書", "約貳": "約翰貳書",
    "約參": "約翰參書", "猶": "猶大書", "啟": "啟示錄",
    "創": "創世記", "出": "出埃及記", "利": "利未記", "民": "民數記", "申": "申命記", "書": "約書亞記",
    "士": "士師記", "得": "路得記", "撒上": "撒母耳記上", "撒下": "撒母耳記下", "王上": "列王紀上",
    "王下": "列王紀下", "代上": "歷代志上", "代下": "歷代志下", "拉": "以斯拉記", "尼": "尼希米記",
    "斯": "以斯帖記", "伯": "約伯記", "詩": "詩篇", "箴": "箴言", "傳": "傳道書", "歌": "雅歌",
    "賽": "以賽亞書", "耶": "耶利米書", "哀": "耶利米哀歌", "結": "以西結書", "但": "但以理書",
    "何": "何西阿書", "珥": "約珥書", "摩": "阿摩司書", "俄": "俄巴底亞書", "拿": "約拿書",
    "彌": "彌迦書", "鴻": "那鴻書", "哈": "哈巴谷書", "番": "西番雅書", "該": "哈該書",
    "亞": "撒迦利亞書", "瑪": "瑪拉基書",
}

# max verse per chapter, derived from the verse files on disk
def build_index():
    idx = {}
    for d in VERSES.iterdir():
        if not d.is_dir():
            continue
        for f in d.glob("*_*_*.md"):
            m = re.match(r"(.+)_(\d+)_(\d+)\.md$", f.name)
            if not m:
                continue
            ab, ch, v = m.group(1), int(m.group(2)), int(m.group(3))
            idx.setdefault(ab, {}).setdefault(ch, 0)
            idx[ab][ch] = max(idx[ab][ch], v)
    return idx

VIDX = build_index()


def expand(ab, sc, sv, ec, ev):
    """List (chapter, verse) from start to end inclusive, crossing chapters."""
    out = []
    ch = sc
    while ch <= ec:
        vmax = VIDX.get(ab, {}).get(ch, 0)
        start = sv if ch == sc else 1
        end = ev if ch == ec else vmax
        for v in range(start, end + 1):
            out.append((ch, v))
        ch += 1
    return out


def parse_verse_md(path):
    """Parse one verse markdown file -> {text, notes:[{label, body}]}."""
    text_lines, notes, note_label, note_buf = [], [], None, []
    section = "head"

    def flush_note():
        nonlocal note_label, note_buf
        if note_label is not None:
            body = "\n\n".join(
                p.strip() for p in "\n".join(note_buf).split("\n\n") if p.strip()
            )
            # 經文裡同一個註標出現兩次時，來源 md 會有兩個 **註N**，第二個是
            # 空殼（上游依 (note_loc, note_num) 逐列輸出所致）。留著會讓標號
            # 在一節內不唯一，且前端渲染出空白的註解框。
            if body:
                notes.append({"label": note_label, "body": body})
        note_label, note_buf = None, []

    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.rstrip()
        if s.startswith("## 註解"):
            section = "notes"
            continue
        if s.startswith("# ") or s == "---":
            continue
        if section == "head":
            if s.startswith(">"):
                text_lines.append(s.lstrip("> ").rstrip())
        else:  # notes
            m = re.match(r"^\*\*註(.+?)\*\*$", s.strip())
            if m:
                flush_note()
                note_label = m.group(1)
            elif note_label is not None:
                note_buf.append(s)
    flush_note()
    return {"text": " ".join(t for t in text_lines if t), "notes": notes}


def ref_str(ab, sc, sv, ec, ev):
    full = ABBR_FULL[ab]
    if sc == ec:
        return f"{full} {sc}:{sv}" if sv == ev else f"{full} {sc}:{sv}-{ev}"
    return f"{full} {sc}:{sv}-{ec}:{ev}"


def build_track(rec):
    """rec: plan nt/ot dict -> full track bundle with verses, or None.

    A day may span multiple books (segments); verses carry a book tag so the
    reader can group them.
    """
    if not rec or not rec.get("segments"):
        return None
    verses = []
    ref_parts = []
    for seg in rec["segments"]:
        ab = BOOK_ABBR[seg["book"]]
        sc, sv, ec, ev = seg["start_ch"], seg["start_v"], seg["end_ch"], seg["end_v"]
        ref_parts.append(ref_str(ab, sc, sv, ec, ev))
        for ch, v in expand(ab, sc, sv, ec, ev):
            f = VERSES / ab / f"{ab}_{ch:02d}_{v:02d}.md"
            parsed = parse_verse_md(f)
            verses.append({"book": ABBR_FULL[ab], "abbr": ab, "ch": ch, "v": v,
                           "text": parsed["text"], "notes": parsed["notes"]})
    first = rec["segments"][0]
    ab0 = BOOK_ABBR[first["book"]]
    return {
        "book": ABBR_FULL[ab0],
        "abbr": ab0,
        "ref": "；".join(ref_parts),
        "start": [first["start_ch"], first["start_v"]],
        "verses": verses,
    }


def main():
    if not VERSES.exists():
        raise SystemExit(
            f"找不到經文來源 {VERSES}/。\n"
            "docs/data/ 已是建好的成品；若要重建，請先從來源專案把 verses/ 複製進來。"
        )
    plan = json.loads(PLAN.read_text(encoding="utf-8"))
    index = []
    written = 0
    for day in plan:
        d = day["day"]
        nt = build_track(day.get("nt"))
        ot = build_track(day.get("ot"))
        if not nt and not ot:
            continue  # day 365 (404 source) — skip
        bundle = {"day": d, "date": day["date"], "nt": nt, "ot": ot}
        (OUT / f"day-{d:03d}.json").write_text(
            json.dumps(bundle, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        written += 1
        index.append({
            "day": d,
            "date": day["date"],
            "nt": {"book": nt["book"], "ref": nt["ref"], "count": len(nt["verses"])} if nt else None,
            "ot": {"book": ot["book"], "ref": ot["ref"], "count": len(ot["verses"])} if ot else None,
        })

    (OUT / "index.json").write_text(
        json.dumps({"days": index, "total": len(index)}, ensure_ascii=False,
                   separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"Wrote {written} day files + index.json to {OUT}")
    # size report
    sizes = sorted((f.stat().st_size for f in OUT.glob("day-*.json")), reverse=True)
    total = sum(f.stat().st_size for f in OUT.glob("*.json"))
    print(f"Largest day: {sizes[0]//1024}KB  avg: {sum(sizes)//len(sizes)//1024}KB  total: {total//1024//1024}MB")


if __name__ == "__main__":
    main()
