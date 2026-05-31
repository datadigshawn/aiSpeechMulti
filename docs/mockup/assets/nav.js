// aiSpeechMulti UI Mockup · 共用導航與 mock action · 2026-05-18

// 1) 三主題循環：dark → light → dark-warm → dark
//    底層由 kit 的 aism-theme.js 處理 init + localStorage（key='aism-theme'）。
//    本檔負責「循環順序」與「按鈕 icon 同步」。
const THEME_ORDER = ['dark', 'light', 'dark-warm'];
const THEME_LABEL = {
  'dark':      '🌙 深色（cool · 日班）',
  'light':     '☀️ 淺色（white · 白班）',
  'dark-warm': '🔥 暖色（warm · 夜班低藍光）',
};

function toggleTheme() {
  const cur = document.documentElement.getAttribute('data-theme') || 'dark';
  const idx = THEME_ORDER.indexOf(cur);
  const next = THEME_ORDER[(idx + 1) % THEME_ORDER.length];

  if (window.Theme && typeof window.Theme.set === 'function') {
    window.Theme.set(next);              // 走 kit API（同步 colorScheme + 觸發 theme-change）
  } else {
    document.documentElement.setAttribute('data-theme', next);
    localStorage.setItem('aism-theme', next);
  }
  syncThemeBtnIcon();
  showToast(`已切換：${THEME_LABEL[next]}`);
}

function syncThemeBtnIcon() {
  const btn = document.getElementById('themeToggleBtn');
  if (!btn) return;
  const cur = document.documentElement.getAttribute('data-theme') || 'dark';
  btn.textContent = cur === 'light' ? '☀️' : cur === 'dark-warm' ? '🔥' : '🌙';
  btn.title = `目前：${THEME_LABEL[cur]} · 點擊切換下一主題`;
}
document.addEventListener('DOMContentLoaded', syncThemeBtnIcon);
window.addEventListener('theme-change', syncThemeBtnIcon);

// 2) Mock toast — anything with class .mock-action triggers a toast
document.addEventListener('click', (e) => {
  const t = e.target.closest('.mock-action');
  if (!t) return;
  if (t.tagName === 'A' && t.getAttribute('href') && t.getAttribute('href').startsWith('#')) {
    // allow hash navigation
  } else {
    e.preventDefault();
  }
  const msg = t.dataset.toast || '🚧 這是 mock 介面，按鈕功能未啟用';
  showToast(msg);
});

function showToast(msg) {
  const old = document.querySelector('.toast');
  if (old) old.remove();
  const t = document.createElement('div');
  t.className = 'toast';
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 2600);
}

// 3) Lab sidebar hash routing
function routeLab() {
  if (!document.querySelector('.lab-layout')) return;
  const hash = location.hash.slice(1) || 'speech';
  document.querySelectorAll('.lab-page').forEach(p => {
    p.classList.toggle('active', p.id === 'lab-' + hash);
  });
  document.querySelectorAll('.lab-sidebar a').forEach(a => {
    a.classList.toggle('active', a.getAttribute('href') === '#' + hash);
  });
  // sync title
  const active = document.querySelector('.lab-sidebar a.active');
  if (active) document.title = `Lab · ${active.textContent.trim()} · aiSpeechMulti Mock`;
}
window.addEventListener('hashchange', routeLab);
document.addEventListener('DOMContentLoaded', routeLab);

// 4) Radio pill toggling (no submit, pure visual)
document.addEventListener('click', (e) => {
  const pill = e.target.closest('.radio-pill');
  if (!pill) return;
  const group = pill.closest('.radio-group');
  if (!group) return;
  group.querySelectorAll('.radio-pill').forEach(p => p.classList.remove('active'));
  pill.classList.add('active');
});

// 5) Capture page: 開始監聽 button toggles state
function toggleCapture(btn) {
  const on = btn.dataset.state === 'on';
  btn.dataset.state = on ? 'off' : 'on';
  btn.textContent = on ? '🎤 開始監聽' : '⏹ 停止監聽';
  btn.classList.toggle('btn--danger', !on);
  showToast(on ? '已停止（mock）' : '已開始監聽（mock）— 此版本不會真的錄音');
}

// 6) Lane feed auto-scroll for mockup demo
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('.lane__feed').forEach(f => f.scrollTop = f.scrollHeight);
});

// 7) Cost bar expand toggle
function toggleCostExpand(btn) {
  const panel = document.getElementById('cost-detail');
  if (!panel) return;
  const open = panel.style.display === 'block';
  panel.style.display = open ? 'none' : 'block';
  btn.textContent = open ? '▼ 展開' : '▲ 收合';
}
