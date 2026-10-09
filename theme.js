/* ============================================================
   theme.js — 全站深色 / 浅色主题系统
   用法：<script src="/theme.js?v=1"></script> 置于 <head>（同步加载，
   保证首帧前 data-theme 已就位，避免闪屏）。
   提供：
   - window.MS_PALETTE()  画布调色板（每次调用读取 CSS 变量，随主题变化）
   - window.msColor(hex)  已知序列色 → 主题化颜色
   - window.msAlpha(color, a) 颜色 + 透明度 → rgba 字符串
   - document 'themechange' 事件（画布重绘监听它）
   ============================================================ */
(function () {
  const KEY = 'ms-theme';
  const root = document.documentElement;

  /* ---- 首帧前恢复用户偏好（默认深色） ---- */
  let saved = null;
  try { saved = localStorage.getItem(KEY); } catch (e) { /* 隐私模式等 */ }
  const initial = saved === 'light' ? 'light' : 'dark';
  root.dataset.theme = initial;

  /* ---- 画布调色板：从 CSS 变量读取，主题切换后值自动更新 ---- */
  window.MS_PALETTE = function () {
    const cs = getComputedStyle(root);
    const v = (name, fallback) => {
      const value = cs.getPropertyValue(name).trim();
      return value || fallback;
    };
    return {
      text: v('--chart-text', '#e9f0f7'),
      axis: v('--chart-axis', '#8ea3b7'),
      axisDim: v('--chart-axis-dim', '#71849a'),
      grid: v('--chart-grid', '#20354e'),
      gridStrong: v('--chart-grid-strong', 'rgba(42,65,91,.62)'),
      zero: v('--chart-zero', 'rgba(233,240,247,.38)'),
      point: v('--chart-point', '#253fd4'),
      red: v('--red', '#ff6b78'),
      green: v('--accent', '#46d6b2'),
      blue: v('--blue', '#5aa7ff'),
      amber: v('--amber', '#f5bd5c'),
      purple: v('--chart-purple', '#9d8cff'),
      cyan: v('--chart-cyan', '#6fd3ff')
    };
  };

  /* ---- 已知序列色 → 主题色（各页数据结构里存的是深色主题 hex） ---- */
  window.msColor = function (color) {
    if (!color) return color;
    const p = window.MS_PALETTE();
    const map = {
      '#46d6b2': p.green, '#ff6b78': p.red, '#ff7182': p.red, '#ff8a72': p.red,
      '#5aa7ff': p.blue, '#f5bd5c': p.amber, '#9d8cff': p.purple, '#6fd3ff': p.cyan
    };
    return map[String(color).toLowerCase()] || color;
  };

  /* ---- 颜色 + 透明度 → rgba() ---- */
  window.msAlpha = function (color, alpha) {
    const m = /^#([0-9a-f]{6})$/i.exec(String(color).trim());
    if (!m) return String(color);
    const n = parseInt(m[1], 16);
    return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${alpha})`;
  };

  /* ---- 切换 ---- */
  let animTimer = null;
  let toggleButton = null;

  function apply(theme, animate) {
    if (animate) {
      root.classList.add('theme-anim');
      clearTimeout(animTimer);
      animTimer = setTimeout(() => root.classList.remove('theme-anim'), 480);
    }
    root.dataset.theme = theme;
    try { localStorage.setItem(KEY, theme); } catch (e) { /* 忽略 */ }
    document.dispatchEvent(new CustomEvent('themechange', { detail: { theme } }));
    updateButton();
  }

  function updateButton() {
    if (!toggleButton) return;
    const light = root.dataset.theme === 'light';
    toggleButton.setAttribute('aria-pressed', String(light));
    toggleButton.title = light ? '切换到深色模式' : '切换到浅色模式';
  }

  function initButton() {
    const host = document.querySelector('.topbar, .detail-topbar');
    if (!host || host.querySelector('.theme-toggle')) return;
    toggleButton = document.createElement('button');
    toggleButton.className = 'theme-toggle';
    toggleButton.type = 'button';
    toggleButton.setAttribute('aria-label', '切换深色 / 浅色模式');
    toggleButton.innerHTML =
      '<svg class="icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">' +
      '<circle cx="12" cy="12" r="4.4"></circle>' +
      '<path d="M12 2.5v2.2M12 19.3v2.2M2.5 12h2.2M19.3 12h2.2M5.2 5.2l1.6 1.6M17.2 17.2l1.6 1.6M18.8 5.2l-1.6 1.6M6.8 17.2l-1.6 1.6"></path></svg>' +
      '<svg class="icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
      '<path d="M20.6 14.2A8.8 8.8 0 0 1 9.8 3.4a8.8 8.8 0 1 0 10.8 10.8z"></path></svg>';
    toggleButton.addEventListener('click', () => {
      apply(root.dataset.theme === 'light' ? 'dark' : 'light', true);
    });
    host.appendChild(toggleButton);
    updateButton();
  }

  /* ---- 跨标签页同步 ---- */
  window.addEventListener('storage', event => {
    if (event.key === KEY && (event.newValue === 'light' || event.newValue === 'dark')) {
      root.dataset.theme = event.newValue;
      document.dispatchEvent(new CustomEvent('themechange', { detail: { theme: event.newValue } }));
      updateButton();
    }
  });

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initButton);
  } else {
    initButton();
  }
})();
