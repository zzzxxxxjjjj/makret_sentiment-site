const INDEXES=[
  {name:'全A',color:'#46d6b2',ratio:'financing-activity',buy:'alla-financing-buy',turnover:'alla-turnover-amount'},
  {name:'沪深300',color:'#5aa7ff',ratio:'hs300-financing-activity',buy:'hs300-financing-buy',turnover:'hs300-turnover-amount'},
  {name:'上证50',color:'#9d8cff',ratio:'sse50-financing-activity',buy:'sse50-financing-buy',turnover:'sse50-turnover-amount'},
  {name:'科创50',color:'#f5bd5c',ratio:'star50-financing-activity',buy:'star50-financing-buy',turnover:'star50-turnover-amount'}
];
const RISK_SERIES=[
  {name:'市场平均维持担保比例',color:'#ff8a72',id:'margin-guarantee-ratio'},
  {name:'两融交易投资者参与率',color:'#5aa7ff',id:'margin-investor-participation-ratio'}
];
const state={series:new Map(),riskSeries:new Map(),riskAsOf:null,riskError:null,years:5,charts:new Map()};
const el=id=>document.getElementById(id);
const validPoints=series=>(series?.points||[]).filter(point=>point.date&&Number.isFinite(Number(point.value))).map(point=>({date:point.date,value:Number(point.value)})).sort((a,b)=>a.date.localeCompare(b.date));
const latest=id=>validPoints(state.series.get(id)).at(-1);
const fmt=(value,digits=2)=>Number.isFinite(value)?value.toLocaleString('zh-CN',{maximumFractionDigits:digits,minimumFractionDigits:digits}):'—';
const avg=(points,count)=>{const values=points.slice(-count).map(point=>point.value);return values.length?values.reduce((sum,value)=>sum+value,0)/values.length:null};

function cutoffDate(){const newest=INDEXES.flatMap(index=>[latest(index.buy)?.date,latest(index.ratio)?.date]).filter(Boolean).sort().at(-1);const date=newest?new Date(`${newest}T12:00:00`):new Date();date.setFullYear(date.getFullYear()-state.years);return date.toISOString().slice(0,10)}
function chartSeries(metric){const cutoff=cutoffDate();return INDEXES.map(index=>({name:index.name,color:index.color,points:validPoints(state.series.get(index[metric])).filter(point=>point.date>=cutoff)})).filter(item=>item.points.length)}
function standaloneSeries(metric){const cutoff=cutoffDate();const meta=RISK_SERIES.find(item=>item.id===metric);return meta?[{name:meta.name,color:meta.color,points:validPoints(state.riskSeries.get(metric)).filter(point=>point.date>=cutoff)}].filter(item=>item.points.length):[]}

function renderSummary(){
  el('summaryGrid').innerHTML=INDEXES.map(index=>{const ratio=latest(index.ratio),buy=latest(index.buy);return `<article class="financing-summary-card"><h3>${index.name}</h3><strong>${fmt(ratio?.value)} <small>%</small></strong><p>${buy?`融资买入额 ${fmt(buy.value)} 亿元 · ${buy.date}`:'等待首次历史回算'}</p></article>`}).join('');
}
function renderTable(){
  el('detailRows').innerHTML=INDEXES.map(index=>{const ratioPoints=validPoints(state.series.get(index.ratio));const ratio=ratioPoints.at(-1),buy=latest(index.buy),turnover=latest(index.turnover);return `<tr><td><span style="color:${index.color}">●</span> ${index.name}</td><td>${fmt(buy?.value)} 亿元</td><td>${fmt(turnover?.value)} 亿元</td><td>${fmt(ratio?.value)}%</td><td>${fmt(avg(ratioPoints,5))}%</td><td>${fmt(avg(ratioPoints,20))}%</td><td>${ratio?.date||buy?.date||'—'}</td></tr>`}).join('');
}
function renderLegend(target,items){el(target).innerHTML=items.map(item=>`<span><i style="--color:${item.color}"></i>${item.name}</span>`).join('')}

function drawChart(canvasId,tooltipId,metric,unit){
  const isRisk=RISK_SERIES.some(item=>item.id===metric),grouped=isRisk?[]:chartSeries(metric),canvas=el(canvasId),wrap=canvas.parentElement,items=isRisk?standaloneSeries(metric):grouped,rect=wrap.getBoundingClientRect(),dpr=window.devicePixelRatio||1;
  canvas.width=Math.max(1,Math.round(rect.width*dpr));canvas.height=Math.max(1,Math.round(rect.height*dpr));
  const ctx=canvas.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);const width=rect.width,height=rect.height,pad={l:58,r:18,t:14,b:30};ctx.clearRect(0,0,width,height);
  const all=items.flatMap(item=>item.points);if(!all.length){state.charts.delete(canvasId);ctx.fillStyle='#708397';ctx.font='13px sans-serif';ctx.fillText(isRisk?'暂无两融账户历史数据':'暂无可用历史序列',pad.l,height/2);return}
  const dates=[...new Set(all.map(point=>point.date))].sort(),dateIndex=new Map(dates.map((date,index)=>[date,index]));let min=Math.min(...all.map(point=>point.value)),max=Math.max(...all.map(point=>point.value));const spread=max-min||Math.max(Math.abs(max),1);min-=spread*.08;max+=spread*.08;
  const x=index=>pad.l+(dates.length===1?0:index/(dates.length-1))*(width-pad.l-pad.r),y=value=>pad.t+(max-value)/(max-min)*(height-pad.t-pad.b);
  ctx.strokeStyle='rgba(119,145,169,.13)';ctx.fillStyle='#667b90';ctx.font='11px sans-serif';ctx.textAlign='right';for(let i=0;i<=4;i++){const yy=pad.t+i*(height-pad.t-pad.b)/4,value=max-i*(max-min)/4;ctx.beginPath();ctx.moveTo(pad.l,yy);ctx.lineTo(width-pad.r,yy);ctx.stroke();ctx.fillText(fmt(value,unit==='%'?2:0),pad.l-8,yy+4)}
  ctx.textAlign='center';[0,.5,1].forEach(f=>{const index=Math.round((dates.length-1)*f);ctx.fillText(dates[index].slice(0,7),x(index),height-8)});
  items.forEach(item=>{ctx.beginPath();ctx.strokeStyle=item.color;ctx.lineWidth=2;let started=false;item.points.forEach(point=>{const xx=x(dateIndex.get(point.date)),yy=y(point.value);if(!started){ctx.moveTo(xx,yy);started=true}else ctx.lineTo(xx,yy)});ctx.stroke()});
  state.charts.set(canvasId,{dates,items,x,pad,width,height,tooltipId,unit});
}

