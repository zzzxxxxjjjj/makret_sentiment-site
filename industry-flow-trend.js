/* 一级行业资金流向：当日、近5日、近20日分组条形图。 */
const FLOW_TREND_META = {
  netFlow: { label: '主力资金净流入', unit: '亿元', signed: true, desc: '当日净额 / 近5个交易日累计 / 近20个交易日累计' },
  marginActivity: { label: '杠杆资金活跃度', unit: '%', signed: false, desc: '融资买入额÷行业成交额；周、月为近5、20个交易日的日均值' },
  amountShare: { label: '成交额占比', unit: '%', signed: false, desc: '行业成交额÷全市场成交额；周、月为近5、20个交易日的日均值' }
};
const FLOW_WINDOWS = [
  { key: 'day', label: '当日', days: 1, color: '#478fff' },
  { key: 'week', label: '最近一周', days: 5, color: '#29b8a3' },
  { key: 'month', label: '最近一个月', days: 20, color: '#c89a39' }
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
  items.sort((a, b) => a.day === null ? (b.day === null ? 0 : 1) : b.day === null ? -1 : b.day - a.day);
  return { metric, items, dates };
}
function renderFlowLegend() {
  el('flowBarLegend').innerHTML = FLOW_WINDOWS.map(window =>
    `<span class="fl-item"><i style="background:${window.color}"></i>${window.label}${window.days > 1 ? `（${window.days}个交易日）` : ''}</span>`
  ).join('');
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
  el('flowDataDate').textContent = model.dates.length ? `数据截至 ${model.dates.at(-1)} · 按当日值降序` : '暂无数据日期';
  el('flowTrendEmpty').hidden = hasData;
  el('flowTrendEmpty').textContent = `暂无${meta.label}数据，待数据更新后显示。`;
  const wrap = el('flowBarWrap');
  wrap.hidden = !hasData;
  if (!hasData) { wrap.innerHTML = ''; return; }
  const values = model.items.flatMap(row => FLOW_WINDOWS.map(window => row[window.key])).filter(value => value !== null);
  const min = Math.min(0, ...values), max = Math.max(0, ...values);
  const span = max - min || 1, zero = -min / span * 100;
  const format = value => value === null ? '—' : `${meta.signed ? signed(value, 2) : fmt(value, 2)}${meta.unit}`;
  wrap.innerHTML = model.items.map(row => {
    const selected = String(state.selected?.code) === row.code;
    const bars = FLOW_WINDOWS.map(window => {
      const value = row[window.key];
      const left = value === null ? zero : (Math.min(0, value) - min) / span * 100;
      const width = value === null ? 0 : Math.abs(value) / span * 100;
      const dates = model.dates.slice(-window.days);
      const title = `${window.label} ${dates[0] || ''}～${dates.at(-1) || ''}：${format(value)}${value === null ? '（数据不足）' : ''}`;
      return `<span class="flow-comparison-line" title="${esc(title)}">
        <span class="flow-period-label">${window.label}</span>
        <span class="flow-comparison-track" aria-hidden="true" style="--zero:${zero}%"><i style="left:${left}%;width:${width}%;background:${window.color}"></i></span>
        <strong class="flow-comparison-value ${meta.signed && value !== null ? signClass(value) : ''}">${format(value)}</strong></span>`;
    }).join('');
    return `<button type="button" class="flow-comparison-row${selected ? ' active' : ''}" data-code="${esc(row.code)}" aria-pressed="${selected}">
      <span class="flow-comparison-name">${esc(row.name)}</span><span class="flow-comparison-bars">${bars}</span></button>`;
  }).join('');
  wrap.setAttribute('aria-label', `${meta.label}分组条形图，单位${meta.unit}`);
};
document.querySelectorAll('#flowMetricTabs .ft-tab').forEach(button => {
  button.addEventListener('click', () => {
    flowTrend.metric = button.dataset.metric;
    renderFlowTrend();
  });
});
el('flowBarWrap').addEventListener('click', event => {
  const row = event.target.closest('.flow-comparison-row');
  if (!row) return;
  selectIndustry(row.dataset.code);
  el('flowBarWrap').querySelectorAll('.flow-comparison-row').forEach(button => {
    const active = button === row;
    button.classList.toggle('active', active);
    button.setAttribute('aria-pressed', String(active));
  });
});
if (state.industries.length) renderFlowTrend();
