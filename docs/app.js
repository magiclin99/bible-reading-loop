// ── 一年讀經一遍 · 靜態閱讀器 ────────────────────────────────
'use strict';

const TOTAL = 364;                 // day 365 source is a 404; plan is 364 days
const LS_STATE = 'blr:state';
const LS_READ  = 'blr:read';

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
const defaults = { startDay: 1, currentDay: 1, currentTrack: 'nt', scroll: {} };
let state = loadState();
let read  = loadRead();
let index = null;                  // data/index.json
const cache = new Map();           // origDay -> day bundle
let restoreScrollTo = null;        // px to restore after first render
let pendingFlash = null;           // {book,ch,v} 待定位高亮的經節
const openNotes = new Set();       // 展開中的註解，key = vkey()
const vkey = (bk, ch, v) => `${bk}-${ch}-${v}`;

function loadState() {
  try { return Object.assign({}, defaults, JSON.parse(localStorage.getItem(LS_STATE) || '{}')); }
  catch { return Object.assign({}, defaults); }
}
function saveState() {
  if (PEEK) return;                // 見上：查考分頁不可覆蓋閱讀位置
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
function saveRead() { try { localStorage.setItem(LS_READ, JSON.stringify([...read])); } catch {} }

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
  let curCh = null, curBook = null;
  for (const vs of t.verses) {
    if (vs.book !== curBook) {           // book change within a day (cross-book)
      curBook = vs.book; curCh = null;
      if (multiBook) {
        h += `<div class="book-mark" style="text-align:center;font-weight:800;font-size:18px;margin:22px 0 4px">${vs.book}</div>`;
      }
    }
    if (vs.ch !== curCh) {
      curCh = vs.ch;
      const unit = vs.abbr === '詩' ? '篇' : '章';
      h += `<div class="ch-mark" style="font-weight:700;color:var(--ink-soft);margin:16px 0 4px;font-size:14px">第 ${curCh} ${unit}</div>`;
    }
    const hasNote = vs.notes && vs.notes.length;
    const k = vkey(vs.book, vs.ch, vs.v);
    const open = openNotes.has(k);
    h += `<p class="verse${hasNote ? ' has-note' : ''}${open ? ' open' : ''}" data-bk="${escapeHTML(vs.book)}" data-ch="${vs.ch}" data-v="${vs.v}">`
       + `<span class="vn">${vs.v}</span><span class="vtext">${escapeHTML(vs.text)}</span></p>`;
    // 展開狀態存在 openNotes 而非只在 DOM，否則任何一次 render（例如按
    // 「標記讀完」）都會把使用者展開的註解全部清空。
    if (open) h += notesHTML(vs);
  }
  return h;
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
function flashTo(book, ch, v, label) {
  const sel = `.verse[data-bk="${CSS.escape(book)}"][data-ch="${ch}"][data-v="${v}"]`;
  const t = page.querySelector(sel);
  if (!t) return;
  t.scrollIntoView({ block: 'center' });
  if (label) {
    const box = t.nextElementSibling;
    const nt = box && box.classList.contains('notes')
      && box.querySelector(`.note[data-label="${CSS.escape(label)}"]`);
    if (nt) nt.classList.add('flash');
  }
  t.classList.add('flash');
  setTimeout(() => {
    t.classList.remove('flash');
    page.querySelectorAll('.note.flash').forEach(x => x.classList.remove('flash'));
  }, 1800);
}

// ── Verse note expand (event delegation) ─────────────────────
page.addEventListener('click', (e) => {
  if (e.target.closest('a.ref')) return;      // 引用連結自己開新分頁
  const v = e.target.closest('.verse');
  if (!v) return;
  const k = vkey(v.dataset.bk, +v.dataset.ch, +v.dataset.v);
  const existing = v.nextElementSibling;
  if (existing && existing.classList.contains('notes')) {
    existing.remove(); v.classList.remove('open'); openNotes.delete(k); return;
  }
  const day = cache.get(state.currentDay);
  const vs = day[state.currentTrack].verses.find(
    x => x.book === v.dataset.bk && x.ch == v.dataset.ch && x.v == v.dataset.v);
  const html = vs && notesHTML(vs);
  if (!html) return;
  v.classList.add('open');
  v.insertAdjacentHTML('afterend', html);
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
  if (read.has(k)) { read.delete(k); toast(`已取消：${label}`); }
  else {
    read.add(k);
    const bp = bookProgress(orig, track);            // readN now includes this day
    if (bp.readN === bp.total) toast(`🎉 ${bp.book} 讀完了！`);
    else toast(`✓ 標記${label}讀完`);
  }
  saveRead();
  render();
}

el('btn-next').onclick = next;
el('btn-prev').onclick = prev;
el('btn-track').onclick = toggleTrack;
el('btn-read').onclick = toggleRead;

// keyboard
window.addEventListener('keydown', (e) => {
  if (!el('browse').hidden) return;
  if (e.key === 'ArrowRight') next();
  else if (e.key === 'ArrowLeft') prev();
  else if (e.key === 't' || e.key === 'T') toggleTrack();
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
window.addEventListener('storage', (e) => {
  if (e.key !== LS_READ) return;
  read = loadRead();
  updateProgress(state.currentTrack);
  const done = isRead(state.currentDay, state.currentTrack);
  const label = state.currentTrack === 'nt' ? '新約' : '舊約';
  const rb = el('btn-read');
  rb.className = `read-btn${done ? ' done' : ''}`;
  rb.textContent = done ? `✓ ${label}已讀完` : `標記${label}讀完`;
});

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

  if (resumed) {
    const label = state.currentTrack === 'nt' ? '新約' : '舊約';
    toast(`已恢復上次閱讀：第 ${userDayOf(state.currentDay)} 天 · ${label}`);
  }
})();
