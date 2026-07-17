export const meta = {
  name: 'audit-ref-links',
  description: '每條註解一次判讀，語意檢查經節引用連結是否指對，回報有疑慮的部分',
  phases: [{ title: 'Audit', detail: '每天一個 agent 判讀該天註解的連結' }],
  model: 'sonnet',
}

// 只跑未稽核的天數。前兩輪（wf_6d0edecb-c43 / wf_4a4bc22c-c00）都被
// session limit 中斷，已完成 271 天，結果在 audit/concerns.tsv。
// 這裡列出剩下的區間，不重跑已完成的。
const RANGES = [[326, 364]]

const RULES = `
這是恢復本聖經註解的經節引用連結。連結由規則式解析器產生，你的工作是「語意判讀它指對了沒有」。

## 引用文法（解析器遵循的規則，已與領域專家逐條確認）
- 章用中文數字、節用阿拉伯數字。「太十二42」= 馬太福音 12:42。
- 中文數字：十=10、十X=10+X、X十=X*10，其餘位值展開（一一九=119、一○四=104，○ 是 0）。
- 無卷名的「章+節」（如「二六4」）→ 承接鏈內最近提到的卷；遇句號、分號、左括弧重設回註解所屬的本卷。
- 裸節（如「26節」「（16。）」）→ 承接鏈內最近的章；同樣規則重設。
- 分隔符「，、與和及至」之間，鏈保持存活並承接（卷,章）。
- 「見」「參」是提示詞，不影響目標，也不打斷鏈。
- 範圍（「路三23～38」「一1～二25」）→ 目標取起點。
- 半節「上/下/中」→ 仍是該節。
- 「本書」=註解所屬的卷、「本章」=所屬的章、「該章」=最近提到的章。
- 單章書（門/猶/俄/約貳/約參）寫成「猶11」，即 猶 1:11。

## 你只會看到「靠承接推論出來的」連結
自帶卷名的引用（如「代上三11～12」）已排除 —— 那種解析器沒有推論，卷章節都寫在原文裡。
你看到的都是解析器**猜**出卷或章的，這正是會出錯的地方。

## 最常見的錯誤類型（優先檢查）
1. **承接斷錯地方**：最主要的錯誤來源。例「（創二二17～18，加三16，14。）」的「14」必須是加拉太書 3:14，不是註解所屬的卷。
   已知實例：可14:20 註1「主的晚餐是在前面19～20節題起的」，前文是「路二二21～23」，故該接路22:19（設立主晚餐處），而非本卷可14:19。
2. **反例（不要過度回報）**：申30:12 註「保羅將摩西在11～14節所說的」雖然前文有「羅十6～8」，但 11～14節 指的是本卷申30，不是承接羅10。
   關鍵在語意：前文的引用是「正在討論的主題」還是「順帶插注」。
3. **非經節的數字**：大綱編號（如「（１）（２）（３）」與「(四)(五)」平行）被誤當成裸節。這種要回報，suggest 寫「不應連結」。

## 判讀原則（極重要）
- **預設是「沒問題」。只有你能說出具體理由時才回報。**
- 誤報的代價很高：這份清單要給人工裁決，充滿假警報就失去意義。
- 你不能修改連結，只能舉手。
- 目標經節「存在」不必檢查（已用全本聖經驗證過）。你要判斷的是**語意上是否為註解真正在講的那一節**。
- 註解常引用「進一步閱讀」的經文，主題不必然完全一致 —— 不要因為「看起來不太相關」就回報。要有具體的解析理由。
`

const SCHEMA = {
  type: 'object',
  properties: {
    findings: {
      type: 'array',
      items: {
        type: 'object',
        properties: {
          id: { type: 'string', description: '該連結的 id 欄位，原樣照抄（形如 可14:20#1@145）' },
          link_text: { type: 'string' },
          target: { type: 'string', description: '目前指向的目標' },
          issue: { type: 'string', description: '具體的問題描述，說明為什麼可疑' },
          suggest: { type: 'string', description: '你認為正確的目標；不該連結就寫「不應連結」；不確定寫「不確定」' },
          severity: { type: 'string', enum: ['high', 'medium', 'low'] },
        },
        required: ['id', 'link_text', 'target', 'issue', 'suggest', 'severity'],
      },
    },
    checked: { type: 'number', description: '你實際檢視的連結筆數' },
  },
  required: ['findings', 'checked'],
}

const days = []
for (const [a, b] of RANGES) for (let d = a; d <= b; d++) days.push(d)

function auditDay(d) {
  const p = String(d).padStart(3, '0')
  return agent(
    `${RULES}

讀取 /Users/gary.yc.lin/Projects/bible-reading-loop/audit/packets/day-${p}.json（用 Read 工具，務必看完全部 items）。

每筆 item 是**一條註解**：
- host：這條註解屬於哪一節
- text：註解全文，待驗的連結就地標成【1:原文】【2:原文】…
- links：每個標記對應的目標
  - n：對應 text 裡的【n:…】
  - id：識別碼，回報時原樣照抄
  - text / target / target_text：原文、目前指向的目標、目標那節的經文

對每條註解，順著 text 讀，判斷每個【n】的 target 是否為該處引用真正該指向的經節。
注意承接鏈：前面出現的卷/章會被後面沒有卷名的引用承接。

回報有疑慮的，沒疑慮的不要列。checked 填你實際看過的連結筆數。
若整天都沒有疑慮，findings 回空陣列。`,
    { label: `day-${p}`, phase: 'Audit', schema: SCHEMA, model: 'sonnet' }
  )
}

// 序列執行，一次只跑一個 agent —— 一次並行 16 個會瞬間打爆每分鐘請求數（429）。
// 慢，但穩；被中斷後 resumeFromRunId 會讓跑過的直接拿快取。
const results = []
for (const d of days) {
  results.push(await auditDay(d))
  log(`day-${String(d).padStart(3, '0')} 完成（${results.length}/${days.length}）`)
}

const ok = results.filter(Boolean)
const findings = ok.flatMap((r, i) => (r.findings || []).map(f => ({ ...f, day: days[i] })))
const checked = ok.reduce((a, r) => a + (r.checked || 0), 0)
log(`完成 ${ok.length}/${days.length} 天，檢視 ${checked} 筆，回報疑慮 ${findings.length} 筆`)

return {
  range: RANGES.map(r => r.join('-')).join(', '),
  days_done: ok.length,
  days_failed: days.length - ok.length,
  checked,
  findings,
}
