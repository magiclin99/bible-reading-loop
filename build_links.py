"""
build_links.py — 解析全部註解，產出 links.tsv（可稽核的清單）

清單是成品，docs/data 只是編譯產物（見 apply_links.py）。這樣調解析器不會
每次都污染 10MB 的 git 歷史。

跑：  python build_links.py
輸出：links.tsv + 一份報告

報告裡最重要的是「未覆蓋的阿拉伯數字」：全語料的阿拉伯數字幾乎專用於節數，
所以未覆蓋 ≈ 0 代表沒有漏掉的引用形式。這個數字若變大，就是有新形式冒出來。
"""
import collections
import re
from pathlib import Path

import corpus
from refs import Parser

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "links.tsv"
OVERRIDES = ROOT / "links_overrides.tsv"

HEADER = ["host", "start", "end", "text", "target", "note", "src"]


def load_overrides():
    """稽核抓出的語意錯誤，逐筆修正。{id: (action, value)}

    id = host#註標@body位移，等同 links.tsv 的「host欄@start欄」。改規則會
    拆東牆補西牆（見 links_overrides.tsv 開頭說明），故已知錯誤在此覆寫。
    """
    ov = {}
    if not OVERRIDES.exists():
        return ov
    for line in OVERRIDES.read_text(encoding="utf-8").splitlines():
        line = line.rstrip()
        if not line or line.startswith("#") or line.startswith("id\t"):
            continue
        parts = line.split("\t")
        ov[parts[0]] = (parts[1], parts[2])
    return ov


def main():
    vmax, full, notes = corpus.load()
    P = Parser(vmax)
    overrides = load_overrides()
    ov_applied = set()

    # 目標經節實際有哪些註標。用來查核「見X註N」指的註是否真的存在 ——
    # 這個檢查是很好的 bug 偵測器：它抓出過 6 個承接錯誤（鏈被「見」、
    # 「至」、「註1三段」打斷，害引用退回 host 卷），而那些錯誤指向的
    # 經節是存在的，光靠經節驗證抓不到。
    labels = {}
    for ab, ch, v, lab, _b, _d, _t in notes:
        labels.setdefault((ab, ch, v), set()).add(lab)

    rows = []
    by_src = collections.Counter()
    uncovered = collections.Counter()
    ghost_notes = []
    n_digits = n_covered = n_killed = 0

    for ab, ch, v, label, body, day, tk in notes:
        links, killed = P.parse_all(body, ab, ch)
        n_killed += len(killed)
        mask = bytearray(len(body))
        # 被「者同」抑制的也算「已解釋」—— 它們是刻意不連，不是漏認
        for l in killed:
            mask[l.start:l.end] = b"\1" * (l.end - l.start)
        for l in links:
            mask[l.start:l.end] = b"\1" * (l.end - l.start)
            by_src[l.src] += 1
            host = f"{ab}{ch}:{v}#{label}"
            target = f"{l.abbr}{l.ch}:{l.v}"
            note = l.note

            # 人工覆寫（稽核修正）：retarget 換目標、drop 刪連結
            ov = overrides.get(f"{host}@{l.start}")
            if ov:
                ov_applied.add(f"{host}@{l.start}")
                action, value = ov
                if action == "drop":
                    continue
                if action == "retarget":
                    target, _, note = value.partition("#")
                    note = note or None

            if note and note not in labels.get((l.abbr, l.ch, l.v), set()):
                # 目標沒有這個註標。連結保留（經節是存在的），但降級掉註標，
                # 免得前端去展開一個不存在的註。
                ghost_notes.append((body[l.start:l.end], f"{l.abbr}{l.ch}:{l.v}",
                                    note, host))
                note = None
            rows.append([
                host,
                str(l.start), str(l.end),
                body[l.start:l.end].replace("\t", " "),
                target,
                note or "-",
                l.src,
            ])
        for m in re.finditer(r"\d+", body):
            n_digits += 1
            if all(mask[k] for k in range(m.start(), m.end())):
                n_covered += 1
            else:
                ctx = body[max(0, m.start() - 14):m.end() + 8].replace("\n", "")
                uncovered[ctx] += 1

    with OUT.open("w", encoding="utf-8") as f:
        f.write("\t".join(HEADER) + "\n")
        for r in rows:
            f.write("\t".join(r) + "\n")

    stale = set(overrides) - ov_applied
    if overrides:
        print(f"人工覆寫：套用 {len(ov_applied)}/{len(overrides)} 筆"
              + (f"　⚠ 失效 {len(stale)} 筆（id 對不到，可能 body 位移變了）: {stale}" if stale else ""))
    print(f"清單：{OUT}  共 {len(rows)} 個連結")
    print(f"  來源層級  " + "  ".join(f"{k}={v}" for k, v in by_src.most_common()))
    print(f"    book    有卷名，如「太十二42」")
    print(f"    chapter 章+節，卷承接自鏈")
    print(f"    bare    純節，卷與章都承接")
    print(f"    anaphor 本書/本章/該章")
    print(f"  「者同」抑制  {n_killed}（刻意不連的譯詞註記）")
    miss = n_digits - n_covered
    print(f"\n阿拉伯數字 {n_digits}　已解釋 {n_covered} ({n_covered/n_digits*100:.2f}%)"
          f"　未解釋 {miss} ({miss/n_digits*100:.2f}%)")
    if uncovered:
        print("\n未解釋取樣（這裡若出現新形式，代表有沒問到的引用寫法）:")
        for ctx, n in uncovered.most_common(15):
            print(f"  {n:3d}  …{ctx}…")

    # 這份清單要盯著看：多半代表鏈的承接斷錯了地方，而不是來源缺註。
    print(f"\n指向不存在的註標 {len(ghost_notes)} 筆（已降級為純經節連結）:")
    for text, target, note, host in ghost_notes:
        print(f"  {text!r} → {target} 註{note}   於 {host}")


if __name__ == "__main__":
    main()
