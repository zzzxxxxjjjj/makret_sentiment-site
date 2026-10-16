(() => {
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 async function load(){
  try {
   const response=await fetch('/data-freshness.json',{cache:'no-store'});
   if(!response.ok)return;
   const report=await response.json();
   const today=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
   const time=new Intl.DateTimeFormat('en-GB',{timeZone:'Asia/Shanghai',hour:'2-digit',minute:'2-digit',hour12:false}).format(new Date());
   const calendar=report.tradingCalendar||[];
   const expected=calendar.filter(date=>date<today).at(-1)||report.targetDate;
   const target=expected>report.targetDate?expected:report.targetDate;
   const daily=report.entries.filter(e=>e.frequency==='daily');
   const missing=daily.filter(e=>!e.asOf || e.asOf<target);
   const current=daily.length-missing.length;
   const overdue=calendar.includes(today)&&time>='09:30'&&target<today&&missing.length>0;
   let banner=document.getElementById('dataHealthBanner');
   if(!banner){banner=document.createElement('details');banner.id='dataHealthBanner';const main=document.querySelector('main');if(!main)return;main.prepend(banner);}
   banner.style.cssText='margin:0 0 24px;padding:12px 16px;border:1px solid var(--line);border-radius:10px;background:var(--panel-bg);color:var(--text);font-size:12px;line-height:1.9';
   const title=missing.length?`${overdue?'更新未达标':'数据尚未全部到齐'} · 日频 ${current}/${daily.length} 项已至 ${target}`:`日频数据已更新至 ${target}`;
   banner.innerHTML=`<summary style="cursor:pointer;color:${missing.length?'var(--amber)':'var(--accent)'}">${esc(title)} · 查看数据日期</summary><p>更新目标：下一交易日09:30前完成。${esc(report.note)}</p>${missing.length?'<ul>'+missing.map(e=>`<li>${esc(e.label)}：${esc(e.asOf||'暂无数据')}</li>`).join('')+'</ul>':''}<p>披露频率指标：${report.entries.filter(e=>e.frequency!=='daily').map(e=>esc(e.label)+' '+esc(e.asOf||'暂无')).join('；')}</p>${report.methodologyChanges?.length?'<p><strong>云端指标口径调整</strong></p><ul>'+report.methodologyChanges.map(text=>`<li>${esc(text)}</li>`).join('')+'</ul>':''}<p>最近核查：${esc(report.checkedAt.replace('T',' ').slice(0,19))}（北京时间）</p>`;
  } catch(error){ /* Main charts remain usable if the status endpoint is unavailable. */ }
 }
 load();setInterval(load,300000);
 document.getElementById('refreshButton')?.addEventListener('click',load);
})();
