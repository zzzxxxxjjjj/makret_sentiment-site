import unittest
from datetime import date,timedelta
import pandas as pd
from rqdata_style_returns_refresh import build_snapshot,FACTORS


class ReturnTests(unittest.TestCase):
    def test_arithmetic_factor_contributions_and_nonoverlapping_weeks(self):
        days=[date(2026,9,1)+timedelta(days=i) for i in range(20)]
        frame=pd.DataFrame({k:[.001]*20 for k in FACTORS},index=days)
        data=build_snapshot(frame,days)
        self.assertEqual([p['values']['size'] for p in data['chart']['periods']],[.5,.5,2])
        self.assertLess(data['chart']['periods'][1]['end'],data['chart']['periods'][0]['start'])
        for broken in [frame.iloc[:-1],frame.assign(size=float('nan'))]:
            with self.assertRaises(ValueError):build_snapshot(broken,days)


if __name__=='__main__':unittest.main()
