"""
corpus.py — 從已建好的 docs/data 讀出解析器需要的聖經座標表。

docs/data 涵蓋全本聖經（66 卷 / 1189 章 / 31103 節，零重複），所以它本身就是
驗證引用是否存在的權威來源，不需要 verses/ 原始語料。
"""
import glob
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "docs" / "data"


def load():
    """回傳 (vmax, full, notes)

    vmax  {(簡稱, 章): 該章最大節}
    full  {簡稱: 全名}
    notes [(簡稱, 章, 節, 註標, 註文, day, track), ...]  依日序
    """
    vmax, full, notes = {}, {}, []
    for f in sorted(glob.glob(str(DATA / "day-*.json"))):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        for tk in ("nt", "ot"):
            if not d.get(tk):
                continue
            for v in d[tk]["verses"]:
                k = (v["abbr"], v["ch"])
                vmax[k] = max(vmax.get(k, 0), v["v"])
                full[v["abbr"]] = v["book"]
                for n in v.get("notes") or []:
                    # 空殼註解：經文裡同一個註標出現兩次時，上游 extract_verses.py
                    # 會依 (note_loc, note_num) 逐列輸出，於是同一標號產生多筆，
                    # 只有一筆有內容。866 條全是這樣，且無一組是「多條都非空」。
                    # 不濾掉的話標號在一節內不唯一，連結會套到錯的註解上。
                    if not n["body"].strip():
                        continue
                    notes.append((v["abbr"], v["ch"], v["v"], n["label"],
                                  n["body"], d["day"], tk))
    return vmax, full, notes


def locator():
    """{簡稱: [[章, 節, 天, track], ...]} —— 每卷書各天區段的起點。

    730 筆即可定位全部 31103 節：找「最後一個起點 <= 目標」即得天數。
    """
    loc = {}
    for f in sorted(glob.glob(str(DATA / "day-*.json")), key=lambda p: int(p[-8:-5])):
        d = json.loads(Path(f).read_text(encoding="utf-8"))
        for tk in ("nt", "ot"):
            if not d.get(tk):
                continue
            for v in d[tk]["verses"]:
                seg = loc.setdefault(v["abbr"], [])
                if not seg or seg[-1][2] != d["day"]:
                    seg.append([v["ch"], v["v"], d["day"], tk])
    return loc
