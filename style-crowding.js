(function () {
  'use strict';
  const codes = ['SIZE', 'MIDCAP', 'GROWTH', 'VALUE', 'DIVYILD', 'MOMENTUM', 'BETA', 'RESVOL'];
  const names = { structure_z: '结构', turnover_z: '换手', trend_z: '趋势', valuation_z: '估值' };
  const num = x => x.toFixed(2);
  function validate(data) {
    if (!data || data.available !== true || data.mode !== 'risk-only' || data.directionStatus !== 'unverified' || !/^\d{4}-\d{2}-\d{2}$/.test(data.asOf || '') || !Array.isArray(data.factors) || data.factors.length !== 16 || new Set(data.factors.map(r => r.code)).size !== 16) throw Error('拥挤度快照不完整');
    for (const r of data.factors) {
      if (r.directionVerified !== false || typeof r.name !== 'string' || !r.name || ['crowding_score', 'crowding_pct', ...Object.keys(names)].some(k => !Number.isFinite(r[k])) || r.crowding_pct < 0 || r.crowding_pct > 100 || (data.comparisonDate ? !Number.isFinite(r.change) : r.change !== null)) throw Error('拥挤度数值未通过校验');
    }
    if (data.comparisonDate && (!/^\d{4}-\d{2}-\d{2}$/.test(data.comparisonDate) || data.comparisonDate >= data.asOf)) throw Error('拥挤度对比日期无效');
    if (codes.some(c => !data.factors.some(r => r.code === c))) throw Error('缺少关键风格因子');
    return data;
  }
  function band(z) { return z >= 1.5 ? '显著拥挤' : z >= 1 ? '偏拥挤' : z <= -1.5 ? '显著低位' : z <= -1 ? '偏低位' : '中性'; }
  function assess(data, timingDate, today) {
    const age = (Date.parse(today) - Date.parse(data.asOf)) / 86400000;
    if (age < 0 || !Number.isFinite(age)) return { stale: true, text: '日期异常，暂停信心调整。' };
    if (age > 4 || (timingDate && data.asOf < timingDate)) return { stale: true, text: '拥挤度日期滞后，暂停信心调整；以下保留实际数据日期。' };
    const high = data.factors.filter(r => r.crowding_score >= 1);
    const extreme = data.factors.filter(r => Object.keys(names).some(k => r[k] >= 1.5));
    return { stale: false, text: high.length ? `信心提示：审慎解读。${high.map(r => r.name).join('、')}因子偏拥挤，相关风格观点需增加风险确认；因子方向待核验，暂不定位轮盘哪一侧。` : `信心提示：保持原判断。综合拥挤度暂未触及偏拥挤区间；${extreme.length ? `${extreme.map(r => r.name).join('、')}存在偏高分项，需留意局部风险；` : ''}低拥挤不作为提高信心或看多的依据。` };
  }
  if (typeof module !== 'undefined' && module.exports) { module.exports = { validate, band, assess }; return; }
  const el = id => document.getElementById(id);
  let request = 0;
  function add(parent, tag, value, cls) { const n = document.createElement(tag); n.textContent = value; if (cls) n.className = cls; parent.append(n); return n; }
  async function load() {
    const id = ++request;
    try {
      const response = await fetch(`/style-crowding.json?t=${Date.now()}`, { cache: 'no-store' });
      if (!response.ok) throw Error('暂时无法读取拥挤度');
      const data = validate(await response.json()); if (id !== request) return;
      const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Shanghai', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
      const result = assess(data, el('asOf').textContent, today);
      el('crowdingDate').textContent = `数据日期 ${data.asOf}${data.comparisonDate ? ` · 对比 ${data.comparisonDate} → ${data.asOf}` : ''}`;
      el('crowdingConfidence').textContent = result.text;
      el('crowdingConfidence').className = `crowding-confidence${result.stale ? ' stale' : ''}`;
      const body = el('crowdingRows'); body.replaceChildren();
      const ordered = [...codes, ...data.factors.map(r => r.code).filter(c => !codes.includes(c))];
      for (const code of ordered) {
        const r = data.factors.find(row => row.code === code), tr = document.createElement('tr');
        add(tr, 'th', r.name); add(tr, 'td', r.crowding_score.toFixed(4)); add(tr, 'td', `${num(r.crowding_pct)}%`);
        add(tr, 'td', band(r.crowding_score), r.crowding_score >= 1 ? 'crowding-high' : '');
        add(tr, 'td', r.change === null ? '—' : `${r.change > 0 ? '+' : ''}${r.change.toFixed(4)}`);
        const parts = Object.entries(names).sort((a, b) => r[b[0]] - r[a[0]]);
        const top = parts[0];
        add(tr, 'td', top && r[top[0]] >= 1 ? `${top[1]} ${num(r[top[0]])}${Object.keys(names).some(k => r[k] <= -1) ? ' · 分项分化' : ''}` : '无分项达到偏拥挤');
        body.append(tr);
      }
      el('crowdingData').hidden = false; el('crowdingError').hidden = true;
    } catch (error) {
      if (id !== request) return;
      el('crowdingData').hidden = true; el('crowdingError').hidden = false;
      el('crowdingError').textContent = `${error.message}，暂停拥挤度信心调整；原轮盘评分继续显示。`;
      el('crowdingDate').textContent = '数据暂不可用';
    }
  }
  el('refreshButton').addEventListener('click', load);
  // Timing data loads independently; reassess freshness when its date arrives.
  new MutationObserver(load).observe(el('asOf'), { childList: true });
  load();
})();
