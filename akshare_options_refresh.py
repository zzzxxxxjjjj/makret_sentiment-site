"""Exchange-reported ETF option PCR; retain history and never infer missing sides."""
import json, math, os
from pathlib import Path
import akshare as ak

ROOT=Path(__file__).resolve().parent
CODES={"510050":"sz50","510300":"hs300","588000":"star50"}
def observations(frame, target):
    result={}
    for row in frame.to_dict("records"):
        code=str(row["合约标的代码"]).split(".")[0]
        if code not in CODES:continue
        day=str(row["交易日"])[:10]
        if day.replace("-","")!=target.replace("-",""):raise ValueError("Unexpected exchange session")
        for metric,call,put in (
            ("volume","认购成交量","认沽成交量"),
            ("oi","未平仓认购合约数","未平仓认沽合约数")):
            a,b=float(row[call]),float(row[put])
            if not all(math.isfinite(v) and v>=0 for v in (a,b)) or a<=0:raise ValueError("Invalid option side totals")
            sid=f"pcr-{metric}-{CODES[code]}"
            if sid in result:raise ValueError("Duplicate underlying")
            result[sid]={"date":target,"value":round(b/a,6)}
    if len(result)!=6:raise ValueError("Incomplete exchange underlying coverage")
    return result

def main():
    import requests
    original=requests.sessions.Session.request
    def bounded(self,method,url,**kwargs):
        kwargs["timeout"]=(10,35)
        return original(self,method,url,**kwargs)
    requests.sessions.Session.request=bounded
    target=os.environ["DAILY_TARGET_DATE"]
    calendar=json.loads((ROOT/"data-freshness.json").read_text())["tradingCalendar"]
    days=[d for d in calendar if d<=target][-3:]
    if not days or days[-1]!=target:raise ValueError("Target not in verified calendar")
    path=ROOT/"akshare-options-pcr.json"
    old=json.loads(path.read_text()) if path.exists() else {"series":[]}
    series={s["id"]:s for s in old["series"]}
    for day in days:
        values=observations(ak.option_daily_stats_sse(date=day.replace("-","")),day)
        for sid,point in values.items():
            item=series.setdefault(sid,{"id":sid,"unit":"倍","points":[]})
            points={p["date"]:p for p in item["points"]}
            points[day]=point
            item.update(points=[points[d] for d in sorted(points)],source="AKShare / 上交所期权每日统计")
    output={"asOf":target,"source":"AKShare / 上交所期权每日统计","series":list(series.values())}
    tmp=path.with_suffix(".tmp")
    tmp.write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding="utf-8")
    tmp.replace(path)
    print("ETF option PCR updated through",target)
if __name__=="__main__":
    from akshare_request_policy import install
    install()
    main()
