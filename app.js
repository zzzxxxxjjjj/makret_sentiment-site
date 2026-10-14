const state={payload:null,series:[],cycle:null,cyclePoints:[],comparisonKey:'sentiment',comparisonGroup:'sentiment',activeComparison:null,visibleBenchmarks:new Set(),cycleHover:null};
const el=id=>document.getElementById(id);
const fmt=(value,digits=2)=>value===null||value===undefined||Number.isNaN(Number(value))?'—':Number(value).toLocaleString('zh-CN',{minimumFractionDigits:digits,maximumFractionDigits:digits});
const fmtDate=value=>value?String(value).slice(0,10):'—';
const escapeHtml=value=>String(value??'').replace(/[&<>'"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));
const hasNumber=value=>value!==null&&value!==undefined&&value!==''&&Number.isFinite(Number(value));
/* 主题调色板垫片：theme.js 正常加载时读取 CSS 变量（随主题变化），否则回退深色 */
const PAL=()=>window.MS_PALETTE?window.MS_PALETTE():{text:'#e9f0f7',axis:'#8ea3b7',axisDim:'#71849a',grid:'#20354e',gridStrong:'rgba(42,65,91,.62)',zero:'rgba(233,240,247,.38)',point:'#253fd4',red:'#ff6b78',green:'#46d6b2',blue:'#5aa7ff',amber:'#f5bd5c',purple:'#9d8cff',cyan:'#6fd3ff'};
const MC=color=>window.msColor?window.msColor(color):color;
const MA=(color,alpha)=>window.msAlpha?window.msAlpha(color,alpha):color;

function renderCards(cards){
  const visible=cards.filter(card=>!['sentiment-cycle','breadth-sentiment'].includes(card.id));
  const groups={
    momentum:['market-turnover','top5-concentration'],
    funds:['margin-financing','institutional-net-buy','dragon-tiger-net-inflow','new-equity-fund-shares','stock-fund-position','broad-etf-flow']
  };
  const renderGroup=(ids,startIndex)=>ids.map(id=>visible.find(card=>card.id===id)).filter(Boolean).map((card,index)=>{
    const hiddenFundLabels=new Set(['等权均值','有效样本']);
    const sub=(card.submetrics||[])
      .filter(item=>card.id!=='stock-fund-position'||!hiddenFundLabels.has(item.label))
      .map(item=>`<div class="submetric"><span>${escapeHtml(item.label)}</span><strong>${item.text?escapeHtml(item.text):fmt(item.value)}<em>${escapeHtml(item.unit||'')}</em></strong></div>`).join('');
    const main=card.value!==null&&card.value!==undefined?`<div class="value-row"><span class="value">${fmt(card.value)}</span><span class="unit">${escapeHtml(card.unit||'')}</span></div>`:'';
    const percentile=card.percentile!==null&&card.percentile!==undefined?`<div class="percentile">历史分位 ${fmt(card.percentile,1)}%</div>`:'';
    return `<article class="metric-card"><div class="card-top"><span class="card-index">${String(startIndex+index+1).padStart(2,'0')}</span><span class="badge ${card.status==='available'?'':'missing'}">${card.status==='available'?'已更新':'待接入'}</span></div><h3>${escapeHtml(card.title)}</h3>${main}${percentile}${sub}<div class="card-note">${escapeHtml(card.note||'数据口径待补充')} · ${fmtDate(card.asOf)}</div></article>`;
  }).join('');
  el('momentumMetricGrid').innerHTML=renderGroup(groups.momentum,0);
  el('fundMetricGrid').innerHTML=renderGroup(groups.funds,groups.momentum.length);
}

function renderBreadthSummary(cards,comparison,definition=state.activeComparison){
  const isMedium=definition?.key==='medium-term-sentiment';
  const card=(cards||[]).find(item=>item.id===(
    isMedium?'medium-term-sentiment':'breadth-sentiment'
  ));
  if(!card){el('breadthSummary').innerHTML='<div class="breadth-summary-loading">暂无可用摘要数据</div>';return}
  const metrics=new Map((card.submetrics||[]).map(item=>[item.label,item]));
  const rows=(isMedium?[
    ['ERP',metrics.get('ERP')],
    ['股债收益差',metrics.get('股债收益差')],
    ['股债位置差',metrics.get('股债位置差')],
    ['融资活跃度',metrics.get('融资活跃度')],
    ['20日融资净流入',metrics.get('20日融资净流入')],
    ['60日融资余额变化',metrics.get('60日融资余额变化')],
    ['60日市场广度',metrics.get('60日市场广度')]
  ]:[
    ['原始市场广度分',metrics.get('原始市场广度分')],
    ['中证全指 RSI',metrics.get('中证全指 RSI')||metrics.get('万得全A RSI')],
    ['20日新高-新低',metrics.get('新高-新低广度')],
    ['20日均线上方',metrics.get('均线上方广度')],
    ['60日广度确认',metrics.get('60日广度确认')],
    ['价格—广度背离',metrics.get('价格—广度背离')],
    ['顶部风险',metrics.get('顶部风险')],
    ['底部修复',metrics.get('底部修复')],
    ['前瞻观察',metrics.get('前瞻观察')]
  ]).filter(([,item])=>item);
  const phase=isMedium?'':(metrics.get('周期阶段')?.text||comparison?.phaseLabel||'—');
  const phaseMarkup=phase?`<div class="breadth-phase">${escapeHtml(phase)}</div>`:'';
  const title=isMedium?'中期情绪':'短期情绪';
  el('breadthSummary').innerHTML=`
    <div class="breadth-summary-head"><div><p class="eyebrow">MARKET SENTIMENT</p><h3>${escapeHtml(title)}</h3></div><span class="badge">已更新</span></div>
    <div class="breadth-score"><strong>${fmt(card.value,1)}</strong><span>分</span></div>
    ${phaseMarkup}
    <div class="breadth-rows">${rows.map(([label,item])=>`<div><span>${escapeHtml(label)}</span><strong>${item.text?escapeHtml(item.text):fmt(item.value,1)}<em>${escapeHtml(item.unit||'')}</em></strong></div>`).join('')}</div>
    <div class="breadth-asof">${fmtDate(card.asOf)}</div>`;
}

function renderSources(sources,notes){
  el('sourceRows').innerHTML=(sources||[]).map(source=>`<tr><td>${escapeHtml(source.name)}</td><td><span class="source-status ${source.status==='available'?'':'off'}"><i></i>${source.status==='available'?'可用':'未接入'}</span></td><td>${fmtDate(source.asOf)}</td><td>${escapeHtml(source.detail||'—')}</td></tr>`).join('');
  el('notes').innerHTML=(notes||[]).map(note=>`<div>• ${escapeHtml(note)}</div>`).join('');
}

const amountBandLines=[
  {key:'market-amount-ma120',label:'120日均线',color:'#8ea3b7'},
  {key:'market-amount-upper1',label:'+1σ',color:'#f5bd5c',dashed:true},
  {key:'market-amount-lower1',label:'−1σ',color:'#f5bd5c',dashed:true},
  {key:'market-amount-upper2',label:'+2σ',color:'#9d8cff',dashed:true},
  {key:'market-amount-lower2',label:'−2σ',color:'#9d8cff',dashed:true}
];

// Calculate on the full daily history before any display range is selected.
function withAmountBands(series){
  const source=series.find(item=>item.id==='alla-turnover-amount');
  const points=(source?.points||[]).filter(point=>point.date&&hasNumber(point.value)).slice().sort((a,b)=>a.date.localeCompare(b.date));
  const bands=amountBandLines.map(line=>({id:line.key,name:line.label,unit:'亿元',points:[]}));
  for(let index=119;index<points.length;index++){
    const values=points.slice(index-119,index+1).map(point=>Number(point.value));
    const mean=values.reduce((sum,value)=>sum+value,0)/120;
    const sigma=Math.sqrt(values.reduce((sum,value)=>sum+(value-mean)**2,0)/120);
    [mean,mean+sigma,mean-sigma,mean+2*sigma,mean-2*sigma].forEach((value,i)=>bands[i].points.push({date:points[index].date,value}));
  }
  return [...series.filter(item=>!amountBandLines.some(line=>line.key===item.id)),...bands];
}

const chartDefinitions=[
  {group:'momentum',key:'marketAmount',title:'两市成交额',description:'中证全指口径全A成交额；120个交易日均线及滚动标准差（总体）',series:['alla-turnover-amount',...amountBandLines.map(line=>line.key)],colors:['#46d6b2',...amountBandLines.map(line=>line.color)],dashes:[false,...amountBandLines.map(line=>line.dashed)],unit:'万亿元',type:'line',valueDivisor:10000,currentMetrics:[{series:'alla-turnover-amount',label:'两市成交额',unit:'万亿元',valueDivisor:10000}]},
  {group:'momentum',key:'concentration',title:'成交额拥挤度',description:'成交额前5%个股占全市场成交额比例',series:['top5-concentration'],card:'top5-concentration',colors:['#f5bd5c'],unit:'%',type:'line',snapshotDomain:[0,100]},
  {group:'funds',key:'margin',title:'融资活跃度',description:'融资活跃度与全A融资买入额（亿元）',series:['financing-activity','alla-financing-buy'],card:'margin-financing',colors:['#46d6b2','#f5bd5c'],unit:'%',type:'line',dualAxis:true,href:'/financing-activity.html?v=20260806',linkLabel:'查看各指数融资明细 →',clickableCard:true,currentMetrics:[{series:'financing-activity',label:'融资活跃度',unit:'%'},{series:'alla-financing-buy',label:'融资买入额',unit:'亿元'}]},
  {group:'funds',key:'etf',title:'宽基ETF流入 / 流出',description:'ETF份额变化 × 收盘价，红色流入、绿色流出',series:['broad-etf-flow'],card:'broad-etf-flow',colors:['#ff6b78'],unit:'亿元',type:'bar',zeroLine:true,href:'/etf-flows.html',linkLabel:'查看9只ETF明细 →'},
  {group:'funds',key:'landConnect',title:'陆股通成交总额 MA5',description:'沪股通与深股通当日成交金额合计的5日移动平均',series:['land-connect-turnover-ma20'],colors:['#9d8cff'],unit:'亿元',type:'line'},
  {group:'funds',key:'institutionalBuy',title:'机构专用席位买入额 MA5',description:'龙虎榜「机构专用」席位买入额的5日移动平均，去除重复披露和多日累计榜；仅覆盖龙虎榜披露交易',series:['institutional-buy-ma5'],colors:['#9d8cff'],unit:'亿元',type:'line',zeroLine:true,currentMetrics:[{series:'institutional-buy-ma5',label:'5日均线',unit:'亿元'}]},
  {group:'funds',key:'newFund',title:'新成立偏股型基金份额',description:'市场宽基情绪指标Excel份额与偏股型基金指数月涨跌幅',series:['new-equity-fund-shares','partial-equity-fund-index-monthly-return'],card:'new-equity-fund-shares',colors:['#6fd3ff','#f5bd5c'],unit:'亿份',type:'bar',dualAxis:true}
];

const comparisonGroups={
  sentiment:[
    {key:'sentiment',label:'短期情绪指标',unit:'分',description:'左轴为0–100短期情绪指标；右轴可叠加宽基指数，指数按当前区间起点归一至100。',sentiment:true},
    {key:'medium-term-sentiment',label:'中期情绪指标',unit:'分',description:'ERP、股债收益差、股债位置差、融资活跃度、20日融资净流入、60日融资余额变化、60日市场广度确认七项子指标等权平均',score:true,plainDescription:true},
    {key:'windall-turnover',label:'万得全A换手率',unit:'%'},
    {key:'hs300-turnover',label:'沪深300换手率',unit:'%'},
    {key:'csi1000-turnover',label:'中证1000换手率',unit:'%'},
    {key:'star50-turnover',label:'科创50换手率',unit:'%'}
  ],
  momentum:[
    {key:'alla-turnover-amount',label:'两市成交额',unit:'万亿元',valueDivisor:10000,type:'line',exactDates:true,lineColor:'#46d6b2',overlays:amountBandLines,description:'中证全指口径全A成交额；120个交易日均线，上下1倍标准差为黄色虚线，上下2倍为紫色虚线。标准差按同一120日窗口计算（总体），满120个有效交易日后显示。'},
    {key:'top5-concentration',label:'成交额前5%占比',unit:'%'},
    {key:'pcr-oi-ma3-sz50',label:'上证50持仓量PCR MA3',unit:'倍'},
    {key:'pcr-amount-volume-ma3-sz50',label:'上证50 PCR价量比 MA3（正向）',unit:'倍',description:'成交额PCR ÷ 成交量PCR的倒数'},
    {key:'pcr-oi-ma3-hs300',label:'沪深300持仓量PCR MA3',unit:'倍'},
    {key:'pcr-amount-volume-ma3-hs300',label:'沪深300 PCR价量比 MA3（正向）',unit:'倍',description:'成交额PCR ÷ 成交量PCR的倒数'},
    {key:'pcr-oi-ma3-csi1000',label:'中证1000持仓量PCR MA3',unit:'倍'},
    {key:'pcr-amount-volume-ma3-csi1000',label:'中证1000 PCR价量比 MA3（正向）',unit:'倍',description:'成交额PCR ÷ 成交量PCR的倒数'},
    {key:'pcr-oi-ma3-star50',label:'科创50持仓量PCR MA3',unit:'倍'},
    {key:'pcr-amount-volume-ma3-star50',label:'科创50 PCR价量比 MA3（正向）',unit:'倍',description:'成交额PCR ÷ 成交量PCR的倒数'},
  ],
  funds:[
    {key:'financing-activity',label:'全A融资买入额占比',unit:'%'},
    {key:'margin-guarantee-ratio',label:'市场平均担保比例',unit:'%'},
    {key:'broad-etf-flow',label:'宽基ETF净流入/流出',unit:'亿元',zeroLine:true},
    {key:'land-connect-turnover-ma20',label:'陆股通成交总额 MA5',unit:'亿元'},
    {key:'a-share-new-accounts',label:'A股新增开户数',unit:'户'},
    {key:'dragon-tiger-net-inflow',label:'龙虎榜资金净流入',unit:'亿元',zeroLine:true},
    {key:'institutional-buy-ma5',label:'机构专用席位买入额 MA5',unit:'亿元',zeroLine:true},
    {key:'new-equity-fund-shares',label:'新成立偏股型基金份额',unit:'亿份',type:'bar',zeroLine:true},
    {key:'partial-equity-fund-index-monthly-return',label:'偏股型基金指数月涨跌幅',unit:'%',zeroLine:true}
  ]
};

const benchmarkDefinitions=[
  {key:'windall-close-excel',label:'万得全A',color:'#5aa7ff'},
  {key:'hs300-close',label:'沪深300',color:'#ff6b78'},
  {key:'csi1000-close',label:'中证1000',color:'#9d8cff'},
  {key:'star50-close',label:'科创50',color:'#f5bd5c'}
];

const derivativeIndexStyles={
  sz50:{label:'上证50',color:'#ff6b78'},
  csi1000:{label:'中证1000',color:'#9d8cff'},
  hs300:{label:'沪深300',color:'#5aa7ff'},
  star50:{label:'科创50',color:'#f5bd5c'}
};

function cardValue(card){
  if(!card)return null;
  if(Number.isFinite(Number(card.value)))return Number(card.value);
  const first=(card.submetrics||[]).find(item=>Number.isFinite(Number(item.value)));
  return first?Number(first.value):null;
}

function renderIndicatorCharts(series,cards){
  state.series=series||[];
  const seriesMap=new Map(state.series.map(item=>[item.id,item]));
  const cardMap=new Map((cards||[]).map(item=>[item.id,item]));
  const markup=chartDefinitions.map((definition,index)=>{
    const selected=definition.series.map(id=>seriesMap.get(id)).filter(Boolean);
    const latestSeries=selected.find(item=>(item.points||[]).some(point=>Number.isFinite(Number(point.value))));
    const latestPoint=latestSeries?.points?.filter(point=>Number.isFinite(Number(point.value))).at(-1);
    const card=cardMap.get(definition.card);
    const current=latestPoint?Number(latestPoint.value)/(definition.valueDivisor||1):cardValue(card);
    const unit=latestSeries?.unit||definition.unit||card?.unit||'';
    const asOf=latestPoint?.date||card?.asOf||'';
    const legend=selected.map((item,seriesIndex)=>`<span><i class="${definition.dashes?.[seriesIndex]?'dashed':''}" style="--legend-color:${MC(definition.colors[seriesIndex]||'#46d6b2')}"></i>${escapeHtml(item.name)}</span>`).join('');
    const detailsLink=definition.href?`<a class="chart-detail-link" href="${definition.href}">${escapeHtml(definition.linkLabel||'查看明细 →')}</a>`:'';
    const cardLink=definition.clickableCard?` is-clickable" data-chart-href="${definition.href}" role="link" tabindex="0"`:'"';
    const currentMarkup=definition.currentMetrics
      ?`<div class="chart-current multi-current">${definition.currentMetrics.map(metric=>{
        const series=seriesMap.get(metric.series);
        const point=(series?.points||[]).filter(item=>Number.isFinite(Number(item.value))).at(-1);
        const value=point?Number(point.value)/(metric.valueDivisor||1):null;
        return `<strong>${fmt(value)}${metric.unit?` <small>${escapeHtml(metric.unit)}</small>`:''}</strong><span>${escapeHtml(metric.label)} · ${fmtDate(point?.date||asOf)}</span>`;
      }).join('')}</div>`
      :`<div class="chart-current"><strong>${fmt(current)}${unit?` <small>${escapeHtml(unit)}</small>`:''}</strong><span>${fmtDate(asOf)}</span></div>`;
    return {group:definition.group,html:`<article class="indicator-chart-card${cardLink}>
      <div class="indicator-chart-head">
        <div><h3>${escapeHtml(definition.title)}</h3><p>${escapeHtml(definition.description)}</p>${detailsLink}</div>
        ${currentMarkup}
      </div>
      <div class="mini-chart-wrap"><canvas id="metricChart${index}"></canvas><div id="metricEmpty${index}" class="mini-chart-empty"></div></div>
      <div class="mini-chart-legend">${legend}<span class="chart-note">${selected.some(item=>(item.points||[]).length>1)?'近260个交易日':'当前快照'}</span></div>
    </article>`};
  });
  el('momentumChartGrid').innerHTML=markup.filter(item=>item.group==='momentum').map(item=>item.html).join('');
  el('fundChartGrid').innerHTML=markup.filter(item=>item.group==='funds').map(item=>item.html).join('');
  chartDefinitions.forEach((definition,index)=>drawIndicatorChart(definition,index,seriesMap,cardMap));
  document.querySelectorAll('[data-chart-href]').forEach(card=>{
    const open=()=>{window.location.href=card.dataset.chartHref};
    card.addEventListener('click',event=>{if(!event.target.closest('a'))open()});
    card.addEventListener('keydown',event=>{if(event.key==='Enter'||event.key===' '){event.preventDefault();open()}});
  });
}

function chartScale(values,forceZero=false){
  let min=Math.min(...values),max=Math.max(...values);
  if(forceZero){min=Math.min(min,0);max=Math.max(max,0)}
  const raw=max-min||Math.max(Math.abs(max),1);
  const margin=raw*.1;
  return {min:min-margin,max:max+margin,range:raw+margin*2};
}

function drawSnapshot(ctx,w,h,pad,value,definition){
  const P=PAL();
  const domain=definition.snapshotDomain||[-Math.max(Math.abs(value)*1.25,1),Math.max(Math.abs(value)*1.25,1)];
  const x=valueToX=>pad.l+(valueToX-domain[0])/(domain[1]-domain[0])*(w-pad.l-pad.r);
  const zero=x(Math.max(domain[0],Math.min(0,domain[1])));
  const target=x(Math.max(domain[0],Math.min(value,domain[1])));
  const y=(pad.t+h-pad.b)/2;
  ctx.strokeStyle=P.grid;ctx.lineWidth=12;ctx.lineCap='round';ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(w-pad.r,y);ctx.stroke();
  ctx.strokeStyle=value>=0?P.red:P.green;ctx.lineWidth=12;ctx.beginPath();ctx.moveTo(zero,y);ctx.lineTo(target,y);ctx.stroke();
  ctx.fillStyle=P.axisDim;ctx.font='10px Segoe UI';ctx.fillText(fmt(domain[0],0),pad.l,h-pad.b+22);ctx.fillText(fmt(domain[1],0),w-pad.r-28,h-pad.b+22);
}

function drawIndicatorChart(definition,index,seriesMap,cardMap){
  const suffix=String(index).replace('accountDragonTiger','');
  const prefix=String(index).startsWith('accountDragonTiger')?'accountDragonTiger':'metric';
  const canvas=el(`${prefix}Chart${suffix}`),wrap=canvas.parentElement,empty=el(`${prefix}Empty${suffix}`),dpr=window.devicePixelRatio||1;
  canvas.width=Math.max(1,wrap.clientWidth*dpr);canvas.height=Math.max(1,wrap.clientHeight*dpr);
  const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);
  const w=wrap.clientWidth,h=wrap.clientHeight,pad={l:46,r:definition.dualAxis?48:14,t:16,b:28};
  const selected=definition.series.map(id=>seriesMap.get(id)).filter(Boolean).map(item=>{
    const points=(item.points||[]).filter(point=>Number.isFinite(Number(point.value)));
    return {
      ...item,
      unit: definition.unit || item.unit,
      points: points.slice(-260).map(point=>({
        ...point,
        value: Number(point.value)/(definition.valueDivisor||1)
      }))
    };
  });
  const hasHistory=selected.some(item=>item.points.length>1);
  const snapshot=cardValue(cardMap.get(definition.card));
  empty.style.display='none';
  if(!hasHistory){
    if(Number.isFinite(snapshot)){drawSnapshot(ctx,w,h,pad,snapshot,definition);return}
    empty.innerHTML='暂无可用历史序列<br>更新数据后将在这里显示';
    empty.style.display='grid';return;
  }
  const active=selected.filter(item=>item.points.length>1);
  const allValues=active.flatMap(item=>item.points.map(point=>Number(point.value)));
  const primaryScale=chartScale(definition.dualAxis?active[0].points.map(point=>Number(point.value)):allValues,definition.zeroLine);
  const secondaryScale=definition.dualAxis&&active[1]?chartScale(active[1].points.map(point=>Number(point.value)),false):primaryScale;
  const plotH=h-pad.t-pad.b,plotW=w-pad.l-pad.r;
  const y=(value,scale)=>pad.t+(scale.max-value)/scale.range*plotH;
  const baseDates=active[0].points.map(point=>point.date);
  const datePositions=new Map(baseDates.map((date,i)=>[date,i]));
  const xDate=date=>pad.l+plotW*(datePositions.get(date)||0)/Math.max(baseDates.length-1,1);
  ctx.font='10px Segoe UI';ctx.lineWidth=1;
  const P=PAL();
  for(let grid=0;grid<5;grid++){
    const gy=pad.t+plotH*grid/4;ctx.strokeStyle=P.grid;ctx.beginPath();ctx.moveTo(pad.l,gy);ctx.lineTo(w-pad.r,gy);ctx.stroke();
    ctx.fillStyle=P.axisDim;ctx.fillText(fmt(primaryScale.max-primaryScale.range*grid/4,1),3,gy+3);
    if(definition.dualAxis)ctx.fillText(fmt(secondaryScale.max-secondaryScale.range*grid/4,1),w-pad.r+6,gy+3);
  }
  if(definition.zeroLine&&primaryScale.min<=0&&primaryScale.max>=0){
    const zy=y(0,primaryScale);ctx.strokeStyle=PAL().zero;ctx.setLineDash([4,4]);ctx.beginPath();ctx.moveTo(pad.l,zy);ctx.lineTo(w-pad.r,zy);ctx.stroke();ctx.setLineDash([]);
  }
  active.forEach((item,seriesIndex)=>{
    const points=item.points,scale=definition.dualAxis&&seriesIndex===1?secondaryScale:primaryScale;
    const x=pointIndex=>xDate(points[pointIndex].date);
    if(definition.type==='bar'&&seriesIndex===0){
      const zeroY=y(0,scale),barWidth=Math.max(1,Math.min(8,plotW/points.length*.7));
      points.forEach((point,pointIndex)=>{const py=y(Number(point.value),scale);const PP=PAL();ctx.fillStyle=Number(point.value)>=0?MA(PP.red,.82):MA(PP.green,.82);ctx.fillRect(x(pointIndex)-barWidth/2,Math.min(py,zeroY),barWidth,Math.max(1,Math.abs(zeroY-py)))});
    }else{
      let started=false;ctx.beginPath();points.forEach((point,pointIndex)=>{if(!datePositions.has(point.date)){started=false;return}if(started)ctx.lineTo(x(pointIndex),y(Number(point.value),scale));else{ctx.moveTo(x(pointIndex),y(Number(point.value),scale));started=true}});
      ctx.strokeStyle=MC(definition.colors[seriesIndex]||'#46d6b2');ctx.lineWidth=1.8;ctx.setLineDash(definition.dashes?.[seriesIndex]?[5,4]:[]);ctx.stroke();ctx.setLineDash([]);
    }
  });
  const longest=active.reduce((best,item)=>item.points.length>best.points.length?item:best,active[0]);
  ctx.fillStyle=PAL().axisDim;ctx.fillText(longest.points[0].date,pad.l,h-7);ctx.fillText(longest.points.at(-1).date,w-pad.r-62,h-7);
}

function pcrLine(seriesMap,metric,indexKey){
  const style=derivativeIndexStyles[indexKey];
  const series=seriesMap.get(`pcr-${metric}-${indexKey}`);
  if(!style||!series)return null;
  return {
    label:`${style.label} MA3`,
    color:style.color,
    dashed:false,
    points:(series.points||[]).filter(point=>point.date&&Number.isFinite(Number(point.value))).slice(-520)
  };
}

function renderDerivatives(series){
  const seriesMap=new Map((series||[]).map(item=>[item.id,item]));
  const indexKeys=['sz50','hs300','csi1000','star50'];
  const oiLines=indexKeys.map(key=>pcrLine(seriesMap,'oi-ma3',key)).filter(Boolean);
  const tradeLines=indexKeys.map(key=>pcrLine(seriesMap,'amount-volume-ma3',key)).filter(Boolean);
  drawDerivativesChart('derivativesOiChart','derivativesOiEmpty','derivativesOiAsOf',oiLines);
  drawDerivativesChart('derivativesTradeChart','derivativesTradeEmpty','derivativesTradeAsOf',tradeLines);
  el('derivativesOiLegend').innerHTML=oiLines.map(line=>`<span><i class="${line.dashed?'dashed':''}" style="--legend-color:${MC(line.color)}"></i>${escapeHtml(line.label)}</span>`).join('');
  el('derivativesTradeLegend').innerHTML=tradeLines.map(line=>`<span><i class="${line.dashed?'dashed':''}" style="--legend-color:${MC(line.color)}"></i>${escapeHtml(line.label)}</span>`).join('');
}

function drawDerivativesChart(canvasId,emptyId,asOfId,lines,forceZero=false){
  const canvas=el(canvasId),empty=el(emptyId),wrap=canvas.parentElement,dpr=window.devicePixelRatio||1;
  const active=lines.filter(line=>line.points.length>1);
  if(!active.length){
    empty.style.display='grid';
    el(asOfId).textContent='—';
    return;
  }
  empty.style.display='none';
  canvas.width=Math.max(1,wrap.clientWidth*dpr);canvas.height=Math.max(1,wrap.clientHeight*dpr);
  const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);
  const w=wrap.clientWidth,h=wrap.clientHeight,pad={l:46,r:14,t:16,b:28};
  const allPoints=active.flatMap(line=>line.points);
  const values=allPoints.map(point=>Number(point.value));
  const scale=chartScale(values,forceZero);
  const timestamps=allPoints.map(point=>Date.parse(point.date)).filter(Number.isFinite);
  const timeMin=Math.min(...timestamps),timeMax=Math.max(...timestamps),timeRange=timeMax-timeMin||1;
  const plotW=w-pad.l-pad.r,plotH=h-pad.t-pad.b;
  const x=date=>pad.l+(Date.parse(date)-timeMin)/timeRange*plotW;
  const y=value=>pad.t+(scale.max-value)/scale.range*plotH;
  ctx.font='10px Segoe UI';ctx.lineWidth=1;
  const P=PAL();
  for(let grid=0;grid<=4;grid++){
    const gy=pad.t+plotH*grid/4;
    ctx.strokeStyle=P.grid;ctx.beginPath();ctx.moveTo(pad.l,gy);ctx.lineTo(w-pad.r,gy);ctx.stroke();
    ctx.fillStyle=P.axisDim;ctx.fillText(fmt(scale.max-scale.range*grid/4,2),3,gy+3);
  }
  if(forceZero&&scale.min<=0&&scale.max>=0){
    const zeroY=y(0);
    ctx.strokeStyle=P.zero;ctx.setLineDash([4,4]);
    ctx.beginPath();ctx.moveTo(pad.l,zeroY);ctx.lineTo(w-pad.r,zeroY);ctx.stroke();ctx.setLineDash([]);
  }
  active.forEach(line=>{
    ctx.beginPath();
    line.points.forEach((point,index)=>index?ctx.lineTo(x(point.date),y(Number(point.value))):ctx.moveTo(x(point.date),y(Number(point.value))));
    ctx.strokeStyle=MC(line.color);ctx.lineWidth=line.dashed?1.25:1.8;ctx.setLineDash(line.dashed?[5,4]:[]);ctx.stroke();
  });
  ctx.setLineDash([]);
  const firstDate=new Date(timeMin).toISOString().slice(0,10);
  const lastDate=new Date(timeMax).toISOString().slice(0,10);
  ctx.fillStyle=P.axisDim;ctx.fillText(firstDate,pad.l,h-7);ctx.fillText(lastDate,w-pad.r-62,h-7);
  const lineDates=active.map(line=>line.points.at(-1).date).sort();
  el(asOfId).textContent=lineDates[0]===lineDates.at(-1)?`更新至 ${lastDate}`:`各曲线截至 ${lineDates[0]} ～ ${lineDates.at(-1)}`;
}

