const focusEtfs=[
  {code:'510300',name:'沪深300ETF华泰柏瑞',index:'沪深300',group:'大盘压舱石'},
  {code:'515390',name:'沪深300ETF华安',index:'沪深300',group:'大盘压舱石'},
  {code:'510210',name:'上证指数ETF富国',index:'上证指数',group:'大盘压舱石'},
  {code:'159949',name:'创业板50ETF华安',index:'创业板50',group:'科技成长主线'},
  {code:'159915',name:'创业板ETF易方达',index:'创业板指',group:'科技成长主线'},
  {code:'588000',name:'科创50ETF华夏',index:'科创50',group:'科技成长主线'},
  {code:'588290',name:'科创芯片ETF华安',index:'科创芯片',group:'科技成长主线'},
  {code:'510500',name:'中证500ETF南方',index:'中证500',group:'中小市值流动性托底'},
  {code:'512100',name:'中证1000ETF南方',index:'中证1000',group:'中小市值流动性托底'}
];
const el=id=>document.getElementById(id);
const fmt=value=>value===null||value===undefined||!Number.isFinite(Number(value))?'—':`${Number(value)>=0?'+':''}${Number(value).toLocaleString('zh-CN',{minimumFractionDigits:2,maximumFractionDigits:2})}`;
const valueClass=value=>Number(value)>0?'flow-positive':Number(value)<0?'flow-negative':'';
const groupClass=group=>group.includes('科技')?'tech':group.includes('中小')?'small':'';

function mergeDetails(details){
  const map=new Map((details||[]).map(item=>[String(item.code),item]));
  return focusEtfs.map(item=>({...item,...(map.get(item.code)||{}),points:map.get(item.code)?.points||[]}));
}

function renderSummary(items){
  const periods=[['flow1D','9只ETF当日合计'],['flow5D','近5日合计'],['flow20D','近20日合计']];
  el('flowSummary').innerHTML=periods.map(([field,label])=>{
    const valid=items.map(item=>Number(item[field])).filter(Number.isFinite);
    const value=valid.length?valid.reduce((sum,current)=>sum+current,0):null;
    return `<article><span>${label}</span><strong class="${valueClass(value)}">${fmt(value)}</strong><em>亿元</em></article>`;
  }).join('');
}

function renderRows(items){
  el('etfRows').innerHTML=items.map((item,index)=>`<tr>
    <td><span class="group-pill ${groupClass(item.group)}">${item.group}</span></td>
    <td><div class="etf-name"><strong>${item.name}</strong><span>${item.index} · ${item.code}</span></div></td>
    <td><span class="flow-value ${valueClass(item.flow1D)}">${fmt(item.flow1D)}</span></td>
    <td><span class="flow-value ${valueClass(item.flow5D)}">${fmt(item.flow5D)}</span></td>
    <td><span class="flow-value ${valueClass(item.flow20D)}">${fmt(item.flow20D)}</span></td>
    <td><div class="spark-wrap"><canvas id="etfSpark${index}"></canvas></div></td>
  </tr>`).join('');
  items.forEach((item,index)=>drawSparkline(el(`etfSpark${index}`),item.points||[]));
  const available=items.filter(item=>Number.isFinite(Number(item.flow1D))).length;
  el('emptyHint').style.display=available?'none':'block';
  el('emptyHint').textContent=available?'':'ETF名单已建立，运行“更新RQData广度并启动网站”后即可显示最新资金流向。';
}

function drawSparkline(canvas,rawPoints){
  const wrap=canvas.parentElement,dpr=window.devicePixelRatio||1,w=wrap.clientWidth,h=wrap.clientHeight;
  canvas.width=w*dpr;canvas.height=h*dpr;
  const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);
  const points=rawPoints.filter(point=>Number.isFinite(Number(point.value))).slice(-40);
  if(points.length<2){ctx.fillStyle='#64788f';ctx.font='10px Segoe UI';ctx.fillText('等待历史数据',4,h/2+3);return}
  const values=points.map(point=>Number(point.value));
  let min=Math.min(...values,0),max=Math.max(...values,0);const margin=(max-min||1)*.1;min-=margin;max+=margin;
  const x=index=>4+(w-8)*(index+.5)/points.length,y=value=>4+(max-value)/(max-min)*(h-8),zero=y(0);
  ctx.strokeStyle='rgba(113,132,154,.32)';ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(0,zero);ctx.lineTo(w,zero);ctx.stroke();
  const barWidth=Math.max(1,Math.min(4,(w-8)/points.length*.62));
  points.forEach((point,index)=>{
    const value=Number(point.value),py=y(value);
    ctx.fillStyle=value>=0?'rgba(255,107,120,.72)':'rgba(70,214,178,.72)';
    ctx.fillRect(x(index)-barWidth/2,Math.min(py,zero),barWidth,Math.max(1,Math.abs(zero-py)));
  });
}

async function loadData(){
  el('statusText').textContent='正在读取数据';el('statusDot').className='dot loading';el('refreshButton').disabled=true;
  try{
    const response=await fetch('/api/broad-sentiment',{cache:'no-store'});
    if(!response.ok)throw new Error(`HTTP ${response.status}`);
    const data=await response.json(),items=mergeDetails(data.etfDetails);
    el('asOf').textContent=data.etfDetails?.map(item=>item.asOf).filter(Boolean).sort().at(-1)||data.asOf||'—';
    renderSummary(items);renderRows(items);
    el('statusText').textContent=data.etfDetails?.length?'数据已更新':'等待ETF明细更新';el('statusDot').className='dot';
    window.currentEtfItems=items;
  }catch(error){
    const items=mergeDetails([]);renderSummary(items);renderRows(items);
    el('statusText').textContent='数据读取失败';el('statusDot').className='dot error';
  }finally{el('refreshButton').disabled=false}
}

el('refreshButton').addEventListener('click',loadData);
window.addEventListener('resize',()=>window.currentEtfItems?.forEach((item,index)=>drawSparkline(el(`etfSpark${index}`),item.points||[])));
loadData();
