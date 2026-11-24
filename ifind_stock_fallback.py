"""Exact-date iFind semantic snapshot for AKShare source failures."""
import json, math
from pathlib import Path
from ifind_client import Client
ROOT=Path(__file__).resolve().parent

def parse(result,target):
    suffix="["+target.replace("-","")+"]"
    expected={"成交额"+suffix:"成交额","换手率"+suffix:"换手率","主力资金流向"+suffix:"今日主力净流入-净额"}
    rows=[]
    for table in result.get("tables") or []:
        data=table.get("table") or {}
        codes=data.get("股票代码") or []
        if not set(expected)<=set(data):raise ValueError("Missing exact-date iFind columns")
        if any(len(data[k])!=len(codes) for k in expected):raise ValueError("Mismatched iFind columns")
        for i,code in enumerate(codes):
            row={"代码":str(code).split(".")[0]}
            for key,name in expected.items():
                try:v=float(data[key][i])
                except (ValueError,TypeError):v=None
                row[name]=v if v is not None and math.isfinite(v) else None
            rows.append(row)
    if len(rows)<4000 or len({r["代码"] for r in rows})!=len(rows):raise ValueError("Incomplete iFind A-share coverage")
    if sum(r["今日主力净流入-净额"] is not None for r in rows)<4000:raise ValueError("Incomplete dated main-flow coverage")
    return rows

def collect(target):
    path=ROOT/"ifind-stock-snapshot.json"
    if path.exists():
        old=json.loads(path.read_text(encoding="utf-8"))
        if old.get("asOf")==target:return old["rows"]
    result=Client().post("smart_stock_picking",dict(searchstring=target.replace("-","年",1).replace("-","月",1)+"日A股成交额、换手率、主力资金流向",searchtype="stock"))
    rows=parse(result,target)
    temporary=path.with_suffix(".tmp")
    temporary.write_text(json.dumps(dict(asOf=target,source="iFind问财；成交额元、换手率%、主力资金流向元；日期字段严格匹配",rows=rows),ensure_ascii=False,allow_nan=False),encoding="utf-8")
    temporary.replace(path)
    return rows