function findComparisonDefinition(key){
  return Object.values(comparisonGroups).flat().find(item=>item.key===key);
}

function comparisonSeriesAvailable(definition){
  if(definition.sentiment)return (state.cycle?.points||[]).some(point=>hasNumber(point.sentiment));
  return state.series.some(item=>item.id===definition.key&&(item.points||[]).some(point=>hasNumber(point.value)));
}

function interpolateBenchmark(points,targetDates,maxGapDays=14,maxCarryDays=4){
  const dayMs=24*60*60*1000;
  const known=(points||[])
    .filter(point=>point.date&&point.value!==null&&point.value!==undefined&&point.value!==''&&Number.isFinite(Number(point.value)))
    .map(point=>({date:point.date,time:Date.parse(point.date),value:Number(point.value)}))
    .filter(point=>Number.isFinite(point.time))
    .sort((a,b)=>a.time-b.time);
  const result=new Map();
  let cursor=0;
  targetDates.forEach(date=>{
    const time=Date.parse(date);
    if(!Number.isFinite(time)||!known.length)return;
    while(cursor<known.length&&known[cursor].time<time)cursor++;
    const next=known[cursor],previous=known[cursor-1];
    if(next&&next.time===time){result.set(date,next.value);return}
    if(previous&&next){
      const gapDays=(next.time-previous.time)/dayMs;
      if(gapDays<=maxGapDays){
        const weight=(time-previous.time)/(next.time-previous.time);
        result.set(date,previous.value+(next.value-previous.value)*weight);
      }
      return;
    }
    if(previous&&(time-previous.time)/dayMs<=maxCarryDays)result.set(date,previous.value);
  });
  return result;
}

