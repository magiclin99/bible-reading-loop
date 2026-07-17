# CLAUDE.md — 給 AI 的專案地圖

一年讀經一遍的靜態讀經器。使用者面向的功能說明見 `README.md`；這裡是
**開發者/AI 視角的結構圖與地雷清單**，尤其是 README 沒涵蓋的「註解經節引用
超連結」子系統。

## 兩句話總覽

- 網站是純靜態的，**執行時只讀 `docs/`**。所有 `.py`、`links.tsv`、`audit/`
  都是 build 工具或記錄，不會被運行中的網站載入。
- 核心資料流：`refs.py`（解析器）→ `links.tsv`（可稽核清單）→ `docs/data`（編譯產物）→ `docs/app.js`（前端渲染）。

## 檔案地圖

### 網站本體（改這些會直接影響使用者）
- `docs/index.html` `docs/app.js` `docs/style.css` — 前端
- `docs/data/day-NNN.json` `docs/data/index.json` — **編譯產物，不要手改**

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

## 驗證真的動起來

改完務必實跑，不能只看程式碼：
- `python3 test_refs.py` 全綠
- `cd docs && python3 -m http.server 8000`，實測 deep link（`#ref=加3:14` 應落在
  加拉太書、`#ref=伯9:5&n=1` 應展開註1）、跨分頁不覆蓋閱讀位置
