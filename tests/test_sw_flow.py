import unittest
import pandas as pd
from sw_flow_refresh import aggregate


class SWFlowTest(unittest.TestCase):
    def inputs(self):
        members = [dict(code=str(i), name='行业'+str(i), stocks=[str(i*20+j).zfill(6) for j in range(20)]) for i in range(30)]
        stocks = pd.DataFrame([{'代码': str(i).zfill(6), '今日主力净流入-净额': 1e8*(-1 if i % 2 else 1)} for i in range(600)])
        return members, stocks

    def test_all_thirty_and_currency_unit(self):
        m, s = self.inputs(); s.loc[0, '今日主力净流入-净额'] = 2e8
        rows = aggregate(m, s)
        self.assertEqual(len(rows), 30)
        self.assertEqual(rows[0]['value'], 1)
        self.assertEqual(rows[0]['covered'], 20)

    def test_partial_subtotal_has_coverage_counts(self):
        m, s = self.inputs()
        row = aggregate(m, s.iloc[2:])[0]
        self.assertEqual((row['covered'], row['total']), (18, 20))

    def test_insufficient_coverage_is_rejected(self):
        m, s = self.inputs()
        with self.assertRaises(ValueError): aggregate(m, s.iloc[3:])

    def test_overlapping_membership_is_rejected(self):
        m, s = self.inputs(); m[1]['stocks'].append(m[0]['stocks'][0])
        with self.assertRaises(ValueError): aggregate(m, s)

    def test_wrong_classification_is_rejected(self):
        m, s = self.inputs(); m[0]['name'] = '综合'
        with self.assertRaises(ValueError): aggregate(m, s)
