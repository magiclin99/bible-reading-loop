"""
apply_audio.py — 把 audio.tsv 編譯進 docs/data

每個日段（day-NNN.json 的 nt / ot）多一個 audio 欄位，是依序要播的片段：

  audio  [{"f": "01/01-Genesis",   音檔，前端補成 …/mp3/bible/{f}.mp3
           "bk": "創世記", "ch": 1,
           "s": 47.38, "e": 349.71,  只播這一段（日段常從章的中間開始或結束）
           "c": [[起, 迄, 節, 種類, 序], ...]}, ...]   跟著高亮的提示
                                     種類 0 = 經文：序 0 = 整節，K = 被綱目切開的第 K 塊
                                     種類 1 = 綱目：序 = 這一節的第幾條綱目
                                     種類 2 = 章標題「第 N 章」

一章一個音檔，所以日段跨幾章就有幾個片段。提示來自 audio.tsv（來源時間軸）
加上 audio_asr.tsv（align_audio.py 用語音辨識補的洞）。兩份都沒有時間的章
只能整章播，不帶提示（"s": 0, "e": null）。

跑：  python apply_audio.py      （可重複執行）
"""
import collections
import json
import urllib.parse
from pathlib import Path

from build_audio import ORDER

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "docs" / "data"
TSV = ROOT / "audio.tsv"
ASR = ROOT / "audio_asr.tsv"

ENGLISH = ["Genesis", "Exodus", "Leviticus", "Numbers", "Deuteronomy", "Joshua", "Judges",
           "Ruth", "1 Samuel", "2 Samuel", "1 Kings", "2 Kings", "1 Chronicles",
           "2 Chronicles", "Ezra", "Nehemiah", "Esther", "Job", "Psalms", "Proverbs",
           "Ecclesiastes", "Song of Songs", "Isaiah", "Jeremiah", "Lamentations", "Ezekiel",
           "Daniel", "Hosea", "Joel", "Amos", "Obadiah", "Jonah", "Micah", "Nahum", "Habakkuk",
           "Zephaniah", "Haggai", "Zechariah", "Malachi", "Matthew", "Mark", "Luke", "John",
           "Acts", "Romans", "1 Corinthians", "2 Corinthians", "Galatians", "Ephesians",
           "Philippians", "Colossians", "1 Thessalonians", "2 Thessalonians", "1 Timothy",
           "2 Timothy", "Titus", "Philemon", "Hebrews", "James", "1 Peter", "2 Peter", "1 John",
           "2 John", "3 John", "Jude", "Revelation"]
KIND = {"v": 0, "o": 1, "t": 2}


def audio_file(ab, ch):
    bk = ORDER.index(ab) + 1
    return f"{bk:02d}/{ch:0{3 if ab == '詩' else 2}d}-{urllib.parse.quote(ENGLISH[bk - 1])}"


def load_tsv(include_asr=True):
    """{(簡稱, 章): [(起, 迄, 節, 種類, 序)]}

    audio.tsv 是來源的時間軸；audio_asr.tsv 是 align_audio.py 用語音辨識補的洞，
    以及它驗出來是錯的錨點。同一個單位兩份都有時，以辨識的為準（經文以整節
    為單位取代，因為兩邊切塊的方式可能不同）。
    """
    def rows(path):
        for line in path.read_text(encoding="utf-8").splitlines()[1:]:
            ref, kind, idx, s, e = line.split("\t")[:5]
            ref, v = ref.rsplit(":", 1)
            i = 0
            while not ref[i].isdigit():
                i += 1
            yield (ref[:i], int(ref[i:])), (float(s), float(e), int(v), KIND[kind], int(idx))

    out = collections.defaultdict(list)
    for k, c in rows(TSV):
        out[k].append(c)
    if include_asr and ASR.exists():
        asr = collections.defaultdict(list)
        for k, c in rows(ASR):
            asr[k].append(c)
        for k, new in asr.items():
            gone = {(c[2], c[3]) if c[3] == 0 else (c[2], c[3], c[4]) for c in new}
            out[k] = [c for c in out[k]
                      if ((c[2], c[3]) if c[3] == 0 else (c[2], c[3], c[4])) not in gone] + new
    return out


# 片段的起訖。來源時間軸偶有漏節（見 build_audio.misaligned），起訖那一節
# 沒有時間時，用前一節的結束／後一節的開始推估 —— 寧可多唸半句，不可漏唸。
# 回傳 (秒數, 是否推估)。
def clip_start(allc, lo):
    own = [c[0] for c in allc if c[2] == lo and c[3] != 2]
    if lo == 1:
        own += [c[0] for c in allc if c[3] == 2]       # 從頭唸：連章標題一起
    if own and (lo == 1 or any(c[2] == lo and c[3] == 0 for c in allc)):
        return min(own), False
    before = [c[1] for c in allc if c[3] == 0 and c[2] < lo]
    return (max(before) if before else 0), True


def clip_end(allc, hi):
    own = [c[1] for c in allc if c[2] == hi and c[3] == 0]
    if own:
        return max(own), False
    after = [c[0] for c in allc if c[3] != 2 and c[2] > hi]
    return (min(after) if after else None), True


def main():
    if not TSV.exists():
        raise SystemExit(f"找不到 {TSV}，請先跑 python build_audio.py")
    cues = load_tsv()
    n_clip = n_bare = n_cue = n_guess = 0
    for f in sorted(DATA.glob("day-*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for tk in ("nt", "ot"):
            t = d.get(tk)
            if not t:
                continue
            # 日段裡每一章用到哪幾節（維持出現順序）
            spans = collections.OrderedDict()
            for vs in t["verses"]:
                spans.setdefault((vs["abbr"], vs["book"], vs["ch"]), []).append(vs["v"])
            clips = []
            for (ab, book, ch), vv in spans.items():
                clip = {"f": audio_file(ab, ch), "bk": book, "ch": ch}
                lo, hi = min(vv), max(vv)
                mine = [c for c in cues.get((ab, ch), [])
                        if lo <= c[2] <= hi or (c[3] == 2 and lo == 1)]
                allc = cues.get((ab, ch), [])
                if not any(c[3] != 2 for c in allc):
                    clip.update(s=0, e=None, c=[])      # 沒有時間軸：整章播
                    n_bare += 1
                else:
                    (st, g1), (en, g2) = clip_start(allc, lo), clip_end(allc, hi)
                    clip.update(s=st, e=en, c=[list(c) for c in sorted(mine)])
                    n_cue += len(mine)
                    n_guess += g1 or g2
                clips.append(clip)
            t["audio"] = clips
            n_clip += len(clips)
        f.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")),
                     encoding="utf-8")
    size = sum(f.stat().st_size for f in DATA.glob("*.json"))
    print(f"寫入 {n_clip} 個音檔片段、{n_cue} 個高亮提示；沒有時間軸、整章播的 {n_bare} 個")
    print(f"起訖節沒有時間、由前後節推估邊界的片段：{n_guess} 個")
    print(f"docs/data 總計 {size/1024/1024:.1f}MB")


if __name__ == "__main__":
    main()
