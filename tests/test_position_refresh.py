import copy
import json
import unittest
from pathlib import Path
import numpy as np
import pandas as pd
from position_refresh import ETFS, INDICES, build, dated, rank, risk_weights


class PositionTest(unittest.TestCase):
    def inputs(self):
        days = pd.bdate_range('2023-01-02', periods=650)
        rng = np.random.default_rng(12)
        prices = pd.DataFrame(100*np.exp(np.cumsum(rng.normal(.0004, .01, (650, 6)), axis=0)), index=days, columns=ETFS)
        pe = pd.DataFrame(rng.uniform(10, 40, (650, 5)), index=days, columns=INDICES)
        flows = pd.DataFrame(rng.normal(0, 10, (650, 5)), index=days, columns=ETFS[:5])
        s = lambda v: pd.Series(v, index=days)
        return dict(prices=prices, pe=pe, flows=flows, breadth=s(np.full(650, 20.)),
                    turnover=s(np.arange(650)+1.), funding=s(rng.normal(0, 10, 650)),
                    pcr=s(rng.uniform(.7, 1.4, 650)), etf50=prices.iloc[:, 0],
                    iv=s(np.full(650, .2)), positions=s(np.full(650, -.03)))

    def template(self):
        return json.loads((Path(__file__).resolve().parents[1]/'position-advice.json').read_text(encoding='utf-8'))

    def test_original_contract_and_limits(self):
        d = self.inputs(); day = str(d['prices'].index[-1].date())
        out = build(self.template(), d, day, day)
        self.assertEqual(len(out['styles']), 4)
        self.assertEqual(len(out['moduleVotes']), 5)
        for m in out['models']:
            self.assertEqual(len(m['assets']), 7)
            self.assertAlmostEqual(sum(a['weight'] for a in m['assets']), 1)
            self.assertLessEqual(m['equity'], .20000001)
            self.assertLessEqual(m['credit'], .80000001)
            self.assertAlmostEqual(sum(a['riskShare'] or 0 for a in m['assets']), 1)
        json.dumps(out, allow_nan=False)

    def test_missing_latest_never_forward_filled(self):
        d = self.inputs(); day = str(d['prices'].index[-1].date())
        d['prices'].iloc[-1, 0] = np.nan
        with self.assertRaises(ValueError): build(self.template(), d, day, day)

    def test_weekly_decision_not_changed_by_later_prices(self):
        d = self.inputs(); day = str(d['prices'].index[-1].date()); decision = str(d['prices'].index[-6].date())
        first = build(self.template(), d, day, decision)
        d['prices'].iloc[-5:, :5] *= 1.5
        second = build(self.template(), d, day, decision)
        self.assertEqual(first['models'], second['models'])
        self.assertEqual(first['moduleVotes'], second['moduleVotes'])
        self.assertNotEqual(first['styles'], second['styles'])

    def test_risk_allocation_has_equal_contributions(self):
        cov = np.array([[.04, .003], [.003, .0004]])
        w = risk_weights(cov, np.ones(2))
        rc = w*(cov@w)/(w@cov@w)
        np.testing.assert_allclose(rc, [.5, .5], atol=1e-5)

    def test_rank_ties_and_insufficient_history(self):
        self.assertEqual(rank([1]*126), 50)
        with self.assertRaises(ValueError): rank([1]*10)

    def test_valuation_trade_date_and_unnamed_datetime_index(self):
        day = pd.to_datetime(['2026-11-03'])
        for name in ['trade_date', None]:
            raw = pd.DataFrame({'pe_ttm': [15.]}, index=pd.DatetimeIndex(day, name=name))
            self.assertEqual(dated(raw, 'pe_ttm').index[-1], day[0])
