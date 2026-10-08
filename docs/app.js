// ── 一年讀經一遍 · 靜態閱讀器 ────────────────────────────────
'use strict';

const TOTAL = 364;                 // day 365 source is a 404; plan is 364 days
const LS_STATE = 'blr:state';
const LS_READ  = 'blr:read';
const LS_STAMPS = 'blr:stamps';    // 已讀標記的時間戳，跨裝置合併用
const LS_SYNC  = 'blr:sync';       // 這台裝置登入過同步 -> 開機時才載 Firebase
                                   // 'link' = 剛登入，位置還沒跟帳號對過；'1' = 已對過
const LS_ONETAP = 'blr:onetap';    // 關掉過 One Tap 或登出過 -> 不再自動跳登入

// ── Deep link ────────────────────────────────────────────────
// #ref=創5:1 或 #ref=伯9:5&n=1
// href 存的是聖經座標而非天數：天數是讀經計畫的產物，計畫一改就全爛了。
// 天數在載入時才用 index.loc 反查。
function parseHash() {
  const m = /^#ref=([^&]+)(?:&n=(\d+))?/.exec(location.hash || '');
  if (!m) return null;
  const r = /^(.+?)(\d+):(\d+)$/.exec(decodeURIComponent(m[1]));
  return r ? { abbr: r[1], ch: +r[2], v: +r[3], note: m[2] || null } : null;
}
// 查考分頁：由註解的連結開新分頁而來。localStorage 是跨分頁共用的，若這裡
// 照常存檔，就會把原分頁的閱讀位置蓋掉 —— 開新分頁反而弄丟進度，正好與
// 「不打擾閱讀」的用意相反。故 peek 時一律不寫 state。
//
// PEEK 恆定（這個分頁永遠不准寫入）；peekView 則是「此刻仍停在被查考的
// 那一節」。使用者一旦在查考分頁換日，頂部列就該顯示正常的天數，否則
// 標題會繼續說「查考 · 創世記 22:17」而內容早就換了。
const PEEK = parseHash();
let peekView = !!PEEK;

// ── State ────────────────────────────────────────────────────
// posAt：閱讀位置（startDay/currentDay/currentTrack）最後一次被使用者改動的
// 時間，跨裝置同步時整組比新舊。
const defaults = { startDay: 1, currentDay: 1, currentTrack: 'nt', scroll: {}, posAt: 0 };
let state = loadState();
let read  = loadRead();
let stamps = loadStamps();         // readKey -> 最後一次標記或取消的時間
const posSig = () => `${state.startDay}|${state.currentDay}|${state.currentTrack}`;
let lastPos = posSig();            // 上次存檔時的位置，用來判斷位置是否真的變了
let index = null;                  // data/index.json
const cache = new Map();           // origDay -> day bundle
let restoreScrollTo = null;        // px to restore after first render
let pendingFlash = null;           // {book,ch,v} 待定位高亮的經節
const openNotes = new Set();       // 展開中的註解，key = vkey()
const vkey = (bk, ch, v) => `${bk}-${ch}-${v}`;
// 收合中的綱目。只放記憶體：每次開啟都是「綱目＋經文」全展開，也不必碰
// localStorage（查考分頁不可寫 state，見 saveState）。
const folded = new Set();          // key = fkey(日段內的綱目序號)
const fkey = (sec) => `${state.currentDay}-${state.currentTrack}-${sec}`;

function loadState() {
  let s;
  try { s = Object.assign({}, defaults, JSON.parse(localStorage.getItem(LS_STATE) || '{}')); }
  catch { s = Object.assign({}, defaults); }
  // 有同步之前就存下的位置沒有 posAt。給它最小的正值：年代不明，但確實是
  // 使用者讀到的地方，要贏過另一台全新裝置的預設值（posAt 0）。
  if (!s.posAt && (s.startDay !== 1 || s.currentDay !== 1 || s.currentTrack !== 'nt')) s.posAt = 1;
  return s;
}
function saveState() {
  if (PEEK) return;                // 見上：查考分頁不可覆蓋閱讀位置
  // render() 每次都會存檔（標記已讀、捲動也會），只有位置真的變了才算改動
  if (posSig() !== lastPos) { lastPos = posSig(); state.posAt = Date.now(); syncSoon(); }
  try { localStorage.setItem(LS_STATE, JSON.stringify(state)); } catch {}
}

// 聖經座標 -> {day, track}。index.loc 每卷書記錄各天區段的起點，
// 找「最後一個起點 <= 目標」即得。730 筆涵蓋全部 31103 節。
function resolve(abbr, ch, v) {
  const segs = index.loc[abbr];
  if (!segs) return null;
  let best = -1;
  for (let i = 0; i < segs.length; i++) {
    const [c, vv] = segs[i];
    if (c < ch || (c === ch && vv <= v)) best = i; else break;
  }
  return best < 0 ? null : { day: segs[best][2], track: segs[best][3] };
}
function loadRead() {
  try { return new Set(JSON.parse(localStorage.getItem(LS_READ) || '[]')); }
  catch { return new Set(); }
}
function loadStamps() {
  try { return JSON.parse(localStorage.getItem(LS_STAMPS) || '{}') || {}; }
  catch { return {}; }
}
function saveRead() {
  try {
    localStorage.setItem(LS_STAMPS, JSON.stringify(stamps));
    localStorage.setItem(LS_READ, JSON.stringify([...read]));
  } catch {}
}

