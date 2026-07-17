"""
refs.py — 解析恢復本註解中的經節引用

註解裡的引用形式（如 `太十二42`、`加三16，14`、`26節`）是章用中文數字、
節用阿拉伯數字。因為散文一律用中文數字，全語料又沒有任何 4 位數或大於 176
的數字（176 = 全聖經最大節號），阿拉伯數字幾乎可斷定就是節數 —— 這是整個
解析器成立的前提。

用法：
    r = Parser(vmax)                      # vmax: {(簡稱, 章): 該章最大節}
    links = r.parse(body, "太", 1)        # body 所屬經節的卷/章
"""
import re

# 章數字用字。「○」＝0（一○四＝104）。「百」「零」不是章數字，只在散文出現
# （一千零三年半、零碎），故不納入。
CN = "一二三四五六七八九十○"
_D = {c: i + 1 for i, c in enumerate("一二三四五六七八九")}
_D["○"] = 0


def decode(s):
    """中文數字 → int。116 種寫法全數驗證通過；無法解碼回 None。

    十=10、十X=10+X、X十=X*10，其餘位值展開（一一九=119、一○四=104）。
    """
    if not s:
        return None
    if s == "十":
        return 10
    if s.startswith("十"):
        return 10 + _D[s[1]] if len(s) == 2 and s[1] in _D else None
    if len(s) == 2 and s.endswith("十") and s[0] in _D:
        return _D[s[0]] * 10
    if all(c in _D for c in s):
        return int("".join(str(_D[c]) for c in s))
    return None


# 鏈狀態重設點。左括弧也重設（一組括號通常是獨立的引用群），但不含數字的
# 括號註記（（二次）、（英譯美國標準本））是插語，跳過而不重設 —— 否則
# 「四6（二次）、7、8」的 7、8 會被誤判成本章，且目標存在、驗證抓不到。
_RESET = set("。；\n（(")
# 分隔符：鏈在這些字之間存活。「至」用於註標範圍（「1註4至2註3」）。
_SEP = set("，、與和及至")
# 提示詞。純粹是「見/參」的意思，不影響目標，也不可打斷鏈 ——
# 「（啟二18～29，見20註3。）」的 20 必須承接啟二。
_HINT = set("見參")
# 註解內的段落／要點指標：「註1三段」「註2第二點」「註1第一、二點」。
# 使用者要的是連到註，段落不處理；但它們不可打斷鏈 ——
# 「見來一1註1三段，與十一13註2」的十一13 必須承接「來」。
_NOTE_PARA = re.compile(r"第?[" + CN + r"]+(?:[、，]第?[" + CN + r"]+)*[段點]")

_ANAPHOR = re.compile(r"(該章|本章|本書)([" + CN + r"]*)(\d+)")
_CHAPTER_MENTION = re.compile(r"([" + CN + r"]+)章")
# 半節標記 上/下/中。後面接中文數字時不算（「註1三段」的三、「39上大人像」）。
# 「節」可出現在範圍前後（「4節～二五46」「42～52節」），故兩處都允許。
# 範圍容忍空白：「王上八46 ～53」。
_TAIL = re.compile(
    r"(?:[上下中](?![" + CN + r"]))?"
    r"節?"
    r"(?:\s*～\s*(?:[" + CN + r"]+)?\d+(?:[上下中](?![" + CN + r"]))?節?)?"
)
# 註標。必須有數字：裸「與註」無法判斷指哪個註（99 筆目標多註、12 筆起點
# 無註），故不解析，只連經節部分。
_NOTE = re.compile(r"(?:與|見)?註(\d+)")
# 「者同」/「同」結尾 → 整條鏈是譯詞註記，不供跳轉，全部抑制。
_SAME = re.compile(r"者?同")


class Link:
    __slots__ = ("start", "end", "abbr", "ch", "v", "note", "src")

    def __init__(self, start, end, abbr, ch, v, note, src):
        self.start, self.end = start, end
        self.abbr, self.ch, self.v = abbr, ch, v
        self.note = note
        self.src = src  # book | chapter | bare | anaphor

    def __repr__(self):
        n = f"註{self.note}" if self.note else ""
        return f"<{self.abbr}{self.ch}:{self.v}{n} @{self.start}:{self.end} {self.src}>"


