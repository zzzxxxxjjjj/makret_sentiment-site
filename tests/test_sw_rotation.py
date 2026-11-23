import unittest
import pandas as pd
from sw_rotation_refresh import calculate

class RotationTests(unittest.TestCase):
    def setUp(self):
        self.days=pd.bdate_range('2026-07-01',periods=100)
        self.prices=pd.DataFrame({str(i):[100+j*(i+1)/100 for j in range(100)] for i in range(30)},index=self.days)
        self.benchmark=pd.Series(range(100,200),index=self.days)
    def test_complete_universe_reaches_target(self):
        rows=calculate(self.prices,self.benchmark,self.days)
        self.assertEqual(rows[-1]['date'],str(self.days[-1].date()))
        self.assertTrue(all(r['industries']==30 for r in rows))
    def test_missing_current_industry_cannot_be_current(self):
        self.prices.iloc[-1,0]=float('nan')
        rows=calculate(self.prices,self.benchmark,self.days)
        self.assertLess(rows[-1]['date'],str(self.days[-1].date()))
    def test_missing_industry_is_rejected(self):
        with self.assertRaisesRegex(ValueError,'30'):
            calculate(self.prices.iloc[:,:29],self.benchmark,self.days)
if __name__=='__main__':unittest.main()
