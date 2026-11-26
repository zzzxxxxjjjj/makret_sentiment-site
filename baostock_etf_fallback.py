"""Baostock ETF daily-batch fallback; no shares inferred from turnover."""
import json,math,subprocess,sys
from pathlib import Path
from datetime import datetime,timezone
ROOT=Path(__file__).resolve().parent

def finite(value):
    if isinstance(value,bool):return None
    try:value=float(value)
    except (ValueError,TypeError):return None
    return value if math.isfinite(value) else None

def build(records,previous,target,exceptions):
    names={r["code"]:r.get("name",r["code"]) for r in previous.get("rows",[])+previous.get("unavailableRows",[])}
    inactive={code:entry for code,entry in exceptions.items() if entry.get("inactiveFrom","9999")<=target}
    expected=set(names)-set(inactive)
    if not expected:raise ValueError("No verified active ETF universe")
    found={}
    for row in records:
        code=str(row.get("code","")).split(".")[-1]
        if code not in expected:continue
        if row.get("date")!=target:raise ValueError("Baostock ETF date mismatch: "+code)
        if row.get("adjustflag","3")!="3":raise ValueError("Unadjusted ETF prices required")
        close,amount=finite(row.get("close")),finite(row.get("amount"))
        if close is None or close<=0 or amount is None or amount<0:raise ValueError("Invalid Baostock ETF fields: "+code)
        if code in found:raise ValueError("Duplicate Baostock ETF: "+code)
        found[code]=dict(code=code,name=names[code],asOf=target,close=close,amount=amount/1e8,
                         change=finite(row.get("pctChg")),shares=None)
    missing=expected-found.keys()
    if missing:
        from etf_net_subscription_refresh import TARGET
        required=set(TARGET)-set(inactive)
        if not set(TARGET)<=set(names) or not required<=set(found):
            raise ValueError("Missing active Baostock ETFs: "+",".join(sorted(missing)))
    archived={r["code"]:r for r in previous.get("inactiveRows",[])}
    for row in previous.get("rows",[]):
        if row["code"] in inactive:
            archived[row["code"]]={**row,"tradingStatus":inactive[row["code"]]["status"],
                                  "statusEvidence":inactive[row["code"]]}
    return dict(available=True,asOf=target,generatedAt=datetime.now(timezone.utc).isoformat(),
        source="Baostock / ETF日线批量；不复权价格、成交额人民币亿元",
        rows=[found[c] for c in sorted(found)],inactiveRows=list(archived.values()),
        sharesAvailable=False,providerUniverseCount=len(records),activeCoverage=len(found),
        expectedCoverage=len(expected),partialUniverse=bool(missing),unavailableCodes=sorted(missing),
        unavailableRows=[r for r in previous.get("rows",[])+previous.get("unavailableRows",[]) if r["code"] in missing],
        note=("23只展示用重点ETF全部核验为同日行情；其他缺失ETF保留旧日期，不记零、不计入当前合计。" if missing else "AKShare失败后的Baostock历史日线兜底；原ETF清单全部在交易标的校验通过。公告确认停牌清算标的保留历史，不要求每日交易行情；份额未提供，净申赎未推算。"))

def collect(previous,target):
    if len(previous.get("rows",[]))<100:raise ValueError("Verified ETF universe unavailable")
    completed=subprocess.run([sys.executable,str(Path(__file__).resolve()),target],capture_output=True,text=True,timeout=150)
    if completed.returncode:raise RuntimeError("Baostock worker failed: "+(completed.stderr or completed.stdout)[-600:])
    lines=[line[len("BAOSTOCK_ETF="):] for line in completed.stdout.splitlines() if line.startswith("BAOSTOCK_ETF=")]
    if len(lines)!=1:raise ValueError("Baostock worker returned no verified batch")
    data=json.loads(lines[0])
    exceptions=json.loads((ROOT/"etf-trading-exceptions.json").read_text(encoding="utf-8"))
    payload=build(data["rows"],previous,target,exceptions)
    print("Baostock ETF batch: "+str(payload["activeCoverage"])+" active, "+str(len(payload["inactiveRows"]))+" inactive, target="+target,flush=True)
    return payload

def worker(target):
    import socket
    import baostock as bs
    socket.setdefaulttimeout(20)
    login=bs.login()
    if login.error_code!="0":raise RuntimeError("Baostock login code "+login.error_code)
    try:
        result=bs.query_daily_history_k_ETF(date=target)
        if result.error_code!="0":raise RuntimeError("Baostock query code "+result.error_code)
        rows=[]
        while result.error_code=="0" and result.next():
            rows.append(dict(zip(result.fields,result.get_row_data())))
        if result.error_code!="0":raise RuntimeError("Incomplete Baostock batch: "+result.error_code)
        print("BAOSTOCK_ETF="+json.dumps(dict(rows=rows),ensure_ascii=False),flush=True)
    finally:bs.logout()
if __name__=="__main__":worker(sys.argv[1])