// ── Day numbering (loop) ─────────────────────────────────────
// startDay only relabels; reading order is the natural cyclic 1..TOTAL.
const userDayOf = (orig) => ((orig - state.startDay + TOTAL) % TOTAL) + 1;
const nextOrig  = (orig) => (orig % TOTAL) + 1;
const prevOrig  = (orig) => ((orig - 2 + TOTAL) % TOTAL) + 1;
const readKey   = (orig, track) => `${orig}-${track}`;
const isRead    = (orig, track) => read.has(readKey(orig, track));

// ── Progress (accumulation, not dates) ───────────────────────
// Total readable portions of a track, and how many are marked read.
const trackTotal = (track) => index.days.filter(d => d[track]).length;
const trackRead  = (track) => index.days.filter(d => d[track] && isRead(d.day, track)).length;

// Where the current day sits inside its Bible book, and how much of that
// book is already read — a near-term milestone, gentler than the 364 total.
function bookProgress(orig, track) {
  const book = index.days[orig - 1][track].book;
  const days = index.days.filter(d => d[track] && d[track].book === book).map(d => d.day);
  return {
    book,
    pos:   days.indexOf(orig) + 1,
    total: days.length,
    readN: days.filter(o => isRead(o, track)).length,
  };
}

// ── Data loading ─────────────────────────────────────────────
async function loadIndex() {
  const r = await fetch('data/index.json');
  index = await r.json();
}
async function loadDay(orig) {
  if (cache.has(orig)) return cache.get(orig);
  const r = await fetch(`data/day-${String(orig).padStart(3, '0')}.json`);
  const d = await r.json();
  cache.set(orig, d);
  return d;
}
function prefetch(orig) {
  loadDay(nextOrig(orig)).catch(() => {});
  loadDay(prevOrig(orig)).catch(() => {});
}

// ── Elements ─────────────────────────────────────────────────
const el = (id) => document.getElementById(id);
const pager = el('pager'), page = el('page');

// ── Render ───────────────────────────────────────────────────
async function render(slideDir) {
  const orig = state.currentDay;
  let day;
  try { day = await loadDay(orig); }
  catch { page.innerHTML = `<p style="text-align:center;color:var(--ink-soft)">載入失敗，請檢查網路。</p>`; return; }

  const track = pickTrack(day);
  state.currentTrack = track;
  const t = day[track];

  // top bar (no date — progress, not schedule)
  if (peekView) {
    el('bar-day').textContent = '查考';
    el('bar-ref').textContent = `${index.abbr[PEEK.abbr]} ${PEEK.ch}:${PEEK.v}`;
  } else {
    el('bar-day').textContent = `第 ${userDayOf(orig)} 天`;
    el('bar-ref').textContent = t ? t.ref : '（無內容）';
  }
  updateProgress(track);
  const other = track === 'nt' ? 'ot' : 'nt';
  const tk = el('btn-track');
  tk.className = `track-toggle ${track}`;
  tk.textContent = track === 'nt' ? '新約' : '舊約';
  tk.title = `切換到${other === 'nt' ? '新約' : '舊約'}`;

  // read button
  const done = isRead(orig, track);
  const rb = el('btn-read');
  rb.className = `read-btn${done ? ' done' : ''}`;
  rb.textContent = done ? `✓ ${track === 'nt' ? '新約' : '舊約'}已讀完` : `標記${track === 'nt' ? '新約' : '舊約'}讀完`;

  // body
  page.innerHTML = buildDayHTML(day, track);
  syncFold();
  page.className = slideDir === 'next' ? 'slide-left' : slideDir === 'prev' ? 'slide-right' : '';

  // scroll: 定位高亮 > 還原上次位置 > 回到頂端（三者互斥，不可各自搶捲動）
  if (pendingFlash) {
    const f = pendingFlash; pendingFlash = null;
    flashTo(f.book, f.ch, f.v, f.note);
  } else if (restoreScrollTo != null) {
    pager.scrollTop = restoreScrollTo; restoreScrollTo = null;
  } else {
    pager.scrollTop = 0;
  }

  saveState();
  prefetch(orig);
}

// overall accumulation strip under the top bar
function updateProgress(track) {
  const fill = el('progress-fill');
  const total = trackTotal(track), done = trackRead(track);
  fill.className = track;
  fill.style.width = total ? (done / total * 100) + '%' : '0';
}

// choose which track to show: honor stored track if it exists this day
function pickTrack(day) {
  if (day[state.currentTrack]) return state.currentTrack;
  return day.nt ? 'nt' : 'ot';
}