function comparisonPoints(definition){
  const sourcePoints=definition.sentiment
    ?(state.cycle?.points||[])
      .filter(point=>point.date&&hasNumber(point.sentiment))
      .map(point=>({date:point.date,indicator:Number(point.sentiment),phaseLabel:point.displayPhaseLabel||point.phaseLabel||''}))
    :(state.series.find(item=>item.id===definition.key)?.points||[])
      .filter(point=>point.date&&hasNumber(point.value))
      .map(point=>({date:point.date,indicator:Number(point.value)/(definition.valueDivisor||1)}));
  const canonicalBenchmark=state.series.find(series=>series.id==='windall-close-excel')
    ||benchmarkDefinitions.map(item=>state.series.find(series=>series.id===item.key)).find(Boolean);
  const allTargetDates=[...new Set((canonicalBenchmark?.points||[])
    .filter(point=>point.date&&hasNumber(point.value))
    .map(point=>point.date))].sort();
  const commonStart=fiveYearStartDate(allTargetDates.at(-1));
  const targetDates=commonStart
    ?allTargetDates.filter(date=>date>=commonStart)
    :allTargetDates;
  if(!targetDates.length)return [];
  const sourceByDate=new Map(sourcePoints.map(point=>[point.date,point]));
  const indicatorMap=definition.type==='bar'||definition.exactDates
    ?new Map(sourcePoints.map(point=>[point.date,point.indicator]))
    :interpolateBenchmark(sourcePoints.map(point=>({date:point.date,value:point.indicator})),targetDates);
  const benchmarkMaps=new Map(benchmarkDefinitions.map(item=>{
    const source=state.series.find(series=>series.id===item.key);
    return [item.key,interpolateBenchmark(source?.points||[],targetDates)];
  }));
  return targetDates.map(date=>({
    date,
    indicator:indicatorMap.get(date)??null,
    phaseLabel:sourceByDate.get(date)?.phaseLabel||'',
    benchmarks:Object.fromEntries(benchmarkDefinitions.map(item=>[
      item.key,
      benchmarkMaps.get(item.key)?.get(date)??null
    ]))
  }));
}

