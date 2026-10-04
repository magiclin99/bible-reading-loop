"""
build_outline.py — 從恢復本資料庫匯出綱目，產出 outline.tsv（可稽核的清單）

清單是成品，docs/data 只是編譯產物（見 apply_outline.py）。資料庫 64MB 且不在
本 repo，匯出成 TSV 進版控後，重建網站就不再依賴它。

跑：  python build_outline.py [資料庫路徑]
      預設 ../cloud-food/db/bible.sqlite（該檔是 Git LFS，沒 pull 下來時只是
      一個指標檔，請改傳實體檔路徑）
輸出：outline.tsv + 一份報告

欄位：
  ref    綱目所在的經節，如「創1:2」
  off    綱目插在該節第幾個字之前（不計註標上標）；0 = 整節之前
  level  層級 1–6（壹／一／1／a／（一）／（1））
  text   綱目原文，含編號與經節範圍，以全形空白分段

資料庫欄位名會誤導：outline_all_big5_05 的 chapter_code 是「卷」，
related_chapters 是「章」，related_number 是「節」，related_section_code 其實是
經文表的 unit_code（0 = 整節，1 = 上半節，2 = 下半節）。半節的切點就是經文表
裡 unit 1 的長度，所以「一2下」這類綱目可以精確還原到字。
"""
import collections
import sqlite3
import sys
from pathlib import Path

import corpus

ROOT = Path(__file__).resolve().parent
DB = ROOT.parent / "cloud-food" / "db" / "bible.sqlite"
OUT = ROOT / "outline.tsv"

HEADER = ["ref", "off", "level", "text"]
SUP = set("⁰¹²³⁴⁵⁶⁷⁸⁹")


def main():
    db = Path(sys.argv[1]) if len(sys.argv) > 1 else DB
    if not db.exists() or db.stat().st_size < 1024:
        raise SystemExit(
            f"{db} 不是可用的資料庫（不存在，或只是 Git LFS 指標檔）。\n"
            "請傳入實體檔路徑：python build_outline.py /path/to/Bible20240820.sqlite"
        )
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)

    abbr = dict(con.execute(
        "SELECT chapter_code, REPLACE(abbreviation,'\"','') FROM volume_all_big5_01"))
    units = collections.defaultdict(dict)   # (卷, 章, 節) -> {unit: 經文}
    for b, ch, v, u, text in con.execute(
            "SELECT chapter_code, section_code, segment_code, unit_code, content "
            "FROM verse_all_final_big5_06"):
        units[(b, ch, v)][u] = text
    rows = con.execute(
        "SELECT chapter_code, related_chapters, related_number, related_section_code, "
        "level, outline_content FROM outline_all_big5_05 "
        "ORDER BY chapter_code, volume_order").fetchall()
    con.close()

    # 切點是用資料庫的經文算的，所以要確認它和本專案的經文逐字相同
    site = {(ab, ch, v): "".join(c for c in text if c not in SUP)
            for ab, ch, v, text in corpus.verses()}

    out, books, n_title, n_split, bad = [], set(), 0, set(), []
    for b, ch, v, u, level, text in rows:
        ab = abbr[b]
        if v == 0:
            # 詩篇卷二～卷四的卷標題掛在章首標題（節 0），本專案沒有節 0
            v, n_title = 1, n_title + 1
        us = units[(b, ch, v)]
        off = sum(len(us[k]) for k in sorted(us) if k < u) if u else 0
        plain = "".join(us[k] for k in sorted(us))
        if site.get((ab, ch, v)) != plain or not 0 <= off < len(plain):
            bad.append(f"{ab}{ch}:{v}")
            continue
        if off:
            n_split.add((ab, ch, v))
        books.add(ab)
        out.append([f"{ab}{ch}:{v}", str(off), str(level), text.strip()])

    if bad:
        raise SystemExit(f"{len(bad)} 條綱目對不上本專案的經文：{bad[:10]}")

    OUT.write_text(
        "\n".join("\t".join(r) for r in [HEADER] + out) + "\n", encoding="utf-8")

    levels = collections.Counter(r[2] for r in out)
    print(f"寫入 {len(out)} 條綱目（{len(books)} 卷）→ {OUT.name}")
    print("各層：" + "、".join(f"L{k} {levels[k]}" for k in sorted(levels)))
    print(f"落在節中間的綱目：{sum(1 for r in out if r[1] != '0')} 條，分佈於 {len(n_split)} 節")
    print(f"詩篇卷標題由節 0 改掛第 1 節：{n_title} 條")


if __name__ == "__main__":
    main()
