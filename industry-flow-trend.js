/* ===================== 行业资金流向走势（行业×交易日热力图） ===================== */
/* 依赖 industry-sentiment.js 中的全局：state / el / numeric / fmt / esc / signed / selectIndustry */

const FLOW_TREND_META = {
  flowRatio: { label: '主力资金净流入率', unit: '%', signed: true, desc: '主动资金净额÷行业成交额' },
  marginActivity: { label: '两融活跃度', unit: '%', signed: false, desc: '融资买入额÷行业成交额' },
  amountShare: { label: '成交额占比', unit: '%', signed: false, desc: '行业成交额÷全市场成交额' }
};

const flowTrend = {
  metric: 'flowRatio',
  range: 120,
  freq: 'week'
};
let flowTrendModel = null;

function flowTrendIndustries() {
  return state.industries.filter(item =>
    Array.isArray(item.series) && item.series.length && !String(item.code).startsWith('fallback-'));
}

function flowTrendMetricAvailable(metric) {
  return flowTrendIndustries().some(item => item.series.some(row => numeric(row[metric]) !== null));
}

function flowWeekKey(dateStr) {
  const date = new Date(`${dateStr}T12:00:00`);
  const weekday = (date.getDay() + 6) % 7; /* 周一=0 */
  const thursday = new Date(date);
  thursday.setDate(date.getDate() - weekday + 3);
  const yearStart = new Date(thursday.getFullYear(), 0, 1);
  const week = 1 + Math.round((thursday - yearStart) / 604800000);
  return `${thursday.getFullYear()}-W${String(week).padStart(2, '0')}`;
}

function buildFlowModel() {
  const metric = flowTrend.metric;
  const items = flowTrendIndustries().map(item => {
    const points = (item.series || [])
      .map(row => ({ date: String(row.date || ''), value: numeric(row[metric]) }))
      .filter(point => point.value !== null && point.date)
      .sort((a, b) => (a.date < b.date ? -1 : 1));
    return { code: String(item.code), name: item.name, points };
  }).filter(item => item.points.length);
  items.forEach(item => { item.latestDaily = item.points[item.points.length - 1].value; });

  let dates = [...new Set(items.flatMap(item => item.points.map(point => point.date)))].sort();
  if (dates.length > flowTrend.range) dates = dates.slice(-flowTrend.range);
  const inRange = new Set(dates);

  if (flowTrend.freq === 'week') {
    const weekOf = new Map();
    const weekLast = new Map();
    dates.forEach(date => {
      const key = flowWeekKey(date);
      weekOf.set(date, key);
      weekLast.set(key, date);
    });
    items.forEach(item => {
      const buckets = new Map();
      item.points.forEach(point => {
        if (!inRange.has(point.date)) return;
        const key = weekOf.get(point.date);
        if (!buckets.has(key)) buckets.set(key, []);
        buckets.get(key).push(point.value);
      });
      item.points = [...buckets.entries()]
        .map(([key, values]) => ({ date: weekLast.get(key), value: values.reduce((sum, v) => sum + v, 0) / values.length }))
        .sort((a, b) => (a.date < b.date ? -1 : 1));
    });
    dates = [...new Set(items.flatMap(item => item.points.map(point => point.date)))].sort();
  }

  const dateIndex = new Map(dates.map((date, i) => [date, i]));
  items.forEach(item => {
    item.values = new Array(dates.length).fill(null);
    const seen = new Set();
    item.points.forEach(point => {
      if (!dateIndex.has(point.date) || seen.has(point.date)) return;
      seen.add(point.date);
      item.values[dateIndex.get(point.date)] = point.value;
    });
    item.latest = item.points.length ? item.points[item.points.length - 1].value : item.latestDaily;
  });
  return { dates, items };
}

function flowTickLabel(dateStr, longSpan) {
  if (longSpan) return `${dateStr.slice(2, 4)}/${dateStr.slice(5, 7)}`;
  return `${dateStr.slice(5, 7)}-${dateStr.slice(8, 10)}`;
}

/* ---------- 热力图（行业 × 交易日） ---------- */

let flowHeatLayout = null;

function flowDivergeColor(t) {
  const clamped = Math.max(-1, Math.min(1, t));
  const alpha = 0.16 + Math.abs(clamped) * 0.78;
  return clamped >= 0
    ? `rgba(255,91,109,${alpha.toFixed(3)})`
    : `rgba(44,190,148,${alpha.toFixed(3)})`;
}