class Parser:
    def __init__(self, vmax):
        """vmax: {(簡稱, 章): 該章最大節}。用來驗證每個解析結果是否真的存在。"""
        self.vmax = vmax
        books = {ab for ab, _ in vmax}
        # 最長優先：撒上 要先於 撒、約壹 要先於 約
        self.abbrs = sorted(books, key=len, reverse=True)
        chmax = {}
        for ab, ch in vmax:
            chmax[ab] = max(chmax.get(ab, 0), ch)
        self.single = {ab for ab, c in chmax.items() if c == 1}  # 門/猶/俄/約貳/約參
        self._book_re = re.compile("(" + "|".join(map(re.escape, self.abbrs)) + ")")
        self._anchor = re.compile(
            r"(?:(" + "|".join(map(re.escape, self.abbrs)) + r"))?"
            r"([" + CN + r"]+)?(\d+)"
        )

    def ok(self, ab, ch, v):
        return bool(ch) and 1 <= v <= self.vmax.get((ab, ch), 0)

    def parse(self, body, host_ab, host_ch):
        """回傳連結清單。"""
        return self.parse_all(body, host_ab, host_ch)[0]

    def parse_all(self, body, host_ab, host_ch):
        """回傳 (連結, 被「者同」抑制的連結)。

        抑制的部分是刻意不連，不是漏認 —— 報告要把兩者分開，否則
        「未覆蓋數字」這個回歸指標會被抑制的數字灌爆而失效。
        """
        out = []
        killed = []         # 被抑制的，供報告區分「刻意不連」與「沒認出來」
        chain = []          # 當前鏈，供「者同」抑制
        i, L = 0, len(body)
        cab, cch = host_ab, host_ch   # 鏈內承接的卷/章
        live = False
        last_ab, last_ch = None, None  # 「該章」用，跨句號記憶

        def flush(j):
            nonlocal chain
            if chain and _SAME.match(body, j):
                for x in chain:
                    if x in out:
                        out.remove(x)
                        killed.append(x)
            chain = []

        while i < L:
            c = body[i]

            if c in _RESET:
                if c in "（(":
                    close = body.find("）" if c == "（" else ")", i)
                    # 不含數字的括號註記是插語，跳過但不打斷鏈
                    if close > 0 and not any(ch.isdigit() for ch in body[i + 1:close]):
                        i = close + 1
                        continue
                flush(i)
                live = False
                cab, cch = host_ab, host_ch
                i += 1
                continue

            # 提示詞不打斷鏈（見 _HINT）
            if c in _HINT:
                i += 1
                continue

            # 落單的「註N」（如「與註1，註2」的後者）不產生連結。必須在
            # 錨點之前擋掉，否則其中的數字會被當成節號。
            if c == "註":
                m = re.match(r"註\d*", body[i:])
                i += m.end()
                continue

            # 指代詞：本書=host 卷、本章=host 章、該章=最近提到的章
            m = _ANAPHOR.match(body, i)
            if m:
                tag, chs, v = m.group(1), m.group(2), int(m.group(3))
                if tag == "本書":
                    ab, ch = host_ab, decode(chs)
                elif tag == "本章":
                    ab, ch = host_ab, host_ch
                else:
                    ab, ch = (last_ab or host_ab), last_ch
                if self.ok(ab, ch, v):
                    e = _TAIL.match(body, m.end()).end()
                    note = None
                    nm = _NOTE.match(body, e)
                    if nm:
                        note, e = nm.group(1), nm.end()
                    # 「註1三段」的段落指標：跳過但不納入連結文字，也不斷鏈
                    skip = e
                    if note:
                        pm = _NOTE_PARA.match(body, e)
                        if pm:
                            skip = pm.end()
                    lk = Link(i, e, ab, ch, v, note, "anaphor")
                    out.append(lk); chain.append(lk)
                    cab, cch, live = ab, ch, True
                    last_ab, last_ch = ab, ch
                    i = skip
                    continue

            # 「十章的天使」—— 供「該章」回指，本身不是引用
            m = _CHAPTER_MENTION.match(body, i)
            if m and decode(m.group(1)) is not None:
                last_ch = decode(m.group(1))
                i = m.end()
                continue

            m = self._anchor.match(body, i)
            if m and m.start() == i:
                bk, chs, v = m.group(1), m.group(2), int(m.group(3))
                start = i
                # 多章書的簡稱後面沒有章數字 → 那個字是散文，不是卷名。
                # 「但」「可」「多」「書」「得」「來」都是常用字兼簡稱，
                # 「但32節的夏天」的「但」是「但是」，32 該用 host 章解析。
                if bk and not chs and bk not in self.single:
                    bk, start = None, m.start(3)
                if bk:
                    ab = bk
                    ch = decode(chs) if chs else 1   # 單章書：門/猶/俄/約貳/約參
                    src = "book"
                else:
                    ab = cab if live else host_ab
                    if chs:
                        ch, src = decode(chs), "chapter"
                    else:
                        ch, src = (cch if live else host_ch), "bare"
                if self.ok(ab, ch, v):
                    e = _TAIL.match(body, m.end()).end()
                    note = None
                    nm = _NOTE.match(body, e)
                    if nm:
                        note, e = nm.group(1), nm.end()
                    # 「註1三段」的段落指標：跳過但不納入連結文字，也不斷鏈
                    skip = e
                    if note:
                        pm = _NOTE_PARA.match(body, e)
                        if pm:
                            skip = pm.end()
                    lk = Link(start, e, ab, ch, v, note, src)
                    out.append(lk); chain.append(lk)
                    cab, cch, live = ab, ch, True
                    last_ab, last_ch = ab, ch
                    i = skip
                    continue
                # 驗證失敗 → 整個數字串跳過，不可退一格重試。否則
                # 「書十三47」（無效）會退成「十三47」用 host 卷解析，
                # 「創一999」會退成「9」—— 兩者都產生看似合理的錯誤連結。
                i = m.end()
                continue

            # 只有分隔符能讓鏈存活；其餘任何字都斷鏈（但不重設承接的卷/章，
            # 那由 _RESET 負責）
            if c not in _SEP:
                flush(i)
                live = False
            i += 1

        flush(L)
        return out, killed
