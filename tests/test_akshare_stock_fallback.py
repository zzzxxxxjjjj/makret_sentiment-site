import unittest
from ifind_stock_fallback import parse
class StockFallbackTests(unittest.TestCase):
    def result(self):
        n=4000
        return {"tables":[{"table":{"股票代码":[str(600000+i)+".SH" for i in range(n)],
            "成交额[20261123]":["1.2E8"]*n,"换手率[20261123]":["2.5"]*n,"主力资金流向[20261123]":[-1000]*n}}]}
    def test_dated_values_and_units(self):
        row=parse(self.result(),"2026-11-23")[0]
        self.assertEqual(row["成交额"],120000000)
        self.assertEqual(row["换手率"],2.5)
        self.assertEqual(row["今日主力净流入-净额"],-1000)
    def test_other_date_rejected(self):
        with self.assertRaises(ValueError):parse(self.result(),"2026-11-20")
    def test_incomplete_coverage_rejected(self):
        r=self.result()
        for k in r["tables"][0]["table"]:r["tables"][0]["table"][k]=r["tables"][0]["table"][k][:10]
        with self.assertRaises(ValueError):parse(r,"2026-11-23")
    def test_duplicate_codes_rejected(self):
        r=self.result();r["tables"][0]["table"]["股票代码"][1]="600000.SH"
        with self.assertRaises(ValueError):parse(r,"2026-11-23")
if __name__=="__main__":unittest.main()