function drawFlowHeat(model, hover = null) {
  const canvas = el('flowHeatChart');
  const wrap = el('flowHeatWrap');
  const rows = [...model.items].sort((a, b) => (b.latestDaily ?? -1e9) - (a.latestDaily ?? -1e9));
  const dates = model.dates;
  const rowH = 20;
  const axisH = 26;
  const labelW = 96;
  const height = rows.length * rowH + axisH;
  wrap.style.height = `${height}px`;
  const rect = { width: wrap.clientWidth || 600, height };
  const dpr = window.devicePixelRatio || 1;
  canvas.width = Math.max(1, Math.round(rect.width * dpr));
  canvas.height = Math.max(1, Math.round(height * dpr));
  const ctx = canvas.getContext('2d');
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, rect.width, height);
  const n = dates.length;
  const plotW = Math.max(10, rect.width - labelW - 6);
  const colW = n ? plotW / n : 1;
  if (!rows.length || !n) {
    ctx.fillStyle = '#8395aa';
    ctx.font = '12px "Microsoft YaHei", system-ui, sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText('暂无数据', rect.width / 2, height / 2);
    flowHeatLayout = null;
    return;
  }

  /* 每列横截面排名（用于配色与 tooltip） */
  const rankMatrix = rows.map(() => new Array(n).fill(null));
  const pctMatrix = rows.map(() => new Array(n).fill(null));
  for (let ci = 0; ci < n; ci++) {
    const order = rows
      .map((row, ri) => ({ ri, value: row.values[ci] }))
      .filter(cell => cell.value !== null)
      .sort((a, b) => b.value - a.value);
    order.forEach((cell, k) => {
      rankMatrix[cell.ri][ci] = k + 1;
      /* 分位从底部计：rank 1（当日最大值）→ 接近 100 → 红色 */
      pctMatrix[cell.ri][ci] = ((order.length - k - 0.5) / order.length) * 100;
    });
  }

  /* 主力资金：以绝对值 P98 分位为满格刻度，避免单日极值把整体洗白 */
  let rawScale = 1;
  if (flowTrend.metric === 'flowRatio') {
    const abs = [];
    rows.forEach(row => row.values.forEach(value => { if (value !== null) abs.push(Math.abs(value)); }));
    if (abs.length) {
      abs.sort((a, b) => a - b);
      rawScale = abs[Math.floor((abs.length - 1) * 0.98)] || abs[abs.length - 1] || 1;
    }
  }

  ctx.font = '11px "Microsoft YaHei", system-ui, sans-serif';
  ctx.textBaseline = 'middle';
  rows.forEach((row, ri) => {
    const y = ri * rowH;
    /* 行悬停高亮 */
    if (hover && hover.ri === ri) {
      ctx.fillStyle = 'rgba(90,167,255,.10)';
      ctx.fillRect(0, y, rect.width, rowH);
    }
    const selected = state.selected && String(state.selected.code) === row.code;
    /* 行标签 */
    ctx.textAlign = 'left';
    ctx.fillStyle = selected ? '#ffffff' : '#c9d6e4';
    if (selected) ctx.font = 'bold 11px "Microsoft YaHei", system-ui, sans-serif';
    ctx.fillText(row.name, 8, y + rowH / 2 + 0.5, labelW - 12);
    if (selected) ctx.font = '11px "Microsoft YaHei", system-ui, sans-serif';
    /* 单元格 */
    for (let ci = 0; ci < n; ci++) {
      const value = row.values[ci];
      const x = labelW + ci * colW;
      if (value === null) {
        ctx.fillStyle = 'rgba(32,53,78,.38)';
      } else if (flowTrend.metric === 'flowRatio') {
        ctx.fillStyle = flowDivergeColor(value / rawScale);
      } else {
        ctx.fillStyle = flowDivergeColor(((pctMatrix[ri][ci] ?? 50) - 50) / 50);
      }
      ctx.fillRect(x, y + 1.2, Math.max(colW - 0.5, 0.7), rowH - 2.4);
    }
  });

  /* 悬停列参考线 */
  if (hover && hover.ci >= 0 && hover.ci < n) {
    ctx.strokeStyle = 'rgba(233,240,247,.45)';
    ctx.beginPath();
    const x = labelW + hover.ci * colW + colW / 2;
    ctx.moveTo(x, 0);
    ctx.lineTo(x, rows.length * rowH);
    ctx.stroke();
  }

  /* 底部时间轴 */
  const longSpan = n > 130;
  ctx.fillStyle = '#8395aa';
  ctx.textAlign = 'center';
  ctx.textBaseline = 'top';
  const tickCount = Math.min(6, n);
  for (let k = 0; k < tickCount; k++) {
    const ci = Math.round((k / (tickCount - 1)) * (n - 1));
    ctx.fillText(flowTickLabel(dates[ci], longSpan), labelW + ci * colW + colW / 2, rows.length * rowH + 7);
  }

  flowHeatLayout = { rows, dates, rankMatrix, pctMatrix, labelW, colW, rowH, n, rawScale };
}

