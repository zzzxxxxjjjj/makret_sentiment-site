const assert=require('node:assert/strict');const fs=require('node:fs');
const {validate}=require('../style-factor-returns.js');
const data=JSON.parse(fs.readFileSync('style-factor-returns.json','utf8'));validate(data);
const bad=structuredClone(data);bad.method='explicit';assert.throws(()=>validate(bad));bad.method='implicit';bad.chart.periods[0].values.size=null;assert.throws(()=>validate(bad));
console.log('PASS: return schema, model/method and missing data guards');
