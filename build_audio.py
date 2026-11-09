"""
build_audio.py — 恢復本朗讀音檔的時間軸 → audio.tsv

來源是 recoveryversion.twgbr.org（網上聖經恢復本）。它每章一個 mp3，另有
一份逐段時間軸，打包成 /assets/{卷}-{章}-{hash}.js，內容長這樣：

    [{start:68.2, end:72.48, selector:"#verse-1"},
     {start:78.43,end:85.5,  selector:"#verse-2-1"},      ← 被綱目切開的上半節
     {start:75.03,end:78.43, selector:"#outline-2-1-0"},  ← 插在 verse-2-1 前的綱目
     {start:64.72,end:66.12, selector:".chapter-title-block .title"}, ...]

selector 綁的是它自己的 DOM，所以這裡把它換成聖經座標（地雷 1：存座標）：

  #verse-V          → v  節 V 整節（part 0）
  #verse-V-K        → v  節 V 的第 K 塊（我們的切法相同：綱目落在節中間就切）
  #outline-V-P-J    → o  節 V 的第幾條綱目（依 P、J 排序後的序號）
  .chapter-title…   → t  章標題「第 N 章」
  .book-title、.topic-line（卷首的書名、著者、主題等）→ 不收，網站沒顯示這些

輸出 audio.tsv（進版控、可稽核），apply_audio.py 再把它編譯進 docs/data。

跑：  python build_audio.py            # 抓時間軸（有快取）→ audio.tsv + 報告
      python build_audio.py --offline  # 只用快取
"""
import argparse
import collections
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

import corpus

ROOT = Path(__file__).resolve().parent
TSV = ROOT / "audio.tsv"
CACHE = ROOT / ".cache" / "timeline"
SITE = "https://recoveryversion.twgbr.org"

# 聖經卷序。音檔網址的卷號與英文卷名見 apply_audio.py
ORDER = ["創", "出", "利", "民", "申", "書", "士", "得", "撒上", "撒下", "王上", "王下",
         "代上", "代下", "拉", "尼", "斯", "伯", "詩", "箴", "傳", "歌", "賽", "耶", "哀",
         "結", "但", "何", "珥", "摩", "俄", "拿", "彌", "鴻", "哈", "番", "該", "亞", "瑪",
         "太", "可", "路", "約", "徒", "羅", "林前", "林後", "加", "弗", "腓", "西", "帖前",
         "帖後", "提前", "提後", "多", "門", "來", "雅", "彼前", "彼後", "約壹", "約貳",
         "約參", "猶", "啟"]


def get(url):
    for i in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "bible-reading-loop build"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8")
        except Exception:
            if i == 3:
                raise
            time.sleep(2 ** (i + 1))


def fetch_all(offline):
    """{(卷號, 章): 時間軸 list}，抓過的放 .cache/timeline/"""
    CACHE.mkdir(parents=True, exist_ok=True)
    manifest = CACHE / "manifest.json"
    if offline:
        files = json.loads(manifest.read_text())
    else:
        html = get(SITE + "/")
        main = re.search(r'src="(/assets/index-[^"]+\.js)"', html).group(1)
        js = get(SITE + main)
        files = dict(re.findall(
            r'"\.\./assets/timeline/(\d+-\d+)\.json":\(\)=>\w+\(\(\)=>import\("\./([^"]+)"\)', js))
        if len(files) < 1000:
            raise SystemExit(f"只找到 {len(files)} 份時間軸，網站改版了？")
        manifest.write_text(json.dumps(files, indent=0))
    out = {}
    for i, (key, name) in enumerate(sorted(files.items())):
        f = CACHE / name
        if not f.exists():
            if offline:
                raise SystemExit(f"快取裡沒有 {name}")
            f.write_text(get(f"{SITE}/assets/{name}"), encoding="utf-8")
            print(f"\r抓時間軸 {i + 1}/{len(files)}", end="", file=sys.stderr)
        src = f.read_text(encoding="utf-8")
        # 小檔是 JS 物件字面值 {start:1.2,…}；大檔是 JSON.parse('[{"start":1.2,…}]')
        rows = re.findall(
            r'\{"?start"?:([\d.]+),"?end"?:([\d.]+),"?selector"?:"((?:[^"\\]|\\.)*)"\}', src)
        bk, ch = map(int, key.split("-"))
        out[(bk, ch)] = [(float(s), float(e), sel) for s, e, sel in rows]
    print(file=sys.stderr)
    return out


def parse(rows):
    """→ verses {節: {part: [(start,end)]}}, outlines {節: [(P,J,start,end)]}, title, 未收"""
    verses = collections.defaultdict(lambda: collections.defaultdict(list))
    outlines = collections.defaultdict(list)
    title, skipped = [], collections.Counter()
    for s, e, sel in rows:
        if e <= s:
            skipped["零長度"] += 1
            continue
        if m := re.fullmatch(r"#verse-(\d+)(?:-(\d+))?", sel):
            verses[int(m[1])][int(m[2] or 0)].append((s, e))
        elif m := re.fullmatch(r"#outline-(\d+)-(\d+)-(\d+)", sel):
            outlines[int(m[1])].append((int(m[2]), int(m[3]), s, e))
        elif sel == ".chapter-title-block .title":
            title.append((s, e))
        else:
            skipped[re.sub(r"\(\d+\)", "(n)", sel)] += 1
    return verses, outlines, title, skipped


