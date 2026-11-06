'use strict';
const el=id=>document.getElementById(id);
let rows=[],direction='desc';
const finite=x=>typeof x==='number'&&Number.isFinite(x);
const fmt=(x,signed=false)=>finite(x)?(signed&&x>0?'+':'')+x.toFixed(2):'—';
function render(){
 const valid=rows.filter(r=>finite(r.amount));const total=valid.reduce((s,r)=>s+r.amount,0),max=Math.max(0,...valid.map(r=>r.amount));
 const sorted=[...rows].sort((a,b)=>!finite(a.amount)?!finite(b.amount)?a.code.localeCompare(b.code):1:!finite(b.amount)?-1:(direction==='desc'?b.amount-a.amount:a.amount-b.amount)||a.code.localeCompare(b.code));
 el('etfRows').replaceChildren();
 for(const r of sorted){const tr=document.createElement('tr');for(const [i,value] of [r.code,r.name,fmt(r.amount),total&&finite(r.amount)?(r.amount/total*100).toFixed(1)+'%':'—',fmt(r.change,true)+(finite(r.change)?'%':''),fmt(r.flow1D,true),fmt(r.flow5D,true)].entries()){const td=document.createElement('td');td.textContent=value;if(i===2&&max&&finite(r.amount)){td.className='amount-cell';td.style.setProperty('--bar',r.amount/max*100+'%');}if(i>=4)td.className=Number([r.change,r.flow1D,r.flow5D][i-4])>0?'flow-positive':Number([r.change,r.flow1D,r.flow5D][i-4])<0?'flow-negative':'';tr.append(td);}el('etfRows').append(tr);}
 el('amountSort').textContent='当日成交额（亿） '+(direction==='desc'?'↓':'↑');el('amountHeader').setAttribute('aria-sort',direction==='desc'?'descending':'ascending');
 el('etfCount').textContent=rows.length+'只';el('flowSummary').textContent='全表成交额合计 '+fmt(total)+' 亿元 · 占比以本表有效成交额合计为分母';
}
async function load(){el('refreshButton').disabled=true;try{
 const r=await fetch('/etf-market.json?t='+Date.now(),{cache:'no-store'});if(!r.ok)throw Error('东方财富成交额快照尚未生成，请稍后重试');const d=await r.json();if(!d.available||!Array.isArray(d.rows)||!d.rows.length)throw Error('暂无完整ETF成交额快照');
 rows=d.rows.filter(x=>x.asOf===d.asOf);let details=[];try{const b=await fetch('/broad-sentiment.json',{cache:'no-store'});if(b.ok)details=(await b.json()).etfDetails||[];}catch(_){}
 const map=new Map(details.map(x=>[String(x.code),x]));rows=rows.map(x=>{const f=map.get(x.code);return {...x,flow1D:f?.asOf===x.asOf?f.flow1D:null,flow5D:f?.asOf===x.asOf?f.flow5D:null};});
 el('asOf').textContent=d.asOf+' · '+new Date(d.generatedAt).toLocaleTimeString('zh-CN',{timeZone:'Asia/Shanghai',hour12:false});render();el('emptyHint').textContent='';el('statusText').textContent='东方财富成交额已读取';el('statusDot').className='dot';
 }catch(e){el('emptyHint').textContent=e.message;el('statusText').textContent='数据读取失败';el('statusDot').className='dot error';}finally{el('refreshButton').disabled=false;}}
el('amountSort').addEventListener('click',()=>{direction=direction==='desc'?'asc':'desc';render();});el('refreshButton').addEventListener('click',load);load();
