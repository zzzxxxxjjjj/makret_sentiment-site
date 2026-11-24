import unittest
from akshare_public_refresh import margin_totals
class MarginUnitTests(unittest.TestCase):
    def test_exchange_specific_units(self):
        balance,buy=margin_totals({"融资余额":1120000000000,"融资买入额":56000000000},{"融资余额":9800,"融资买入额":500})
        self.assertEqual(balance,21000)
        self.assertEqual(buy,1060)
if __name__=="__main__":unittest.main()