function buildDayHTML(day, track) {
  const t = day[track];
  if (!t) return `<p style="text-align:center;color:var(--ink-soft)">這一天沒有${track === 'nt' ? '新約' : '舊約'}內容。</p>`;

  // Book name + range live in the fixed top bar; only label books inline when
  // a day spans more than one book (so the two books can be told apart).
  const multiBook = new Set(t.verses.map(v => v.book)).size > 1;

  // In-page header: book progress (near milestone) + running total (accumulation)
  const bp = bookProgress(day.day, track);
  const total = trackTotal(track), done = trackRead(track);
  const bookPct = bp.total ? Math.round(bp.readN / bp.total * 100) : 0;
  const trackName = track === 'nt' ? '新約' : '舊約';
  let h = `<div class="day-head">
      <div class="dh-title">${escapeHTML(bp.book)}</div>
      <div class="dh-bookbar ${track}"><span style="width:${bookPct}%"></span></div>
      <div class="dh-sub">本卷 第 ${bp.pos} / ${bp.total} 天　·　${trackName}累積 ${done} / ${total}</div>
    </div>`;
  // 綱目與經文是平鋪的兄弟節點：[綱目][經文區塊][綱目][經文區塊]…
  // 每個 .ol-body 記著它屬於哪一條綱目（data-sec），收合就是藏掉 body。
  // 章標、卷標放在 body 之外，全部收合後仍留著當路標。
  let curCh = null, curBook = null;
  let sec = -1, nSec = 0, bodyOpen = false;
  const openBody  = () => { if (!bodyOpen) { h += `<div class="ol-body" data-sec="${sec}">`; bodyOpen = true; } };
  const closeBody = () => { if (bodyOpen) { h += `</div>`; bodyOpen = false; } };
  const heading = (lv, text, carry) => { closeBody(); sec = nSec++; h += outlineHTML(sec, lv, text, carry); };
  for (const vs of t.verses) {
    if (vs.book !== curBook) {           // book change within a day (cross-book)
      curBook = vs.book; curCh = null;
      if (multiBook) {
        closeBody();
        h += `<div class="book-mark" style="text-align:center;font-weight:800;font-size:18px;margin:22px 0 4px">${vs.book}</div>`;
      }
    }
    if (vs.ch !== curCh) {
      curCh = vs.ch;
      const unit = vs.abbr === '詩' ? '篇' : '章';
      closeBody();
      h += `<div class="ch-mark" style="font-weight:700;color:var(--ink-soft);margin:16px 0 4px;font-size:14px">第 ${curCh} ${unit}</div>`;
    }
    for (const [lv, text] of vs.carry || []) heading(lv, text, true);

    const hasNote = vs.notes && vs.notes.length;
    const k = vkey(vs.book, vs.ch, vs.v);
    const open = openNotes.has(k);
    // 綱目可能落在一節的中間（如創1:2「…淵面黑暗。‖神的靈…」），那一節就
    // 切成上下兩塊，各自歸屬不同的綱目。兩塊帶同樣的 data-bk/ch/v。
    let pos = 0, part = 0;
    const chunk = (end) => {
      openBody();
      h += `<p class="verse${hasNote ? ' has-note' : ''}${open ? ' open' : ''}${part ? ' cont' : ''}" data-bk="${escapeHTML(vs.book)}" data-ch="${vs.ch}" data-v="${vs.v}">`
         + `<span class="vn">${vs.v}${part ? '下' : ''}</span><span class="vtext">${escapeHTML(vs.text.slice(pos, end))}</span></p>`;
      pos = end; part++;
    };
    for (const [at, lv, text] of vs.outline || []) {
      if (at > pos) chunk(at);
      heading(lv, text, false);
    }
    chunk(vs.text.length);
    // 展開狀態存在 openNotes 而非只在 DOM，否則任何一次 render（例如按
    // 「標記讀完」）都會把使用者展開的註解全部清空。
    if (open) h += notesHTML(vs);
  }
  closeBody();
  return h;
}

// ── 綱目 ─────────────────────────────────────────────────────
function outlineHTML(sec, lv, text, carry) {
  // 「壹　神的創造　一1～二25」以全形空白分段；末段帶數字的是經節範圍
  const parts = text.split('\u3000');
  const range = parts.length >= 3 && /[0-9０-９]/.test(parts[parts.length - 1]) ? parts.pop() : '';
  let title = parts.join('\u3000');
  // 承接自前幾天的綱目：沿用紙本「（續）」的標法
  if (carry && !title.includes('續')) title += '（續）';
  return `<button type="button" class="ol ol-l${lv}${carry ? ' carry' : ''}" data-sec="${sec}" data-lv="${lv}">`
       + `<span class="ol-tw" aria-hidden="true"></span>`
       + `<span class="ol-t">${escapeHTML(title)}${range ? `<span class="ol-r">${escapeHTML(range)}</span>` : ''}</span>`
       + `</button>`;
}

