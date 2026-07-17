"""
make_audit_packets.py — 產出每天一份的稽核包，供 sub agent 判讀

兩個設計決定，都是量測出來的（見下）：

1. **按註解分組**，不是每個連結一份。同一條註解的段落只出現一次，所有連結
   用【1:…】【2:…】標在原文裡。省 52% 的量，而且判讀更準 —— 承接鏈是唯一
   會出錯的地方，agent 需要一眼看到整條鏈（可14:20 那筆就是要看到
   「路二二21～23 →…敘述…→ 19～20節」整串才判得出來）。

2. **跳過 book 層**（自帶卷名的引用，如「代上三11～12」）。那層解析器沒有
   推論任何東西，卷/章/節全寫在原文裡；會錯的是 bare/chapter 這種靠承接
   猜出來的。實測所有 findings 都出在 bare 層。跳過後再省 20%（合計 72%，
   364 天約 3.4M → 0.9M token）。
   代價：那 14762 筆永遠不被稽核。已知的理論風險是常用字被誤認成卷名
   （「但」= 但是／但以理書），實測未發現案例。

輸出：audit/packets/day-NNN.json
"""
import json
from pathlib import Path

import corpus

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "docs" / "data"
TSV = ROOT / "links.tsv"
OUT = ROOT / "audit" / "packets"

SKIP_SRC = {"book"}      # 見上；設成 set() 可恢復全層稽核
TARGET_TEXT_MAX = 60     # 判讀主題夠用，全文佔 15% 的量


def main():
    _, full, _ = corpus.load()

    # 每個連結的來源層級（links.tsv 的 src 欄），key = host@start
    src = {}
    for line in TSV.read_text(encoding="utf-8").splitlines()[1:]:
        p = line.split("\t")
        src[f"{p[0]}@{p[1]}"] = p[6]

    text = {}
    for f in sorted(DATA.glob("day-*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for tk in ("nt", "ot"):
            if not d.get(tk):
                continue
            for v in d[tk]["verses"]:
                text[(v["abbr"], v["ch"], v["v"])] = v["text"]

    OUT.mkdir(parents=True, exist_ok=True)
    n_items = n_links = 0
    for f in sorted(DATA.glob("day-*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        items = []
        for tk in ("nt", "ot"):
            if not d.get(tk):
                continue
            for v in d[tk]["verses"]:
                for n in v.get("notes") or []:
                    body = n["body"]
                    host = f"{v['abbr']}{v['ch']}:{v['v']}#{n['label']}"
                    sel = [(s, e, ab, ch, vv, lab)
                           for s, e, ab, ch, vv, lab in (n.get("links") or [])
                           if src.get(f"{host}@{s}") not in SKIP_SRC]
                    if not sel:
                        continue
                    # 註解全文，連結就地標成【1:原文】
                    marked, cur = [], 0
                    for i, (s, e, *_rest) in enumerate(sel, 1):
                        marked.append(body[cur:s])
                        marked.append(f"【{i}:{body[s:e]}】")
                        cur = e
                    marked.append(body[cur:])
                    items.append({
                        "host_id": host,
                        "host": f"{full[v['abbr']]} {v['ch']}:{v['v']} 註{n['label']}",
                        "text": "".join(marked),
                        "links": [{
                            "n": i,
                            "id": f"{host}@{s}",
                            "text": body[s:e],
                            "target": f"{full[ab]} {ch}:{vv}" + (f" 註{lab}" if lab else ""),
                            "target_text": text.get((ab, ch, vv), "（查無此節）")[:TARGET_TEXT_MAX],
                        } for i, (s, e, ab, ch, vv, lab) in enumerate(sel, 1)],
                    })
                    n_links += len(sel)
        n_items += len(items)
        (OUT / f.name).write_text(
            json.dumps({"day": d["day"], "items": items}, ensure_ascii=False, indent=1),
            encoding="utf-8")

    total = sum(p.stat().st_size for p in OUT.glob("day-*.json"))
    print(f"產出 {len(list(OUT.glob('day-*.json')))} 份稽核包")
    print(f"  {n_items} 條註解　{n_links} 個待驗連結（已跳過 {', '.join(SKIP_SRC)} 層）")
    print(f"  總計 {total/1024/1024:.1f}MB")
    sizes = sorted((p.stat().st_size for p in OUT.glob("day-*.json")), reverse=True)
    print(f"  最大 {sizes[0]//1024}KB　中位 {sizes[len(sizes)//2]//1024}KB")


if __name__ == "__main__":
    main()
