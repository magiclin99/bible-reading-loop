# 一年讀經一遍 · bible-reading-loop

按「新約 + 舊約」雙軌一年讀完一遍的線上讀經器。純靜態網頁，
資料來自 [line.twgbr.org 恢復版一年讀經](https://line.twgbr.org/recoveryversion/oneyear/2026.html)，
經文與註解為恢復版。

## 功能

- 首次進入顯示第 1 天（馬太福音 1:1-6）。
- 右上角切換新約／舊約（同一天兩條軌道）。
- 上下捲動讀經文；← → 鍵或底部按鈕切換前後天。
- 點經節展開該節的恢復版註解，再點收合。
- 經文之間穿插恢復版綱目。點綱目可收合它底下的經文；右上角「收合」
  一次收起全部經文，只留當天的綱目（快捷鍵 `O`）。
- 底部按鈕標記當天當軌道「讀完」；新約、舊約分開記。
- 可瀏覽全部 364 天、跳到任一天，或把某天「設為第一天」
  （之後以那天為你的第 1 天，讀滿 364 天繞一圈）。
- 重新整理會回到上次的天／軌道／捲動位置，並提示已恢復。
- 進度存在瀏覽器 `localStorage`（`blr:state`、`blr:read`）。
- 跨裝置同步（選用）：以 Google 登入後，已讀標記與閱讀位置會同步到其他裝置。
  還沒登入過的裝置開頁時會跳一次 Google One Tap；關掉後就不再跳，之後從
  「全部日程」裡的按鈕登入。需要先設定 Firebase，見下方「跨裝置同步」；沒設定時
  不會出現登入列。

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

## 跨裝置同步（選用）

用 Firebase 免費方案（Spark，不綁信用卡就不會產生費用），沒有自己的後端。

1. 到 [Firebase 主控台](https://console.firebase.google.com/) 建專案。
2. **Authentication → Sign-in method** 啟用 Google；**Settings → Authorized
   domains** 加入 `magiclin99.github.io`。
3. **Firestore Database** 建立資料庫，選「正式版模式」（不要選測試模式）。
4. 部署安全規則：`firebase deploy --only firestore:rules --project <專案 ID>`，
   或把 `firestore.rules` 的內容貼到主控台的「規則」分頁。
5. **專案設定 → 你的應用程式** 新增網頁應用程式，把得到的 `firebaseConfig`
   物件貼進 `docs/firebase-config.js`（取代 `null`）。
6. One Tap：到 Google Cloud Console → API 和服務 → 憑證，打開 Firebase 自動
   建立的 Web client，在「已授權的 JavaScript 來源」加上
   `https://magiclin99.github.io`、`http://localhost`、`http://localhost:8000`，
   再把它的用戶端 ID 填進 `firebase-config.js` 的 `googleClientId`。
   不填就不跳 One Tap，只留日程頁的登入按鈕。
7. （建議）到 Google Cloud Console → API 和服務 → 憑證，把那把 API key 的
   HTTP 參照網址限制為 `magiclin99.github.io/*` 和 `localhost`。

`firebase-config.js` 的內容是公開值，可以進版控；擋人的是 `firestore.rules`
（每個人只能讀寫自己的 `progress/{uid}`）。

合併規則：已讀標記逐筆比時間、新的贏（取消已讀也會同步）；閱讀位置整組
新的贏；捲動位置不同步。唯一會問人的情況：剛登入時，這台裝置和帳號裡的
閱讀位置不一樣，會跳出來讓你選要接續哪一個（已讀記錄不受影響）。

## 資料重建（選用）

```bash
# 1) 重新抓讀經計畫（可加環境變數 ONEYEAR_CA_BUNDLE 指定 CA）
python3 scrape_oneyear.py          # -> data/oneyear_plan.json

# 2) 產生網站資料（需要 verses/ 經文來源）
python3 build_site_data.py         # -> docs/data/

# 3) 把註解引用連結與綱目編譯進去（不需要 verses/）
python3 apply_links.py             # links.tsv   -> docs/data/
python3 apply_outline.py           # outline.tsv -> docs/data/
```
