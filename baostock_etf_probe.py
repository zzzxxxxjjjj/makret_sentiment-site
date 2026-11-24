"""Read-only Baostock ETF coverage check."""
import json,socket,time
from pathlib import Path
import baostock as bs
socket.setdefaulttimeout(20)
target=json.loads(Path("data-freshness.json").read_text(encoding="utf-8"))["targetDate"]
start=time.monotonic()
login=bs.login()
print("BAO_LOGIN="+json.dumps(dict(code=login.error_code,message=login.error_msg)),flush=True)
if login.error_code!="0":raise SystemExit("Baostock login failed")
try:
    result=bs.query_daily_history_k_ETF(date=target)
    print("BAO_QUERY="+json.dumps(dict(code=result.error_code,message=result.error_msg,fields=result.fields)),flush=True)
    rows=[]
    while result.error_code=="0" and result.next():
        rows.append(dict(zip(result.fields,result.get_row_data())))
    print("BAO_RESULT="+json.dumps(dict(target=target,rows=len(rows),elapsed=round(time.monotonic()-start,2),
        sample=[r for r in rows if r.get("code") in ("sz.159528","sh.510300","sz.159919","sh.588000")]),ensure_ascii=False),flush=True)
finally:bs.logout()