function showFlowHeatTooltip(event) {
  const wrap = el('flowHeatWrap');
  const tip = el('flowHeatTooltip');
  const canvas = el('flowHeatChart');
  if (!flowHeatLayout) return;
  const { rows, dates, rankMatrix, labelW, colW, rowH, n } = flowHeatLayout;
  const x = event.offsetX;
  const y = event.offsetY;
  if (x < labelW || y > rows.length * rowH || !n) { tip.style.display = 'none'; drawFlowHeat(flowTrendModel); return; }
  const ci = Math.max(0, Math.min(n - 1, Math.floor((x - labelW) / colW)));
  const ri = Math.max(0, Math.min(rows.length - 1, Math.floor(y / rowH)));
  drawFlowHeat(flowTrendModel, { ri, ci });
  const row = rows[ri];
  const value = row.values[ci];
  const meta = FLOW_TREND_META[flowTrend.metric];
  if (value === null) {
    tip.innerHTML = `<div class="tt-date">${esc(row.name)} · ${dates[ci]}</div><div class="tt-row"><em>当日无数据</em></div>`;
  } else {
    const rank = rankMatrix[ri][ci];
    tip.innerHTML = `
      <div class="tt-date">${esc(row.name)} · ${dates[ci]}</div>
      <div class="tt-row"><span>${esc(meta.label)}</span><em>${meta.signed ? signed(value, 2) : fmt(value, 2)}${meta.unit}</em></div>
      <div class="tt-row"><span>当日排名</span><em>${rank ?? '—'} / ${rows.length}</em></div>
      <div class="tt-row"><span>最新值</span><em>${row.latestDaily === null ? '—' : `${meta.signed ? signed(row.latestDaily, 2) : fmt(row.latestDaily, 2)}${meta.unit}`}</em></div>`;
  }
  tip.style.display = 'block';
  const tipW = tip.offsetWidth;
  const left = Math.max(4, Math.min(event.offsetX + 14, wrap.clientWidth - tipW - 4));
  tip.style.left = `${left}px`;
  tip.style.top = `${Math.max(4, Math.min(event.offsetY - 10, wrap.clientHeight - tip.offsetHeight - 4))}px`;
  canvas.style.cursor = 'pointer';
}

/* ---------- 总渲染 ---------- */

window.renderFlowTrend = function renderFlowTrend() {
  const hasData = flowTrendIndustries().length > 0;
  updateFlowMetricTabs();
  el('flowTrendEmpty').hidden = hasData;
  el('flowHeatWrap').hidden = !hasData;
  if (!hasData) { flowTrendModel = null; return; }
  flowTrendModel = buildFlowModel();
  drawFlowHeat(flowTrendModel);
};

function updateFlowMetricTabs() {
  const hasData = flowTrendIndustries().length > 0;
  document.querySelectorAll('#flowMetricTabs .ft-tab').forEach(btn => {
    const ok = !hasData || flowTrendMetricAvailable(btn.dataset.metric);
    btn.classList.toggle('disabled', !ok);
    btn.title = ok ? '' : '当前数据中该指标不可用（接口未返回）';
  });
  if (hasData && !flowTrendMetricAvailable(flowTrend.metric)) {
    flowTrend.metric = 'flowRatio';
    document.querySelectorAll('#flowMetricTabs .ft-tab').forEach(btn =>
      btn.classList.toggle('active', btn.dataset.metric === 'flowRatio'));
  }
}

/* ---------- 事件绑定 ---------- */

document.querySelectorAll('#flowMetricTabs .ft-tab').forEach(btn => {
  btn.addEventListener('click', () => {
    if (btn.classList.contains('disabled')) return;
    flowTrend.metric = btn.dataset.metric;
    document.querySelectorAll('#flowMetricTabs .ft-tab').forEach(item => item.classList.toggle('active', item === btn));
    renderFlowTrend();
  });
});

function wireFlowSeg(id, attr, apply) {
  const box = el(id);
  box.querySelectorAll('.ft-seg-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      box.querySelectorAll('.ft-seg-btn').forEach(item => item.classList.toggle('active', item === btn));
      apply(btn.dataset[attr]);
      renderFlowTrend();
    });
  });
}
wireFlowSeg('flowRangeSeg', 'range', value => { flowTrend.range = Number(value); });
wireFlowSeg('flowFreqSeg', 'freq', value => { flowTrend.freq = value; });

el('flowHeatChart').addEventListener('pointermove', event => {
  if (!flowTrendModel) return;
  showFlowHeatTooltip(event);
});
el('flowHeatChart').addEventListener('pointerleave', () => {
  el('flowHeatTooltip').style.display = 'none';
  if (flowTrendModel) drawFlowHeat(flowTrendModel);
});
el('flowHeatChart').addEventListener('click', event => {
  if (!flowHeatLayout || !flowTrendModel) return;
  const { rows, labelW, colW, rowH, n } = flowHeatLayout;
  const x = event.offsetX;
  const y = event.offsetY;
  if (y > rows.length * rowH || y < 0) return;
  const ri = Math.max(0, Math.min(rows.length - 1, Math.floor(y / rowH)));
  const row = rows[ri];
  if (!row) return;
  /* 点击行业行：联动选中行业（同步下方二级行业面板） */
  if (typeof selectIndustry === 'function') selectIndustry(row.code);
});

let flowTrendResizeTimer = null;
window.addEventListener('resize', () => {
  if (!flowTrendModel) return;
  clearTimeout(flowTrendResizeTimer);
  flowTrendResizeTimer = setTimeout(renderFlowTrend, 150);
});

/* 首次加载：若主脚本已完成数据加载则立即渲染，否则由 loadData 的钩子触发 */
if (state.industries.length && !String(state.industries[0].code).startsWith('fallback-')) {
  renderFlowTrend();
}
