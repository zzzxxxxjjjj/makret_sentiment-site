"""Institution-only buying disclosed on single-day Dragon Tiger lists."""
from datetime import timedelta
import pandas as pd

SERIES_IDS = {'institutional-buy', 'institutional-buy-ma5'}


def daily_institutional_buy(details, events, dates):
    """Exclude cumulative lists and avoid counting the same seat on both sides."""
    dates = pd.Index(pd.to_datetime(dates).date)
    daily = pd.Series(0.0, index=dates)
    if events.empty:
        return daily
    required = {'order_book_id', 'date', 'type', 'abnormal_s_date', 'abnormal_e_date'}
    if not required.issubset(events.columns):
        raise ValueError('Abnormal-stock dates/period fields are missing')
    eligible = events.copy()
    for col in ['date', 'abnormal_s_date', 'abnormal_e_date']:
        eligible[col] = pd.to_datetime(eligible[col]).dt.date
    eligible = eligible[eligible.abnormal_s_date == eligible.abnormal_e_date]
    if eligible.empty:
        return daily
    if details.empty:
        raise ValueError('Missing transaction details for disclosed daily lists')
    required = {'order_book_id', 'date', 'type', 'agency', 'side', 'rank', 'buy_value', 'sell_value'}
    if not required.issubset(details.columns):
        raise ValueError('Institutional transaction detail fields are missing')
    data = details.copy()
    data['date'] = pd.to_datetime(data['date']).dt.date
    data = data.merge(eligible[['order_book_id', 'date', 'type']].drop_duplicates(),
                      on=['order_book_id', 'date', 'type'], how='inner')
    data = data[data.agency.astype(str).str.strip().eq('机构专用')
                & data.side.astype(str).str.lower().isin(['buy', 'sell'])].copy()
    if data.empty:
        return daily
    for col in ['buy_value', 'sell_value']:
        data[col] = pd.to_numeric(data[col], errors='coerce')
    # Shanghai disclosures may omit the amount on the opposite side. A sell
    # row with no reported buy amount cannot contribute to gross buying;
    # an absent sell amount must not invalidate a reported purchase.
    if data.loc[data.side.eq('buy'), 'buy_value'].isna().any() or (data.buy_value < 0).any():
        raise ValueError('Invalid institutional transaction amounts')
    data = data[data.buy_value.notna()].copy()
    if data.empty:
        return daily
    identity = ['order_book_id', 'date', 'agency', 'buy_value', 'sell_value']
    # Same daily transaction can appear for multiple listing reasons.
    data = data.drop_duplicates(identity + ['type', 'side', 'rank'])
    # Keep equal-valued but distinct seats, while merging buy/sell-list copies.
    data['_occurrence'] = data.groupby(identity + ['type', 'side'], dropna=False).cumcount()
    data = data.drop_duplicates(identity + ['_occurrence'])
    sums = data.groupby('date').buy_value.sum() / 1e8
    daily.loc[daily.index.intersection(sums.index)] = sums.reindex(daily.index).dropna()
    return daily


def fetch_institutional_buy(rq, as_of, previous):
    dates = [pd.Timestamp(d).date() for d in rq.get_trading_dates(as_of - timedelta(days=366*5), as_of)]
    old = next((s.get('points', []) for s in previous.get('series', [])
                if s.get('id') == 'institutional-buy'), [])
    history = {pd.Timestamp(p['date']).date(): float(p['value']) for p in old
               if p.get('date') and p.get('value') is not None}
    # Recheck five recent days for revisions; fetch uncached history once.
    missing = [d for d in dates if d not in history or d in dates[-5:]]
    for offset in range(0, len(missing), 60):
        window = missing[offset:offset+60]
        raw = rq.get_abnormal_stocks(window[0], window[-1])
        events = raw.reset_index() if raw is not None else pd.DataFrame()
        chunks = []
        if not events.empty:
            ids = events.order_book_id.dropna().unique().tolist()
            for start in range(0, len(ids), 200):
                value = rq.get_abnormal_stocks_detail(ids[start:start+200], window[0], window[-1])
                if value is None or value.empty:
                    raise ValueError('Missing transaction detail batch; previous cache retained')
                chunks.append(value.reset_index())
        detail = pd.concat(chunks, ignore_index=True) if chunks else pd.DataFrame()
        history.update(daily_institutional_buy(detail, events, window).to_dict())
        print(f'Institutional buying: {min(offset+60,len(missing))}/{len(missing)} trading days', flush=True)
    values = pd.Series({d: history[d] for d in dates if d in history}).sort_index()
    if values.empty:
        raise ValueError('No institutional buying history')
    ma5 = values.rolling(5, min_periods=5).mean().dropna()
    def points(s):
        return [{'date': d.isoformat(), 'value': round(float(v), 6)} for d,v in s.items()]
    return {
        'institutionalBuyAsOf': values.index[-1].isoformat(),
        'institutionalBuy': round(float(values.iloc[-1]), 6),
        'institutionalBuyMA5': round(float(ma5.iloc[-1]), 6) if not ma5.empty else None,
        'institutionalBuy5D': round(float(values.tail(5).sum()), 6),
        'institutionalBuy20D': round(float(values.tail(20).sum()), 6),
    }, [
        {'id': 'institutional-buy', 'name': '机构买入额（龙虎榜单日榜）', 'unit': '亿元', 'points': points(values)},
        {'id': 'institutional-buy-ma5', 'name': '机构买入额 MA5', 'unit': '亿元', 'points': points(ma5)},
    ]