def misaligned(verses):
    """對齊失敗的節。

    來源的對齊器有時漏掉一長串節，漏掉的頭一節被塞到後面去，例如箴14:1 標在
    126 秒、和 14:16（128 秒）疊在一起，而 14:2～15 都不見了 —— 實際上 14:1
    在章標題後就唸了。這種節的時間是錯的，留著會把片段起點拉到兩分鐘後。
    判準：跟下一個有時間的節重疊超過 1 秒，且中間隔著沒有時間的節。
    """
    bad = []
    order = sorted(verses)
    for a, b in zip(order, order[1:]):
        if b - a > 1 and max(e for parts in verses[a].values() for _, e in parts) \
                > min(s for parts in verses[b].values() for s, _ in parts) + 1:
            bad.append(a)
    return bad


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()

    timelines = fetch_all(args.offline)
    vmax, _, _ = corpus.load()

    # 我們這邊每節有幾條綱目、切成幾塊（綱目落在節中間 = 多一塊）
    ours = {}
    for ab, ch, v, text in corpus.verses():
        ours[(ab, ch, v)] = None
    for f in sorted((ROOT / "docs" / "data").glob("day-*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for tk in ("nt", "ot"):
            for vs in (d.get(tk) or {}).get("verses", []):
                ol = vs.get("outline") or []
                ours[(vs["abbr"], vs["ch"], vs["v"])] = (len(ol), 1 + len({a for a, _, _ in ol if a}))

    lines = ["ref\tkind\tidx\tstart\tend"]
    rep = collections.Counter()
    skipped_all = collections.Counter()
    problems = []
    for ab in ORDER:
        bk = ORDER.index(ab) + 1
        chs = sorted(c for a, c in vmax if a == ab)
        for ch in chs:
            rows = timelines.get((bk, ch))
            if rows is None:
                problems.append(f"{ab}{ch}：網站沒有時間軸（音檔照樣播，只是不跟著高亮）")
                rep["缺章"] += 1
                continue
            verses, outlines, title, skipped = parse(rows)
            skipped_all.update(skipped)
            for v in misaligned(verses):
                problems.append(f"{ab}{ch}:{v}：時間落在後面的節裡（對齊失敗），丟掉")
                rep["對齊失敗"] += 1
                del verses[v]
            for s, e in title[:1]:
                lines.append(f"{ab}{ch}:0\tt\t0\t{s:g}\t{e:g}")
            for v in range(1, vmax[(ab, ch)] + 1):
                n_ol, n_part = ours.get((ab, ch, v)) or (0, 1)
                parts = verses.get(v, {})
                if not parts:
                    problems.append(f"{ab}{ch}:{v}：時間軸沒有這一節")
                    rep["缺節"] += 1
                for k in sorted(parts):
                    if k > n_part:
                        problems.append(f"{ab}{ch}:{v}：時間軸切成 {max(parts)} 塊，我們只有 {n_part} 塊，第 {k} 塊併入整節")
                        rep["切法不同"] += 1
                    for s, e in parts[k]:
                        lines.append(f"{ab}{ch}:{v}\tv\t{k if k <= n_part else 0}\t{s:g}\t{e:g}")
                ol = sorted(outlines.get(v, []))
                if len(ol) != n_ol:
                    problems.append(f"{ab}{ch}:{v}：時間軸 {len(ol)} 條綱目，我們有 {n_ol} 條，綱目不跟著高亮")
                    rep["綱目數不同"] += 1
                    continue
                for j, (_, _, s, e) in enumerate(ol):
                    lines.append(f"{ab}{ch}:{v}\to\t{j}\t{s:g}\t{e:g}")
            extra = [v for v in verses if v > vmax[(ab, ch)]] + [v for v in outlines if v > vmax[(ab, ch)]]
            if extra:
                problems.append(f"{ab}{ch}：時間軸有我們沒有的節 {sorted(set(extra))}")
                rep["多出的節"] += 1
            rep["章"] += 1

    TSV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    kinds = collections.Counter(l.split("\t")[1] for l in lines[1:])
    print(f"寫入 {TSV.name}：{len(lines) - 1} 列（節 {kinds['v']}、綱目 {kinds['o']}、章標題 {kinds['t']}）")
    print(f"涵蓋 {rep['章']} 章；" + "、".join(f"{k} {v}" for k, v in rep.items() if k != "章"))
    print("沒收的 selector：" + "、".join(f"{k}×{v}" for k, v in skipped_all.most_common()))
    for p in problems:
        print("  " + p)


if __name__ == "__main__":
    main()
