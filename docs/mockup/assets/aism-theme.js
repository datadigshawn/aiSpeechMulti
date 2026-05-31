// Theme toggle — light / dark, persisted in localStorage.
// Defaults to OS prefers-color-scheme.
// Run AS EARLY AS POSSIBLE (before paint) to avoid flash of dark/light.
(function () {
  const KEY = 'aism-theme';
  function osPrefersLight() {
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: light)').matches;
  }
  function current() {
    return localStorage.getItem(KEY) || (osPrefersLight() ? 'light' : 'dark');
  }
  function apply(t) {
    document.documentElement.setAttribute('data-theme', t);
    document.documentElement.style.colorScheme = t;
  }
  apply(current());

  window.Theme = {
    get current() { return current(); },
    set(t) { localStorage.setItem(KEY, t); apply(t); window.dispatchEvent(new CustomEvent('theme-change', {detail: t})); },
    toggle() { this.set(current() === 'light' ? 'dark' : 'light'); },

    // Inject a toggle button into a container element.
    // Container can be a CSS selector or an element.
    mountToggle(container) {
      const host = typeof container === 'string' ? document.querySelector(container) : container;
      if (!host) return;
      const btn = document.createElement('button');
      btn.className = 'btn btn--ghost btn--sm theme-toggle';
      btn.setAttribute('aria-label', 'Toggle day/night theme');
      btn.title = 'Toggle day / night';
      btn.innerHTML = renderIcon(current());
      btn.addEventListener('click', () => { this.toggle(); });
      window.addEventListener('theme-change', e => { btn.innerHTML = renderIcon(e.detail); });
      host.appendChild(btn);
      return btn;
    }
  };

  function renderIcon(theme) {
    const moon = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>`;
    const sun  = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" style="width:14px;height:14px"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4 12H2M22 12h-2M5.6 5.6 4.2 4.2M19.8 19.8l-1.4-1.4M5.6 18.4l-1.4 1.4M19.8 4.2l-1.4 1.4"/></svg>`;
    return theme === 'light'
      ? sun  + '<span style="margin-left:6px">Day</span>'
      : moon + '<span style="margin-left:6px">Night</span>';
  }

  // Auto-mount a floating toggle on every page (unless the page opted out with
  // <html data-theme-toggle="off"> or <body class="no-theme-toggle">).
  function autoMount() {
    if (document.documentElement.getAttribute('data-theme-toggle') === 'off') return;
    if (document.body && document.body.classList.contains('no-theme-toggle')) return;

    // Inject minimal floating styles
    const css = `
      .theme-fab {
        position: fixed; top: 14px; right: 18px;
        z-index: 9999;
        display: inline-flex; align-items: center; gap: 6px;
        height: 30px; padding: 0 12px;
        background: var(--neutral-2);
        color: var(--neutral-11);
        border: 1px solid var(--neutral-6);
        border-radius: 999px;
        font-family: var(--font-sans);
        font-size: 12px; font-weight: 500;
        letter-spacing: 0.02em;
        cursor: pointer;
        backdrop-filter: blur(8px);
        transition: background 120ms, border-color 120ms, color 120ms;
        box-shadow: var(--shadow-1);
      }
      .theme-fab:hover { border-color: var(--neutral-7); color: var(--neutral-13); }
      .theme-fab svg  { display: block; }
    `;
    const style = document.createElement('style');
    style.textContent = css;
    document.head.appendChild(style);

    const fab = document.createElement('button');
    fab.className = 'theme-fab';
    fab.setAttribute('aria-label', 'Toggle day / night');
    fab.title = 'Toggle day / night theme';
    fab.innerHTML = renderIcon(current());
    fab.addEventListener('click', () => window.Theme.toggle());
    window.addEventListener('theme-change', e => { fab.innerHTML = renderIcon(e.detail); });
    document.body.appendChild(fab);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', autoMount);
  } else {
    autoMount();
  }
})();