function availableBenchmarks(){
  return benchmarkDefinitions.filter(definition=>state.series.some(series=>
    series.id===definition.key&&(series.points||[]).some(point=>Number.isFinite(Number(point.value)))
  ));
}

function activeBenchmarks(){
  return availableBenchmarks().filter(definition=>state.visibleBenchmarks.has(definition.key));
}

function fiveYearStartDate(endDate){
  const end=new Date(`${endDate}T00:00:00Z`);
  if(!Number.isFinite(end.getTime()))return null;
  end.setUTCFullYear(end.getUTCFullYear()-5);
  return end.toISOString().slice(0,10);
}

function renderBenchmarkToggles(){
  const available=new Set(availableBenchmarks().map(item=>item.key));
  if(state.visibleBenchmarks.size&&![...state.visibleBenchmarks].some(key=>available.has(key))){
    const fallback=benchmarkDefinitions.find(item=>available.has(item.key));
    if(fallback)state.visibleBenchmarks.add(fallback.key);
  }
  el('benchmarkToggles').innerHTML=benchmarkDefinitions.map(item=>{
    const enabled=available.has(item.key),active=enabled&&state.visibleBenchmarks.has(item.key);
    return `<button type="button" class="benchmark-toggle ${active?'active':''}" data-benchmark="${item.key}" aria-pressed="${active}" ${enabled?'':'disabled'} style="--benchmark-color:${item.color}"><i></i>${escapeHtml(item.label)}</button>`;
  }).join('');
  renderBenchmarkLegend();
}

