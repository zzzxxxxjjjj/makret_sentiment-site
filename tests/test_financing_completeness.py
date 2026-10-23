import unittest
from datetime import date
from unittest.mock import patch

import pandas as pd
import rqdata_refresh as refresh


class FinancingCompletenessTests(unittest.TestCase):
    def fetch(self, rows):
        with patch.object(refresh.rq, 'get_securities_margin', return_value=pd.DataFrame(rows)):
            return refresh.fetch_financing(date(2026, 10, 21), {
                date(2026, 10, 20): 1000, date(2026, 10, 21): 1000})

    def row(self, dt, exchange, **changes):
        return dict(date=dt, order_book_id=exchange, margin_balance=100,
                    buy_on_margin_value=40, margin_repayment=30, **changes)

    def test_partial_latest_day_is_excluded(self):
        rows = [self.row('2026-10-20', ex) for ex in ['XSHG', 'XSHE']]
        rows.append(self.row('2026-10-21', 'XSHG'))
        metrics, series = self.fetch(rows)
        self.assertEqual(metrics['financingAsOf'], '2026-10-20')
        self.assertEqual(metrics['financingActivity'], 8)
        self.assertTrue(all(p['date'] == '2026-10-20' for s in series for p in s['points']))

    def test_complete_latest_day_is_included(self):
        metrics, _ = self.fetch([self.row('2026-10-21', ex) for ex in ['XSHG', 'XSHE']])
        self.assertEqual(metrics['financingAsOf'], '2026-10-21')
        self.assertEqual(metrics['financingActivity'], 8)

    def test_missing_field_and_duplicate_exchange_are_rejected(self):
        rows = [self.row('2026-10-21', ex) for ex in ['XSHG', 'XSHE']]
        rows[1]['buy_on_margin_value'] = None
        with self.assertRaises(ValueError):
            self.fetch(rows)
        with self.assertRaises(ValueError):
            self.fetch([self.row('2026-10-21', 'XSHG')] * 2)


class IndexFinancingCompletenessTests(unittest.TestCase):
    def calculate(self, buys):
        dt = date(2026, 10, 21)
        codes = ['600000.XSHG', '000001.XSHE', '000002.XSHE']
        weights = pd.DataFrame({'date': [dt] * 3, 'order_book_id': codes})
        turnover = weights.assign(total_turnover=100)
        margin = pd.DataFrame({'date': [dt] * len(buys),
                               'order_book_id': codes[:len(buys)],
                               'buy_on_margin_value': buys})
        previous = {'series': [{'id': sid, 'points': [{'date': str(dt), 'value': 999}]}
                               for sid in refresh.index_financing_metric_ids()]}
        with patch.object(refresh.rq, 'index_weights_ex', return_value=weights), \
                patch.object(refresh.rq, 'get_price', return_value=turnover), \
                patch.object(refresh.rq, 'get_securities_margin', return_value=margin), \
                patch.object(refresh.rq, 'get_margin_stocks', return_value=codes[:2]):
            return {s['id']: s['points'] for s in
                    refresh.build_index_financing_activity_series(previous, [dt])}

    def test_partial_stock_data_removes_unverified_cached_point(self):
        result = self.calculate([40])
        self.assertTrue(result)
        self.assertTrue(all(points == [] for points in result.values()))

    def test_non_eligible_stock_is_structural_zero(self):
        result = self.calculate([40, 20])
        self.assertEqual(result['hs300-financing-activity'][0]['value'], 20)

    def test_reported_zero_is_valid_but_null_is_not(self):
        self.assertEqual(self.calculate([0, 0])['hs300-financing-activity'][0]['value'], 0)
        self.assertEqual(self.calculate([40, None])['hs300-financing-activity'], [])

    def test_complete_refresh_replaces_cached_value(self):
        self.assertEqual(self.calculate([90, 30])['hs300-financing-activity'][0]['value'], 40)
