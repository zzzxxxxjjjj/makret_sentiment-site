/* Weekly rotation uses a trailing four-observation mean before range selection. */
(() => {
  const el = id => document.getElementById(id);
  const view = { payload:null, customRange:false, start:0, end:0, points:[], chart:null };
  const number = (v,d=1) => Number(v).toLocaleString('zh-CN',{maximumFractionDigits:d,minimumFractionDigits:d});
  const color = (name,fallback) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
  function weeklyPoints(points) {
    const weeks=new Map();
    for(const point of points){
      const monday=new Date(point.date+'T00:00:00Z');
      monday.setUTCDate(monday.getUTCDate()-(monday.getUTCDay()+6)%7);
      const key=monday.toISOString().slice(0,10),previous=weeks.get(key);
      if(!previous || point.date>previous.date)weeks.set(key,point);
    }
    const weekly=[...weeks.entries()].sort(([a],[b])=>a.localeCompare(b)).map(([,point])=>point);
    return weekly.slice(3).map((point,index)=>({
      ...point,rawValue:point.value,
      value:weekly.slice(index,index+4).reduce((sum,item)=>sum+item.value,0)/4
    }));
  }
  function rangePoints() {
    return (view.payload?.points || []).slice(view.start,view.end+1);
  }
  function syncSlider() {
    const points=view.payload?.points || [],last=Math.max(0,points.length-1);
    const start=el('rotationHistoryStart'),end=el('rotationHistoryEnd');
    for(const input of [start,end]){input.max=last;input.disabled=points.length<2;}
    start.value=view.start;end.value=view.end;
    start.setAttribute('aria-valuetext',points[view.start]?.date || '暂无数据');
    end.setAttribute('aria-valuetext',points[view.end]?.date || '暂无数据');
    const track=el('rotationHistorySliderTrack');
    track.style.setProperty('--range-start',(last?view.start/last*100:0)+'%');
    track.style.setProperty('--range-end',(last?view.end/last*100:100)+'%');
    el('rotationHistorySliderDates').textContent=points.length?`${points[view.start].date} ～ ${points[view.end].date}`:'暂无数据';
    el('rotationHistoryFirstDate').textContent=points[0]?.date || '—';
    el('rotationHistoryLastDate').textContent=points.at(-1)?.date || '—';
  }
  function slide(event) {
    if(!view.payload?.points.length)return;
    const value=Number(event.target.value);
    if(event.target.id==='rotationHistoryStart')view.start=Math.min(value,view.end-1);
    else view.end=Math.max(value,view.start+1);
    view.customRange=true;el('rotationHistoryTooltip').hidden=true;syncSlider();draw();
  }
  function draw() {
    const canvas=el('rotationHistoryChart'), wrap=canvas.parentElement;
    const points=rangePoints(); view.points=points;
    const width=wrap.clientWidth,height=wrap.clientHeight,dpr=window.devicePixelRatio||1;
    canvas.width=Math.round(width*dpr);canvas.height=Math.round(height*dpr);
    const ctx=canvas.getContext('2d');ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,width,height);
    el('rotationHistoryEmpty').hidden=points.length>1;
    if(points.length<2){view.chart=null;return;}
    const pad={l:width<600?42:54,r:width<600?52:64,t:24,b:32};
    const pw=width-pad.l-pad.r,ph=height-pad.t-pad.b;
    const rotationMax=Math.max(...points.map(p=>p.value))*1.12||1;
    const low=Math.min(...points.map(p=>p.indexClose)),high=Math.max(...points.map(p=>p.indexClose));
    const margin=Math.max(high-low,1)*.08,indexMin=Math.max(0,low-margin),indexMax=high+margin;
    const x=i=>pad.l+i/(points.length-1)*pw;
    const yr=v=>pad.t+(1-v/rotationMax)*ph;
    const yi=v=>pad.t+(indexMax-v)/(indexMax-indexMin)*ph;
    const rotationColor=color('--amber','#f5bd5c'),indexColor=color('--blue','#5aa7ff');
    ctx.font='10px "Microsoft YaHei",sans-serif';ctx.textBaseline='middle';
    for(let i=0;i<=4;i++){
      const y=pad.t+ph*i/4;
      ctx.strokeStyle=color('--chart-grid','#20354e');ctx.lineWidth=1;
      ctx.beginPath();ctx.moveTo(pad.l,y);ctx.lineTo(width-pad.r,y);ctx.stroke();
      ctx.fillStyle=rotationColor;ctx.textAlign='right';ctx.fillText(number(rotationMax*(1-i/4),0),pad.l-8,y);
      ctx.fillStyle=indexColor;ctx.textAlign='left';ctx.fillText(number(indexMax-(indexMax-indexMin)*i/4,0),width-pad.r+8,y);
    }
    ctx.fillStyle=color('--muted','#8ea3b7');ctx.textAlign='center';
    const ticks=width<600?3:6;
    for(let i=0;i<=ticks;i++){
      const index=Math.round((points.length-1)*i/ticks);
      ctx.fillText(points[index].date.slice(0,7),x(index),height-12);
    }
    ctx.save();ctx.beginPath();ctx.rect(pad.l,pad.t,pw,ph);ctx.clip();
    function line(field,y,stroke){
      ctx.beginPath();points.forEach((p,i)=>i?ctx.lineTo(x(i),y(p[field])):ctx.moveTo(x(i),y(p[field])));
      ctx.strokeStyle=stroke;ctx.lineWidth=field==='value'?1.1:1.6;ctx.stroke();
    }
    line('indexClose',yi,indexColor);line('value',yr,rotationColor);ctx.restore();
    view.chart={pad,pw,width,height};
    el('rotationHistoryRange').textContent=`${points[0].date} ～ ${points.at(-1).date} · ${points.length.toLocaleString()}个周度观测`;
  }
  function tooltip(event){
    if(!view.chart)return;
    const {pad,pw,width}=view.chart;
    const box=event.currentTarget.getBoundingClientRect(),mx=event.clientX-box.left,my=event.clientY-box.top;
    const tip=el('rotationHistoryTooltip');
    if(mx<pad.l || mx>pad.l+pw){tip.hidden=true;return;}
    const point=view.points[Math.max(0,Math.min(view.points.length-1,Math.round((mx-pad.l)/pw*(view.points.length-1))))];
    tip.textContent=`${point.date}（当周末次观测）\n轮动强度MA4：${number(point.value,1)}\n原始周度值：${number(point.rawValue,0)}\n中证全指：${number(point.indexClose,2)}点\n行业覆盖：${point.industries || 29}个`;
    tip.hidden=false;tip.style.left=Math.max(4,Math.min(mx+12,width-tip.offsetWidth-8))+'px';tip.style.top=Math.max(4,my-95)+'px';
  }
  async function load(){
    try{
      const response=await fetch('/rqdata-industry-rotation.json',{cache:'no-store'});
      if(!response.ok)throw new Error('missing');
      const data=await response.json();
      if(!Array.isArray(data.points)||data.points.length<2)throw new Error('empty');
      data.points=weeklyPoints(data.points);
      if(data.points.length<2)throw new Error('insufficient weekly history');
      const previous=rangePoints();
      view.payload=data;
      if(!view.customRange){view.start=0;view.end=data.points.length-1;syncSlider();}
      else {
        const start=data.points.findIndex(p=>p.date>=(previous[0]?.date || data.points[0].date));
        const after=data.points.findIndex(p=>p.date>(previous.at(-1)?.date || data.points.at(-1).date));
        view.start=Math.max(0,Math.min(start<0?data.points.length-2:start,data.points.length-2));
        view.end=Math.max(view.start+1,after<0?data.points.length-1:after-1);
        syncSlider();
      }
      const latest=data.points.at(-1),window=data.points.slice(-52);
      el('rotationHistoryValue').textContent=number(latest.value,1);
      el('rotationHistoryPercentile').textContent=number(window.filter(p=>p.value<=latest.value).length/window.length*100,1)+'%';
      el('rotationHistoryDate').textContent='周度 · 数据截至 '+data.points.at(-1).date;
      el('rotationHistoryIndex').textContent=number(data.points.at(-1).indexClose,2)+'点';
      draw();
    }catch(error){
      view.payload=null;view.start=0;view.end=0;syncSlider();view.chart=null;el('rotationHistoryRange').textContent='';el('rotationHistoryEmpty').hidden=false;el('rotationHistoryEmpty').textContent='暂无完整行业轮动和中证全指对比数据';
    }
  }
  el('rotationHistoryStart').addEventListener('input',slide);
  el('rotationHistoryEnd').addEventListener('input',slide);
  el('rotationHistoryChart').addEventListener('pointermove',tooltip);
  el('rotationHistoryChart').addEventListener('pointerdown',tooltip);
  el('rotationHistoryChart').addEventListener('pointerleave',()=>{el('rotationHistoryTooltip').hidden=true;});
  el('refreshButton').addEventListener('click',load);
  window.addEventListener('resize',draw);document.addEventListener('themechange',draw);
  load();
})();
