// ── 一年讀經一遍 · 靜態閱讀器 ────────────────────────────────
'use strict';

const TOTAL = 364;                 // day 365 source is a 404; plan is 364 days
const LS_STATE = 'blr:state';
const LS_READ  = 'blr:read';

// ── State ────────────────────────────────────────────────────
const defaults = { startDay: 1, currentDay: 1, currentTrack: 'nt', scroll: {} };
let state = loadState();
let read  = loadRead();
let index = null;                  // data/index.json
const cache = new Map();           // origDay -> day bundle
let restoreScrollTo = null;        // px to restore after first render

function loadState() {
  try { return Object.assign({}, defaults, JSON.parse(localStorage.getItem(LS_STATE) || '{}')); }
  catch { return Object.assign({}, defaults); }
}
function saveState() { try { localStorage.setItem(LS_STATE, JSON.stringify(state)); } catch {} }
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

  // top bar
  el('bar-day').textContent = `第 ${userDayOf(orig)} 天 · ${day.date}`;
  el('bar-ref').textContent = t ? t.ref : '（無內容）';
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

  // scroll: restore on resume, else top
  if (restoreScrollTo != null) { pager.scrollTop = restoreScrollTo; restoreScrollTo = null; }
  else { pager.scrollTop = 0; }

  saveState();
  prefetch(orig);
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

  let h = '';
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
    h += `<p class="verse${hasNote ? ' has-note' : ''}" data-bk="${escapeHTML(vs.book)}" data-ch="${vs.ch}" data-v="${vs.v}">`
       + `<span class="vn">${vs.v}</span><span class="vtext">${escapeHTML(vs.text)}</span></p>`;
    // notes container (rendered lazily on open, but embed data)
  }
  return h;
}

function escapeHTML(s) {
  return s.replace(/[&<>]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]));
}

// ── Verse note expand (event delegation) ─────────────────────
page.addEventListener('click', (e) => {
  const v = e.target.closest('.verse');
  if (!v) return;
  const existing = v.nextElementSibling;
  if (existing && existing.classList.contains('notes')) {
    existing.remove(); v.classList.remove('open'); return;
  }
  const day = cache.get(state.currentDay);
  const t = day[state.currentTrack];
  const vs = t.verses.find(x => x.book === v.dataset.bk && x.ch == v.dataset.ch && x.v == v.dataset.v);
  if (!vs || !vs.notes || !vs.notes.length) return;
  const box = document.createElement('div');
  box.className = 'notes';
  box.innerHTML = vs.notes.map(n =>
    `<div class="note"><span class="note-label">註${n.label}</span>` +
    n.body.split('\n\n').map(p => `<p>${escapeHTML(p)}</p>`).join('') + `</div>`
  ).join('');
  v.classList.add('open');
  v.after(box);
});

// ── Navigation ───────────────────────────────────────────────
function go(orig, dir) { state.currentDay = orig; render(dir); }
function next() { go(nextOrig(state.currentDay), 'next'); }
function prev() { go(prevOrig(state.currentDay), 'prev'); }

function toggleTrack() {
  const day = cache.get(state.currentDay);
  const other = state.currentTrack === 'nt' ? 'ot' : 'nt';
  if (!day[other]) { toast(`這一天沒有${other === 'nt' ? '新約' : '舊約'}`); return; }
  state.currentTrack = other;
  render();
}

function toggleRead() {
  const k = readKey(state.currentDay, state.currentTrack);
  const label = state.currentTrack === 'nt' ? '新約' : '舊約';
  if (read.has(k)) { read.delete(k); toast(`已取消：${label}`); }
  else { read.add(k); toast(`✓ 標記${label}讀完`); }
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

// ── Horizontal swipe (left/right = day) vs vertical scroll ───
let sx = 0, sy = 0, swiping = false, decided = false, horiz = false;
pager.addEventListener('touchstart', (e) => {
  if (e.touches.length !== 1) return;
  sx = e.touches[0].clientX; sy = e.touches[0].clientY;
  swiping = true; decided = false; horiz = false;
}, { passive: true });
pager.addEventListener('touchmove', (e) => {
  if (!swiping) return;
  const dx = e.touches[0].clientX - sx, dy = e.touches[0].clientY - sy;
  if (!decided && (Math.abs(dx) > 10 || Math.abs(dy) > 10)) {
    decided = true; horiz = Math.abs(dx) > Math.abs(dy) * 1.3;
  }
}, { passive: true });
pager.addEventListener('touchend', (e) => {
  if (!swiping) return; swiping = false;
  if (!horiz) return;
  const dx = e.changedTouches[0].clientX - sx;
  if (Math.abs(dx) < 55) return;
  if (dx < 0) next(); else prev();
}, { passive: true });

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
        <div class="card-day">第 ${u} 天 · ${info.date}${isCur ? ' · <span class="cur-tag">閱讀中</span>' : ''}${isStart ? ' · <span class="cur-tag">你的第1天</span>' : ''}</div>
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
    state.currentDay = +main.dataset.orig;
    state.currentTrack = browseTrack;
    closeBrowse(); render();
    return;
  }
  const set = e.target.closest('.card-set');
  if (set) {
    const orig = +set.dataset.set;
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

// ── Boot ─────────────────────────────────────────────────────
(async function boot() {
  await loadIndex();

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
