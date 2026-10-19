const industryNames = [
  '石油石化','煤炭','有色金属','电力及公用事业','钢铁','基础化工','建筑','建材','轻工制造','机械',
  '电力设备及新能源','国防军工','汽车','商贸零售','消费者服务','家电','纺织服装','医药','食品饮料',
  '农林牧渔','银行','非银行金融','房地产','交通运输','电子','通信','计算机','传媒','综合金融'
];

const state = { industries: [], selected: null, selectedSubIndustry: null, valuationChart: null };
const el = id => document.getElementById(id);
const numeric = value => Number.isFinite(Number(value)) ? Number(value) : null;
const fmt = (value, digits = 1) => {
  const number = numeric(value);
  return number === null ? '—' : number.toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits
  });
};
const esc = value => String(value ?? '').replace(/[&<>'"]/g, char => ({
  '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
}[char]));
const signClass = value => numeric(value) === null ? '' : Number(value) > 0 ? 'flow-positive' : Number(value) < 0 ? 'flow-negative' : '';
const signed = (value, digits = 1) => {
  const number = numeric(value);
  if (number === null) return '—';
  return `${number > 0 ? '+' : ''}${fmt(number, digits)}`;
};

function fallbackIndustries() {
  return industryNames.map((name, index) => ({
    code: `fallback-${index}`,
    name,
    flow1D: null,
    flow5D: null,
    flow20D: null,
    series: []
  }));
}

function renderSummary() {
  const valid = state.industries.filter(item => numeric(item.flow1D) !== null);
  const total1D = valid.reduce((sum, item) => sum + Number(item.flow1D), 0);
  const positive5D = valid.filter(item => Number(item.flow5D) > 0).length;
  const strongest = [...valid]
    .filter(item => numeric(item.flowRatio5D) !== null)
    .sort((a, b) => Number(b.flowRatio5D) - Number(a.flowRatio5D))[0];
  const broadest = [...valid]
    .filter(item => numeric(item.flowBreadth5D) !== null)
    .sort((a, b) => Number(b.flowBreadth5D) - Number(a.flowBreadth5D))[0];
  const mostCrowded = [...state.industries]
    .filter(item => numeric(item.crowdingScore) !== null)
    .sort((a, b) => Number(b.crowdingScore) - Number(a.crowdingScore))[0];

  const tiles = [
    ['全行业当日净额', valid.length ? signed(total1D, 1) : '—', valid.length ? '亿元' : '', valid.length ? signClass(total1D) : ''],
    ['近5日净流入行业', positive5D || (valid.length ? '0' : '—'), `/${valid.length || 30}`, ''],
    ['5日净流入率领先', strongest ? strongest.name : '—', strongest ? `${signed(strongest.flowRatio5D, 2)}%` : '', ''],
    ['主动资金流入占比领先', broadest ? broadest.name : '—', broadest ? `${fmt(broadest.flowBreadth5D, 1)}%` : '', ''],
    ['行业拥挤度最高', mostCrowded ? mostCrowded.name : '—', mostCrowded ? `${fmt(mostCrowded.crowdingScore, 1)}分` : '', '']
  ];
  el('industrySummary').innerHTML = tiles.map(([label, value, unit, className]) =>
    `<article class="summary-tile"><span>${esc(label)}</span><strong class="${className}">${esc(value)}</strong><em>${esc(unit)}</em></article>`
  ).join('');
}

