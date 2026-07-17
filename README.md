# 一年讀經一遍 · bible-reading-loop

按「新約 + 舊約」雙軌一年讀完一遍的線上讀經器。純靜態網頁，
資料來自 [line.twgbr.org 恢復版一年讀經](https://line.twgbr.org/recoveryversion/oneyear/2026.html)，
經文與註解為恢復版。

## 功能

- 首次進入顯示第 1 天（馬太福音 1:1-6）。
- 右上角切換新約／舊約（同一天兩條軌道）。
- 上下捲動讀經文；← → 鍵或底部按鈕切換前後天。
- 點經節展開該節的恢復版註解，再點收合。
- 底部按鈕標記當天當軌道「讀完」；新約、舊約分開記。
- 可瀏覽全部 364 天、跳到任一天，或把某天「設為第一天」
  （之後以那天為你的第 1 天，讀滿 364 天繞一圈）。
- 重新整理會回到上次的天／軌道／捲動位置，並提示已恢復。
- 進度存在瀏覽器 `localStorage`（`blr:state`、`blr:read`），不跨裝置同步。

## 目錄結構

```
docs/                 ← 發佈用的靜態網站（GitHub Pages 根目錄）
  index.html
  style.css
  app.js
  data/               ← 每日經文 + 註解（day-001.json … day-364.json）＋ index.json
scrape_oneyear.py     ← 從來源網站抓「讀經計畫」→ data/oneyear_plan.json
build_site_data.py    ← 用計畫 + 經文來源產生 docs/data/
data/
  oneyear_plan.json   ← 364 天雙軌讀經計畫
```

> `docs/data/` 是**建好的成品**，網站執行時只依賴 `docs/` 本身。
> 逐節經文原始檔（`verses/`，約 122MB / 3 萬多檔）**不放在本 repo**；
> 若要重建 `docs/data/`，先把 `verses/` 從來源專案複製進來再跑 `build_site_data.py`。

## 本機預覽

```bash
cd docs
python3 -m http.server 8000
# 開 http://localhost:8000
```

必須用 HTTP 伺服器開，不能直接 `file://`（網頁會 fetch JSON）。

## 發佈到 GitHub Pages

本 repo 已把網站放在 `docs/`。在 GitHub 上：

1. **Settings → Pages**
2. **Source**：`Deploy from a branch`
3. **Branch**：`main`，資料夾選 **`/docs`**，按 **Save**

幾分鐘後即可在 `https://magiclin99.github.io/bible-reading-loop/` 開啟。
所有資源都用相對路徑，子路徑下也能正常運作。

## 資料重建（選用）

```bash
# 1) 重新抓讀經計畫（可加環境變數 ONEYEAR_CA_BUNDLE 指定 CA）
python3 scrape_oneyear.py          # -> data/oneyear_plan.json

# 2) 產生網站資料（需要 verses/ 經文來源）
python3 build_site_data.py         # -> docs/data/
```
