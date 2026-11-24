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
  const available = Array.isArray(payload?.industries) && payload.industries.length > 0;
  el('fundOwEmpty').hidden = available;
  el('fundOwAsOf').textContent = available
    ? `${payload.asOf || '—'} · ${payload.indexName || ''}（${payload.index || ''}）· 周频`
    : '暂无快照';
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


async function loadIndustryHeader(){try{const r=await fetch('/sw-industry-flow.json',{cache:'no-store'});if(!r.ok)throw Error();const d=await r.json();const p=(d.snapshots||[]).filter(p=>p.date===d.asOf).at(-1);if(!d.available||!p)throw Error();el('asOf').textContent=d.asOf;el('coverage').textContent=p.rows.length+'/30';el('statusText').textContent='申万主力资金已更新';el('statusDot').className='dot';}catch(e){el('statusText').textContent='暂未取得申万资金快照';}}
el('refreshButton').addEventListener('click',()=>{loadIndustryHeader();loadFundOverweight();});
loadIndustryHeader();loadFundOverweight();
