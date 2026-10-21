(function () {
  'use strict';
  const factors=[['book_to_price','价值（B/P）'],['growth','成长'],['profitability','盈利能力'],['liquidity','流动性'],['dividend_yield','股息率'],['size','规模'],['mid_cap','中盘'],['leverage','杠杆'],['momentum','动量'],['beta','BETA'],['residual_volatility','残差波动'],['earnings_quality','盈利质量'],['earnings_variability','盈利波动'],['investment_quality','投资质量'],['longterm_reversal','长期反转'],['earnings_yield','盈利收益率']];
  const colors=['#ff535a','#538fda','#777e89'];
  function validate(data){
    const ps=data?.chart?.periods;
    if(data?.available!==true||data.model!=='v2'||data.method!=='implicit'||data.universe!=='whole_market'||data.chart?.method!=='factor-return-sum'||!/^\d{4}-\d{2}-\d{2}$/.test(data.asOf||'')||!Array.isArray(ps)||ps.length!==3)throw Error('历史因子收益暂不完整');
    ps.forEach((p,i)=>{if(p.id!==['week','previousWeek','month'][i]||p.count!==[5,5,20][i]||!/^\d{4}-\d{2}-\d{2}$/.test(p.start||'')||!/^\d{4}-\d{2}-\d{2}$/.test(p.end||'')||p.start>p.end||p.end>data.asOf||factors.some(([c])=>!Number.isFinite(p.values?.[c])))throw Error('因子收益区间未通过校验');});
    if(ps[0].end!==data.asOf||ps[2].end!==data.asOf||ps[1].end>=ps[0].start)throw Error('因子收益区间日期不一致');return data;
  }
  function scale(values){const min=Math.min(0,...values),max=Math.max(0,...values),step=Math.max(.5,Math.ceil((max-min)/5*2)/2);return{min:Math.floor(min/step)*step,max:Math.max(step,Math.ceil(max/step)*step),step};}
  if(typeof module!=='undefined'&&module.exports){module.exports={validate,scale};return;}
  const el=id=>document.getElementById(id),ns='http://www.w3.org/2000/svg';let request=0;
  function render(data){
    const periods=data.chart.periods,svg=el('factorReturnsChart');svg.replaceChildren();
    const width=1400,height=390,left=60,right=20,top=28,bottom=80,plotW=width-left-right,plotH=height-top-bottom;
    svg.setAttribute('viewBox',`0 0 ${width} ${height}`);
    function add(tag,attrs,text){const n=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v));if(text!==undefined)n.textContent=text;svg.append(n);return n;}
    add('title',{},'风格因子超额收益：近一周、上一周、近一月的日因子收益累加');
    const s=scale(periods.flatMap(p=>factors.map(([c])=>p.values[c]))),y=v=>top+(s.max-v)/(s.max-s.min)*plotH;
    for(let v=s.min;v<=s.max+1e-8;v+=s.step){add('line',{x1:left,y1:y(v),x2:width-right,y2:y(v),class:v===0?'crowd-zero':'crowd-grid'});add('text',{x:left-10,y:y(v)+4,'text-anchor':'end',class:'crowd-tick'},v.toFixed(1)+'%');}
    add('text',{x:left,y:14,class:'crowd-tick'},'因子收益（%）');
    const group=plotW/factors.length,bar=Math.min(19,group/4);
    factors.forEach(([code,name],i)=>{const cx=left+group*(i+.5);
      periods.forEach((p,j)=>{const value=p.values[code],yy=y(value),rect=add('rect',{x:cx+(j-1.5)*bar,y:Math.min(yy,y(0)),width:bar-1,height:Math.max(1,Math.abs(yy-y(0))),fill:colors[j],tabindex:0,role:'img','aria-label':`${name}，${p.label}，${p.start}至${p.end}，${value.toFixed(4)}%`});
        const title=document.createElementNS(ns,'title');title.textContent=`${name} · ${p.label}\n${p.start} → ${p.end}（${p.count}个观测日）\n累计因子收益 ${value.toFixed(4)}%`;rect.append(title);
        for(const event of ['focus','mouseenter','click'])rect.addEventListener(event,()=>{el('factorReturnsTooltip').textContent=title.textContent;});
      });add('text',{x:cx,y:height-bottom+26,'text-anchor':'middle',class:'crowd-label'},name);
    });
    el('factorReturnsLegend').replaceChildren();periods.forEach((p,i)=>{const item=document.createElement('span'),swatch=document.createElement('i');swatch.style.background=colors[i];item.append(swatch,document.createTextNode(`${p.label} · ${p.start}—${p.end}`));el('factorReturnsLegend').append(item);});
    el('factorReturnsDate').textContent=`截至 ${data.asOf}`;el('factorReturnsTooltip').textContent='悬停或选中柱形，查看对应因子、日期区间与精确数值。';el('factorReturnsData').hidden=false;el('factorReturnsError').hidden=true;
  }
  async function load(){const id=++request;try{const response=await fetch(`/style-factor-returns.json?t=${Date.now()}`,{cache:'no-store'});if(!response.ok)throw Error('因子收益数据暂不可用');const data=validate(await response.json());if(id===request)render(data);}catch(error){if(id!==request)return;el('factorReturnsData').hidden=true;el('factorReturnsError').hidden=false;el('factorReturnsError').textContent=error.message+'，请稍后重新读取。';el('factorReturnsDate').textContent='数据暂不可用';}}
  el('refreshButton').addEventListener('click',load);load();
})();

