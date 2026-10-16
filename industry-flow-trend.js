/* 一级行业资金流向：日度、周度、月度各自独立排名。 */
const FLOW_TREND_META = {
  netFlow: { label: '主力资金净流入', unit: '亿元', signed: true, desc: '当日净额 / 近5个交易日累计 / 近20个交易日累计' },
  marginActivity: { label: '杠杆资金活跃度', unit: '%', signed: false, desc: '融资买入额÷行业成交额；周、月为近5、20个交易日的日均值' },
  amountShare: { label: '成交额占比', unit: '%', signed: false, desc: '行业成交额÷全市场成交额；周、月为近5、20个交易日的日均值' }
};
const FLOW_WINDOWS = [
  { key: 'day', label: '日度', days: 1 },
  { key: 'week', label: '周度', days: 5 },
  { key: 'month', label: '月度', days: 20 }
];
const flowTrend = { metric: 'netFlow' };

// 缺失值不能变为零，也不能用更早的日期补足窗口。
function flowNumber(value) {
  return value === null || value === undefined || String(value).trim() === ''
    ? null : Number.isFinite(Number(value)) ? Number(value) : null;
}
function flowTrendIndustries() {
  return state.industries.filter(item => !String(item.code).startsWith('fallback-'));
}
function buildFlowModel() {
  const metric = flowTrend.metric;
  const industries = flowTrendIndustries();
  const dates = [...new Set(industries.flatMap(item => (item.series || []).map(row => row.date).filter(Boolean)))].sort();
  const items = industries.map(item => {
    const byDate = new Map((item.series || []).map(row => [row.date, flowNumber(row[metric])]));
    const values = Object.fromEntries(FLOW_WINDOWS.map(window => {
      const period = dates.slice(-window.days);
      const points = period.map(date => byDate.get(date) ?? null);
      if (period.length < window.days || points.some(value => value === null)) return [window.key, null];
      const total = points.reduce((sum, value) => sum + value, 0);
      return [window.key, metric === 'netFlow' ? total : total / points.length];
    }));
    return { code: String(item.code), name: item.name, ...values };
  });
  return { metric, items, dates };
}
function rankFlowItems(items, key) {
  return [...items].sort((a, b) => a[key] === null ? (b[key] === null ? 0 : 1) : b[key] === null ? -1 : b[key] - a[key]);
}
function renderFlowLegend() {
  el('flowBarLegend').innerHTML = flowTrend.metric === 'netFlow'
    ? '<span class="fl-item"><i style="background:var(--red)"></i>净流入</span><span class="fl-item"><i style="background:var(--accent)"></i>净流出</span>'
    : '<span class="fl-item"><i style="background:var(--blue)"></i>占比</span>';
}
window.renderFlowTrend = function renderFlowTrend() {
  const model = buildFlowModel();
  const meta = FLOW_TREND_META[model.metric];
  const hasData = model.items.some(row => FLOW_WINDOWS.some(window => row[window.key] !== null));
  document.querySelectorAll('#flowMetricTabs .ft-tab').forEach(button => {
    const active = button.dataset.metric === model.metric;
    button.classList.toggle('active', active);
    button.setAttribute('aria-selected', String(active));
    button.setAttribute('role', 'tab');
  });
  renderFlowLegend();
  el('flowMetricDescription').textContent = `${meta.label}（${meta.unit}） · ${meta.desc}`;
  el('flowDataDate').textContent = model.dates.length ? `数据截至 ${model.dates.at(-1)} · 各时间维度独立降序排名` : '暂无数据日期';
  el('flowTrendEmpty').hidden = hasData;
  el('flowTrendEmpty').textContent = `暂无${meta.label}数据，待数据更新后显示。`;
  const wrap = el('flowBarWrap');
  wrap.hidden = !hasData;
  if (!hasData) { wrap.innerHTML = ''; return; }
  const format = value => value === null ? '—' : `${meta.signed ? signed(value, 2) : fmt(value, 2)}${meta.unit}`;
  wrap.innerHTML = FLOW_WINDOWS.map(window => {
    const rows = rankFlowItems(model.items, window.key);
    const values = rows.map(row => row[window.key]).filter(value => value !== null);
    const min = Math.min(0, ...values), max = Math.max(0, ...values);
    const span = max - min || 1, zero = -min / span * 100;
    const dates = model.dates.slice(-window.days);
    const period = window.days === 1 ? '当日' : `近${window.days}个交易日`;
    const statistic = meta.signed ? (window.days === 1 ? '净流入' : '累计净流入') : (window.days === 1 ? '占比' : '日均占比');
    const bars = rows.map((row, index) => {
      const value = row[window.key];
      const left = value === null ? zero : (Math.min(0, value) - min) / span * 100;
      const width = value === null ? 0 : Math.abs(value) / span * 100;
      const selected = String(state.selected?.code) === row.code;
      const color = meta.signed ? (value < 0 ? 'var(--accent)' : 'var(--red)') : 'var(--blue)';
      const title = `${row.name} · ${window.label}：${format(value)}${value === null ? '（数据不足）' : ''}`;
      return `<button type="button" class="flow-ranking-row${selected ? ' active' : ''}" data-code="${esc(row.code)}" aria-pressed="${selected}" title="${esc(title)}">
        <span class="flow-rank-number">${value === null ? '—' : index + 1}</span>
        <span class="flow-ranking-name">${esc(row.name)}</span>
        <span class="flow-ranking-track" aria-hidden="true" style="--zero:${zero}%"><i style="left:${left}%;width:${width}%;background:${color}"></i></span>
        <strong class="flow-ranking-value ${meta.signed && value !== null ? signClass(value) : ''}">${format(value)}</strong></button>`;
    }).join('');
    return `<section class="flow-ranking-card" data-period="${window.key}" aria-label="${window.label}${meta.label}排行">
      <header class="flow-ranking-heading"><h3>${window.label}排行</h3><span>${period} · ${statistic}</span><small>${esc(dates[0] || '—')}${window.days > 1 ? ` ～ ${esc(dates.at(-1) || '—')}` : ''}</small></header>
      <div class="flow-ranking-list">${bars}</div></section>`;
  }).join('');
  wrap.setAttribute('aria-label', `${meta.label}日度、周度、月度独立排行，单位${meta.unit}`);
};
document.querySelectorAll('#flowMetricTabs .ft-tab').forEach(button => {
  button.addEventListener('click', () => {
    flowTrend.metric = button.dataset.metric;
    renderFlowTrend();
  });
});
el('flowBarWrap').addEventListener('click', event => {
  const row = event.target.closest('.flow-ranking-row');
  if (!row) return;
  selectIndustry(row.dataset.code);
  el('flowBarWrap').querySelectorAll('.flow-ranking-row').forEach(button => {
    const active = button.dataset.code === row.dataset.code;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
  });
});
if (state.industries.length) renderFlowTrend();
