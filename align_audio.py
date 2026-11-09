"""
align_audio.py — 用語音辨識補上時間軸缺的地方 → audio_asr.tsv

audio.tsv 來自網上聖經恢復本，但有洞（見 CLAUDE.md 地雷 18）：漏掉的節、
對齊失敗被丟掉的節、條數對不上而沒收的綱目、整章沒時間軸的申24 與多3。
這支只處理那些洞：

  1. 把每章的朗讀單位依序排好：章標題、綱目、經文（被綱目切開的節算兩塊）。
  2. audio.tsv 裡有時間的單位當錨點；夾在兩個錨點之間、沒有時間的一串單位
     就是一個洞，對應的音檔區間是「前一錨點結束 ～ 下一錨點開始」。
  3. 用 faster-whisper 辨識那一小段，拿到逐字時間。
  4. 辨識結果（轉成繁體）和該段經文逐字比對（difflib），每個單位取它對上的
     第一個字和最後一個字的時間。對上的字太少就不收，寧缺勿錯。

輸出 audio_asr.tsv，欄位同 audio.tsv，多一欄 match（該單位對上的字數比例）
供稽核。apply_audio.py 會把兩份一起編進 docs/data。

需要：ffmpeg、pip install faster-whisper opencc-python-reimplemented
跑：  python align_audio.py                 # 全部的洞；中斷了再跑會接續（進度在 .cache/）
      python align_audio.py --fresh         # 不接續，全部重做
      python align_audio.py 箴2 申24        # 只重做這幾章
      python align_audio.py --check 8       # 自我驗證準度
      python align_audio.py --model medium  # 預設 small
"""
import argparse
import collections
import difflib
import json
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

from apply_audio import audio_file, load_tsv as load_cues
from build_audio import ORDER

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "docs" / "data"
OUT = ROOT / "audio_asr.tsv"
PROGRESS = ROOT / ".cache" / "align_progress.json"
MP3 = ROOT / ".cache" / "mp3"
BASE = "https://plan.bible365.today/plan/mp3/bible/"
KINDS = "vot"
MIN_MATCH = 0.4          # 一個單位至少要對上這麼多比例的字才收
CN = "零一二三四五六七八九"


def cn_num(n):
    """119 → 一百一十九（章標題「第一百一十九篇」用）"""
    if n < 10:
        return CN[n]
    if n < 20:
        return "十" + (CN[n % 10] if n % 10 else "")
    if n < 100:
        return CN[n // 10] + "十" + (CN[n % 10] if n % 10 else "")
    rest = n % 100
    return CN[n // 100] + "百" + ("" if not rest else ("零" + CN[rest] if rest < 10 else
                                                     ("一" + cn_num(rest) if rest < 20 else cn_num(rest))))


def clean(s):
    """只留漢字和數字：標點、註標上標都不唸"""
    return "".join(c for c in s if "一" <= c <= "鿿" or c.isdigit() or c in CN)


def outline_title(text):
    """「壹　神的創造　一1～二25」→ 唸出來的是「壹神的創造」，範圍不唸"""
    parts = text.split("　")
    if len(parts) >= 3 and re.search(r"[0-9０-９]", parts[-1]):
        parts.pop()
    return "".join(parts)