function showTooltip(event,canvasId){const chart=state.charts.get(canvasId);if(!chart)return;const rect=event.currentTarget.getBoundingClientRect(),mouseX=event.clientX-rect.left,plotWidth=chart.width-chart.pad.l-chart.pad.r,index=Math.max(0,Math.min(chart.dates.length-1,Math.round((mouseX-chart.pad.l)/plotWidth*(chart.dates.length-1)))),date=chart.dates[index],tooltip=el(chart.tooltipId);const rows=chart.items.map(item=>{const points=item.points;let nearest=points.reduce((best,point)=>Math.abs(point.date.localeCompare(date))<Math.abs(best.date.localeCompare(date))?point:best,points[0]);const exact=points.find(point=>point.date===date);nearest=exact||nearest;return `<div><span style="color:${item.color}">●</span> ${item.name}：${fmt(nearest.value)}${chart.unit}</div>`}).join('');tooltip.innerHTML=`<strong>${date}</strong>${rows}`;tooltip.style.display='block';tooltip.style.left=`${Math.min(chart.width-190,Math.max(8,mouseX+12))}px`;tooltip.style.top='16px'}
function hideTooltip(id){el(id).style.display='none'}
function renderCharts(){const ratio=chartSeries('ratio'),guarantee=standaloneSeries('margin-guarantee-ratio'),investor=standaloneSeries('margin-investor-participation-ratio');drawChart('ratioChart','ratioTooltip','ratio','%');renderLegend('ratioLegend',ratio);drawChart('guaranteeChart','guaranteeTooltip','margin-guarantee-ratio','%');renderLegend('guaranteeLegend',guarantee);drawChart('investorChart','investorTooltip','margin-investor-participation-ratio','%');renderLegend('investorLegend',investor)}

async function fetchJson(url){const response=await fetch(`${url}${url.includes('?')?'&':'?'}t=${Date.now()}`,{cache:'no-store'});if(!response.ok)throw new Error(`HTTP ${response.status}`);return response.json()}
function hasFinancingHistory(data){const map=new Map((data.series||[]).map(item=>[item.id,item]));return INDEXES.some(index=>(map.get(index.buy)?.points||[]).length>0)}
async function loadData(){const button=el('refreshButton');button.disabled=true;try{
  const [broadResult,riskResult]=await Promise.allSettled([
    fetchJson('/api/broad-sentiment').then(async data=>hasFinancingHistory(data)?data:fetchJson('/rqdata-broad-sentiment.json')),
    fetchJson('/akshare-margin-risk.json')
  ]);
  if(broadResult.status==='fulfilled'){
    state.series=new Map((broadResult.value.series||[]).map(item=>[item.id,item]));
    const dates=INDEXES.flatMap(index=>[latest(index.ratio)?.date,latest(index.buy)?.date]).filter(Boolean).sort();
    el('asOf').textContent=dates.length?`融资明细更新至 ${dates.at(-1)}`:'暂无融资明细';
    renderSummary();renderTable();
  }else el('asOf').textContent=`融资明细读取失败：${broadResult.reason.message}`;
  if(riskResult.status==='fulfilled'){
    const data=riskResult.value;
    state.riskSeries=new Map((data.series||[]).map(item=>[item.id,item]));
    state.riskAsOf=RISK_SERIES.map(item=>validPoints(state.riskSeries.get(item.id)).at(-1)?.date).filter(Boolean).sort()[0]||null;
    state.riskError=null;
  }else{
    state.riskSeries=new Map();state.riskAsOf=null;state.riskError=riskResult.reason.message;
  }
  el('riskAsOf').textContent=state.riskAsOf?`AKShare / 东方财富 · 数据截至 ${state.riskAsOf}`:`两融账户数据暂不可用${state.riskError?`：${state.riskError}`:''}`;
  renderCharts();
}finally{button.disabled=false}}

el('refreshButton').addEventListener('click',loadData);el('rangeButtons').addEventListener('click',event=>{const button=event.target.closest('[data-years]');if(!button)return;state.years=Number(button.dataset.years);document.querySelectorAll('[data-years]').forEach(item=>item.classList.toggle('active',item===button));renderCharts()});el('ratioChart').addEventListener('pointermove',event=>showTooltip(event,'ratioChart'));el('ratioChart').addEventListener('pointerleave',()=>hideTooltip('ratioTooltip'));el('guaranteeChart').addEventListener('pointermove',event=>showTooltip(event,'guaranteeChart'));el('guaranteeChart').addEventListener('pointerleave',()=>hideTooltip('guaranteeTooltip'));el('investorChart').addEventListener('pointermove',event=>showTooltip(event,'investorChart'));el('investorChart').addEventListener('pointerleave',()=>hideTooltip('investorTooltip'));window.addEventListener('resize',()=>renderCharts());loadData();