function renderValuationScatter() {
  const canvas = el('valuationChart');
  const wrap = canvas.parentElement;
  const empty = el('valuationEmpty');
  const dpr = window.devicePixelRatio || 1;
  const width = wrap.clientWidth;
  const height = wrap.clientHeight;
  canvas.width = width * dpr;
  canvas.height = height * dpr;
  const ctx = canvas.getContext('2d');
  ctx.scale(dpr, dpr);

  const points = state.industries
    .map(item => ({
      code: item.code,
      name: item.name,
      x: numeric(item.roePercentile),
      y: numeric(item.pbPercentile),
      pb: numeric(item.pb),
      roe: numeric(item.roe),
      asOf: item.valuationAsOf
    }))
    .filter(item => item.x !== null && item.y !== null);
  if (points.length < 2) {
    empty.style.display = 'grid';
    el('valuationAsOf').textContent = '暂无可用数据';
    state.valuationChart = null;
    return;
  }
  empty.style.display = 'none';
  const latestDate = points.map(item => item.asOf).filter(Boolean).sort().at(-1);
  el('valuationAsOf').textContent = latestDate ? `更新至 ${latestDate}` : '—';

  const pad = { l: 60, r: 26, t: 28, b: 46 };
  const plotW = width - pad.l - pad.r;
  const plotH = height - pad.t - pad.b;
  const x = value => pad.l + value / 100 * plotW;
  const y = value => pad.t + (100 - value) / 100 * plotH;
  ctx.clearRect(0, 0, width, height);
  ctx.font = '11px Segoe UI';
  ctx.lineWidth = 1;

  for (let tick = 0; tick <= 100; tick += 20) {
    const xx = x(tick);
    const yy = y(tick);
    ctx.strokeStyle = tick === 50 ? 'rgba(233,240,247,.28)' : 'rgba(42,65,91,.62)';
    ctx.beginPath();
    ctx.moveTo(xx, pad.t);
    ctx.lineTo(xx, height - pad.b);
    ctx.stroke();
    ctx.beginPath();
    ctx.moveTo(pad.l, yy);
    ctx.lineTo(width - pad.r, yy);
    ctx.stroke();
    ctx.fillStyle = '#71849a';
    ctx.textAlign = 'center';
    ctx.fillText(`${tick}%`, xx, height - 18);
    ctx.textAlign = 'right';
    ctx.fillText(`${tick}%`, pad.l - 10, yy + 4);
  }
  ctx.fillStyle = '#8ea3b7';
  ctx.textAlign = 'center';
  ctx.fillText('ROE历史分位', pad.l + plotW / 2, height - 4);
  ctx.save();
  ctx.translate(16, pad.t + plotH / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.fillText('PB历史分位', 0, 0);
  ctx.restore();

  ctx.save();
  ctx.beginPath();
  ctx.moveTo(x(0), y(0));
  ctx.lineTo(x(100), y(100));
  ctx.strokeStyle = 'rgba(142,163,183,.34)';
  ctx.lineWidth = 1.6;
  ctx.lineCap = 'round';
  ctx.stroke();
  ctx.restore();

  const plotted = points.map(item => ({ ...item, px: x(item.x), py: y(item.y) }));
  plotted.forEach(item => {
    ctx.fillStyle = state.selected?.code === item.code ? '#ff7182' : '#253fd4';
    ctx.strokeStyle = 'rgba(255,255,255,.72)';
    ctx.lineWidth = state.selected?.code === item.code ? 2 : 1;
    ctx.beginPath();
    ctx.arc(item.px, item.py, state.selected?.code === item.code ? 5 : 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.stroke();
  });

  ctx.font = '600 12px Segoe UI';
  plotted.forEach(item => {
    const label = item.name;
    const textWidth = ctx.measureText(label).width;
    const labelX = Math.min(width - pad.r - textWidth, Math.max(pad.l, item.px + 7));
    const labelY = Math.max(pad.t + 12, item.py - 7);
    ctx.fillStyle = '#e9f0f7';
    ctx.fillText(label, labelX, labelY);
  });
  state.valuationChart = { points: plotted, width, height };
}

function nearestValuationPoint(event) {
  const chart = state.valuationChart;
  if (!chart) return null;
  const rect = event.currentTarget.getBoundingClientRect();
  const mx = event.clientX - rect.left;
  const my = event.clientY - rect.top;
  let best = null;
  let bestDistance = Infinity;
  chart.points.forEach(point => {
    const distance = Math.hypot(point.px - mx, point.py - my);
    if (distance < bestDistance) {
      best = point;
      bestDistance = distance;
    }
  });
  return bestDistance <= 26 ? { point: best, x: mx, y: my } : null;
}

function showValuationTooltip(event) {
  const hit = nearestValuationPoint(event);
  const tooltip = el('valuationTooltip');
  if (!hit) {
    tooltip.style.display = 'none';
    return;
  }
  const { point, x, y } = hit;
  tooltip.innerHTML = `<strong>${esc(point.name)}</strong>
    <span>PB分位 <em>${fmt(point.y, 1)}%</em></span>
    <span>ROE分位 <em>${fmt(point.x, 1)}%</em></span>
    <span>PB当前值 <em>${fmt(point.pb, 2)}</em></span>
    <span>ROE当前值 <em>${fmt(point.roe, 2)}%</em></span>`;
  tooltip.style.display = 'block';
  tooltip.style.left = `${Math.min(state.valuationChart.width - 210, Math.max(10, x + 14))}px`;
  tooltip.style.top = `${Math.max(10, y - 26)}px`;
}

function hideValuationTooltip() {
  el('valuationTooltip').style.display = 'none';
}

function clickValuationPoint(event) {
  const hit = nearestValuationPoint(event);
  if (hit) selectIndustry(hit.point.code);
}

function renderSubIndustryInlineHeatmap(item) {
  const children = Array.isArray(item?.children) ? item.children : [];
  const latestAsOf = children.map(child => child.asOf).filter(Boolean).sort().at(-1);
  el('inlineSubIndustryCount').textContent = children.length
    ? `${children.length}个二级行业${latestAsOf ? ` · ${latestAsOf}` : ''}`
    : '暂无二级数据';
  if (!children.length) {
    el('inlineSubIndustryHeatmap').innerHTML = '<div class="subindustry-empty">暂无二级行业数据，请重新运行一次RQData行业更新。</div>';
    renderSubIndustryStockPanel(null);
    return;
  }
  const values = children.map(child => numeric(child.flow5D)).filter(value => value !== null);
  const scale = values.length ? Math.max(...values.map(value => Math.abs(value))) : 1;
  const sorted = [...children].sort((a, b) => {
    const av = numeric(a.flow5D);
    const bv = numeric(b.flow5D);
    return (bv === null ? -Infinity : bv) - (av === null ? -Infinity : av);
  });
  if (!state.selectedSubIndustry || !children.some(child => String(child.code) === String(state.selectedSubIndustry))) {
    state.selectedSubIndustry = sorted[0]?.code || children[0]?.code || null;
  }
  el('inlineSubIndustryHeatmap').className = 'subindustry-heatmap subindustry-flow-list';
  el('inlineSubIndustryHeatmap').innerHTML = sorted.map(child => {
    const flow = numeric(child.flow5D);
    const ratio = numeric(child.flowRatio5D);
    const centered = flow === null ? 0 : flow;
    const width = flow === null ? 0 : Math.max(2, Math.min(50, Math.abs(centered) / Math.max(scale, 0.0001) * 50));
    const topStock = Array.isArray(child.topStocks) ? child.topStocks[0] : null;
    const leader = topStock ? `${topStock.name || topStock.orderBookId} ${signed(topStock.flow5D, 2)}亿` : '暂无个股排行';
    return `<button class="subindustry-flow-row ${String(child.code) === String(state.selectedSubIndustry) ? 'active' : ''}" data-second-code="${esc(child.code)}">
      <span class="flow-bar-name">${esc(child.name)}</span>
      <span class="flow-bar-track">
        <i class="${centered >= 0 ? 'positive' : 'negative'}" style="--bar:${width}%"></i>
      </span>
      <strong class="${signClass(centered)}">${flow === null ? '—' : `${signed(flow, 2)}亿`}</strong>
      <em>流入占比 ${fmt(child.flowBreadth5D, 0)}% · ${esc(leader)}</em>
    </button>`;
  }).join('');
  el('inlineSubIndustryHeatmap').querySelectorAll('[data-second-code]').forEach(button => {
    button.addEventListener('click', () => {
      state.selectedSubIndustry = button.dataset.secondCode;
      renderSubIndustryInlineHeatmap(item);
    });
  });
  renderSubIndustryStockPanel(children.find(child => String(child.code) === String(state.selectedSubIndustry)) || sorted[0]);
}

function renderSubIndustryStockPanel(child) {
  const panel = el('subIndustryStockPanel');
  if (!child) {
    panel.innerHTML = '';
    return;
  }
  const stocks = Array.isArray(child.topStocks) ? child.topStocks : [];
  if (!stocks.length) {
    panel.innerHTML = `<div class="stock-leader-empty">${esc(child.name)} 暂无个股主动资金排行，请运行二级行业轻量刷新脚本。</div>`;
    return;
  }
  panel.innerHTML = `
    <div class="stock-leader-head">
      <div><span>个股主动资金净流入</span><strong>${esc(child.name)}</strong></div>
      <em>按近5日净额排序</em>
    </div>
    <div class="stock-leader-list">
      ${stocks.map((stock, index) => `
        <div class="stock-leader-row">
          <i>${index + 1}</i>
          <strong>${esc(stock.name || stock.orderBookId)}</strong>
          <span>${esc(stock.orderBookId || '')}</span>
          <b class="${signClass(stock.flow5D)}">${signed(stock.flow5D, 2)}亿</b>
          <em class="${signClass(stock.flow1D)}">当日 ${signed(stock.flow1D, 2)}亿</em>
        </div>
      `).join('')}
    </div>
  `;
}

function selectIndustry(code) {
  state.selected = state.industries.find(item => String(item.code) === String(code)) || state.industries[0];
  state.selectedSubIndustry = null;
  renderValuationScatter();
  renderDetail();
}

function renderDetail() {
  const item = state.selected;
  if (!item) return;
  el('subIndustryPanelTitle').textContent = `${item.name}：二级行业主动资金净流入热力图`;
  renderSubIndustryInlineHeatmap(item);
}

async function loadData() {
  el('refreshButton').disabled = true;
  el('statusText').textContent = '正在读取数据';
  el('statusDot').className = 'dot loading';
  try {
    const response = await fetch('/rqdata-industry-sentiment.json', { cache: 'no-store' });
    if (!response.ok) throw new Error('no cache');
    const data = await response.json();
    const ordinaryRoeReady = data?.valuationFactorStatus?.roeFactor === 'return_on_equity_ttm';
    state.industries = Array.isArray(data.industries) && data.industries.length
      ? data.industries.filter(item => String(item.name || '').trim() !== '综合')
      : fallbackIndustries();
    if (!ordinaryRoeReady) {
      state.industries = state.industries.map(item => ({
        ...item,
        pb: null,
        roe: null,
        pbPercentile: null,
        roePercentile: null,
        valuationAsOf: null
      }));
    }
    el('asOf').textContent = data.asOf || '—';
    el('coverage').textContent = `${state.industries.length}/29`;
    const hasFlow = state.industries.some(item => numeric(item.flow1D) !== null);
    el('statusText').textContent = hasFlow ? '资金数据已更新' : '等待首次资金更新';
    el('statusDot').className = hasFlow ? 'dot' : 'dot loading';
  } catch (error) {
    state.industries = fallbackIndustries();
    el('asOf').textContent = '—';
    el('coverage').textContent = '0/30';
    el('statusText').textContent = '等待首次资金更新';
    el('statusDot').className = 'dot loading';
  } finally {
    state.selected = state.industries.find(item => numeric(item.flowRatio5D) !== null) || state.industries[0];
    renderSummary();
    renderValuationScatter();
    renderDetail();
    if (typeof window.renderFlowTrend === 'function') window.renderFlowTrend();
    el('refreshButton').disabled = false;
  }
}

/* ===================== 公募偏股基金行业超配 ===================== */

const fundOwState = { payload: null };

function fundOwBar(overPp, scale, extraClass = '') {
  const value = numeric(overPp);
  const centered = value === null ? 0 : value;
  const raw = value === null ? 0 : Math.max(1.5, Math.min(50, Math.abs(centered) / Math.max(scale, 0.0001) * 50));
  return `<span class="flow-bar-track ${extraClass}">` +
    `<i class="${centered >= 0 ? 'positive' : 'negative'}" style="--bar:${raw.toFixed(2)}%"></i></span>`;
}

function renderFundChanges(payload) {
  const comparison = payload?.comparison;
  const rows = Array.isArray(comparison?.industries) ? comparison.industries : [];
  const valid = comparison?.asOf === payload?.asOf && comparison?.previousAsOf < comparison?.asOf && rows.length === 31 &&
    rows.every(r => ['changeOverPp', 'previousOverPp', 'currentOverPp', 'weightChangePp', 'benchmarkChangePp']
      .every(k => typeof r[k] === 'number' && Number.isFinite(r[k])));
  if (!valid) {
    el('fundChangeDates').textContent = '暂无完整的两期对比数据';
    el('fundChangeUpNote').textContent = '等待上期数据';
    el('fundChangeDownNote').textContent = '等待上期数据';
    for (const id of ['fundChangeUp', 'fundChangeDown']) el(id).innerHTML = '<div class="fund-ow-row-empty">暂无可比较的周度数据</div>';
    return;
  }
  el('fundChangeDates').textContent = `${comparison.previousAsOf} → ${comparison.asOf}`;
  const up = rows.filter(r => r.changeOverPp > 0).sort((a,b) => b.changeOverPp-a.changeOverPp || String(a.code).localeCompare(String(b.code)));
  const down = rows.filter(r => r.changeOverPp < 0).sort((a,b) => a.changeOverPp-b.changeOverPp || String(a.code).localeCompare(String(b.code)));
  const scale = Math.max(...rows.map(r => Math.abs(r.changeOverPp)), 0.0001);
  const changeText = value => signed(value, value !== 0 && Math.abs(value) < 0.01 ? 4 : 2);
  const render = list => list.slice(0,10).map((r,i) => `<div class="fund-ow-row fund-change-row">
    <span class="fund-ow-row-name"><i class="fund-change-rank">${i+1}</i>${esc(r.name)}</span>
    ${fundOwBar(r.changeOverPp,scale,'fund-ow-row-bar')}
    <strong class="${signClass(r.changeOverPp)}">${changeText(r.changeOverPp)}pp</strong>
    <em title="上期超配 → 本期超配">${changeText(r.previousOverPp)} → ${changeText(r.currentOverPp)}pp</em>
    <small class="fund-change-breakdown">基金配置 ${changeText(r.weightChangePp)}pp · 市场基准 ${changeText(r.benchmarkChangePp)}pp</small>
  </div>`).join('');
  el('fundChangeUpNote').textContent = `${up.length}个行业上升${up.length>10?' · 显示前10名':''}`;
  el('fundChangeDownNote').textContent = `${down.length}个行业下降${down.length>10?' · 显示前10名':''}`;
  el('fundChangeUp').innerHTML = up.length ? render(up) : '<div class="fund-ow-row-empty">本期无行业超配上升</div>';
  el('fundChangeDown').innerHTML = down.length ? render(down) : '<div class="fund-ow-row-empty">本期无行业超配下降</div>';
}

function renderFundOverweight() {
  const payload = fundOwState.payload;
  renderFundChanges(payload);
  const rows = Array.isArray(payload?.industries) ? payload.industries : [];
  const empty = el('fundOwEmpty');

  if (!rows.length) {
    empty.hidden = false;
    el('fundOwAsOf').textContent = '暂无快照';
    el('fundOwTopListNote').textContent = 'over_pp > 0 的行业';
    el('fundOwUnderListNote').textContent = 'over_pp < 0 的行业';
    el('fundOwTopList').innerHTML = '';
    el('fundOwUnderList').innerHTML = '';
    return;
  }
  empty.hidden = true;

  const scale = Math.max(...rows.map(item => Math.abs(numeric(item.overPp) ?? 0)), 0.0001);
  const byOver = [...rows].sort((a, b) => b.overPp - a.overPp);
  const overRows = byOver.filter(item => Number(item.overPp) > 0);
  const underRows = byOver.filter(item => Number(item.overPp) < 0);
  const top = overRows.slice(0, 10);
  const under = underRows.slice(-10).reverse();

  el('fundOwAsOf').textContent = `${payload.asOf || '—'} · ${payload.indexName || ''}（${payload.index || ''}）· 周频`;

  const renderList = list => list.map(item => {
    const value = numeric(item.overPp);
    return `<div class="fund-ow-row">
      <span class="fund-ow-row-name">${esc(item.name)}</span>
      ${fundOwBar(item.overPp, scale, 'fund-ow-row-bar')}
      <strong class="${signClass(value)}">${signed(value, 2)}pp</strong>
      <em title="行业权重 wgt_eq / 全市场自由流通市值占比 mkt">${fmt(item.wgtEq, 2)}% / ${fmt(item.mkt, 2)}%</em>
    </div>`;
  }).join('');
  el('fundOwTopListNote').textContent = overRows.length
    ? `over_pp > 0 的 ${overRows.length} 个行业${overRows.length > top.length ? `（显示前 ${top.length} 个）` : ''}`
    : '当前无行业超配';
  el('fundOwUnderListNote').textContent = underRows.length
    ? `over_pp < 0 的 ${underRows.length} 个行业（显示最低的 ${under.length} 个）`
    : '当前无行业低配';
  el('fundOwTopList').innerHTML = top.length ? renderList(top) : '<div class="fund-ow-row-empty">当前没有超配行业</div>';
  el('fundOwUnderList').innerHTML = under.length ? renderList(under) : '<div class="fund-ow-row-empty">当前没有低配行业</div>';
}

async function loadFundOverweight() {
  try {
    const response = await fetch('/rqdata-fund-exposure.json', { cache: 'no-store' });
    if (!response.ok) throw new Error('no fund exposure cache');
    fundOwState.payload = await response.json();
  } catch (error) {
    fundOwState.payload = null;
  }
  renderFundOverweight();
}

el('refreshButton').addEventListener('click', () => {
  loadData();
  loadFundOverweight();
});
el('valuationChart').addEventListener('pointermove', showValuationTooltip);
el('valuationChart').addEventListener('pointerleave', hideValuationTooltip);
el('valuationChart').addEventListener('click', clickValuationPoint);
window.addEventListener('resize', () => {
  if (state.industries.length) renderValuationScatter();
  if (state.selected) renderSubIndustryInlineHeatmap(state.selected);
});
loadData();
loadFundOverweight();