def chapters():
    """{(簡稱, 章): [單位, ...]}，單位 = (種類, 節, 序, 要唸的字)，依朗讀順序"""
    vs = {}
    for f in sorted(DATA.glob("day-*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for tk in ("nt", "ot"):
            for v in (d.get(tk) or {}).get("verses", []):
                vs[(v["abbr"], v["ch"], v["v"])] = v
    out = collections.defaultdict(list)
    for (ab, ch, n), v in sorted(vs.items(), key=lambda x: (ORDER.index(x[0][0]), x[0][1], x[0][2])):
        units = out[(ab, ch)]
        if not units:
            unit = "篇" if ab == "詩" else "章"
            units.append(("t", 0, 0, f"第{cn_num(ch)}{unit}"))
        ol = v.get("outline") or []
        cuts = sorted({a for a, _, _ in ol if a})
        bounds = [0] + cuts + [len(v["text"])]
        split = bool(cuts)
        j = 0
        for k in range(len(bounds) - 1):
            while j < len(ol) and ol[j][0] == bounds[k]:
                units.append(("o", n, j, outline_title(ol[j][2])))
                j += 1
            units.append(("v", n, k + 1 if split else 0, v["text"][bounds[k]:bounds[k + 1]]))
    return out


def timed(cues):
    """audio.tsv 的提示 → {(種類, 節, 序): (起, 迄)}"""
    t = {}
    for s, e, v, kind, idx in cues:
        key = (KINDS[kind], v, idx)
        s0, e0 = t.get(key, (s, e))
        t[key] = (min(s, s0), max(e, e0))
    return t


def verse_timed(t, kind, n, idx):
    """經文的切法兩邊可能不同（來源沒切只有 part 0，或反過來），
    所以這一節只要有任何一塊有時間，就當它每一塊都有。"""
    if (kind, n, idx) in t:
        return t[(kind, n, idx)]
    if kind == "v":
        hits = [x for k, x in t.items() if k[0] == "v" and k[1] == n]
        if hits:
            return min(h[0] for h in hits), max(h[1] for h in hits)
    return None


def gaps(units, t):
    """[(前一錨點, 後一錨點, [沒時間的單位])]，錨點 = (單位, 起, 迄) 或 None（章首／檔尾）"""
    out, run, prev = [], [], None
    for u in units:
        hit = verse_timed(t, *u[:3])
        if hit:
            if run:
                out.append((prev, (u, *hit), run))
                run = []
            prev = (u, *hit)
        else:
            run.append(u)
    if run:
        out.append((prev, None, run))
    return out


def mp3(ab, ch):
    MP3.mkdir(parents=True, exist_ok=True)
    f = MP3 / (audio_file(ab, ch).replace("/", "-").replace("%20", "_") + ".mp3")
    if not f.exists():
        req = urllib.request.Request(BASE + audio_file(ab, ch) + ".mp3",
                                     headers={"User-Agent": "bible-reading-loop build"})
        with urllib.request.urlopen(req, timeout=120) as r:
            f.write_bytes(r.read())
    return f


def transcribe(model, src, s, e, prompt):
    """[(字, 起, 迄)]，時間是整個音檔的秒數"""
    import numpy as np
    # 自己用 ffmpeg 解碼成 16kHz 單聲道 float，不經 faster-whisper 內建的 PyAV
    # （新版 PyAV 的 API 跟它對不上）
    off = max(0, s - 0.3)
    cmd = ["ffmpeg", "-v", "error", "-ss", f"{off:.2f}", "-i", str(src)]
    if e is not None:
        cmd += ["-t", f"{e - s + 0.6:.2f}"]
    raw = subprocess.run(cmd + ["-ac", "1", "-ar", "16000", "-f", "f32le", "-"],
                         check=True, capture_output=True).stdout
    segs, _ = model.transcribe(np.frombuffer(raw, np.float32), language="zh",
                               word_timestamps=True, initial_prompt=prompt[:200],
                               vad_filter=False, beam_size=5)
    chars = []
    for seg in segs:
        for wd in seg.words or []:
            cs = clean(TO_TRAD(wd.word))
            for i, c in enumerate(cs):
                a = wd.start + (wd.end - wd.start) * i / len(cs)
                b = wd.start + (wd.end - wd.start) * (i + 1) / len(cs)
                chars.append((c, off + a, off + b))
    return chars


def align(units, chars):
    """[(單位, 起, 迄, 比例)]，對不上的單位不回傳"""
    tgt, owner = [], []
    for i, u in enumerate(units):
        for c in clean(u[3]):
            tgt.append(c)
            owner.append(i)
    rec = "".join(c for c, _, _ in chars)
    sm = difflib.SequenceMatcher(None, "".join(tgt), rec, autojunk=False)
    hit = collections.defaultdict(list)          # 單位 -> [(起, 迄)]
    for a, b, size in sm.get_matching_blocks():
        if size < 2:                             # 單字的零星巧合不算（綱目短，最容易被湊上）
            continue
        for k in range(size):
            hit[owner[a + k]].append(chars[b + k][1:])
    out = []
    n_chars = collections.Counter(owner)
    for i, u in enumerate(units):
        h = hit.get(i, [])
        ratio = len(h) / n_chars[i] if n_chars[i] else 0
        if len(h) >= 2 and ratio >= MIN_MATCH:
            a, b = min(x[0] for x in h), max(x[1] for x in h)
            if plausible(n_chars[i], a, b):
                out.append((u, a, b, ratio))
    return out


def plausible(n, a, b):
    """唸 n 個字花的時間合不合理。朗讀約每秒 4～5 字；比對若東湊一個字、
    西湊一個字，跨度會長得離譜（實測有綱目被拉到 20 秒）。"""
    return b - a <= n * 0.45 + 2


def fill(model, ab, ch, units, t, run):
    """補一個洞，回傳 ([(單位, 起, 迄, 比例)], 被改正的錨點)。

    洞旁邊的錨點本身也常常不準（例如撒上1:1 被標在其實唸 1:3 的地方），
    只夾「前一錨點結束～後一錨點開始」會夾出唸不完一節、甚至根本不含洞的
    空檔。所以：
      1. 辨識範圍包含前後錨點整段，比對時把錨點經文也放進去當上下文。
      2. 錨點自己的字對不上 = 錨點時間是錯的：把它也算進洞裡，往外擴到再
         前／後一個錨點重試（最多 3 次）。擴進來的錨點若對上了，就用辨識
         的時間取代來源的。
    """
    def anchor(i, step):
        while 0 <= i < len(units):
            hit = verse_timed(t, *units[i][:3])
            if hit:
                return i, hit
            i += step
        return None, None

    lo, hi = units.index(run[0]), units.index(run[-1])
    for _ in range(4):
        pi, ph = anchor(lo - 1, -1)
        ni, nh = anchor(hi + 1, +1)
        # 錨點可能錯到前後顛倒（撒下12 的前錨點比後錨點還晚），取兩者涵蓋的範圍
        s = min(ph[0], nh[0]) if ph and nh else ph[0] if ph else 0.0
        e = max(ph[1], nh[1]) if ph and nh else nh[1] if nh else None
        ctx = units[(pi if pi is not None else lo):(ni + 1 if ni is not None else len(units))]
        want = "".join(clean(u[3]) for u in ctx)
        chars = transcribe(model, mp3(ab, ch), s, e, want)
        if len(chars) < 0.5 * len(want):
            # 模型偶爾整段漏聽（撒下2 只吐出「第二章」），不帶提示再聽一次
            chars = max(chars, transcribe(model, mp3(ab, ch), s, e, ""), key=len)
        got = {g[0]: g for g in align(ctx, chars)}
        bad_prev = pi is not None and units[pi] not in got
        bad_next = ni is not None and units[ni] not in got
        if not (bad_prev or bad_next):
            break
        if bad_prev:
            lo = pi
        if bad_next:
            hi = ni
    inside = units[lo:hi + 1]
    fixed = [u for u in inside if u not in run]
    return [got[u] for u in inside if u in got], fixed


def check(model, cues, n):
    """挖洞再補：誤差 = 補出來的起點 − 來源的起點"""
    import random
    rnd = random.Random(1)
    chs = chapters()
    good = [k for k, units in chs.items()
            if len(units) > 12 and not gaps(units, timed(cues.get(k, [])))]
    errs, lost = [], 0
    for ab, ch in rnd.sample(good, n):
        units = chs[(ab, ch)]
        t = timed(cues[(ab, ch)])
        vs = [i for i, u in enumerate(units) if u[0] == "v"]
        i0 = rnd.randrange(1, len(vs) - 8)
        run = [units[i] for i in range(vs[i0], vs[i0 + 6])]       # 挖掉約 6 節
        tt = {k: x for k, x in t.items()
              if not any(k[0] == u[0] and k[1] == u[1] for u in run)}   # 把這段挖掉
        got = {g[0]: g for g in fill(model, ab, ch, units, tt, run)[0]}
        for u in run:
            if u not in got:
                lost += 1
                continue
            truth = verse_timed(t, *u[:3])
            errs.append((abs(got[u][1] - truth[0]), abs(got[u][2] - truth[1]), f"{ab}{ch}:{u[1]}{u[0]}"))
        print(f"{ab}{ch}：挖 {len(run)} 個單位", file=sys.stderr)
    errs.sort()
    st = sorted(x[0] for x in errs)
    en = sorted(x[1] for x in errs)
    q = lambda xs, p: xs[min(len(xs) - 1, int(len(xs) * p))]
    print(f"{len(errs)} 個單位補上、{lost} 個對不上")
    print(f"起點誤差：中位數 {q(st, .5):.2f}s、90% {q(st, .9):.2f}s、最大 {st[-1]:.2f}s")
    print(f"終點誤差：中位數 {q(en, .5):.2f}s、90% {q(en, .9):.2f}s、最大 {en[-1]:.2f}s")
    for a, b, tag in sorted(errs, key=lambda x: -x[0])[:5]:
        print(f"  {tag} 起點差 {a:.2f}s 終點差 {b:.2f}s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("only", nargs="*", help="只跑這幾章，如 箴2 申24")
    ap.add_argument("--model", default="small")
    ap.add_argument("--fresh", action="store_true", help="不接續上次的進度，全部重做")
    ap.add_argument("--check", type=int, metavar="N",
                    help="自我驗證：在 N 個來源時間軸完整的章裡挖掉一段節再補回來，跟原本的時間比")
    args = ap.parse_args()

    global TO_TRAD
    import opencc
    from faster_whisper import WhisperModel
    TO_TRAD = opencc.OpenCC("s2t").convert          # whisper 常吐簡體，轉成繁體再比
    model = WhisperModel(args.model, device="cpu", compute_type="int8")

    cues = load_cues(include_asr=False)
    if args.check:
        return check(model, cues, args.check)
    # 每章做完就記進 PROGRESS 並重寫 OUT：跑一次要半小時以上，中途斷了不必重來。
    # 不帶章名重跑會跳過做過的章；--fresh 全部重做；帶章名就只重做那幾章。
    done = {} if args.fresh or not PROGRESS.exists() else json.loads(PROGRESS.read_text())
    # 舊進度也套用目前的合理性檢查（規則改嚴之後不必整輪重跑）
    chs = chapters()
    for tag, lines in done.items():
        ab = re.match(r"\D+", tag).group()
        size = {(f"{ab}{int(tag[len(ab):])}:{u[1]}", u[0], str(u[2])): len(clean(u[3]))
                for u in chs[(ab, int(tag[len(ab):]))]}
        for k in list(lines):
            a, b, _ = map(float, lines[k].split("\t"))
            if not plausible(size[tuple(k.split("\t"))], a, b):
                print(f"剔除不合理的舊結果 {k.replace(chr(9), ' ')} {a:.1f}-{b:.1f}", file=sys.stderr)
                del lines[k]
    rep = collections.Counter()
    for (ab, ch), units in chapters().items():
        tag = f"{ab}{ch}"
        if args.only and tag not in args.only:
            continue
        t = timed(cues.get((ab, ch), []))
        holes = gaps(units, t)
        if not holes or (not args.only and tag in done):
            continue
        lines = {}
        for _, _, run in holes:
            got, fixed = fill(model, ab, ch, units, t, run)
            for u, a, b, r in got:
                ref = f"{ab}{ch}:{u[1]}"
                lines[f"{ref}\t{u[0]}\t{u[2]}"] = f"{a:.2f}\t{b:.2f}\t{r:.2f}"
            ok = {g[0] for g in got}
            name = lambda u: f"{u[1]}{'' if u[0] == 'v' else u[0]}{'.' + str(u[2]) if u[0] != 'v' or u[2] else ''}"
            miss = [name(u) for u in run if u not in ok]
            fix = [name(u) for u in fixed if u in ok]
            rep["補上"] += len(run) - len(miss)
            rep["對不上"] += len(miss)
            rep["改正錨點"] += len(fix)
            print(f"{tag}：洞 {len(run)} 個，補上 {len(run) - len(miss)}"
                  + (f"，改正錨點 {' '.join(fix)}" if fix else "")
                  + (f"，對不上 {' '.join(miss)}" if miss else ""), file=sys.stderr, flush=True)
        done[tag] = lines
        PROGRESS.parent.mkdir(parents=True, exist_ok=True)
        PROGRESS.write_text(json.dumps(done, ensure_ascii=False))
        write_out(done)
    write_out(done)
    n = sum(len(x) for x in done.values())
    print(f"寫入 {OUT.name}：{n} 列；本次 " + "、".join(f"{k} {v}" for k, v in rep.items()))


def write_out(done):
    def order(key):
        ref, kind, idx = key.split("\t")
        ab = re.match(r"\D+", ref).group()
        ch, v = map(int, ref[len(ab):].split(":"))
        return (ORDER.index(ab), ch, v, "tov".index(kind), int(idx))
    rows = {k: v for lines in done.values() for k, v in lines.items()}
    OUT.write_text("ref\tkind\tidx\tstart\tend\tmatch\n"
                   + "".join(f"{k}\t{rows[k]}\n" for k in sorted(rows, key=order)), encoding="utf-8")

if __name__ == "__main__":
    main()
