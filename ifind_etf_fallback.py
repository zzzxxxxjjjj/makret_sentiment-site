"""iFind fallback for verified ETF quotation fields, never substitute stale shares."""
import json, math
from datetime import datetime, timezone
from ifind_client import Client

def number(value):
    return type(value) in (int,float) and math.isfinite(value)

def decode(result, expected, target):
    found={}
    for table in result.get("tables") or []:
        code=table.get("thscode")
        if code not in expected:continue
        dates=table.get("time") or []
        if target not in dates:raise ValueError("iFind ETF target date missing: "+code)
        i=dates.index(target);values=table.get("table") or {}
        def field(name):
            rows=values.get(name) or []
            return rows[i] if i<len(rows) else None
        close,amount,change=field("close"),field("amount"),field("changeRatio")
        if not number(close) or close<=0 or not number(amount) or amount<0:
            raise ValueError("iFind ETF quote fields missing: "+code)
        if code in found:raise ValueError("Duplicate ETF quotation")
        found[code]=dict(code=code.split(".")[0],name=expected[code],close=close,amount=amount/1e8,
                         change=change if number(change) else None,asOf=target,shares=None)
    if set(found)!=set(expected):raise ValueError("Incomplete iFind ETF quotation coverage")
    return list(found.values())

def collect(previous,target,client=None):
    expected={}
    for row in previous.get("rows",[]):
        code=row["code"]
        suffix="SH" if code.startswith(("5","6")) else "SZ"
        expected[code+"."+suffix]=row.get("name",code)
    if len(expected)<100:raise ValueError("Verified ETF universe unavailable")
    client=client or Client()
    rows=[]
    codes=sorted(expected)
    for offset in range(0,len(codes),80):
        batch=codes[offset:offset+80]
        result=client.post("cmd_history_quotation",dict(codes=",".join(batch),indicators="close,amount,changeRatio",
                    startdate=target,enddate=target,functionpara={"Fill":"Omit"}))
        rows.extend(decode(result,{c:expected[c] for c in batch},target))
    return dict(available=True,asOf=target,generatedAt=datetime.now(timezone.utc).isoformat(),
                source="iFind / 历史行情；原ETF清单，成交额人民币亿元",rows=rows,sharesAvailable=False,
                universeDate=previous.get("universeDate") or previous.get("asOf"),
                note="AKShare失败后的iFind行情兜底；保留原ETF清单，未获取份额，未推算净申赎。")
