"""Read-only source capability audit; never writes production data."""
import json, subprocess, sys

CASES = [
 ("margin_sh", "ak", "stock_margin_sse", {"start_date":"20261119","end_date":"20261120"}),
 ("margin_sz", "ak", "stock_margin_szse", {"date":"20261120"}),
 ("lhb_detail", "ak", "stock_lhb_detail_em", {"start_date":"20261102","end_date":"20261120"}),
 ("lhb_institution", "ak", "stock_lhb_jgmmtj_em", {"start_date":"20261102","end_date":"20261120"}),
 ("sw_daily", "ak", "index_analysis_daily_sw", {"symbol":"一级行业","start_date":"20261120","end_date":"20261120"}),
 ("option_sse", "ak", "option_daily_stats_sse", {"date":"20261120"}),
 ("option_szse", "ak", "option_daily_stats_szse", {"date":"20261120"}),
 ("ifind_market", "ifind", "cmd_history_quotation", {"codes":"881001.TI","indicators":"close,amount,turnoverRatio","startdate":"2026-11-20","enddate":"2026-11-20","functionpara":{"Fill":"Omit"}}),
 ("ifind_margin_configured", "ifind", "cmd_history_quotation", {"codes":"881001.TI","indicators":"margin_balance,margin_buy_amount","startdate":"2026-11-20","enddate":"2026-11-20","functionpara":{"Fill":"Omit"}}),
]
def child(case):
    key,provider,name,kwargs=case
    if provider=="ifind":
        from ifind_client import Client
        data=Client().post(name,kwargs)
        tables=data.get("tables") or []
        print("PROBE="+json.dumps({"id":key,"ok":True,"tables":tables},ensure_ascii=False,default=str))
        return
    import akshare as ak
    import requests,re
    original=requests.sessions.Session.request
    def bounded(self,method,url,**kw):
        kw.setdefault("timeout",(5,15))
        return original(self,method,url,**kw)
    requests.sessions.Session.request=bounded
    try: func=getattr(ak,name)
    except AttributeError as exc:
        match=re.search(r"改用 ak\.([A-Za-z_0-9]+)",str(exc))
        if not match: raise
        name=match.group(1);func=getattr(ak,name)
    frame=func(**kwargs)
    print("PROBE="+json.dumps({"id":key,"ok":True,"interface":name,"rows":len(frame),"columns":list(frame.columns),"sample":frame.head(2).to_dict("records"),"tail":frame.tail(1).to_dict("records")},ensure_ascii=False,default=str))
if __name__=="__main__":
    if len(sys.argv)>1:
        case=CASES[int(sys.argv[1])]
        try: child(case)
        except Exception as exc:
            print("PROBE="+json.dumps({"id":case[0],"ok":False,"errorType":type(exc).__name__,"error":str(exc)[:500]},ensure_ascii=False))
    else:
        for i,case in enumerate(CASES):
            try:
                done=subprocess.run([sys.executable,__file__,str(i)],capture_output=True,text=True,timeout=45)
                lines=[line for line in done.stdout.splitlines() if line.startswith("PROBE=")]
                print(lines[-1] if lines else "PROBE="+json.dumps({"id":case[0],"ok":False,"error":"No structured response"}),flush=True)
            except subprocess.TimeoutExpired:
                print("PROBE="+json.dumps({"id":case[0],"ok":False,"error":"45 second timeout"}),flush=True)
