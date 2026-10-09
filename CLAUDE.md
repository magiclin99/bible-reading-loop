# CLAUDE.md — 給 AI 的專案地圖

一年讀經一遍的靜態讀經器。使用者面向的功能說明見 `README.md`；這裡是
**開發者/AI 視角的結構圖與地雷清單**，尤其是 README 沒涵蓋的「註解經節引用
超連結」子系統。

## 兩句話總覽

- 網站是純靜態的，**執行時只讀 `docs/`**。所有 `.py`、`links.tsv`、`audit/`
  都是 build 工具或記錄，不會被運行中的網站載入。
- 核心資料流：`refs.py`（解析器）→ `links.tsv`（可稽核清單）→ `docs/data`（編譯產物）→ `docs/app.js`（前端渲染）。
- 綱目是另一條平行的管線：恢復本資料庫 → `outline.tsv` → `docs/data`，與連結互不影響。

## 檔案地圖

### 網站本體（改這些會直接影響使用者）
- `docs/index.html` `docs/app.js` `docs/style.css` — 前端
- `docs/data/day-NNN.json` `docs/data/index.json` — **編譯產物，不要手改**
- `docs/firebase-config.js` — 跨裝置同步的 Firebase 設定；`null` = 功能整個關閉
- `firestore.rules` `firebase.json` — 同步的安全規則與模擬器設定（網站不載入，
  但規則是雲端資料唯一的防線）

### 引用連結管線（改註解或解析規則時用）
| 檔案 | 作用 |
|---|---|
| `refs.py` | 引用解析器。純函式。規則與理由都寫在檔頭與行內註解 |
| `corpus.py` | 從 docs/data 讀出解析器要的表（各章最大節、簡稱↔全名、日段定位） |
| `build_links.py` | 跑解析器 → 產出 `links.tsv` + 報告；套用人工覆寫 |
| `apply_links.py` | 把 `links.tsv` 編譯進 docs/data，並補 index.json 的 loc/abbr |
| `test_refs.py` | 回歸測試，每個 case 都是踩過的真坑。**改 refs.py 前後必跑** |
| `links.tsv` | 29371 個連結的清單，**這是可稽核的成品**（進版控） |
| `links_overrides.tsv` | 人工修正（稽核抓到的語意錯誤）。**不可刪**，刪了重建會退回錯連結 |

### 綱目管線
| 檔案 | 作用 |
|---|---|
| `build_outline.py` | 恢復本資料庫 → `outline.tsv`。**需要資料庫實體檔**（見下） |
| `apply_outline.py` | 把 `outline.tsv` 編譯進 docs/data（每節的 `outline` / `carry` 欄位） |
| `outline.tsv` | 3141 條綱目的清單，進版控。平常重建只需要它，不需要資料庫 |

資料庫是 `../cloud-food/db/bible.sqlite`（Git LFS；沒 pull 時只是 133 bytes 的
指標檔），同一個檔也在 `../bible-mcp/Bible20240820.sqlite`。綱目在
`outline_all_big5_05` 表，欄位名會誤導，對照寫在 `build_outline.py` 檔頭。

### 建置（源頭重建，需要 `../cloud-food/verses`）
- `build_site_data.py` — 計畫 + 經文源 → docs/data
- `scrape_oneyear.py` — 抓讀經計畫

### 稽核記錄（一次性，保留供追溯）
- `audit/README.md` `progress.tsv` `concerns.tsv` `verdicts.tsv` — 364 天語意稽核的過程與裁決
- `audit/consolidate.py` `audit-ref-links.js` — 當時的工具。**consolidate.py 已是死碼**（依賴已清除的 session transcript）

## 重建連結的流程

```bash
python3 build_links.py    # refs.py → links.tsv（看報告：未解釋數字應≈0）
python3 test_refs.py      # 必須全綠
python3 apply_links.py    # links.tsv → docs/data
```
改 `docs/data` 註解或改 `refs.py` 後跑這三步。**只跑這個不需要 verses/。**

`build_site_data.py` 從頭重建 docs/data 之後，連結和綱目都要重新編譯進去：
```bash
python3 apply_links.py
python3 apply_outline.py  # outline.tsv → docs/data，可重複執行
```

## 地雷（都是實際踩過、修過的，別重犯）

1. **href 存聖經座標，不存天數**。`#ref=創5:1` 不是 `#ref=day6`。天數是讀經
   計畫的產物，計畫一改所有連結就爛；座標永遠有效。天數在載入時用 `index.loc` 反查。

2. **驗證失敗不可退一格重試**。`書十三47`（無效）若退成 `十三47` 用 host 卷
   重解，會生出看似合理的錯連結。見 refs.py 的 `i = m.end(); continue`。

