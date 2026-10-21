(function () {
  'use strict';
  const factors=[['VALUE','价值'],['GROWTH','成长'],['PROFIT','盈利能力'],['LIQUIDITY','流动性'],['DIVYILD','股息率'],['SIZE','规模'],['MIDCAP','中盘'],['LEVERAGE','杠杆'],['MOMENTUM','动量'],['BETA','BETA'],['RESVOL','残差波动'],['EARNQLTY','盈利质量'],['EARNVAR','盈利波动'],['INVSQLTY','投资质量'],['LTREVRSL','长期反转'],['Other','民营企业']];
  const colors=['#ff535a','#538fda','#777e89'];
  function validate(data){
    const ps=data?.chart?.periods;
    if(data?.available!==true||data.chart?.method!=='observation-mean'||!/^\d{4}-\d{2}-\d{2}$/.test(data.asOf||'')||!Array.isArray(ps)||ps.length!==3)throw Error('历史拥挤度暂不完整');
    ps.forEach((p,i)=>{if(p.id!==['week','previousWeek','month'][i]||p.count!==[5,5,20][i]||!/^\d{4}-\d{2}-\d{2}$/.test(p.start||'')||!/^\d{4}-\d{2}-\d{2}$/.test(p.end||'')||p.start>p.end||p.end>data.asOf||factors.some(([c])=>!Number.isFinite(p.values?.[c])))throw Error('拥挤度区间未通过校验');});
    if(ps[0].end!==data.asOf||ps[2].end!==data.asOf||ps[1].end>=ps[0].start)throw Error('拥挤度区间日期不一致');return data;
  }
  function scale(values){const min=Math.min(0,...values),max=Math.max(0,...values),step=Math.max(.5,Math.ceil((max-min)/5*2)/2);return{min:Math.floor(min/step)*step,max:Math.max(step,Math.ceil(max/step)*step),step};}
  if(typeof module!=='undefined'&&module.exports){module.exports={validate,scale};return;}
  const el=id=>document.getElementById(id),ns='http://www.w3.org/2000/svg';let request=0;
  function render(data){
    const periods=data.chart.periods,svg=el('crowdingChart');svg.replaceChildren();
    const width=1400,height=390,left=60,right=20,top=28,bottom=80,plotW=width-left-right,plotH=height-top-bottom;
    svg.setAttribute('viewBox',`0 0 ${width} ${height}`);
    function add(tag,attrs,text){const n=document.createElementNS(ns,tag);Object.entries(attrs).forEach(([k,v])=>n.setAttribute(k,v));if(text!==undefined)n.textContent=text;svg.append(n);return n;}
    add('title',{},'风格因子拥挤度：近一周、上一周、近一月的观测均值');
    const s=scale(periods.flatMap(p=>factors.map(([c])=>p.values[c]))),y=v=>top+(s.max-v)/(s.max-s.min)*plotH;
    for(let v=s.min;v<=s.max+1e-8;v+=s.step){add('line',{x1:left,y1:y(v),x2:width-right,y2:y(v),class:v===0?'crowd-zero':'crowd-grid'});add('text',{x:left-10,y:y(v)+4,'text-anchor':'end',class:'crowd-tick'},v.toFixed(1));}
    add('text',{x:left,y:14,class:'crowd-tick'},'拥挤度（标准差）');
    const group=plotW/factors.length,bar=Math.min(19,group/4);
    factors.forEach(([code,name],i)=>{const cx=left+group*(i+.5);
      periods.forEach((p,j)=>{const value=p.values[code],yy=y(value),rect=add('rect',{x:cx+(j-1.5)*bar,y:Math.min(yy,y(0)),width:bar-1,height:Math.max(1,Math.abs(yy-y(0))),fill:colors[j],tabindex:0,role:'img','aria-label':`${name}，${p.label}，${p.start}至${p.end}，${value.toFixed(4)}个标准差`});
        const title=document.createElementNS(ns,'title');title.textContent=`${name} · ${p.label}\n${p.start} → ${p.end}（${p.count}个观测日）\n平均拥挤度 ${value.toFixed(4)}`;rect.append(title);
        for(const event of ['focus','mouseenter','click'])rect.addEventListener(event,()=>{el('crowdingTooltip').textContent=title.textContent;});
      });add('text',{x:cx,y:height-bottom+26,'text-anchor':'middle',class:'crowd-label'},name);
    });
    el('crowdingLegend').replaceChildren();periods.forEach((p,i)=>{const item=document.createElement('span'),swatch=document.createElement('i');swatch.style.background=colors[i];item.append(swatch,document.createTextNode(`${p.label} · ${p.start}—${p.end}`));el('crowdingLegend').append(item);});
    el('crowdingDate').textContent=`截至 ${data.asOf}`;el('crowdingTooltip').textContent='悬停或选中柱形，查看对应因子、日期区间与精确数值。';el('crowdingData').hidden=false;el('crowdingError').hidden=true;
  }
  async function load(){const id=++request;try{const response=await fetch(`/style-crowding.json?t=${Date.now()}`,{cache:'no-store'});if(!response.ok)throw Error('拥挤度数据暂不可用');const data=validate(await response.json());if(id===request)render(data);}catch(error){if(id!==request)return;el('crowdingData').hidden=true;el('crowdingError').hidden=false;el('crowdingError').textContent=error.message+'，请稍后重新读取。';el('crowdingDate').textContent='数据暂不可用';}}
  el('refreshButton').addEventListener('click',load);load();
})();
