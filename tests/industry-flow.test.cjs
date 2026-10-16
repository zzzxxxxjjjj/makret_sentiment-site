const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('industry-flow-trend.js', 'utf8');
const sandbox = { state: { industries: [] }, window: {}, document: { querySelectorAll: () => [] }, el: () => ({ addEventListener() {} }) };
vm.createContext(sandbox);
vm.runInContext(source, sandbox);
const evaluate = code => vm.runInContext(code, sandbox);
const dates = Array.from({ length: 20 }, (_, i) => `2026-09-${String(i + 1).padStart(2, '0')}`);
sandbox.state.industries = [{ code: 'A', name: '行业A', series: dates.map((date, i) => ({ date, netFlow: i + 1, marginActivity: 10, amountShare: 5 })) }];
let row = evaluate('buildFlowModel().items[0]');
assert.equal(row.day, 20);
assert.equal(row.week, 90);
assert.equal(row.month, 210);
evaluate("flowTrend.metric = 'marginActivity'");
row = evaluate('buildFlowModel().items[0]');
assert.equal(row.week, 10);
assert.equal(row.month, 10);
for (const missing of [null, undefined, '', ' ', NaN]) {
  sandbox.value = missing;
  assert.equal(evaluate('flowNumber(value)'), null);
}
assert.equal(evaluate('flowNumber(0)'), 0);
sandbox.state.industries[0].series.at(-1).marginActivity = null;
row = evaluate('buildFlowModel().items[0]');
assert.equal(row.day, null);
assert.equal(row.week, null);
assert.equal(row.month, null);
sandbox.state.industries.push({ code: 'B', name: '旧数据', series: dates.slice(0, -1).map(date => ({ date, netFlow: 100 })) });
evaluate("flowTrend.metric = 'netFlow'");
assert.equal(evaluate("buildFlowModel().items.find(row => row.code === 'B').day"), null);
sandbox.state.industries = [{ code: 'C', name: '短历史', series: dates.slice(-4).map(date => ({ date, netFlow: -2 })) }];
row = evaluate('buildFlowModel().items[0]');
assert.equal(row.day, -2);
assert.equal(row.week, null);
assert.equal(row.month, null);
console.log('PASS: cumulative flows, mean ratios, missing/zero values, aligned dates and short histories');
// 日/周/月必须按各自数值独立排序，不能复用日度名次。
sandbox.rankingItems = [
 { code: 'A', day: 20, week: -3, month: 2 },
 { code: 'B', day: 10, week: 30, month: -5 },
 { code: 'C', day: -1, week: 0, month: 100 },
 { code: 'D', day: null, week: null, month: null }
];
assert.equal(evaluate("rankFlowItems(rankingItems, 'day').map(row => row.code).join(',')"), 'A,B,C,D');
assert.equal(evaluate("rankFlowItems(rankingItems, 'week').map(row => row.code).join(',')"), 'B,C,A,D');
assert.equal(evaluate("rankFlowItems(rankingItems, 'month').map(row => row.code).join(',')"), 'C,A,B,D');
assert.equal(sandbox.rankingItems.map(row => row.code).join(','), 'A,B,C,D');
console.log('PASS: independent daily/weekly/monthly rankings, negatives/zero, missing values last, source order retained');
