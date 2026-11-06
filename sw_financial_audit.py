"""Audit original financial inputs; never substitute PE-implied or adjusted ROE."""
import json
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT=Path(__file__).resolve().parent


def main():
    import akshare as ak
    import requests
    original=requests.sessions.Session.request
    def bounded(self,method,url,**kwargs):
        kwargs['timeout']=20
        return original(self,method,url,**kwargs)
    requests.sessions.Session.request=bounded
    samples=[]
    for code in ['SH600519','SH600036','SZ300750']:
        row=dict(code=code)
        for key,fn in [('profit',ak.stock_profit_sheet_by_report_em),('balance',ak.stock_balance_sheet_by_report_em)]:
            try:
                frame=fn(symbol=code)
                cols=list(map(str,frame.columns))
                candidates=[c for c in cols if ('PARENT' in c and ('PROFIT' in c or 'EQUITY' in c)) or 'NOTICE' in c or c=='REPORT_DATE']
                row[key]=dict(rows=len(frame),fields=candidates,
                    reports=sorted(set(str(d)[:10] for d in frame.get('REPORT_DATE',[])))[-8:],
                    hasDisclosureDate='NOTICE_DATE' in cols)
            except Exception as exc:row[key]=dict(errorType=type(exc).__name__,message=str(exc)[:160])
        samples.append(row)
        print(json.dumps(row,ensure_ascii=True),flush=True)
    report=dict(checkedAt=datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(),source='AKShare / 东方财富原始财务报表',
        status='sample_audit_only_not_production_approved',samples=samples,
        requirements=['普通归母净利润TTM，非扣非、非加权累计年化ROE','归母权益及原ROE平均权益定义','历史披露时间与修订版本','原行业账面净资产加权口径、足够历史样本及30行业覆盖'],
        note='抽样字段可用不等于全市场历史口径已通过核验；没有使用PB/PE代理值，未替换原PB-ROE图。')
    p=ROOT/'sw-financial-audit.json';p.write_text(json.dumps(report,ensure_ascii=False,allow_nan=False,indent=2),encoding='utf-8')


if __name__=='__main__':main()
