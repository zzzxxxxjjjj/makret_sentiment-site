'use strict';
(async () => {
 const host=document.getElementById('weeklyFlowChart'), controls=document.getElementById('weeklyFlowControls'), note=document.getElementById('weeklyFlowNote');
 try {
 const response=await fetch('/etf-weekly-relative-flow.json',{cache:'no-store'});
 if(!response.ok) throw Error('历史数据尚未生成');
 const data=await response.json(), selected=new Set(), colors=['#c74848','#4479bc','#b88b30','#398779','#9a61ab','#e47c40','#6b8095'];
 const items=data.series||[];
 note.textContent=data.formula+'。'+data.note;
 function render(){
   host.replaceChildren();
   const active=items.filter(s=>selected.has(s.code)&&s.points.length);
   if(!active.length){host.textContent='请选择有完整基准数据的ETF。当前可画 '+items.filter(s=>s.available).length+' / '+items.length+' 只；缺失历史不以0填补。';return;}
   const dates=[...new Set(active.flatMap(s=>s.points.map(p=>p.date)))].sort(), values=active.flatMap(s=>s.points.map(p=>p.value));
   const lo=Math.min(0,...values),hi=Math.max(1,...values),w=1000,h=360,px=65,py=30;
   const x=d=>px+(dates.length===1?0:dates.indexOf(d)/(dates.length-1))*(w-px-25),y=v=>h-py-(v-lo)/(hi-lo)*(h-2*py);
   const ns='http://www.w3.org/2000/svg', svg=document.createElementNS(ns,'svg');
   svg.setAttribute('viewBox','0 0 '+w+' '+h);svg.setAttribute('role','img');svg.setAttribute('aria-label','每周累计净流入除以基准规模');
   function add(tag,attrs,text){const e=document.createElementNS(ns,tag);for(const [k,v] of Object.entries(attrs))e.setAttribute(k,v);if(text!==undefined)e.textContent=text;svg.append(e);return e;}
   for(let i=0;i<=4;i++){const v=lo+(hi-lo)*i/4;add('line',{x1:px,x2:w-25,y1:y(v),y2:y(v),stroke:'#ddd'});add('text',{x:5,y:y(v)+4,'font-size':12,fill:'#666'},v.toFixed(1)+'%');}
   active.forEach((s,i)=>{const color=colors[i%colors.length];add('path',{d:s.points.map((p,j)=>(j?'L':'M')+x(p.date)+','+y(p.value)).join(' '),fill:'none',stroke:color,'stroke-width':2});const label=document.createElement('span');label.style.color=color;label.textContent=s.code+' '+s.name+'（'+s.points.at(-1).value.toFixed(2)+'%） ';host.append(label);});
   add('text',{x:px,y:h-4,'font-size':12,fill:'#666'},dates[0]);add('text',{x:w-110,y:h-4,'font-size':12,fill:'#666'},dates.at(-1));
   svg.style.width='100%';host.append(svg);
 }
 items.forEach(s=>{const label=document.createElement('label'), input=document.createElement('input');input.type='checkbox';input.disabled=!s.available;if(s.available&&selected.size<4){input.checked=true;selected.add(s.code);}label.title=s.reason||'';label.style.marginRight='12px';label.style.display='inline-block';label.style.marginBottom='8px';label.append(input,document.createTextNode(s.code+' '+s.name+(s.available?'':'（待补历史）')));input.addEventListener('change',()=>{input.checked?selected.add(s.code):selected.delete(s.code);render();});controls.append(label);});render();
 } catch(e){host.textContent='历史数据暂不可用：'+e.message;}
})();
