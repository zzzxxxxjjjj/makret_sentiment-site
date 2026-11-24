import unittest
from ifind_etf_fallback import decode
class ETFProviderTests(unittest.TestCase):
    def result(self):
        return {"tables":[{"thscode":"510300.SH","time":["2026-11-23"],"table":{"close":[4.023],"amount":[5589278193],"changeRatio":[.12444]}}]}
    def test_units_and_no_invented_shares(self):
        row=decode(self.result(),{"510300.SH":"沪深300ETF"},"2026-11-23")[0]
        self.assertAlmostEqual(row["amount"],55.89278193)
        self.assertIsNone(row["shares"])
    def test_wrong_day_rejected(self):
        with self.assertRaises(ValueError):decode(self.result(),{"510300.SH":"ETF"},"2026-11-20")
    def test_empty_success_rejected(self):
        with self.assertRaises(ValueError):decode({"tables":[]} ,{"510300.SH":"ETF"},"2026-11-23")
    def test_null_amount_rejected(self):
        result=self.result();result["tables"][0]["table"]["amount"]=[None]
        with self.assertRaises(ValueError):decode(result,{"510300.SH":"ETF"},"2026-11-23")
if __name__=="__main__":unittest.main()