3. **承接歧義用覆寫，不改規則**。放寬承接會「修 1 個壞 30 個」（實測）。
   已知語意錯誤逐筆寫進 `links_overrides.tsv`，解析器維持不動。

4. **peek 模式**：localStorage 跨分頁共用。查考分頁（`#ref=` 開啟）**絕不可
   寫 state**，否則開新分頁會蓋掉原分頁閱讀位置。guard 在 `saveState()` 單點。

5. **空殼註解**：上游 extract_verses.py 對重複註標會產生空 body 的第二筆。
   已在 corpus.py / build_site_data.py 濾除；不濾會讓標號在一節內不唯一。

6. **中文數字含 `○`（=0）**，如 `一○四`=104。字元集是 `一二三四五六七八九十○`；
   `百`/`零` 不是章數字（只在散文出現）。

7. **全形阿拉伯數字**：`（１）（２）` 是大綱編號不是節號，但 Python `\d` 會吃。
   已在覆寫清單處理掉那 6 處。

8. **驗證的「零失敗」只證明目標存在，不證明指對了**。承接錯誤（如可14:20）
   目標是存在的，只有語意判讀抓得到。這是 audit/ 那輪稽核存在的理由。

9. **綱目收合狀態只放記憶體**（`folded`），不寫 localStorage。理由同第 4 點，
   而且預設就該是「綱目＋經文」全展開。

10. **一節可能是兩個 `.verse` 元素**。74 節被綱目從中間切開（如創1:2），上下
    兩塊帶同樣的 `data-bk/ch/v`。找經節一律用 `verseEls()`，註解框接在最後
    一塊之後；用 `querySelector` 只會拿到上半節。

11. **綱目收的是經文，不是子綱目**。點一條綱目只藏它轄下的 `.ol-body`，各層
    子綱目照樣顯示，所以「全部收合」剩下的是當日綱目骨架。少數綱目在原始
    資料裡同節並列、底下沒有經文（`.ol.empty`），不可收合。

12. **同步不可取聯集，也不可在套用雲端資料時重蓋時間戳**。已讀標記逐筆比
    `blr:stamps` 的時間（取消已讀也是一筆改動，取聯集會讓它在另一台復活）；
    閱讀位置比 `state.posAt`。`mergeRemote()` 套用別台的位置時先把 `lastPos`
    對齊，否則 `saveState()` 會把它當成本機剛改的、蓋成現在時間，下次就
    反過來壓掉真正較新的那台。

13. **查考分頁完全不碰雲端**（`loadFirebase()` 單點擋掉，理由同第 4 點）。它
    標的已讀靠 `storage` 事件由原分頁代傳。

14. **登入按鈕不可在 `await` 之後才開視窗**。Safari 只准在點擊的同一拍
    `window.open`，所以 SDK 在打開日程頁時就預載；別為了省流量改成按下才載。

15. **剛登入的第一次同步，位置不可照時間戳自動決定**。在新裝置上隨手翻兩頁
    的時間戳，會比另一台讀了 23 天、升級前沒有時間戳的位置「新」，照「新的
    贏」就把真正的進度蓋掉了。所以 `blr:sync` 有 `link`（剛登入）這個狀態：
    兩邊都動過位置且不同時 `askLink()` 問使用者，期間位置擱著、已讀照常
    合併。選完才轉成 `1`，重新整理也不會跳過這一問。

16. **One Tap 只問一次，且不可拖著 Firebase SDK 一起載**。`offerOneTap()` 只載
    Google 的登入腳本，使用者點了才 `loadFirebase()`；關掉或登出就寫
    `blr:onetap`，之後不再跳。它的浮層是瀏覽器畫的（FedCM），不在 DOM 裡，
    自動化截圖看不到，只能人眼驗。

## 驗證真的動起來

改完務必實跑，不能只看程式碼：
- `python3 test_refs.py` 全綠
- `cd docs && python3 -m http.server 8000`，實測 deep link（`#ref=加3:14` 應落在
  加拉太書、`#ref=伯9:5&n=1` 應展開註1）、跨分頁不覆蓋閱讀位置
- 同步：`firebase emulators:start --only auth,firestore --project demo-blr`，
  把 `docs/firebase-config.js` 暫時改成
  `{ apiKey: 'demo', authDomain: 'demo-blr.firebaseapp.com', projectId: 'demo-blr', emulator: true }`，
  用兩個不同 port 的 http.server 當兩台裝置（origin 不同，localStorage 就分開）。
  現在設定檔裡是正式專案，別直接改它：另開一個目錄把 `docs/` 的檔案 symlink
  過去、只換掉 `firebase-config.js`，從那裡起 server。瀏覽器會快取 `app.js`，
  改完程式要強制重新整理
- 綱目：舊約第 1 天（創1:2 應切成「2」「2下」兩塊）、右上「收合」後只剩綱目、
  點單條綱目只收它底下的經文
