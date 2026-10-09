const el=id=>document.getElementById(id);
const definitions=[
  {id:'credit-pulse',label:'信贷脉冲',color:'#ff6b78',axis:'left',unit:'%'},
  {id:'all-a-market-cap-to-household-deposits',label:'全A总市值/居民存款',color:'#9d8cff',axis:'left',unit:'倍'},
  {id:'china-ppi-yoy',label:'中国:PPI:当月同比',color:'#f5bd5c',axis:'right',unit:'%'},
  {id:'fx-pulse-leading-3m',label:'外汇脉冲：领先3M',color:'#46d6b2',axis:'left',unit:'点'},
  {id:'hs300-yoy',label:'沪深300',color:'#5aa7ff',axis:'right',unit:'%'}
];
const state={payload:null,series:[],dates:[],visible:new Set(definitions.map(item=>item.id)),rangePoints:[],geometry:null};

function hasNumber(value){return Number.isFinite(Number(value))}
function fmt(value,digits=2){return hasNumber(value)?Number(value).toLocaleString('zh-CN',{minimumFractionDigits:digits,maximumFractionDigits:digits}):'—'}
function escapeHtml(value){return String(value??'').replace(/[&<>'"]/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[char]))}

function seriesById(id){return state.series.find(item=>item.id===id)}
function activeDefinitions(){return definitions.filter(item=>state.visible.has(item.id)&&seriesById(item.id)?.points?.some(point=>hasNumber(point.value)))}

function renderToggles(){
  const available=new Set(state.series.filter(series=>series.points?.some(point=>hasNumber(point.value))).map(series=>series.id));
  el('macroToggles').innerHTML=definitions.map(item=>{
    const enabled=available.has(item.id),active=enabled&&state.visible.has(item.id);
    return `<button type="button" class="benchmark-toggle ${active?'active':''}" data-series="${item.id}" aria-pressed="${active}" ${enabled?'':'disabled'} style="--benchmark-color:${item.color}"><i></i>${escapeHtml(item.label)}</button>`;
  }).join('');
}

function fiveYearStartIndex(dates){
  if(!dates.length)return 0;
  const end=new Date(`${dates.at(-1)}T00:00:00Z`);
  end.setUTCFullYear(end.getUTCFullYear()-5);
  const threshold=end.toISOString().slice(0,10);
  const index=dates.findIndex(date=>date>=threshold);
  return index<0?0:index;
}

function configureTimeline(){
  state.dates=[...new Set(state.series.flatMap(series=>(series.points||[]).filter(point=>point.date>='2016-01-01'&&hasNumber(point.value)).map(point=>point.date)))].sort();
  const maximum=Math.max(state.dates.length-1,0);
  const start=fiveYearStartIndex(state.dates);
  for(const id of ['macroStart','macroEnd']){el(id).min=0;el(id).max=maximum}
  el('macroStart').value=start;
  el('macroEnd').value=maximum;
  updateRange();
}

function updateRange(changed){
  if(!state.dates.length){el('macroEmpty').style.display='grid';return}
  const maximum=state.dates.length-1;
  let start=Number(el('macroStart').value),end=Number(el('macroEnd').value);
  if(start>=end){
    if(changed==='start')start=Math.max(0,end-1);else end=Math.min(maximum,start+1);
  }
  el('macroStart').value=start;el('macroEnd').value=end;
  const span=Math.max(maximum,1);
  el('macroRangeFill').style.left=`${start/span*100}%`;
  el('macroRangeFill').style.width=`${(end-start)/span*100}%`;
  el('macroRangeStart').textContent=state.dates[start];
  el('macroRangeEnd').textContent=state.dates[end];
  state.rangePoints=state.dates.slice(start,end+1);
  drawChart();
}

function scaleFor(values){
  if(!values.length)return {min:0,max:1,range:1};
  let min=Math.min(...values),max=Math.max(...values);
  if(min===max){const margin=Math.abs(min||1)*.1;min-=margin;max+=margin}
  const margin=(max-min)*.1;
  return {min:min-margin,max:max+margin,range:max-min+margin*2};
}

function linePoints(series,startDate,endDate){
  return (series?.points||[]).filter(point=>point.date>=startDate&&point.date<=endDate&&hasNumber(point.value));
}

function drawChart(){
  const canvas=el('macroChart'),wrap=canvas.parentElement,dpr=window.devicePixelRatio||1;
  const width=wrap.clientWidth,height=wrap.clientHeight;
  canvas.width=Math.max(1,Math.round(width*dpr));canvas.height=Math.max(1,Math.round(height*dpr));
  const ctx=canvas.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,width,height);
  const active=activeDefinitions(),dates=state.rangePoints;
  el('macroEmpty').style.display=!active.length||dates.length<2?'grid':'none';
  if(!active.length||dates.length<2){state.geometry=null;return}

  const startDate=dates[0],endDate=dates.at(-1),startTime=Date.parse(startDate),endTime=Date.parse(endDate),timeRange=endTime-startTime||1;
  const plotted=active.map(definition=>({definition,points:linePoints(seriesById(definition.id),startDate,endDate)}));
  const leftValues=plotted.filter(item=>item.definition.axis==='left').flatMap(item=>item.points.map(point=>Number(point.value)));
  const rightValues=plotted.filter(item=>item.definition.axis==='right').flatMap(item=>item.points.map(point=>Number(point.value)));
  const leftScale=scaleFor(leftValues),rightScale=scaleFor(rightValues.length?rightValues:leftValues);
  const pad={l:58,r:62,t:18,b:40},plotW=width-pad.l-pad.r,plotH=height-pad.t-pad.b;
  const x=date=>pad.l+(Date.parse(date)-startTime)/timeRange*plotW;
  const y=(value,scale)=>pad.t+(scale.max-value)/scale.range*plotH;

  ctx.font='10px Segoe UI';ctx.lineWidth=1;
  for(let grid=0;grid<=4;grid++){
    const gy=pad.t+plotH*grid/4;
    ctx.strokeStyle='#20354e';ctx.beginPath();ctx.moveTo(pad.l,gy);ctx.lineTo(width-pad.r,gy);ctx.stroke();
    ctx.fillStyle='#8395aa';ctx.textAlign='right';ctx.fillText(fmt(leftScale.max-leftScale.range*grid/4,1),pad.l-8,gy+3);
    ctx.fillStyle='#5aa7ff';ctx.textAlign='left';ctx.fillText(fmt(rightScale.max-rightScale.range*grid/4,1),width-pad.r+8,gy+3);
  }
  ctx.textAlign='center';ctx.fillStyle='#71849a';
  for(let tick=0;tick<=5;tick++){
    const index=Math.round((dates.length-1)*tick/5),date=dates[index];
    ctx.fillText(date.slice(0,7),pad.l+plotW*tick/5,height-12);
  }

  for(const item of plotted){
    if(!item.points.length)continue;
    const scale=item.definition.axis==='right'?rightScale:leftScale;
    ctx.strokeStyle=item.definition.color;ctx.lineWidth=2;ctx.lineJoin='round';ctx.lineCap='round';ctx.beginPath();
    item.points.forEach((point,index)=>{const px=x(point.date),py=y(Number(point.value),scale);if(index===0)ctx.moveTo(px,py);else ctx.lineTo(px,py)});
    ctx.stroke();
  }
  state.geometry={pad,plotW,plotH,startTime,endTime,timeRange,width,height,plotted};
  const latest=plotted.flatMap(item=>item.points.map(point=>point.date)).sort().at(-1);
  el('macroLatest').textContent=latest?`当前区间更新至 ${latest}`:'—';
}

function hideTooltip(){el('macroTooltip').hidden=true;el('macroHoverLine').hidden=true}
function showTooltip(event){
  const geometry=state.geometry;if(!geometry)return;
  const rect=el('macroChart').getBoundingClientRect(),localX=event.clientX-rect.left;
  const ratio=Math.max(0,Math.min(1,(localX-geometry.pad.l)/geometry.plotW));
  const targetTime=geometry.startTime+geometry.timeRange*ratio;
  const date=state.rangePoints.reduce((best,item)=>Math.abs(Date.parse(item)-targetTime)<Math.abs(Date.parse(best)-targetTime)?item:best,state.rangePoints[0]);
  const lineX=geometry.pad.l+(Date.parse(date)-geometry.startTime)/geometry.timeRange*geometry.plotW;
  const rows=activeDefinitions().map(definition=>{
    const point=seriesById(definition.id)?.points?.find(item=>item.date===date);
    return `<span><b style="color:${definition.color}">${escapeHtml(definition.label)}</b><em>${point&&hasNumber(point.value)?fmt(point.value,2)+' '+definition.unit:'—'}</em></span>`;
  }).join('');
  const tooltip=el('macroTooltip');tooltip.innerHTML=`<strong>${date}</strong>${rows}`;tooltip.hidden=false;
  const desiredX=lineX+14,tooltipWidth=tooltip.offsetWidth||220;
  tooltip.style.left=`${Math.min(Math.max(8,desiredX),geometry.width-tooltipWidth-8)}px`;tooltip.style.top='24px';
  const hover=el('macroHoverLine');hover.hidden=false;hover.style.left=`${lineX}px`;
}

async function loadData(){
  el('statusDot').className='dot loading';el('statusText').textContent='正在读取数据';
  try{
    const response=await fetch(`/macro-tracking.json?_=${Date.now()}`,{cache:'no-store'});
    if(!response.ok)throw new Error(`HTTP ${response.status}`);
    const payload=await response.json();state.payload=payload;state.series=payload.series||[];
    el('asOf').textContent=payload.asOf||'—';el('coverage').textContent=`${state.series.filter(item=>item.points?.length).length} / ${definitions.length}`;
    el('generatedAt').textContent=payload.generatedAt?`页面数据生成于 ${payload.generatedAt.replace('T',' ')}`:'—';
    renderToggles();configureTimeline();
    el('statusDot').className='dot';el('statusText').textContent='数据已更新';
  }catch(error){
    el('statusDot').className='dot error';el('statusText').textContent='读取失败';el('macroEmpty').style.display='grid';
    el('macroEmpty').textContent=`宏观数据读取失败：${error.message}`;
  }
}

el('macroToggles').addEventListener('click',event=>{const button=event.target.closest('[data-series]');if(!button||button.disabled)return;const id=button.dataset.series;if(state.visible.has(id))state.visible.delete(id);else state.visible.add(id);renderToggles();drawChart()});
el('showAll').addEventListener('click',()=>{state.visible=new Set(definitions.map(item=>item.id));renderToggles();drawChart()});
el('hideAll').addEventListener('click',()=>{state.visible.clear();renderToggles();drawChart()});
el('macroStart').addEventListener('input',()=>updateRange('start'));
el('macroEnd').addEventListener('input',()=>updateRange('end'));
el('macroChart').addEventListener('pointermove',showTooltip);
el('macroChart').addEventListener('pointerleave',hideTooltip);
el('refreshButton').addEventListener('click',loadData);
window.addEventListener('resize',()=>{if(state.payload)drawChart()});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)loadData()});
window.setInterval(loadData,5*60*1000);
loadData();
