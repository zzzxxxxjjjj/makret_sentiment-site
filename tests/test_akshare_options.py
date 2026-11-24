import unittest
import pandas as pd
from akshare_options_refresh import observations
class OptionsTests(unittest.TestCase):
    def rows(self):
        return pd.DataFrame([{"合约标的代码":c,"交易日":"2026-11-23","认购成交量":20,"认沽成交量":10,"未平仓认购合约数":40,"未平仓认沽合约数":30} for c in ("510050","510300","588000")])
    def test_ratios(self):
        result=observations(self.rows(),"2026-11-23")
        self.assertEqual(len(result),6)
        self.assertEqual(result["pcr-oi-star50"]["value"],.75)
        self.assertEqual(result["pcr-volume-hs300"]["value"],.5)
    def test_wrong_session(self):
        with self.assertRaises(ValueError):observations(self.rows(),"2026-11-20")
    def test_missing_underlying(self):
        with self.assertRaises(ValueError):observations(self.rows().iloc[:2],"2026-11-23")
    def test_zero_denominator(self):
        rows=self.rows();rows.loc[0,"认购成交量"]=0
        with self.assertRaises(ValueError):observations(rows,"2026-11-23")
if __name__=="__main__":unittest.main()
