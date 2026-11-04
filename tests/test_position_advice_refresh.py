import unittest
from position_advice_refresh import build


class ObservationsTest(unittest.TestCase):
    def payload(self):
        return {'series': [{'id': 'allshare-close', 'points': [
            {'date': d, 'value': 100} for d in ['2026-09-30', '2026-10-08', '2026-10-09', '2026-10-12']]}]}

    def test_holiday_week_uses_actual_session(self):
        self.assertEqual(build(self.payload())['lastDecisionDate'], '2026-10-09')

    def test_missing_is_not_neutral_or_old_snapshot(self):
        d = build(self.payload())
        self.assertTrue(all(m['vote'] is None for m in d['moduleVotes']))
        self.assertIsNone(d['compositeMean'])
        self.assertTrue(all(s['momentum120'] is None for s in d['styles']))

    def test_stale_factor_keeps_date_and_no_vote(self):
        p = self.payload()
        p['series'].append({'id': 'financing-net', 'points': [{'date': '2026-10-09', 'value': 5}]})
        f = build(p)['moduleVotes'][1]['factors'][1]
        self.assertEqual(f['asOf'], '2026-10-09')
        self.assertIsNone(f['vote'])

    def test_pcr_contracts_never_count_as_two_families(self):
        p = self.payload()
        for key in ['pcr-oi-ma3-sz50', 'pcr-oi-ma3-hs300']:
            p['series'].append({'id': key, 'points': [{'date': '2026-10-12', 'value': 1.5}]})
        self.assertIsNone(build(p)['moduleVotes'][4]['vote'])
