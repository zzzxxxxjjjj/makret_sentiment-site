(function () {
  'use strict';
  const $ = id => document.getElementById(id);
  function line(parent, text, tag = 'p') { const n = document.createElement(tag); n.textContent = text; parent.append(n); }
  async function load() {
    $('refreshButton').disabled = true;
    $('statusText').textContent = '正在读取数据';
    try {
      const response = await fetch('/position-advice.json?t=' + Date.now(), {cache:'no-store'});
      if (!response.ok) throw new Error('数据读取失败，请稍后重试');
      const d = await response.json();
      if (d.version !== 'observations-v2' || !Array.isArray(d.moduleVotes) || d.moduleVotes.length !== 5) throw new Error('新版本数据尚未发布完成，请稍后重新读取');
      $('loadError').hidden = true; $('positionContent').hidden = false;
      $('asOf').textContent = d.asOf; $('decisionDate').textContent = d.lastDecisionDate || '待确认';
      $('styleWheel').hidden = true;
      $('styleButtons').replaceChildren(); $('styleDetail').replaceChildren();
      for (const s of d.styles) line($('styleDetail'), `${s.name}：${s.momentum120 === null ? '待补数据' : (s.momentum120 * 100).toFixed(2) + '%'}（截至 ${s.asOf || '暂无'}）`);
      $('moduleVotes').replaceChildren();
      for (const row of d.moduleVotes) {
        const box = document.createElement('div'); box.className = 'style-detail';
        line(box, `${row.name} · ${row.vote === null ? '待补数据' : row.vote > 0 ? '观察偏多' : row.vote < 0 ? '观察偏空' : '观察中性'}`, 'strong');
        if (row.reason) line(box, row.reason);
        for (const f of row.factors) line(box, `${f.name}：${f.vote === null ? f.reason : '研究票 ' + (f.vote > 0 ? '+' : '') + f.vote} · ${f.asOf || '暂无数据'}`);
        $('moduleVotes').append(box);
      }
      $('compositeMean').textContent = '—'; $('compositeLabel').textContent = '研究观察 · 暂不生成仓位';
      $('signalScope').textContent = '数据不足保留NA；观察票尚未通过正式证据准入。';
      $('methodNotes').replaceChildren(); d.notes.forEach(n => line($('methodNotes'), n, 'li'));
      $('sourceNote').textContent = '来源：项目已发布RQData行情、广度、ETF资金流及PCR序列；独立更新的因子收益与拥挤度见下方。';
      $('generatedAt').textContent = '计算时间 ' + new Date(d.generatedAt).toLocaleString('zh-CN', {timeZone:'Asia/Shanghai',hour12:false});
      $('statusText').textContent = '研究观察已读取 · 核验日 ' + d.asOf; $('statusDot').className = 'dot';
    } catch (e) {
      $('positionContent').hidden = true; $('loadError').hidden = false; $('loadError').textContent = e.message;
      $('statusText').textContent = '读取失败'; $('statusDot').className = 'dot error';
    } finally { $('refreshButton').disabled = false; }
  }
  $('refreshButton').addEventListener('click', load); load();
})();