// 綱目恆顯示，收合的只有經文。點一條綱目，收起它底下（含各層子綱目）的
// 經文，子綱目本身留著 —— 所以全部收合後剩下的正是當日的綱目骨架。
function foldScope() {
  const heads = [...page.querySelectorAll('.ol')];
  const bodies = [...page.querySelectorAll('.ol-body')];
  const owns = new Set(bodies.map(b => +b.dataset.sec).filter(i => i >= 0));
  // 某條綱目轄下、且真的帶有經文的綱目（含自己）
  const under = (i) => {
    const lv = +heads[i].dataset.lv, out = [];
    for (let j = i; j < heads.length && (j === i || +heads[j].dataset.lv > lv); j++) {
      if (owns.has(j)) out.push(j);
    }
    return out;
  };
  return { heads, bodies, owns: [...owns], under };
}
const allFolded = (secs) => secs.length > 0 && secs.every(j => folded.has(fkey(j)));
function setFolded(secs, on) {
  for (const j of secs) on ? folded.add(fkey(j)) : folded.delete(fkey(j));
  syncFold();
}
function syncFold() {
  const { heads, bodies, owns, under } = foldScope();
  bodies.forEach(b => b.classList.toggle('folded', folded.has(fkey(b.dataset.sec))));
  heads.forEach((x, i) => {
    const secs = under(i), shut = allFolded(secs);
    // 原始綱目有少數幾條在同一節上連續並列（如啟22:3 的 a、b、c），前幾條
    // 底下沒有經文可收，就不給收合箭頭
    x.classList.toggle('empty', !secs.length);
    x.classList.toggle('folded', shut);
    x.setAttribute('aria-expanded', String(!shut));
  });
  const btn = el('btn-fold');
  btn.hidden = !owns.length;
  const shut = allFolded(owns);
  btn.classList.toggle('on', shut);
  btn.textContent = shut ? '展開' : '收合';
  btn.title = shut ? '展開全部經文' : '收合全部經文，只看綱目';
}
function toggleFold(i) {
  const secs = foldScope().under(i);
  setFolded(secs, !allFolded(secs));
}
function toggleFoldAll() {
  const { owns } = foldScope();
  if (!owns.length) return;
  const shut = allFolded(owns);
  setFolded(owns, !shut);
  if (!shut) pager.scrollTop = 0;      // 收合後內容短很多，從頭看綱目
}

function escapeHTML(s) {
  return s.replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}

// ── Notes + 引用連結 ─────────────────────────────────────────
function notesHTML(vs) {
  if (!vs.notes || !vs.notes.length) return '';
  return `<div class="notes">` + vs.notes.map(n =>
    `<div class="note" data-label="${escapeHTML(n.label)}">` +
    `<span class="note-label">註${escapeHTML(n.label)}</span>` +
    noteBodyHTML(n) + `</div>`
  ).join('') + `</div>`;
}

// links 的位移是相對於 body 全文，但 body 是以 \n\n 分段渲染的，
// 所以逐段推進累計位移，換算成段內位置。
function noteBodyHTML(n) {
  const links = n.links || [];
  let off = 0, h = '';
  for (const p of n.body.split('\n\n')) {
    h += `<p>${linkify(p, off, links)}</p>`;
    off += p.length + 2;
  }
  return h;
}

function linkify(text, off, links) {
  const end = off + text.length;
  const here = links.filter(l => l[0] >= off && l[1] <= end);
  if (!here.length) return escapeHTML(text);
  let h = '', cur = 0;
  for (const [s, e, ab, ch, v, note] of here) {
    const a = s - off, b = e - off;
    if (a < cur) continue;                       // 保險：重疊就跳過
    h += escapeHTML(text.slice(cur, a));
    const href = `#ref=${encodeURIComponent(`${ab}${ch}:${v}`)}` + (note ? `&n=${note}` : '');
    h += `<a class="ref" href="${href}" target="_blank" rel="noopener">`
       + escapeHTML(text.slice(a, b)) + `</a>`;
    cur = b;
  }
  return h + escapeHTML(text.slice(cur));
}

// 捲到某節並短暫高亮「就是這裡」
// 一節可能被綱目切成兩塊（見 buildDayHTML），註解框接在最後一塊之後
function verseEls(book, ch, v) {
  return [...page.querySelectorAll(
    `.verse[data-bk="${CSS.escape(book)}"][data-ch="${ch}"][data-v="${v}"]`)];
}

function flashTo(book, ch, v, label) {
  const els = verseEls(book, ch, v);
  const t = els[0];
  if (!t) return;
  const shut = els.map(x => x.closest('.ol-body.folded')).filter(Boolean);
  if (shut.length) setFolded(shut.map(b => +b.dataset.sec), false);
  t.scrollIntoView({ block: 'center' });
  if (label) {
    const box = els[els.length - 1].nextElementSibling;
    const nt = box && box.classList.contains('notes')
      && box.querySelector(`.note[data-label="${CSS.escape(label)}"]`);
    if (nt) nt.classList.add('flash');
  }
  els.forEach(x => x.classList.add('flash'));
  setTimeout(() => {
    els.forEach(x => x.classList.remove('flash'));
    page.querySelectorAll('.note.flash').forEach(x => x.classList.remove('flash'));
  }, 1800);
}