function renderBenchmarkLegend(){
  const active=activeBenchmarks();
  el('cyclePriceLegend').innerHTML=active.map(item=>`<span><i style="--benchmark-color:${item.color}"></i>${escapeHtml(item.label)}</span>`).join('');
  el('cyclePriceLegend').style.display=active.length?'flex':'none';
}

function activateComparisonGroup(group,preferredKey){
  const available=(comparisonGroups[group]||[]).filter(comparisonSeriesAvailable);
  state.comparisonGroup=group;
  document.querySelectorAll('[data-comparison-group]').forEach(button=>{
    const active=button.dataset.comparisonGroup===group;
    button.classList.toggle('active',active);
    button.setAttribute('aria-selected',String(active));
  });
  const select=el('comparisonMetric');
  select.innerHTML=available.map(item=>`<option value="${escapeHtml(item.key)}">${escapeHtml(item.label)}</option>`).join('');
  const selected=available.find(item=>item.key===preferredKey)||available[0];
  if(!selected){
    state.cyclePoints=[];
    el('cycleEmpty').textContent='该类别暂无可用历史序列';
    el('cycleEmpty').style.display='grid';
    return;
  }
  select.value=selected.key;
  activateComparison(selected.key);
}

function activateComparison(key){
  const definition=findComparisonDefinition(key);
  if(!definition)return;
  state.comparisonKey=key;
  state.activeComparison=definition;
  state.cyclePoints=comparisonPoints(definition);
  if(state.payload)renderBreadthSummary(state.payload.cards||[],state.payload.cycleComparison,definition);
  renderBenchmarkToggles();
  el('cycleTitle').textContent=definition.sentiment?'短期情绪指标':definition.label;
  const description=definition.description||`左轴为${definition.label}（${definition.unit}）；右轴可叠加宽基指数，指数按当前区间起点归一至100。`;
  el('cycleDescription').textContent=definition.plainDescription
    ?description
    :definition.sentiment||definition.score
    ?`${description}；虚线为历史P5/P95极值；时间轴固定显示最近五年。`
    :`${description}；时间轴固定显示最近五年。`;
  el('cycleMetricLegend').innerHTML=`<i class="${definition.type==='bar'?'indicator-bar':'sentiment-line'}"${definition.lineColor?` style="background:${MC(definition.lineColor)}"`:''}></i>${escapeHtml(definition.label)}${definition.overlays?.map(line=>`<span class="cycle-band-label"><i class="${line.dashed?'dashed':''}" style="--legend-color:${MC(line.color)}"></i>${escapeHtml(line.label)}</span>`).join('')||''}`;
  const updateInfo=state.series.find(item=>item.id===definition.key)?.updateInfo;
  if(updateInfo&&updateInfo.status!=='current')el('cycleDescription').textContent+=` 当前数据截至 ${updateInfo.asOf||'—'}，${updateInfo.mode==='Wind快照'?'等待Wind快照更新':'等待来源更新'}。`;
  renderBenchmarkLegend();
  if(state.cyclePoints.length<2){
    el('cycleEmpty').textContent='暂无可用的指标对比历史';
    el('cycleEmpty').style.display='grid';
    return;
  }
  el('cycleEmpty').style.display='none';
  const maximum=state.cyclePoints.length-1;
  const fixedStart=fiveYearStartDate(state.cyclePoints.at(-1)?.date);
  const fixedStartIndex=fixedStart
    ?state.cyclePoints.findIndex(point=>point.date>=fixedStart)
    :0;
  const minimum=fixedStartIndex>=0?fixedStartIndex:0;
  el('cycleStart').min=minimum;el('cycleEnd').min=minimum;
  el('cycleStart').max=maximum;el('cycleEnd').max=maximum;
  el('cycleStart').value=minimum;
  el('cycleEnd').value=maximum;
  updateCycleRange();
}

