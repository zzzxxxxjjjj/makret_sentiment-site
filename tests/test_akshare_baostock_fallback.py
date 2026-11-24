import unittest
from baostock_etf_fallback import build
class BaoETFTests(unittest.TestCase):
    def previous(self):
        return {"rows":[{"code":"510300","name":"沪深300ETF","asOf":"2026-11-18","close":4.058,"amount":76.3,"shares":1000},
                        {"code":"159528","name":"国企改革ETF富国","asOf":"2026-11-18","close":1.123,"amount":.0035,"shares":7320773}]}
    def records(self):
        return [{"date":"2026-11-23","code":"sh.510300","close":"4.0230","amount":"5589278193","pctChg":".1244","adjustflag":"3"}]
    def exceptions(self):
        return {"159528":{"inactiveFrom":"2026-11-19","status":"suspended-for-liquidation"}}
    def test_units_and_preserved_inactive_history(self):
        previous=self.previous()
        result=build(self.records(),previous,"2026-11-23",self.exceptions())
        self.assertAlmostEqual(result["rows"][0]["amount"],55.89278193)
        self.assertEqual(result["activeCoverage"],1)
        self.assertEqual(result["inactiveRows"][0]["asOf"],"2026-11-18")
        self.assertEqual(result["inactiveRows"][0]["shares"],7320773)
        self.assertIsNone(result["rows"][0]["shares"])
        self.assertFalse(result["sharesAvailable"])
        self.assertEqual(len(previous["rows"]),2)
    def test_unexplained_missing_code_rejected(self):
        with self.assertRaises(ValueError):build(self.records(),self.previous(),"2026-11-23",{})
    def test_future_exception_not_applied(self):
        exceptions=self.exceptions();exceptions["159528"]["inactiveFrom"]="2026-11-24"
        with self.assertRaises(ValueError):build(self.records(),self.previous(),"2026-11-23",exceptions)
    def test_wrong_date_rejected(self):
        with self.assertRaises(ValueError):build(self.records(),self.previous(),"2026-11-20",self.exceptions())
    def test_negative_amount_rejected(self):
        rows=self.records();rows[0]["amount"]="-1"
        with self.assertRaises(ValueError):build(rows,self.previous(),"2026-11-23",self.exceptions())
    def test_duplicate_rejected(self):
        rows=self.records()*2
        with self.assertRaises(ValueError):build(rows,self.previous(),"2026-11-23",self.exceptions())
    def test_adjusted_quote_rejected(self):
        rows=self.records();rows[0]["adjustflag"]="2"
        with self.assertRaises(ValueError):build(rows,self.previous(),"2026-11-23",self.exceptions())
if __name__=="__main__":unittest.main()