// ── Verse note expand (event delegation) ─────────────────────
page.addEventListener('click', (e) => {
  if (e.target.closest('a.ref')) return;      // 引用連結自己開新分頁
  const ol = e.target.closest('.ol');
  if (ol) { toggleFold(+ol.dataset.sec); return; }
  const v = e.target.closest('.verse');
  if (!v) return;
  const k = vkey(v.dataset.bk, +v.dataset.ch, +v.dataset.v);
  const els = verseEls(v.dataset.bk, v.dataset.ch, v.dataset.v);
  const last = els[els.length - 1];
  const existing = last.nextElementSibling;
  if (existing && existing.classList.contains('notes')) {
    existing.remove(); els.forEach(x => x.classList.remove('open')); openNotes.delete(k); return;
  }
  const day = cache.get(state.currentDay);
  const vs = day[state.currentTrack].verses.find(
    x => x.book === v.dataset.bk && x.ch == v.dataset.ch && x.v == v.dataset.v);
  const html = vs && notesHTML(vs);
  if (!html) return;
  els.forEach(x => x.classList.add('open'));
  last.insertAdjacentHTML('afterend', html);
  openNotes.add(k);                            // 讓展開狀態撐過下一次 render
});

// ── Navigation ───────────────────────────────────────────────
// 一離開被查考的那一節，頂部列就回到正常的天數顯示（但 PEEK 的存檔封鎖
// 不解除 —— 這個分頁自始至終都不該覆蓋原分頁的閱讀位置）。
function leavePeek() {
  if (!peekView) return;
  peekView = false;
  document.body.classList.remove('peek');
}
function go(orig, dir) { leavePeek(); state.currentDay = orig; render(dir); }
function next() { go(nextOrig(state.currentDay), 'next'); }
function prev() { go(prevOrig(state.currentDay), 'prev'); }

function toggleTrack() {
  const day = cache.get(state.currentDay);
  const other = state.currentTrack === 'nt' ? 'ot' : 'nt';
  if (!day[other]) { toast(`這一天沒有${other === 'nt' ? '新約' : '舊約'}`); return; }
  leavePeek();
  state.currentTrack = other;
  render();
}

function toggleRead() {
  const orig = state.currentDay, track = state.currentTrack;
  const k = readKey(orig, track);
  const label = track === 'nt' ? '新約' : '舊約';
  stamps[k] = Date.now();
  if (read.has(k)) { read.delete(k); toast(`已取消：${label}`); }
  else {
    read.add(k);
    const bp = bookProgress(orig, track);            // readN now includes this day
    if (bp.readN === bp.total) toast(`🎉 ${bp.book} 讀完了！`);
    else toast(`✓ 標記${label}讀完`);
  }
  saveRead();
  syncSoon();
  render();
}

el('btn-next').onclick = next;
el('btn-prev').onclick = prev;
el('btn-track').onclick = toggleTrack;
el('btn-read').onclick = toggleRead;
el('btn-fold').onclick = toggleFoldAll;

// keyboard
window.addEventListener('keydown', (e) => {
  if (!el('browse').hidden || !el('link').hidden) return;
  if (e.key === 'ArrowRight') next();
  else if (e.key === 'ArrowLeft') prev();
  else if (e.key === 't' || e.key === 'T') toggleTrack();
  else if (e.key === 'o' || e.key === 'O') toggleFoldAll();
});

// ── Scroll persistence (throttled) ───────────────────────────
let scrollTimer = null;
pager.addEventListener('scroll', () => {
  if (scrollTimer) return;
  scrollTimer = setTimeout(() => {
    scrollTimer = null;
    state.scroll = { day: state.currentDay, track: state.currentTrack, top: pager.scrollTop };
    saveState();
  }, 220);
}, { passive: true });

// ── Browse ───────────────────────────────────────────────────
let browseTrack = 'nt';
function openBrowse() {
  browseTrack = state.currentTrack;
  renderBrowse();
  el('browse').hidden = false;
  loadFirebase().catch(() => {});      // 先載好，按登入時才能同步開視窗（見 btn-sync）
}
function closeBrowse() { el('browse').hidden = true; }

function renderBrowse() {
  el('browse-track').textContent = browseTrack === 'nt' ? '看新約' : '看舊約';
  const total = trackTotal(browseTrack), done = trackRead(browseTrack);
  const pct = total ? Math.round(done / total * 100) : 0;
  el('browse-progress').innerHTML =
    `<div class="bp-bar ${browseTrack}"><span style="width:${pct}%"></span></div>` +
    `<div class="bp-txt">${browseTrack === 'nt' ? '新約' : '舊約'} 已讀 ${done} / ${total}（${pct}%）</div>`;
  const list = el('browse-list');
  // ordered by the user's day numbering (their day 1..TOTAL)
  let html = '';
  for (let u = 1; u <= TOTAL; u++) {
    const orig = ((state.startDay - 1 + (u - 1)) % TOTAL) + 1;
    const info = index.days[orig - 1];
    const tk = info[browseTrack];
    if (!tk) continue;
    const done = isRead(orig, browseTrack);
    const isCur = orig === state.currentDay;
    const isStart = orig === state.startDay;
    html += `<div class="card${isCur ? ' is-current' : ''}${isStart ? ' is-start' : ''}">
      <div class="card-main" data-orig="${orig}">
        <div class="card-day">第 ${u} 天${isCur ? ' · <span class="cur-tag">閱讀中</span>' : ''}${isStart ? ' · <span class="cur-tag">你的第1天</span>' : ''}</div>
        <div class="card-ref">${tk.ref}<span class="rmark ${done ? 'read' : 'unread'}">${done ? '✓ 已讀' : '未讀'}</span></div>
      </div>
      <button class="card-set" data-set="${orig}">設為第一天</button>
    </div>`;
  }
  list.innerHTML = html;
}

