/* Independent daily rotation panel; data uses the source's actual trading dates. */
(() => {
  const el = id => document.getElementById(id);
  const view = { payload:null, years:10, points:[], chart:null };
  const number = (v,d=1) => Number(v).toLocaleString('zh-CN',{maximumFractionDigits:d,minimumFractionDigits:d});
  const color = (name,fallback) => getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
  function rangePoints() {
    const points = view.payload?.points || [];
    if (!points.length) return [];
    const first = new Date(points.at(-1).date+'T00:00:00Z');
    first.setUTCFullYear(first.getUTCFullYear()-view.years);
    return points.filter(p=>p.date >= first.toISOString().slice(0,10));
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
    el('rotationHistoryRange').textContent=`${points[0].date} ～ ${points.at(-1).date} · ${points.length.toLocaleString()}个交易日`;
  }
  function tooltip(event){
    if(!view.chart)return;
    const {pad,pw,width}=view.chart;
    const box=event.currentTarget.getBoundingClientRect(),mx=event.clientX-box.left,my=event.clientY-box.top;
    const tip=el('rotationHistoryTooltip');
    if(mx<pad.l || mx>pad.l+pw){tip.hidden=true;return;}
    const point=view.points[Math.max(0,Math.min(view.points.length-1,Math.round((mx-pad.l)/pw*(view.points.length-1))))];
    tip.textContent=`${point.date}\n轮动强度：${number(point.value,0)}\n中证全指：${number(point.indexClose,2)}点\n行业覆盖：${point.industries || 29}个`;
    tip.hidden=false;tip.style.left=Math.max(4,Math.min(mx+12,width-tip.offsetWidth-8))+'px';tip.style.top=Math.max(4,my-95)+'px';
  }
  async function load(){
    try{
      const response=await fetch('/rqdata-industry-rotation.json',{cache:'no-store'});
      if(!response.ok)throw new Error('missing');
      const data=await response.json();
      if(!Array.isArray(data.points)||!data.points.length)throw new Error('empty');
      view.payload=data;
      el('rotationHistoryValue').textContent=number(data.value,0);
      el('rotationHistoryPercentile').textContent=number(data.percentile250D,1)+'%';
      el('rotationHistoryDate').textContent='数据截至 '+data.asOf+' · 日度更新';
      el('rotationHistoryIndex').textContent=number(data.points.at(-1).indexClose,2)+'点';
      draw();
    }catch(error){
      view.payload=null;el('rotationHistoryEmpty').hidden=false;el('rotationHistoryEmpty').textContent='暂无完整行业轮动和中证全指对比数据';
    }
  }
  document.querySelectorAll('[data-rotation-years]').forEach(button=>button.addEventListener('click',()=>{
    view.years=Number(button.dataset.rotationYears);
    document.querySelectorAll('[data-rotation-years]').forEach(item=>{const active=item===button;item.classList.toggle('active',active);item.setAttribute('aria-pressed',String(active));});
    el('rotationHistoryTooltip').hidden=true;draw();
  }));
  el('rotationHistoryChart').addEventListener('pointermove',tooltip);
  el('rotationHistoryChart').addEventListener('pointerdown',tooltip);
  el('rotationHistoryChart').addEventListener('pointerleave',()=>{el('rotationHistoryTooltip').hidden=true;});
  el('refreshButton').addEventListener('click',load);
  window.addEventListener('resize',draw);document.addEventListener('themechange',draw);
  load();
})();