function renderCycle(comparison){
  state.cycle=comparison;
  activateComparisonGroup(state.comparisonGroup||'sentiment',state.comparisonKey||'sentiment');
}

function updateCycleRange(changed){
  const points=state.cyclePoints;
  if(points.length<2)return;
  const maximum=points.length-1;
  const minimum=Math.min(maximum,Number(el('cycleStart').min)||0);
  const span=Math.max(1,maximum-minimum);
  const minGap=Math.min(60,span);
  let start=Math.max(minimum,Math.min(maximum,Number(el('cycleStart').value)));
  let end=Math.max(minimum,Math.min(maximum,Number(el('cycleEnd').value)));
  if(end-start<minGap){
    if(changed==='start')start=Math.max(minimum,end-minGap);
    else end=Math.min(maximum,start+minGap);
  }
  el('cycleStart').value=start;el('cycleEnd').value=end;
  const left=(start-minimum)/span*100,right=(end-minimum)/span*100;
  el('cycleRangeFill').style.left=`${left}%`;
  el('cycleRangeFill').style.width=`${right-left}%`;
  el('cycleRangeStart').textContent=points[start].date;
  el('cycleRangeEnd').textContent=points[end].date;
  drawCycleChart(points.slice(start,end+1));
}

function drawCycleChart(points){
  const canvas=el('cycleChart'),wrap=canvas.parentElement,dpr=window.devicePixelRatio||1;
  canvas.width=wrap.clientWidth*dpr;canvas.height=wrap.clientHeight*dpr;
  const ctx=canvas.getContext('2d');ctx.scale(dpr,dpr);
  const w=wrap.clientWidth,h=wrap.clientHeight,pad={l:54,r:62,t:18,b:32};
  const definition=state.activeComparison||comparisonGroups.sentiment[0];
  const indicatorValues=points.map(point=>hasNumber(point.indicator)?Number(point.indicator):null).filter(Number.isFinite);
  const benchmarkSeries=activeBenchmarks();
  const benchmarkLines=benchmarkSeries.map(series=>{
    const rawValues=points.map(point=>{
      const value=point.benchmarks?.[series.key];
      return hasNumber(value)?Number(value):null;
    });
    const base=rawValues.find(value=>Number.isFinite(value)&&value!==0);
    return {
      ...series,
      values:rawValues.map(value=>Number.isFinite(value)&&Number.isFinite(base)?value/base*100:null)
    };
  });
  const benchmarkValues=benchmarkLines.flatMap(series=>series.values.filter(Number.isFinite));
  const hasBenchmark=benchmarkValues.length>1;
  const overlayMaps=(definition.overlays||[]).map(line=>({
    ...line,
    values:new Map((state.series.find(item=>item.id===line.key)?.points||[]).filter(point=>point.date&&hasNumber(point.value)).map(point=>[point.date,Number(point.value)/(definition.valueDivisor||1)]))
  }));
  const overlayValues=overlayMaps.flatMap(line=>points.map(point=>line.values.get(point.date)).filter(Number.isFinite));
  const indicatorScale=definition.sentiment||definition.score?{min:0,max:100,range:100}:chartScale([...indicatorValues,...overlayValues],definition.zeroLine);
  const benchmarkScale=hasBenchmark?chartScale(benchmarkValues,false):{min:0,max:1,range:1};
  const plotTop=pad.t,plotBottom=h-pad.b,plotHeight=plotBottom-plotTop;
  const x=index=>pad.l+(w-pad.l-pad.r)*index/Math.max(points.length-1,1);
  const y=(value,scale)=>plotTop+(scale.max-value)/scale.range*plotHeight;

  if(definition.sentiment||definition.score){
    ctx.fillStyle='rgba(255,107,120,.035)';ctx.fillRect(pad.l,y(33,indicatorScale),w-pad.l-pad.r,plotBottom-y(33,indicatorScale));
    ctx.fillStyle='rgba(70,214,178,.035)';ctx.fillRect(pad.l,y(75,indicatorScale),w-pad.l-pad.r,y(55,indicatorScale)-y(75,indicatorScale));
    ctx.fillStyle='rgba(245,189,92,.035)';ctx.fillRect(pad.l,plotTop,w-pad.l-pad.r,y(80,indicatorScale)-plotTop);
  }
  ctx.font='10px Segoe UI';ctx.lineWidth=1;
  for(let grid=0;grid<=4;grid++){
    const ratio=grid/4,gy=plotTop+plotHeight*ratio;
    ctx.strokeStyle='#20354e';ctx.beginPath();ctx.moveTo(pad.l,gy);ctx.lineTo(w-pad.r,gy);ctx.stroke();
    const indicatorLabel=indicatorScale.max-indicatorScale.range*ratio;
    ctx.fillStyle='#71849a';ctx.fillText(fmt(indicatorLabel,definition.sentiment||definition.score?0:1),4,gy+3);
    if(hasBenchmark){
      const benchmarkLabel=benchmarkScale.max-benchmarkScale.range*ratio;
      ctx.fillText(fmt(benchmarkLabel,0),w-pad.r+8,gy+3);
    }
  }
  if(definition.zeroLine&&indicatorScale.min<0&&indicatorScale.max>0){
    const zeroY=y(0,indicatorScale);
    ctx.strokeStyle='rgba(245,189,92,.5)';ctx.setLineDash([4,4]);ctx.beginPath();ctx.moveTo(pad.l,zeroY);ctx.lineTo(w-pad.r,zeroY);ctx.stroke();ctx.setLineDash([]);
  }
  if(definition.sentiment||definition.score){
    const history=state.cyclePoints.map(point=>hasNumber(point.indicator)?Number(point.indicator):null).filter(Number.isFinite).sort((a,b)=>a-b);
    const quantile=ratio=>{
      if(!history.length)return null;
      const position=(history.length-1)*ratio;
      const lower=Math.floor(position),upper=Math.ceil(position);
      return history[lower]+(history[upper]-history[lower])*(position-lower);
    };
    const extremeLines=[
      {value:quantile(.95),color:'#ff6b78'},
      {value:quantile(.05),color:'#5aa7ff'}
    ].filter(item=>Number.isFinite(item.value));
    ctx.save();
    ctx.setLineDash([6,5]);
    ctx.font='10px Segoe UI';
    extremeLines.forEach(item=>{
      const lineY=y(item.value,indicatorScale);
      ctx.strokeStyle=item.color;
      ctx.globalAlpha=.82;
      ctx.beginPath();
      ctx.moveTo(pad.l,lineY);
      ctx.lineTo(w-pad.r,lineY);
      ctx.stroke();
      ctx.globalAlpha=1;
      ctx.fillStyle=item.color;
      ctx.fillText(fmt(item.value,1),pad.l+7,lineY-5);
    });
    ctx.restore();
  }
  if(definition.type==='bar'){
    const zeroY=y(0,indicatorScale);
    const barWidth=Math.max(1,Math.min(9,(w-pad.l-pad.r)/Math.max(points.length,1)*.72));
    points.forEach((point,index)=>{
      if(!hasNumber(point.indicator))return;
      const value=Number(point.indicator);
      const pointY=y(value,indicatorScale);
      ctx.fillStyle=value>=0?'rgba(70,214,178,.58)':'rgba(255,107,120,.58)';
      ctx.fillRect(x(index)-barWidth/2,Math.min(pointY,zeroY),barWidth,Math.max(1,Math.abs(zeroY-pointY)));
    });
  }
  overlayMaps.forEach(line=>{
    let started=false;ctx.beginPath();
    points.forEach((point,index)=>{
      const value=line.values.get(point.date);
      if(!Number.isFinite(value)){started=false;return}
      if(started)ctx.lineTo(x(index),y(value,indicatorScale));else{ctx.moveTo(x(index),y(value,indicatorScale));started=true}
    });
    ctx.strokeStyle=MC(line.color);ctx.lineWidth=1.8;ctx.setLineDash(line.dashed?[6,4]:[]);ctx.stroke();ctx.setLineDash([]);
  });
  if(hasBenchmark)benchmarkLines.forEach(series=>{
    let started=false;
    ctx.beginPath();
    series.values.forEach((value,index)=>{
      if(!Number.isFinite(value)){started=false;return}
      if(started)ctx.lineTo(x(index),y(value,benchmarkScale));
      else{ctx.moveTo(x(index),y(value,benchmarkScale));started=true}
    });
    ctx.strokeStyle=series.color;ctx.lineWidth=2;ctx.lineJoin='round';ctx.lineCap='round';ctx.globalAlpha=.96;ctx.stroke();ctx.globalAlpha=1;
  });
  if(definition.type!=='bar'){
    let started=false;ctx.beginPath();points.forEach((point,index)=>{if(!hasNumber(point.indicator)){started=false;return}const value=Number(point.indicator);if(started)ctx.lineTo(x(index),y(value,indicatorScale));else{ctx.moveTo(x(index),y(value,indicatorScale));started=true}});
    ctx.strokeStyle=MC(definition.lineColor||'#46d6b2');ctx.lineWidth=2.2;ctx.stroke();
  }

  ctx.fillStyle='#71849a';ctx.fillText(points[0].date,pad.l,h-9);
  const end=points.at(-1).date;ctx.fillText(end,w-pad.r-62,h-9);
  const latest=[...points].reverse().find(point=>hasNumber(point.indicator))||points.at(-1);
  const phase=definition.sentiment&&latest.phaseLabel?` · ${latest.phaseLabel}`:'';
  const latestBenchmarks=benchmarkSeries.map(series=>{
    const point=[...points].reverse().find(item=>{
      const value=item.benchmarks?.[series.key];
      return value!==null&&value!==undefined&&value!==''&&Number.isFinite(Number(value));
    });
    return point?`${series.label} ${fmt(point.benchmarks[series.key],0)}`:'';
  }).filter(Boolean);
    el('cycleLatest').textContent=`${latest.date}${phase} · ${definition.label} ${fmt(latest.indicator,definition.sentiment||definition.score?1:2)} ${definition.unit}${latestBenchmarks.length?` · ${latestBenchmarks.join(' · ')}`:''}`;
  state.cycleHover={points,benchmarkSeries,definition,pad,w,overlayMaps};
}

