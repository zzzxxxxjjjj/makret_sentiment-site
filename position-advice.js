(function () {
  'use strict';
  const el = id => document.getElementById(id);
  const state = { data: null, styleId: null, request: 0 };
  const percent = value => `${(Number(value) * 100).toFixed(2).replace(/\.00$/, '')}%`;
  const number = value => Number(value).toFixed(1);
  const labels = value => value > 0 ? 'ƫ��' : value < 0 ? 'ƫ��' : '����';
  const tone = value => value > 0 ? 'positive' : value < 0 ? 'negative' : 'neutral';

  function validate(data) {
    if (!data || data.available !== true || !/^\d{4}-\d{2}-\d{2}$/.test(data.asOf || '')) throw new Error('��δ�ṩ�Ѻ���Ĳ�λ���ա�');
    if (!Array.isArray(data.styles) || data.styles.length !== 4 || new Set(data.styles.map(s => s.id)).size !== 4 || data.styles.some(s => ['score', 'momentum', 'valuation', 'flow'].some(k => !Number.isFinite(s[k]) || s[k] < 0 || s[k] > 100))) throw new Error('������ֲ��������ݲ���ʾ��λ��');
    if (!Array.isArray(data.models) || !data.models.some(m => m.id === 'multidimensional')) throw new Error('ȱ�ٶ�ά�ȶ��ֽ����');
    for (const m of data.models) {
      if (![m.equity, m.credit, m.cash].every(v => Number.isFinite(v) && v >= 0) || Math.abs(m.equity + m.credit + m.cash - 1) > 1e-7 || m.equity > .20000001 || m.credit > .80000001) throw new Error('��λδͨ��������ϼ�У�飬�ݲ���ʾ��');
      if (![-1, 0, 1].includes(m.signal) || (m.signal <= 0 && m.equity > 1e-7)) throw new Error('��λ����ʱ�źŲ�һ�¡�');
      if (!Array.isArray(m.assets) || m.assets.length !== 7 || m.assets.some(a => !Number.isFinite(a.weight) || a.weight < 0) || Math.abs(m.assets.reduce((sum, a) => sum + a.weight, 0) - 1) > 1e-7) throw new Error('���ñ�����ݲ�������');
      if (new Set(m.assets.map(a => a.name)).size !== 7 || m.assets.some(a => !['equity', 'credit', 'cash'].includes(a.kind))) throw new Error('���ñ�ķ��಻������');
      for (const kind of ['equity', 'credit', 'cash']) if (Math.abs(m.assets.filter(a => a.kind === kind).reduce((sum, a) => sum + a.weight, 0) - m[kind]) > 1e-7) throw new Error('���ܲ�λ������ϸ��һ�¡�');
      const risks = m.assets.filter(a => a.kind !== 'cash');
      if (risks.some(a => !Number.isFinite(a.riskShare) || a.riskShare < 0) || Math.abs(risks.reduce((sum, a) => sum + a.riskShare, 0) - 1) > 1e-7) throw new Error('���չ������ݲ�������');
    }
    if (!Array.isArray(data.moduleVotes) || data.moduleVotes.length !== 5 || data.moduleVotes.some(v => ![-1, 0, 1].includes(v.vote))) throw new Error('��ά��ͶƱ���ݲ�������');
    const mean = data.moduleVotes.reduce((sum, row) => sum + row.vote, 0) / 5;
    if (!Number.isFinite(data.compositeMean) || Math.abs(mean - data.compositeMean) > 1e-8 || Math.sign(mean) !== data.models.find(m => m.id === 'multidimensional').signal) throw new Error('��ά�����ź�δͨ�����ˡ�');
    return data;
  }

  function renderVotes() {
    el('moduleVotes').replaceChildren();
    for (const row of state.data.moduleVotes) {
      const item = document.createElement('div'); item.className = 'module-row';
      const name = document.createElement('span'); name.textContent = row.name;
      const scale = document.createElement('div'); scale.className = 'module-scale'; scale.setAttribute('aria-hidden', 'true');
      for (const value of [-1, 0, 1]) { const mark = document.createElement('span'); mark.className = `${value === row.vote ? 'active ' : ''}${tone(value)}`; scale.append(mark); }
      const vote = document.createElement('span'); vote.className = `module-value ${tone(row.vote)}`; vote.textContent = `${row.vote > 0 ? '+' : ''}${row.vote} �� ${labels(row.vote)}`; item.append(name, scale, vote); el('moduleVotes').append(item);
    }
    el('compositeMean').textContent = state.data.compositeMean.toFixed(2);
    el('compositeLabel').textContent = `���ά�ȵ�Ȩƽ�� �� ${labels(state.data.models[0].signal)}�ź�`;
    el('signalScope').textContent = state.data.signalScope + '����Ȩ��Ҫ�ο�50ETF���ڻ��ֲֲο�IF��';
  }

  function renderStyleDetail() {
    const style = state.data.styles.find(s => s.id === state.styleId) || state.data.styles[0]; state.styleId = style.id;
    el('styleButtons').querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.style === style.id)));
    el('styleDetail').replaceChildren(); const heading = document.createElement('div'); heading.className = 'style-detail-heading';
    const title = document.createElement('strong'); title.textContent = `${style.name} �� ��${style.rank}λ`; const proxy = document.createElement('span'); proxy.textContent = style.proxy; heading.append(title, proxy); el('styleDetail').append(heading);
    const components = document.createElement('div'); components.className = 'score-components';
    for (const [key, text] of [['momentum', '��Զ��� �� 50%'], ['valuation', '��ֵ������ �� 30%'], ['flow', '�ʽ�֧�� �� 20%']]) {
      const row = document.createElement('div'); row.className = 'score-component'; const label = document.createElement('span'); label.textContent = text; const track = document.createElement('div'); track.className = 'score-track'; const fill = document.createElement('div'); fill.className = 'score-fill'; fill.style.width = `${style[key]}%`; track.append(fill); const value = document.createElement('strong'); value.textContent = number(style[key]); row.append(label, track, value); components.append(row);
    }
    const caption = document.createElement('p'); caption.textContent = `��120���ǵ� ${percent(style.momentum120)} �� ��60���껯���� ${percent(style.vol60)}��${style.id === 'value' ? '�������������ڴ���ֵ����ֵ������Խ�ߣ���ʾ���������ʷԽ���ˡ�' : '������Ȳ��������������ǣ�����ͨ������ʱ�����Ԥ�㡣'}`;
    el('styleDetail').append(components, caption); renderWheel();
  }

  function renderWheel() {
    if (!state.data || el('positionContent').hidden) return;
    const svg = el('styleWheel'), width = svg.getBoundingClientRect().width;
    if (!width) return;
    const height = width < 400 ? 310 : 350, cx = width / 2, cy = height / 2, radius = Math.min(115, (width - 142) / 2, (height - 90) / 2), ns = 'http://www.w3.org/2000/svg';
    svg.setAttribute('viewBox', `0 0 ${width} ${height}`); svg.setAttribute('height', height); svg.replaceChildren();
    function add(tag, attributes, text) { const node = document.createElementNS(ns, tag); Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value)); if (text !== undefined) node.textContent = text; svg.append(node); return node; }
    add('title', {}, `������̣�${state.data.asOf}�������������Ǹ���`);
    add('desc', {}, state.data.styles.map(s => `${s.name}${number(s.score)}��`).join('��'));
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
      const button = document.createElement('button'); button.type = 'button'; button.dataset.style = style.id; button.setAttribute('aria-label', `�鿴${style.name}���ֹ���`); const label = document.createElement('span'); label.textContent = style.name; const value = document.createElement('strong'); value.textContent = number(style.score); button.append(label, value); button.addEventListener('click', () => { state.styleId = style.id; renderStyleDetail(); }); el('styleButtons').append(button);
    }
    el('methodNotes').replaceChildren(); for (const note of data.notes) { const item = document.createElement('li'); item.textContent = note; el('methodNotes').append(item); }
    el('sourceNote').textContent = data.source;
    const generated = new Date(data.generatedAt); el('generatedAt').textContent = Number.isNaN(generated.valueOf()) ? '' : `���յ��� ${generated.toLocaleString('zh-CN', { timeZone: 'Asia/Shanghai', hour12: false })}`;
    renderVotes(); renderStyleDetail(); el('statusDot').className = 'dot'; el('statusText').textContent = '�Ѷ�ȡ����';
  }

  async function load() {
    const request = ++state.request; el('refreshButton').disabled = true; el('statusDot').className = 'dot loading'; el('statusText').textContent = '���ڶ�ȡ����';
    try {
      const response = await fetch(`/position-advice.json?t=${Date.now()}`, { cache: 'no-store' });
      if (!response.ok) throw new Error('��λ������ʱ�޷���ȡ�����Ժ����ԡ�');
      const data = validate(await response.json()); if (request !== state.request) return; render(data);
    } catch (error) {
      if (request !== state.request) return;
      state.data = null; el('positionContent').hidden = true; el('loadError').hidden = false; el('loadError').textContent = error.message || '�о����ݶ�ȡʧ�ܡ�'; el('asOf').textContent = '��'; el('decisionDate').textContent = '��'; el('generatedAt').textContent = ''; el('statusDot').className = 'dot error'; el('statusText').textContent = '��ȡʧ��';
    } finally { if (request === state.request) el('refreshButton').disabled = false; }
  }
  el('refreshButton').addEventListener('click', load);
  new ResizeObserver(renderWheel).observe(el('styleWheel'));
  document.addEventListener('themechange', renderWheel);
  load();
})();
