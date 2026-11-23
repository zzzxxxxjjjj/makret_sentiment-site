import json, math, os, urllib.request
from pathlib import Path
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
def post(endpoint, headers, body):
    request = urllib.request.Request(
        'https://quantapi.51ifind.com/api/v1/' + endpoint,
        data=json.dumps(body).encode(),
        headers={'Content-Type': 'application/json', **headers},
        method='POST')
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)
secret = os.environ.get('IFIND_REFRESH_TOKEN')
if not secret:
    raise SystemExit('Secret unavailable')
auth = post('get_access_token', {'refresh_token': secret}, {})
token = auth.get('data', {}).get('access_token') if isinstance(auth.get('data'), dict) else None
if not token:
    raise SystemExit(f"Authentication failed, code {auth.get('errorcode')}")
now = datetime.now(ZoneInfo('Asia/Shanghai'))
end = datetime.fromisoformat(os.environ['DAILY_TARGET_DATE']).date() if os.environ.get('DAILY_TARGET_DATE') else now.date() - timedelta(days=int(now.hour < 18))
path = Path('ifind-index-turnover.json')
previous_payload = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
previous_series = {s['id']: s for s in previous_payload.get('series', [])}
last_dates = [s['points'][-1]['date'] for s in previous_series.values() if s.get('points')]
start = end - timedelta(days=1825)
if len(last_dates) == 3:
    start = datetime.fromisoformat(min(last_dates)).date() + timedelta(days=1)
if start > end:
    raise SystemExit(0)
result = post('cmd_history_quotation', {'access_token': token}, {
    'codes': '000300.SH,000852.SH,000688.SH',
    'indicators': 'turnoverRatio',
    'startdate': str(start),
    'enddate': str(end),
    'functionpara': {'Fill': 'Omit'},
})
print('Provider status:', result.get('errorcode'))
series = {}
names = {'000300.SH': ('hs300-turnover', '沪深300换手率'), '000852.SH': ('csi1000-turnover', '中证1000换手率'), '000688.SH': ('star50-turnover', '科创50换手率')}
if result.get('errorcode') != 0:
    raise SystemExit('iFinD request failed')
for table in result.get('tables') or []:
    values = (table.get('table') or {}).get('turnoverRatio') or []
    dates = table.get('time') or []
    code = table.get('thscode')
    if code not in names:
        continue
    observations = {d[:10]: v for d, v in zip(dates, values)
                    if type(v) in (float, int) and math.isfinite(v) and 0 <= v <= 100}
    sid, name = names[code]
    observations = {**{p['date']: p['value'] for p in previous_series.get(sid, {}).get('points', [])}, **observations}
    if len(observations) < 126 or not any(observations.values()):
        raise SystemExit('Incomplete turnover history: ' + code)
    sid, name = names[code]
    series[code] = dict(id=sid, name=name, unit='%', source='iFinD / 历史日换手率',
                        points=[dict(date=d, value=v) for d,v in sorted(observations.items())])
    print(code, len(observations), max(observations), observations[max(observations)])
if series.keys() != names.keys() or len({s['points'][-1]['date'] for s in series.values()}) != 1:
    raise SystemExit('Incomplete or mismatched index turnover coverage')
path = Path('ifind-index-turnover.json')
if path.exists():
    previous = {s['id']: s['points'][-1]['date'] for s in json.loads(path.read_text(encoding='utf-8'))['series']}
    if any(s['points'][-1]['date'] < previous.get(s['id'], '') for s in series.values()):
        raise SystemExit('Refusing date rollback')
path.write_text(json.dumps(dict(series=list(series.values())), ensure_ascii=False), encoding='utf-8')