function hideCycleTooltip(){
  el('cycleTooltip').hidden=true;
  el('cycleHoverLine').hidden=true;
}

function showCycleTooltip(event){
  const hover=state.cycleHover;
  if(!hover||hover.points.length<1)return;
  const canvas=el('cycleChart');
  const wrap=canvas.parentElement;
  const rect=canvas.getBoundingClientRect();
  const plotLeft=hover.pad.l;
  const plotRight=rect.width-hover.pad.r;
  const pointerX=Math.max(plotLeft,Math.min(plotRight,event.clientX-rect.left));
  const ratio=(pointerX-plotLeft)/Math.max(plotRight-plotLeft,1);
  const index=Math.max(0,Math.min(hover.points.length-1,Math.round(ratio*(hover.points.length-1))));
  const point=hover.points[index];
  const indicator=hasNumber(point.indicator)?Number(point.indicator):null;
  const rows=[
    hasNumber(indicator)?`<span>${escapeHtml(hover.definition.label)}<em>${fmt(indicator,hover.definition.sentiment||hover.definition.score?1:2)} ${escapeHtml(hover.definition.unit||'')}</em></span>`:'',
    ...(hover.overlayMaps||[]).map(line=>{
      const value=line.values.get(point.date);
      return Number.isFinite(value)?`<span>${escapeHtml(line.label)}<em>${fmt(value,2)} ${escapeHtml(hover.definition.unit||'')}</em></span>`:'';
    }),
    ...hover.benchmarkSeries.map(series=>{
      const value=point.benchmarks?.[series.key];
      return value!==null&&value!==undefined&&value!==''&&Number.isFinite(Number(value))
        ?`<span>${escapeHtml(series.label)}<em>${fmt(value,2)}</em></span>`
        :'';
    }).filter(Boolean)
  ].filter(Boolean);
  const tooltip=el('cycleTooltip');
  const line=el('cycleHoverLine');
  tooltip.innerHTML=`<strong>${escapeHtml(point.date)}</strong>${rows.join('')}`;
  tooltip.hidden=false;
  line.hidden=false;
  line.style.left=`${pointerX}px`;
  const tooltipWidth=tooltip.offsetWidth||180;
  const preferredLeft=pointerX+14;
  tooltip.style.left=`${preferredLeft+tooltipWidth+8>rect.width?Math.max(6,pointerX-tooltipWidth-14):preferredLeft}px`;
  tooltip.style.top='12px';
}

