"""
apply_links.py — 把 links.tsv 編譯進 docs/data

links.tsv 是成品，這支只是把它攤進網站要載的 JSON。改解析器 → 重跑
build_links.py → 檢查 links.tsv 的 diff → 再跑這支。

同時往 index.json 補兩張前端用的表：
  loc   {簡稱: [[章, 節, 天, track], ...]}  730 筆日段起點，用來把引用座標
        換算成「第幾天／哪個 track」。href 存的是「創5:1」而不是「第6天」，
        因為天數是讀經計畫的產物 —— 計畫一改，存天數的連結就全爛了。
  abbr  {簡稱: 全名}  前端要用全名比對 .verse[data-bk]

跑：  python apply_links.py
"""
import collections
import json
from pathlib import Path

import corpus

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "docs" / "data"
TSV = ROOT / "links.tsv"


def load_tsv():
    """{host_ref: [[起, 訖, 簡稱, 章, 節, 註標|None], ...]}"""
    out = collections.defaultdict(list)
    lines = TSV.read_text(encoding="utf-8").splitlines()
    for line in lines[1:]:
        host, s, e, _text, target, note, _src = line.split("\t")
        # target 形如「創38:6」：卷名是非數字前綴，章是其後的數字
        ref, v = target.rsplit(":", 1)
        i = 0
        while i < len(ref) and not ref[i].isdigit():
            i += 1
        ab, ch = ref[:i], int(ref[i:])
        out[host].append([int(s), int(e), ab, ch, int(v),
                          None if note == "-" else note])
    return out


def main():
    if not TSV.exists():
        raise SystemExit(f"找不到 {TSV}，請先跑 python build_links.py")
    links = load_tsv()

    n_notes = n_links = n_dropped = 0
    for f in sorted(DATA.glob("day-*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for tk in ("nt", "ot"):
            if not d.get(tk):
                continue
            for v in d[tk]["verses"]:
                ns = v.get("notes") or []
                # 先丟掉空殼註解（見 corpus.load 的說明）。它們讓標號在一節內
                # 不唯一，且前端會把它們渲染成只有標題、內容空白的框。
                keep = [n for n in ns if n["body"].strip()]
                n_dropped += len(ns) - len(keep)
                v["notes"] = keep
                for n in keep:
                    key = f"{v['abbr']}{v['ch']}:{v['v']}#{n['label']}"
                    ls = links.get(key)
                    if ls:
                        n["links"] = ls
                        n_notes += 1
                        n_links += len(ls)
                    elif "links" in n:
                        del n["links"]      # 重跑時清掉舊的
        f.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")),
                     encoding="utf-8")

    # index.json 補 loc / abbr
    idx_path = DATA / "index.json"
    idx = json.loads(idx_path.read_text(encoding="utf-8"))
    _, full, _ = corpus.load()
    idx["loc"] = corpus.locator()
    idx["abbr"] = full
    idx_path.write_text(json.dumps(idx, ensure_ascii=False, separators=(",", ":")),
                        encoding="utf-8")

    total = sum(f.stat().st_size for f in DATA.glob("*.json"))
    print(f"寫入 {n_links} 個連結，分佈於 {n_notes} 條註解")
    print(f"丟棄 {n_dropped} 條空殼註解（上游 extract_verses.py 的產物）")
    print(f"index.json：loc {sum(len(v) for v in idx['loc'].values())} 筆日段起點"
          f"、abbr {len(idx['abbr'])} 卷")
    print(f"docs/data 總計 {total/1024/1024:.1f}MB")


if __name__ == "__main__":
    main()