el('browse-list').addEventListener('click', (e) => {
  const main = e.target.closest('.card-main');
  if (main) {
    leavePeek();
    state.currentDay = +main.dataset.orig;
    state.currentTrack = browseTrack;
    closeBrowse(); render();
    return;
  }
  const set = e.target.closest('.card-set');
  if (set) {
    const orig = +set.dataset.set;
    leavePeek();
    state.startDay = orig;
    state.currentDay = orig;
    state.currentTrack = browseTrack;
    saveState();
    closeBrowse(); render();
    toast(`已設為第 1 天：${index.days[orig - 1][browseTrack].ref}`);
  }
});
el('browse-track').onclick = () => {
  browseTrack = browseTrack === 'nt' ? 'ot' : 'nt';
  renderBrowse();
};
el('btn-browse').onclick = openBrowse;
el('btn-close').onclick = closeBrowse;

// ── Toast ────────────────────────────────────────────────────
let toastTimer = null;
function toast(msg) {
  const t = el('toast');
  t.textContent = msg; t.hidden = false;
  requestAnimationFrame(() => t.classList.add('show'));
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    t.classList.remove('show');
    setTimeout(() => { t.hidden = true; }, 300);
  }, 2200);
}

// ── 跨分頁同步 ───────────────────────────────────────────────
// 開新分頁查考成為常態後，兩個分頁各自 saveRead() 會整包互相覆蓋。
function refreshReadUI() {
  updateProgress(state.currentTrack);
  const done = isRead(state.currentDay, state.currentTrack);
  const label = state.currentTrack === 'nt' ? '新約' : '舊約';
  const rb = el('btn-read');
  rb.className = `read-btn${done ? ' done' : ''}`;
  rb.textContent = done ? `✓ ${label}已讀完` : `標記${label}讀完`;
}
window.addEventListener('storage', (e) => {
  if (e.key !== LS_READ && e.key !== LS_STAMPS) return;
  read = loadRead();
  stamps = loadStamps();
  refreshReadUI();
  syncSoon();                      // 查考分頁不連雲端，它標的已讀由原分頁代傳
});

// ── 跨裝置同步（Firebase，選用）──────────────────────────────
// localStorage 仍是唯一的真相來源，雲端只是另一份拿來合併的副本。沒設定
// firebase-config.js、沒登入、離線時，閱讀器的行為完全不變。
//
// 合併規則：
//   已讀標記 —— 逐筆比時間戳，新的贏。不可取聯集：取消已讀會在另一台復活。
//              時間戳相同時已讀贏；舊資料沒有時間戳，一律當 0，所以兩台
//              舊裝置第一次登入的結果正好是聯集。
//   閱讀位置 —— startDay/currentDay/currentTrack 整組比 posAt，新的贏。
//              例外是剛登入的第一次同步：這台和帳號各有各的位置時，時間戳
//              分不出誰才是真正的進度（在新裝置上隨手翻兩頁就會比讀了
//              23 天的舊位置「新」），所以問使用者，見 askLink()。
//   捲動位置 —— 不同步。px 在手機與電腦上對不到同一處。
//
// 查考分頁完全不碰雲端（loadFirebase 單點擋掉），理由同 saveState 的 guard。
const FB_CFG = window.FIREBASE_CONFIG || null;
const FB_VER = '12.4.0';
let fb = null, fbLoading = null;   // SDK 只在登入過或打開日程頁時才載
let user = null;
let expectUser = false;            // 這台登入過，等 SDK 回報登入狀態中
let syncTimer = null, syncBusy = false, syncAgain = false, syncErr = false;

function loadFirebase() {
  if (!FB_CFG || PEEK) return Promise.resolve(null);
  return fbLoading || (fbLoading = (async () => {
    const base = `https://www.gstatic.com/firebasejs/${FB_VER}/firebase-`;
    const [app, auth, fs] = await Promise.all(
      ['app', 'auth', 'firestore-lite'].map(m => import(`${base}${m}.js`)));
    const { emulator, googleClientId, ...cfg } = FB_CFG;
    const a = app.initializeApp(cfg);
    const f = { auth: auth.getAuth(a), db: fs.getFirestore(a), authApi: auth, fs };
    if (emulator) {                // 本機測試：firebase emulators:start（見 CLAUDE.md）
      auth.connectAuthEmulator(f.auth, 'http://127.0.0.1:9099', { disableWarnings: true });
      fs.connectFirestoreEmulator(f.db, '127.0.0.1', 8088);
    }
    auth.onAuthStateChanged(f.auth, (u) => {
      user = u; expectUser = false;
      try {
        if (!u) localStorage.removeItem(LS_SYNC);
        else if (!localStorage.getItem(LS_SYNC)) localStorage.setItem(LS_SYNC, 'link');
      } catch {}
      renderSync();
      if (u) syncNow();
    });
    return fb = f;
  })().catch((e) => { fbLoading = null; throw e; }));
}

const validMark = (k) => { const m = /^([1-9]\d{0,2})-(nt|ot)$/.exec(k); return !!m && +m[1] <= TOTAL; };
const validDay  = (n) => Number.isInteger(n) && n >= 1 && n <= TOTAL;

