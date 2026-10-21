const assert=require('node:assert/strict');
const fs=require('node:fs');
const {validate,scale}=require('../style-crowding-chart.js');
const data=JSON.parse(fs.readFileSync('style-crowding.json','utf8'));
validate(data);
const copy=structuredClone(data);copy.chart.periods[0].values.SIZE=null;assert.throws(()=>validate(copy));
copy.chart.periods[0].values.SIZE=0;copy.chart.periods[1].end=copy.asOf;assert.throws(()=>validate(copy));
for(const values of [[0,0],[-2,-1],[1,2],[-3,4]]){const s=scale(values);assert.ok(s.min<=Math.min(0,...values));assert.ok(s.max>=Math.max(0,...values));assert.ok(s.max>s.min);}
console.log('PASS: three-period chart dates, missing values and positive/negative/zero scale');
