"""
apply_outline.py — 把 outline.tsv 編譯進 docs/data

outline.tsv 是成品，這支只是把它攤進網站要載的 JSON。每節最多多出兩個欄位：

  outline  [[位置, 層級, 綱目], ...]  插在這一節的綱目。位置是 text 的字串索引
           （已把註標上標算進去），0 = 整節之前，>0 = 把這一節從那裡切開。
  carry    [[層級, 綱目], ...]  承接的上層綱目。日段是照讀經計畫切的，常常從
           某個綱目段落的中間開始；只看當天會不知道自己在哪一段，所以在日段
           （或日段內換卷）的第一節補上當時仍有效的各層綱目。

跑：  python apply_outline.py
"""
import collections
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "docs" / "data"
TSV = ROOT / "outline.tsv"

SUP = set("⁰¹²³⁴⁵⁶⁷⁸⁹")


def load_tsv():
    """{簡稱: [(章, 節, 位移, 層級, 綱目), ...]}，卷與條目都維持聖經順序"""
    out = collections.OrderedDict()
    for line in TSV.read_text(encoding="utf-8").splitlines()[1:]:
        ref, off, level, text = line.split("\t")
        ref, v = ref.rsplit(":", 1)
        i = 0
        while i < len(ref) and not ref[i].isdigit():
            i += 1
        out.setdefault(ref[:i], []).append(
            (int(ref[i:]), int(v), int(off), int(level), text))
    return out


def push(stack, level, text):
    """綱目是階層的：新的一條會結束所有同層與更深層的綱目。"""
    while stack and stack[-1][0] >= level:
        stack.pop()
    stack.append([level, text])


def initial_stacks(outline):
    """{簡稱: 該卷開始前就已有效的綱目}

    撒下、王下、代下的綱目是接著上卷編的（撒下第一條就是第 4 層的「t　大衛的
    反應」），它們的上層綱目在前一卷。其餘各卷都從第 1 層開始，不承接。
    """
    init, prev = {}, []
    for ab, items in outline.items():
        init[ab] = [] if items[0][3] == 1 else [list(x) for x in prev]
        stack = [list(x) for x in init[ab]]
        for _, _, _, level, text in items:
            push(stack, level, text)
        prev = stack
    return init


def text_index(text, off):
    """不計註標的位移 → text 的字串索引。

    註標標的是它後面那個字，所以切點要落在註標之前，讓註標跟著下半節走。
    """
    if off == 0:
        return 0
    n = 0
    for i, c in enumerate(text):
        if n == off:
            return i
        if c not in SUP:
            n += 1
    raise ValueError(f"位移 {off} 超出經文長度")


def main():
    if not TSV.exists():
        raise SystemExit(f"找不到 {TSV}，請先跑 python build_outline.py")
    outline = load_tsv()
    init = initial_stacks(outline)
    at = collections.defaultdict(list)       # (簡稱, 章, 節) -> [(位移, 層級, 綱目)]
    for ab, items in outline.items():
        for ch, v, off, level, text in items:
            at[(ab, ch, v)].append((off, level, text))

    def carry_for(ab, ch, v):
        stack = [list(x) for x in init.get(ab, [])]
        for c, vv, _, level, text in outline.get(ab, []):
            if (c, vv) >= (ch, v):
                break
            push(stack, level, text)
        # 這一節自己開頭的綱目會取代同層以下的，只留比它高的層級
        own = [x for x in at.get((ab, ch, v), []) if x[0] == 0]
        return [x for x in stack if x[0] < own[0][1]] if own else stack

    n_placed = n_split = n_carry = 0
    for f in sorted(DATA.glob("day-*.json")):
        d = json.loads(f.read_text(encoding="utf-8"))
        for tk in ("nt", "ot"):
            if not d.get(tk):
                continue
            prev = None
            for v in d[tk]["verses"]:
                v.pop("outline", None)       # 重跑時清掉舊的
                v.pop("carry", None)
                key = (v["abbr"], v["ch"], v["v"])
                if key in at:
                    v["outline"] = [[text_index(v["text"], off), level, text]
                                    for off, level, text in at[key]]
                    n_placed += len(v["outline"])
                    n_split += any(x[0] for x in v["outline"])
                if v["abbr"] != prev:
                    prev = v["abbr"]
                    carry = carry_for(*key)
                    if carry:
                        v["carry"] = carry
                        n_carry += 1
        f.write_text(json.dumps(d, ensure_ascii=False, separators=(",", ":")),
                     encoding="utf-8")

    total = sum(len(x) for x in outline.values())
    if n_placed != total:
        raise SystemExit(f"outline.tsv 有 {total} 條，只放進 {n_placed} 條")
    size = sum(f.stat().st_size for f in DATA.glob("*.json"))
    print(f"寫入 {n_placed} 條綱目，其中 {n_split} 節被綱目從中間切開")
    print(f"補上承接綱目的日段起點：{n_carry} 處")
    print(f"docs/data 總計 {size/1024/1024:.1f}MB")


if __name__ == "__main__":
    main()
