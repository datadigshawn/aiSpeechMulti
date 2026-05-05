// Lab shell — injects sidenav, sets active item, fills icons
window.LabShell = {
  mount: async function(activeKey) {
    const host = document.getElementById('lab-sidenav');
    const html = await fetch('partials/sidenav.html').then(r => r.text());
    host.outerHTML = html;
    document.getElementById('brand-mark').innerHTML = Icon.logo;
    document.querySelectorAll('[data-i]').forEach(el => {
      const k = el.getAttribute('data-i');
      if (Icon[k]) el.innerHTML = Icon[k];
    });
    const active = document.querySelector(`.sidenav__item[data-key="${activeKey}"]`);
    if (active) active.classList.add('sidenav__item--active');
  }
};
