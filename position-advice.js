(function () {
  'use strict';
  const el = id => document.getElementById(id);
  const state = { data: null, styleId: null, request: 0 };
  const percent = value => `${(Number(value) * 100).toFixed(2).replace(/\.00$/, '')}%`;
  const number = value => Number(value).toFixed(1);
  const labels = value => value > 0 ? '偏多' : value < 0 ? '偏空' : '中性';
  const tone = value => value > 0 ? 'positive' : value < 0 ? 'negative' : 'neutral';

  function validate(data) {
    if (!data || data.available !== true || !/^\d{4}-\d{2}-\d{2}$/.test(data.asOf || '')) throw new Error('暂未提供已核验的仓位快照。');
    if (!Array.isArray(data.styles) || data.styles.length !== 4 || new Set(data.styles.map(s => s.id)).size !== 4 || data.styles.some(s => ['score', 'momentum', 'valuation', 'flow'].some(k => !Number.isFinite(s[k]) || s[k] < 0 || s[k] > 100))) throw new Error('风格评分不完整，暂不显示仓位。');
    if (!Array.isArray(data.models) || !data.models.some(m => m.id === 'multidimensional')) throw new Error('缺少多维度定仓结果。');
    for (const m of data.models) {
      if (![m.equity, m.credit, m.cash].every(v => Number.isFinite(v) && v >= 0) || Math.abs(m.equity + m.credit + m.cash - 1) > 1e-7 || m.equity > .20000001 || m.credit > .80000001) throw new Error('仓位未通过上限与合计校验，暂不显示。');
      if (![-1, 0, 1].includes(m.signal) || (m.signal <= 0 && m.equity > 1e-7)) throw new Error('仓位与择时信号不一致。');
      if (!Array.isArray(m.assets) || m.assets.length !== 7 || m.assets.some(a => !Number.isFinite(a.weight) || a.weight < 0) || Math.abs(m.assets.reduce((sum, a) => sum + a.weight, 0) - 1) > 1e-7) throw new Error('配置标的数据不完整。');
      if (new Set(m.assets.map(a => a.name)).size !== 7 || m.assets.some(a => !['equity', 'credit', 'cash'].includes(a.kind))) throw new Error('配置标的分类不完整。');
      for (const kind of ['equity', 'credit', 'cash']) if (Math.abs(m.assets.filter(a => a.kind === kind).reduce((sum, a) => sum + a.weight, 0) - m[kind]) > 1e-7) throw new Error('汇总仓位与标的明细不一致。');
      const risks = m.assets.filter(a => a.kind !== 'cash');
      if (risks.some(a => !Number.isFinite(a.riskShare) || a.riskShare < 0) || Math.abs(risks.reduce((sum, a) => sum + a.riskShare, 0) - 1) > 1e-7) throw new Error('风险贡献数据不完整。');
    }
    if (data.mode !== 'five-dimensions-v4' || !Array.isArray(data.moduleVotes) || data.moduleVotes.length !== 5 || data.moduleVotes.some((v, i) => v.name !== ['宏观', '估值', '资金', '价量', '情绪'][i] || !Number.isFinite(v.vote) || Math.abs(v.vote) > 1)) throw new Error('等待统一五维仓位快照。');
    const mean = data.moduleVotes.reduce((sum, row) => sum + row.vote, 0) / 5;
    if (!Number.isFinite(data.compositeMean) || Math.abs(mean - data.compositeMean) > 1e-8 || data.models.some(m => Math.sign(mean) !== m.signal)) throw new Error('多维度总信号未通过复核。');
    return data;
  }

  function renderVotes() {
    const data = state.data;
    const rows = data.moduleVotes.map(({name, vote}) => [name, vote]);
    const format = value => Number.isFinite(value)
      ? `${value > 0 ? '+' : ''}${value.toFixed(2)} · ${labels(value)}` : '待补数据';
    const container = el('moduleVotes');
    container.replaceChildren();
    for (const [label, value] of rows) {
      const item = document.createElement('div'); item.className = 'module-row';
      const name = document.createElement('span'); name.textContent = label;
      const scale = document.createElement('div'); scale.className = 'module-scale'; scale.setAttribute('aria-hidden', 'true');
      for (const direction of [-1, 0, 1]) {
        const mark = document.createElement('span');
        const active = Number.isFinite(value) && Math.sign(value) === direction;
        mark.className = `${active ? 'active ' : ''}${tone(direction)}`;
        scale.append(mark);
      }
      const score = document.createElement('span');
      score.className = `module-value ${tone(value)}`;
      score.textContent = format(value);
      item.append(name, scale, score); container.append(item);
    }
    const notes = el('methodNotes');
    notes.replaceChildren();
    const rules = data.notes;
    for (const rule of rules) {
      const note = document.createElement('li'); note.textContent = rule; notes.append(note);
    }
    const mean = data.compositeMean;
    el('compositeMean').textContent = Number.isFinite(mean) ? mean.toFixed(2) : '—';
    el('compositeLabel').textContent = Number.isFinite(mean) ? labels(mean) : '等待五维数据齐备';
    el('signalScope').textContent = `市场快照 ${data.asOf} · 五维与仓位决策日 ${data.lastDecisionDate}`;
  }

  function renderStyleDetail() {
    const style = state.data.styles.find(s => s.id === state.styleId) || state.data.styles[0]; state.styleId = style.id;
    el('styleButtons').querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.style === style.id)));
    el('styleDetail').replaceChildren(); const heading = document.createElement('div'); heading.className = 'style-detail-heading';
    const title = document.createElement('strong'); title.textContent = `${style.name} · 第${style.rank}位`; const proxy = document.createElement('span'); proxy.textContent = style.proxy; heading.append(title, proxy); el('styleDetail').append(heading);
    const components = document.createElement('div'); components.className = 'score-components';
    for (const [key, text] of [['momentum', '相对动量 · 50%'], ['valuation', '估值吸引力 · 30%'], ['flow', '资金支持 · 20%']]) {
      const row = document.createElement('div'); row.className = 'score-component'; const label = document.createElement('span'); label.textContent = text; const track = document.createElement('div'); track.className = 'score-track'; const fill = document.createElement('div'); fill.className = 'score-fill'; fill.style.width = `${style[key]}%`; track.append(fill); const value = document.createElement('strong'); value.textContent = number(style[key]); row.append(label, track, value); components.append(row);
    }
    const caption = document.createElement('p'); caption.textContent = `近120日涨跌 ${percent(style.momentum120)} · 近60日年化波动 ${percent(style.vol60)}。${style.id === 'value' ? '红利代理不等于纯价值；估值吸引力越高，表示相对自身历史越便宜。' : '相对领先并不代表绝对上涨，仍需通过总择时与风险预算。'}`;
    el('styleDetail').append(components, caption); renderWheel();
  }

  function renderWheel() {
    if (!state.data || el('positionContent').hidden) return;
    const svg = el('styleWheel'), width = svg.getBoundingClientRect().width;
    if (!width) return;
    const height = width < 400 ? 310 : 350, cx = width / 2, cy = height / 2, radius = Math.min(115, (width - 142) / 2, (height - 90) / 2), ns = 'http://www.w3.org/2000/svg';
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`); svg.setAttribute('height', height); svg.replaceChildren();
    function add(tag, attributes, text) { const node = document.createElementNS(ns, tag); Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value)); if (text !== undefined) node.textContent = text; svg.append(node); return node; }
    add('title', {}, `风格轮盘，${state.data.asOf}，分数不是上涨概率`);
    add('desc', {}, state.data.styles.map(s => `${s.name}${number(s.score)}分`).join('；'));
    for (const level of [.25, .5, .75, 1]) add('circle', { cx, cy, r: radius * level, fill: 'none', stroke: 'var(--line)', 'stroke-width': 1 });
    const order = [['large', -90], ['small', 0], ['growth', 90], ['value', 180]];
    for (const [id, angle] of order) {
      const style = state.data.styles.find(s => s.id === id); if (!style) continue;
      const a = angle * Math.PI / 180, r = radius * style.score / 100;
      add('line', { x1: cx, y1: cy, x2: cx + radius * Math.cos(a), y2: cy + radius * Math.sin(a), stroke: 'var(--line)', 'stroke-width': 1 });
      const p1 = [cx + r * Math.cos(a - .55), cy + r * Math.sin(a - .55)], p2 = [cx + r * Math.cos(a + .55), cy + r * Math.sin(a + .55)];
      const path = add('path', { d: `M${cx},${cy} L${p1} A${r},${r} 0 0 1 ${p2} Z`, fill: style.rank <= 2 ? 'var(--accent)' : 'var(--blue)', opacity: state.styleId === id ? .95 : style.rank <= 2 ? .6 : .28, 'data-style': id });
      path.style.cursor = 'pointer'; path.addEventListener('click', () => { state.styleId = id; renderStyleDetail(); });
      if (angle === -90 || angle === 90) {
        const y = angle === -90 ? cy - radius - 28 : cy + radius + 23;
        add('text', { x: cx, y, 'text-anchor': 'middle' }, `${style.name} ${number(style.score)}`); add('text', { x: cx, y: y + 18, 'text-anchor': 'middle', class: 'proxy' }, style.proxy);
      } else {
        const x = angle === 180 ? Math.max(35, cx - radius - 34) : Math.min(width - 35, cx + radius + 34);
        add('text', { x, y: cy - 18, 'text-anchor': 'middle' }, style.name); add('text', { x, y: cy, 'text-anchor': 'middle' }, number(style.score)); add('text', { x, y: cy + 18, 'text-anchor': 'middle', class: 'proxy' }, style.proxy);
      }
    }
  }

  function render(data) {
    state.data = data; el('positionContent').hidden = false; el('loadError').hidden = true;
    el('asOf').textContent = data.asOf; el('decisionDate').textContent = data.lastDecisionDate;
    el('styleButtons').replaceChildren();
    for (const style of data.styles) {
      const button = document.createElement('button'); button.type = 'button'; button.dataset.style = style.id; button.setAttribute('aria-label', `查看${style.name}评分构成`); const label = document.createElement('span'); label.textContent = style.name; const value = document.createElement('strong'); value.textContent = number(style.score); button.append(label, value); button.addEventListener('click', () => { state.styleId = style.id; renderStyleDetail(); }); el('styleButtons').append(button);
    }
    el('sourceNote').textContent = data.source;
    const generated = new Date(data.generatedAt); el('generatedAt').textContent = Number.isNaN(generated.valueOf()) ? '' : `快照导出 ${generated.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })}`;
    const cards = el('allocationModels');
    cards.replaceChildren();
    for (const model of data.models) {
      const title = document.createElement('h3');
      title.textContent = `${model.name} · ${labels(model.signal)}`;
      const metrics = document.createElement('div');
      metrics.className = 'position-metrics';
      for (const [key, label] of [['equity', '权益'], ['credit', '信用债'], ['cash', '现金']]) {
        const card = document.createElement('div');
        card.className = 'position-metric';
        const caption = document.createElement('span');
        caption.textContent = label;
        const weight = document.createElement('strong');
        weight.textContent = percent(model[key]);
        card.append(caption, weight);
        metrics.append(card);
      }
      cards.append(title, metrics);
    }
    renderVotes(); renderStyleDetail(); el('statusDot').className = 'dot'; el('statusText').textContent = '已读取数据';
  }

  async function load() {
    const request = ++state.request; el('refreshButton').disabled = true; el('statusDot').className = 'dot loading'; el('statusText').textContent = '正在读取数据';
    try {
      const response = await fetch(`/position-advice.json?t=${Date.now()}`, { cache: 'no-store' });
      if (!response.ok) throw new Error('仓位快照暂时无法读取，请稍后重试。');
      const data = validate(await response.json()); if (request !== state.request) return; render(data);
      try {
        const statusResponse = await fetch(`/position-update-status.json?t=${Date.now()}`, { cache: 'no-store' });
        if (statusResponse.ok) {
          const status = await statusResponse.json();
          if (request !== state.request) return;
          if (status.ok === false) {
            el('statusText').textContent = `更新失败 · 保留 ${data.asOf} 数据`;
            el('statusDot').className = 'dot error';
            el('statusText').title = `${status.message || '数据获取或校验未通过'} 检查时间：${status.checkedAt || '未知'}`;
          } else if (status.ok === true && status.asOf === data.asOf) {
            el('statusText').textContent = `自动更新 · ${data.asOf}`;
          }
        }
      } catch (_) { /* Main snapshot remains usable if the status request fails. */ }
    } catch (error) {
      if (request !== state.request) return;
      state.data = null; el('positionContent').hidden = true; el('loadError').hidden = false; el('loadError').textContent = error.message || '研究数据读取失败。'; el('asOf').textContent = '—'; el('decisionDate').textContent = '—'; el('generatedAt').textContent = ''; el('statusDot').className = 'dot error'; el('statusText').textContent = '读取失败';
    } finally { if (request === state.request) el('refreshButton').disabled = false; }
  }
  el('refreshButton').addEventListener('click', load);
  new ResizeObserver(renderWheel).observe(el('styleWheel'));
  document.addEventListener('themechange', renderWheel);
  load();
})();
