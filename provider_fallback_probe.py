"""Read-only checks for provider fallback fields; no production writes."""
import json
from ifind_client import Client
client=Client()
cases=[
 ("etf_quotes","cmd_history_quotation",dict(codes="510300.SH,159919.SZ",indicators="close,amount,changeRatio",startdate="2026-11-18",enddate="2026-11-23",functionpara={"Fill":"Omit"})),
 ("etf_shares","cmd_history_quotation",dict(codes="510300.SH,159919.SZ",indicators="totalShares",startdate="2026-11-18",enddate="2026-11-23",functionpara={"Fill":"Omit"})),
 ("sw_flow_history","cmd_history_quotation",dict(codes="801010.SL",indicators="mainNetInflow",startdate="2026-11-23",enddate="2026-11-23",functionpara={"Fill":"Omit"})),
 ("stock_flow_history","cmd_history_quotation",dict(codes="600000.SH",indicators="mainNetInflow",startdate="2026-11-23",enddate="2026-11-23",functionpara={"Fill":"Omit"})),
]
for name,path,body in cases:
    try:
        result=client.post(path,body)
        print("FALLBACK="+json.dumps(dict(case=name,ok=True,tables=result.get("tables"),datatype=result.get("datatype")),ensure_ascii=False),flush=True)
    except Exception as exc:
        print("FALLBACK="+json.dumps(dict(case=name,ok=False,error=str(exc)),ensure_ascii=False),flush=True)