// 把雲端那份併進本機；回傳要寫回雲端的整份文件，雲端已是最新則回傳 null。
function mergeRemote(remote) {
  const rMarks = (remote && remote.marks) || {}, rPos = (remote && remote.pos) || {};
  let push = !remote, marksChanged = false;

  for (const k of new Set([...read, ...Object.keys(stamps), ...Object.keys(rMarks)])) {
    if (!validMark(k)) continue;
    const lr = read.has(k), lt = stamps[k] || 0;
    const rr = !!(rMarks[k] && rMarks[k].r), rt = +(rMarks[k] && rMarks[k].t) || 0;
    if (rt > lt || (rt === lt && rr && !lr)) {
      rr ? read.add(k) : read.delete(k);
      if (rt) stamps[k] = rt;
      marksChanged = true;
    } else if (lt > rt || lr !== rr) push = true;
  }

  const lt = state.posAt || 0, rt = +rPos.at || 0;
  const rValid = validDay(rPos.startDay) && validDay(rPos.currentDay) &&
                 (rPos.currentTrack === 'nt' || rPos.currentTrack === 'ot');
  const rSig = `${rPos.startDay}|${rPos.currentDay}|${rPos.currentTrack}`;
  let moved = false, hold = false;
  if (linking() && rValid && lt > 0 && rt > 0 && rSig !== posSig()) {
    hold = true;                   // 兩邊都動過位置：先擱著，等使用者選
    askLink(rPos);
  } else if (rt > lt && rValid) {
    const before = posSig();
    state.startDay = rPos.startDay;
    state.currentDay = rPos.currentDay;
    state.currentTrack = rPos.currentTrack;
    state.posAt = rt;
    lastPos = posSig();            // 這是別台的改動，不可在 saveState 被蓋成現在
    moved = lastPos !== before;
    if (moved) state.scroll = {};
    saveState();
  } else if (lt > rt) push = true;
  if (!hold) linked();

  if (marksChanged) saveRead();
  if (moved) {
    render().then(() => toast(`已接續其他裝置的進度：第 ${userDayOf(state.currentDay)} 天 · ${state.currentTrack === 'nt' ? '新約' : '舊約'}`));
  } else if (marksChanged) refreshReadUI();
  if ((moved || marksChanged) && !el('browse').hidden) renderBrowse();

  if (!push) return null;
  const marks = {};
  for (const k of new Set([...read, ...Object.keys(stamps)])) {
    if (validMark(k)) marks[k] = { r: read.has(k), t: stamps[k] || 0 };
  }
  // 位置擱著時，已讀照常上傳，雲端的位置原封不動寫回去
  const p = hold ? { ...rPos, posAt: rt } : state;
  return { v: 1, marks, pos: {
    startDay: p.startDay, currentDay: p.currentDay,
    currentTrack: p.currentTrack, at: p.posAt || 0,
  } };
}

// 剛登入、這台和帳號的位置不一樣時問一次。已讀標記不受影響，兩邊照常合併。
// 選擇只是調整本機的 posAt，讓下一輪同步照平常的「新的贏」得出使用者要的結果。
const linking = () => { try { return localStorage.getItem(LS_SYNC) === 'link'; } catch { return false; } };
function linked() { try { if (linking()) localStorage.setItem(LS_SYNC, '1'); } catch {} }
function posLabel(p) {
  const t = index.days[p.currentDay - 1][p.currentTrack];
  const n = ((p.currentDay - p.startDay + TOTAL) % TOTAL) + 1;
  return `第 ${n} 天 · ${t ? t.ref : (p.currentTrack === 'nt' ? '新約' : '舊約')}`;
}
function askLink(rPos) {
  el('link-local').textContent = `這台裝置：${posLabel(state)}`;
  el('link-remote').textContent = `帳號裡的：${posLabel(rPos)}`;
  el('link').hidden = false;
}
function chooseLink(keepLocal) {
  state.posAt = keepLocal ? Date.now() : 0;
  saveState();
  linked();
  el('link').hidden = true;
  syncNow();
}
el('link-local').onclick  = () => chooseLink(true);
el('link-remote').onclick = () => chooseLink(false);

// 每次都是「拉 → 併 → 有差才寫」，所以重複呼叫是安全的。
async function syncNow() {
  clearTimeout(syncTimer); syncTimer = null;
  if (!user) return;
  if (syncBusy) { syncAgain = true; return; }
  syncBusy = true;
  try {
    const { doc, getDoc, setDoc } = fb.fs;
    const ref = doc(fb.db, 'progress', user.uid);
    const snap = await getDoc(ref);
    const out = mergeRemote(snap.exists() ? snap.data() : null);
    if (out) await setDoc(ref, out);
    syncErr = false;
  } catch (e) {
    syncErr = true;
    console.warn('同步失敗', e);
  }
  syncBusy = false;
  renderSync();
  if (syncAgain) { syncAgain = false; syncSoon(); }
}
function syncSoon() {
  if (!user) return;
  clearTimeout(syncTimer);
  syncTimer = setTimeout(syncNow, 2500);
}

