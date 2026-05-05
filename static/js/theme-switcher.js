/* ============================================================
   aiSpeechMulti — Theme Switcher (Phase 1)
   ─────────────────────────────────────────────
   兩套主題：dark-cool (預設) / dark-warm (夜班暖色)
   - localStorage 持久化（key: aispeech-theme）
   - URL ?theme=X 鎖定（給大螢幕投放避免誤觸）
   - 跨頁同步（同 origin 之 storage event）
   ============================================================ */

(function () {
  "use strict";

  const STORAGE_KEY = "aispeech-theme";
  const THEMES      = ["dark-cool", "dark-warm"];
  const META = {
    "dark-cool": { icon: "🌙", label: "深冷" },
    "dark-warm": { icon: "🔥", label: "暖琥珀" },
  };

  function isLocked() {
    return new URLSearchParams(location.search).has("theme");
  }

  function getInitialTheme() {
    // 1) URL ?theme= 最優先（給大螢幕鎖定用）
    const url = new URLSearchParams(location.search).get("theme");
    if (url && THEMES.includes(url)) return url;

    // 2) localStorage
    try {
      const ls = localStorage.getItem(STORAGE_KEY);
      if (ls && THEMES.includes(ls)) return ls;
    } catch (_) {}

    // 3) 預設
    return "dark-cool";
  }

  function applyTheme(theme, opts = {}) {
    if (!THEMES.includes(theme)) theme = "dark-cool";
    document.documentElement.setAttribute("data-theme", theme);

    if (!opts.skipPersist && !isLocked()) {
      try { localStorage.setItem(STORAGE_KEY, theme); } catch (_) {}
    }

    // 更新所有 toggle 按鈕的視覺
    document.querySelectorAll("[data-theme-toggle]").forEach((btn) => {
      const meta = META[theme] || META["dark-cool"];
      const iconEl  = btn.querySelector("[data-theme-icon]");
      const labelEl = btn.querySelector("[data-theme-label]");
      if (iconEl)  iconEl.textContent  = meta.icon;
      if (labelEl) labelEl.textContent = meta.label;

      if (isLocked()) {
        btn.setAttribute("disabled", "true");
        btn.setAttribute("aria-disabled", "true");
        btn.title = "URL 已用 ?theme= 鎖定，無法切換";
      }
    });

    // 廣播 event 讓頁面內其他模組（plotly chart 等）有機會跟著更新
    document.dispatchEvent(new CustomEvent("aispeech:theme-change", { detail: { theme } }));
  }

  function toggleTheme() {
    if (isLocked()) return;
    const cur  = document.documentElement.getAttribute("data-theme") || "dark-cool";
    const next = THEMES[(THEMES.indexOf(cur) + 1) % THEMES.length];
    applyTheme(next);
  }

  function setTheme(theme) {
    applyTheme(theme);
  }

  // 跨頁同步：當另一個分頁切換主題時，同步本頁
  window.addEventListener("storage", (e) => {
    if (e.key === STORAGE_KEY && e.newValue && THEMES.includes(e.newValue)) {
      applyTheme(e.newValue, { skipPersist: true });
    }
  });

  // 初始套用（DOMContentLoaded 前就跑，避免 FOUC）
  applyTheme(getInitialTheme(), { skipPersist: true });

  // 綁定 toggle 按鈕（DOM ready 後）
  function bind() {
    document.querySelectorAll("[data-theme-toggle]").forEach((btn) => {
      btn.addEventListener("click", toggleTheme);
    });
  }
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }

  // 對外 API
  window.AispeechTheme = {
    apply: setTheme,
    toggle: toggleTheme,
    current: () => document.documentElement.getAttribute("data-theme") || "dark-cool",
    isLocked,
    THEMES,
  };
})();
