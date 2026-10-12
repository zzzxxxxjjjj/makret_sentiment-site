import unittest
import pandas as pd
from rqdata_institutional_flow import daily_institutional_buy


class InstitutionalBuyingTests(unittest.TestCase):
    day = '2026-10-09'

    def events(self, types=('U01',)):
        return pd.DataFrame([dict(order_book_id='600001.XSHG', date=self.day,
                                  type=t, abnormal_s_date=self.day,
                                  abnormal_e_date=self.day) for t in types])

    def row(self, **extra):
        return dict(order_book_id='600001.XSHG', date=self.day, type='U01',
                    agency='机构专用', side='buy', rank=1, buy_value=1e8,
                    sell_value=2e7, **extra)

    def total(self, rows, events=None):
        return daily_institutional_buy(pd.DataFrame(rows),
                                       self.events() if events is None else events,
                                       [self.day]).iloc[0]

    def test_opposite_side_missing_amounts(self):
        buy = self.row(); buy['sell_value'] = None
        sell = self.row(); sell.update(side='sell', buy_value=None)
        self.assertEqual(self.total([buy, sell]), 1.0)

    def test_equal_distinct_seats_preserved_copies_deduplicated(self):
        a = self.row(); b = {**a, 'rank': 2}
        sell = {**a, 'side': 'sell', 'rank': 3}
        reason_a = {**a, 'type': 'U02', 'rank': 4}
        reason_b = {**b, 'type': 'U02', 'rank': 5}
        self.assertEqual(self.total([a, b, sell, reason_a, reason_b],
                                    self.events(('U01','U02'))), 2.0)

    def test_cumulative_and_broker_seats_excluded(self):
        events = self.events(); events.loc[0, 'abnormal_s_date'] = '2026-10-08'
        self.assertEqual(self.total([self.row()], events), 0.0)
        row = self.row(); row['agency'] = '普通营业部'
        self.assertEqual(self.total([row]), 0.0)

    def test_buy_disclosure_missing_amount_fails(self):
        row = self.row(); row['buy_value'] = None
        with self.assertRaises(ValueError): self.total([row])


if __name__ == '__main__':
    unittest.main()