// 回到分頁時拉一次（另一台可能讀過了）；離開時把還沒送出的變更趕快送掉
function syncWake() {
  if (user) syncNow();
  else if (expectUser) loadFirebase().catch(() => {});   // 開機時離線沒載到 SDK
}
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') syncWake();
  else if (syncTimer) syncNow();
});
window.addEventListener('online', syncWake);

function renderSync() {
  if (!FB_CFG || PEEK) return;
  el('sync').hidden = false;
  el('sync-txt').textContent =
    user ? `${syncErr ? '同步失敗，會自動重試' : '已開啟跨裝置同步'} · ${user.email || ''}`
         : expectUser ? '同步連線中…' : '登入後，閱讀進度會跨裝置同步';
  const btn = el('btn-sync');
  btn.hidden = !user && expectUser;
  btn.textContent = user ? '登出' : '以 Google 登入';
}
el('btn-sync').onclick = async () => {
  try {
    if (user) {
      await fb.authApi.signOut(fb.auth);
      oneTapOff();                 // 自己登出的人，下次開頁別再跳出來問
      toast('已登出，這台裝置的進度仍保留');
      return;
    }
    // Safari 只准在點擊的同一拍開視窗；SDK 若還沒載完，await 之後就會被擋，
    // 所以 openBrowse 先預載，這裡的 await 只是保底。
    const f = fb || await loadFirebase();
    await f.authApi.signInWithPopup(f.auth, new f.authApi.GoogleAuthProvider());
  } catch (e) {
    const code = e && e.code;
    if (code === 'auth/popup-closed-by-user' || code === 'auth/cancelled-popup-request') return;
    toast(code === 'auth/popup-blocked' ? '登入視窗被擋下，請再按一次' : '登入失敗，請稍後再試');
  }
};

// ── Google One Tap ───────────────────────────────────────────
// 一進頁面就浮出的「以 XXX 的身分繼續」。只給還沒登入過的裝置看，而且只問
// 一次：關掉就記在 LS_ONETAP，之後要登入走日程頁的按鈕。查考分頁不問。
// 這裡只載 Google 的登入腳本；Firebase SDK 等使用者真的點了才載。
function oneTapOff() { try { localStorage.setItem(LS_ONETAP, 'off'); } catch {} }
function offerOneTap() {
  if (!FB_CFG || !FB_CFG.googleClientId || PEEK || expectUser) return;
  try { if (localStorage.getItem(LS_ONETAP)) return; } catch { return; }
  const s = document.createElement('script');
  s.src = 'https://accounts.google.com/gsi/client';
  s.async = true;
  s.onload = () => {
    google.accounts.id.initialize({
      client_id: FB_CFG.googleClientId,
      use_fedcm_for_prompt: true,
      callback: async (resp) => {
        try {
          const f = await loadFirebase();
          await f.authApi.signInWithCredential(
            f.auth, f.authApi.GoogleAuthProvider.credential(resp.credential));
          toast('已登入，閱讀進度會跨裝置同步');
        } catch (e) {
          console.warn('One Tap 登入失敗', e);
          toast('登入失敗，請稍後再試');
        }
      },
    });
    // FedCM 下只剩 skipped / dismissed 兩種通知可查；skipped = 使用者按了關閉
    google.accounts.id.prompt((n) => { if (n.isSkippedMoment()) oneTapOff(); });
  };
  document.head.appendChild(s);
}

// ── Boot ─────────────────────────────────────────────────────
(async function boot() {
  await loadIndex();

  // 查考分頁：由引用座標反查天數，跳過去、定位、高亮。不動閱讀位置。
  if (PEEK) {
    const hit = resolve(PEEK.abbr, PEEK.ch, PEEK.v);
    const book = index.abbr[PEEK.abbr];
    if (!hit || !book) {
      page.innerHTML = `<p style="text-align:center;color:var(--ink-soft)">找不到這處經文。</p>`;
      return;
    }
    state.currentDay = hit.day;
    state.currentTrack = hit.track;
    if (PEEK.note) openNotes.add(vkey(book, PEEK.ch, PEEK.v));   // 自動展開該註
    pendingFlash = { book, ch: PEEK.ch, v: PEEK.v, note: PEEK.note };
    document.body.classList.add('peek');
    await render();
    return;
  }

  // resume: restore day/track/scroll and announce
  const resumed = state.currentDay !== defaults.currentDay ||
                  state.currentTrack !== defaults.currentTrack ||
                  state.startDay !== defaults.startDay ||
                  (state.scroll && state.scroll.top);
  if (state.scroll && state.scroll.day === state.currentDay &&
      state.scroll.track === state.currentTrack) {
    restoreScrollTo = state.scroll.top || 0;
  }

  await render();

  // 登入過的裝置才在開機時載 Firebase；沒用同步的人不必多下載 SDK
  try { expectUser = !!FB_CFG && !!localStorage.getItem(LS_SYNC); } catch {}
  renderSync();
  if (expectUser) loadFirebase().catch(() => {});
  else offerOneTap();

  if (resumed) {
    const label = state.currentTrack === 'nt' ? '新約' : '舊約';
    toast(`已恢復上次閱讀：第 ${userDayOf(state.currentDay)} 天 · ${label}`);
  }
})();