async function loadData(){
  el('statusText').textContent='正在读取数据';el('statusDot').className='dot loading';el('refreshButton').disabled=true;
  try{
    const response=await fetch(`/api/broad-sentiment?_=${Date.now()}`,{cache:'no-store',headers:{'Cache-Control':'no-cache'}});if(!response.ok)throw new Error(`HTTP ${response.status}`);
    const data=await response.json();state.payload=data;state.series=withAmountBands(data.series||[]);
    el('asOf').textContent=fmtDate(data.asOf);el('coverage').textContent=`${data.availableCount}/${data.cards.length}`;
    el('generatedAt').textContent=`生成于 ${String(data.generatedAt||'').replace('T',' ')}`;
    renderCards(data.cards||[]);renderCycle(data.cycleComparison);renderDerivatives(state.series);renderIndicatorCharts(state.series,data.cards);
    el('statusText').textContent=data.freshness?.delayedCount?'已读取 · 部分指标待更新':data.missingCount?`已更新 · ${data.missingCount}项待接入`:'数据已更新';el('statusDot').className='dot';
  }catch(error){el('statusText').textContent='数据读取失败';el('statusDot').className='dot error';el('momentumMetricGrid').innerHTML=`<article class="metric-card"><h3>暂时无法读取数据</h3><p class="summary">${escapeHtml(error.message)}</p></article>`;el('fundMetricGrid').innerHTML=''}
  finally{el('refreshButton').disabled=false}
}

el('refreshButton').addEventListener('click',loadData);
document.querySelectorAll('[data-comparison-group]').forEach(button=>button.addEventListener('click',()=>activateComparisonGroup(button.dataset.comparisonGroup)));
el('comparisonMetric').addEventListener('change',event=>activateComparison(event.target.value));
el('benchmarkToggles').addEventListener('click',event=>{
  const button=event.target.closest('[data-benchmark]');
  if(!button||button.disabled)return;
  const key=button.dataset.benchmark;
  if(state.visibleBenchmarks.has(key))state.visibleBenchmarks.delete(key);
  else state.visibleBenchmarks.add(key);
  renderBenchmarkToggles();
  if(state.cyclePoints.length)updateCycleRange();
});
el('cycleStart').addEventListener('input',()=>updateCycleRange('start'));
el('cycleEnd').addEventListener('input',()=>updateCycleRange('end'));
el('cycleChart').addEventListener('pointermove',showCycleTooltip);
el('cycleChart').addEventListener('pointerleave',hideCycleTooltip);
window.addEventListener('resize',()=>{if(state.payload){renderDerivatives(state.series);renderIndicatorCharts(state.series,state.payload.cards)}if(state.cyclePoints.length)updateCycleRange()});
document.addEventListener('visibilitychange',()=>{if(!document.hidden)loadData()});
window.setInterval(loadData,5*60*1000);
loadData();
