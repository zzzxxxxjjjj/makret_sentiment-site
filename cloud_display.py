"""Apply explicit cloud-v2 labels and actual observation dates to the saved dashboard."""
import json
from pathlib import Path

def apply_cloud_display(payload,directory):
    base=Path(directory)
    try: cloud=json.loads((base/'cloud-market-inputs.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):return payload
    if cloud.get('modelVersion')!='cloud-v2':return payload
    series={s['id']:s for s in payload.get('series',[])}
    def put(sid,name,unit,points,source):
        series[sid]={'id':sid,'name':name,'unit':unit,'points':points,'source':source,'methodologyVersion':'cloud-v2'}
    replacements={'万得全A':'中证全指','10年国开债':'10年国债','国开债到期收益率':'国债到期收益率','偏债混合型基金指数':'上证国债指数','偏债基金':'上证国债指数'}
    for item in series.values():
        if item['id'].startswith('medium-'):
            for old,new in replacements.items():item['name']=item.get('name','').replace(old,new)
            item['source']=('AKShare中证全指 / iFind 701014.TI；保留历史' if item['id'] in ('medium-equity-bond-position','medium-equity-bond-relative-return-120d','medium-position-score','medium-relative-return-score') else 'AKShare中证全指PE；保留同口径历史' if item['id']=='medium-pe-ttm' else item.get('source','历史模型输入'))
    equity={p['date']:p for p in cloud['inputs']['equity']}
    try: latest=json.loads((base/'akshare-medium-inputs.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):latest={}
    last=max(equity,default='')
    for item in latest.get('series',[]):
        if item.get('id')=='csi-all-share-close':
            equity.update({p['date']:p for p in item.get('points',[]) if p['date']>last})
    put('windall-close-excel','中证全指','点',[equity[d] for d in sorted(equity)],'AKShare中证全指000985；保留同口径历史')
    if series.get('market-turnover',{}).get('points'):
        put('windall-turnover','全A等权换手率','%',series['market-turnover']['points'],'RQData全A个股日换手率等权平均')
    put('new-equity-fund-shares','股票型公募基金新成立数量（20日累计）','只',cloud['fundEstablishment20D'],'RQData基金成立日期；股票型及股票指数型；主代码去重')
    put('land-connect-turnover-ma20','陆股通成交总额MA5','亿元',cloud['northboundMA5'],'港交所沪深北向总成交额（含股票及ETF），MA5')
    # Retire an unsupported legacy fund-index comparator explicitly, without carrying its old daily tail.
    series.pop('partial-equity-fund-index-monthly-return',None)
    try: position=json.loads((base/'rqdata-fund-stock-position-history.json').read_text(encoding='utf-8'))
    except (OSError,ValueError):position={}
    if position.get('points'):
        put('stock-fund-position','股票型基金披露仓位（季频）','%',position['points'],'RQData基金定期报告；普通股票型；净资产加权')
        series['stock-fund-position']['frequency']='quarterly'
    aliases={'institutional-net-buy':('institutional-buy-ma5','机构买入额MA5'),
             'new-equity-fund-shares':('new-equity-fund-shares','股票型公募基金新成立数量'),
             'stock-fund-position':('stock-fund-position','股票型基金披露仓位（季频）')}
    for card in payload.get('cards',[]):
        sid,title=aliases.get(card.get('id'),(None,None))
        if sid and series.get(sid,{}).get('points'):
            item=series[sid];points=item['points'];last=points[-1];history=[p['value'] for p in points[-750:]]
            card.update(title=title,asOf=last['date'],value=last['value'],unit=item['unit'],source=item.get('source','RQData'),
                        description=item.get('source','RQData'),percentile=round(sum(v<=last['value'] for v in history)/len(history)*100,1),submetrics=[])
        if card.get('id')=='medium-term-sentiment':
            card['source']='云端版v2 · 七因子等权；历史按新口径重算'
            for old,new in replacements.items():
                for key in ('description','detail','note'):
                    if isinstance(card.get(key),str):card[key]=card[key].replace(old,new)
    # Existing freshness diagnostics must follow the replacement's actual source dates too.
    for item in payload.get('freshness',{}).get('items',[]):
        sid=item.get('id');canonical=aliases.get(sid,(sid,None))[0]
        current=series.get(canonical,{})
        if current.get('points'):
            actual=current['points'][-1]['date'];quarterly=canonical=='stock-fund-position'
            item.update(name=current.get('name'),asOf=actual,source=current.get('source'),mode='季频披露、每日检查' if quarterly else '云端每日更新',
                        status='periodic' if quarterly else 'current' if actual>=cloud['asOf'] else 'delayed')
    payload['series']=list(series.values())
    payload['methodologyVersion']='cloud-v2';payload['methodologyChanges']=cloud['methodologyChanges']
    payload.setdefault('freshness',{})['delayedCount']=sum(i['status'] not in ('current','periodic') for i in payload.get('freshness',{}).get('items',[]))
    return payload
