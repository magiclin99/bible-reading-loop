"""
consolidate.py — 從 workflow journal 彙整稽核進度

⚠ 已是死碼，保留供追溯。它讀 ~/.claude/.../workflows/ 裡的 agent transcript，
那些 session 檔跑完會被清除，所以現在再跑也讀不到東西。它的產出（progress.tsv
/ concerns.tsv）已經定稿在 audit/ 裡，稽核也已 364/364 完成。若日後要再跑一輪
稽核，改用 audit-ref-links.js（workflow）產生新的 transcript 後，才需要這支。

原用途：workflow 分多次跑（會被 session limit 中斷），這支把散落在 agent
transcript 裡的結果收攏成兩份清單：
  audit/progress.tsv   每天一列：跑了沒、檢視幾筆、回報幾筆
  audit/concerns.tsv   逐筆疑慮，供人工裁決後寫進 links_overrides.tsv

跑：  python audit/consolidate.py
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 稽核分多輪跑（額度中斷、格式調整都會開新 run），故掃全部 workflow 目錄
WF_ROOT = (Path.home() / ".claude/projects/-Users-gary-yc-lin-Projects-bible-reading-loop"
           / "5c9d2b62-f0a0-43e1-9a87-e9bc5496f3cc/subagents/workflows")
AUDIT = ROOT / "audit"
TOTAL_DAYS = 364


def scan():
    """{day: {checked, findings}} —— 從每個 agent 的 transcript 撈出結果。

    journal.jsonl 的 result 只有 key hash，對不回天數；agent-*.jsonl 裡才有
    它讀的 packet 路徑（day-NNN）和結構化輸出。
    後跑的 run 覆蓋先跑的（同一天若重跑，以新結果為準）。
    """
    done = {}
    files = sorted(WF_ROOT.glob("*/agent-*.jsonl"), key=lambda p: p.stat().st_mtime)
    for f in files:
        txt = f.read_text(errors="ignore")
        m = re.search(r"day-(\d{3})\.json", txt)
        if not m:
            continue
        day = int(m.group(1))
        checked, findings = None, None
        for line in txt.splitlines():
            if '"findings"' not in line or '"checked"' not in line:
                continue
            cm = re.search(r'"checked"\s*:\s*(\d+)', line)
            if cm:
                checked = int(cm.group(1))
            fm = re.search(r'"findings"\s*:\s*(\[.*?\])\s*,\s*"checked"', line)
            if fm:
                try:
                    findings = json.loads(fm.group(1))
                except Exception:
                    pass
        if checked is not None:
            done[day] = {"checked": checked, "findings": findings or []}
    return done


def main():
    done = scan()
    todo = [d for d in range(1, TOTAL_DAYS + 1) if d not in done]

    # 每天一列的進度表
    rows = ["day\tstatus\tchecked\tconcerns"]
    for d in range(1, TOTAL_DAYS + 1):
        r = done.get(d)
        if r:
            rows.append(f"{d}\tdone\t{r['checked']}\t{len(r['findings'])}")
        else:
            rows.append(f"{d}\ttodo\t-\t-")
    (AUDIT / "progress.tsv").write_text("\n".join(rows) + "\n", encoding="utf-8")

    # 疑慮清單
    cols = ["day", "id", "link_text", "target", "suggest", "severity", "issue"]
    lines = ["\t".join(cols)]
    n = 0
    for d in sorted(done):
        for f in done[d]["findings"]:
            n += 1
            lines.append("\t".join([
                str(d), f.get("id", ""), f.get("link_text", ""),
                f.get("target", ""), f.get("suggest", ""), f.get("severity", ""),
                (f.get("issue", "") or "").replace("\t", " ").replace("\n", " "),
            ]))
    (AUDIT / "concerns.tsv").write_text("\n".join(lines) + "\n", encoding="utf-8")

    checked = sum(r["checked"] for r in done.values())
    print(f"已稽核 {len(done)}/{TOTAL_DAYS} 天　未跑 {len(todo)} 天")
    print(f"已檢視連結 {checked} / 29378（{checked/29378*100:.0f}%）")
    print(f"回報疑慮 {n} 筆")
    print(f"\n  audit/progress.tsv  每天一列的進度")
    print(f"  audit/concerns.tsv  {n} 筆待裁決疑慮")
    if todo:
        # 印出待跑區間，方便接續
        runs, s = [], todo[0]
        for a, b in zip(todo, todo[1:] + [None]):
            if b != (a + 1):
                runs.append(f"{s}" if s == a else f"{s}-{a}")
                s = b
        print(f"\n未跑天數: {', '.join(runs)}")


if __name__ == "__main__":
    main()
