import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from rqdata_fund_exposure_refresh import save_snapshot, validate_snapshot, build_weekly_comparison, main


def snapshot():
    return {'asOf': '2026-10-16', 'updatedAt': 'first', 'industries': [
        {'code': str(i), 'name': 'Industry ' + str(i), 'tradeDate': '2026-10-16',
         'wgtEq': 100 / 31, 'mkt': 100 / 31, 'overPp': 0} for i in range(31)]}


class FundExposureTests(unittest.TestCase):
    @staticmethod
    def raw(data):
        return {'as_of': data['asOf'], 'data': [
            {'code': r['code'], 'name': r['name'], 'trade_date': r['tradeDate'],
             'wgt_eq': r['wgtEq'], 'mkt': r['mkt'], 'over_pp': r['overPp']} for r in data['industries']]}

    def test_relative_changes_include_benchmark_changes_and_holiday_gap(self):
        current = snapshot()
        prior = copy.deepcopy(current)
        prior['asOf'] = '2026-10-08'
        for row in prior['industries']:
            row['tradeDate'] = prior['asOf']
        prior['industries'][0]['mkt'] += 0.5
        prior['industries'][0]['overPp'] = -0.5
        prior['industries'][1]['mkt'] -= 0.5
        prior['industries'][1]['overPp'] = 0.5
        result = build_weekly_comparison(current, self.raw(prior))
        self.assertEqual(result['previousAsOf'], '2026-10-08')
        self.assertEqual(len(result['industries']), 31)
        row = next(r for r in result['industries'] if r['code'] == '0')
        self.assertEqual(row['changeOverPp'], 0.5)
        self.assertEqual(row['weightChangePp'], 0)
        self.assertEqual(row['benchmarkChangePp'], -0.5)

    def test_fetches_last_observation_before_latest_not_seven_days_ago(self):
        current = snapshot()
        prior = copy.deepcopy(current)
        prior['asOf'] = '2026-10-08'
        for row in prior['industries']:
            row['tradeDate'] = prior['asOf']
        with tempfile.TemporaryDirectory() as tmp, \
                patch('rqdata_fund_exposure_refresh.resolve_api_key', return_value='unused'), \
                patch('rqdata_fund_exposure_refresh.fetch_json', side_effect=[self.raw(current), self.raw(prior)]) as fetch:
            output = Path(tmp) / 'snapshot.json'
            main(['--output', str(output)])
            self.assertEqual(fetch.call_args.args[3]['date'], '2026-10-15')
            self.assertEqual(json.loads(output.read_text())['comparison']['previousAsOf'], '2026-10-08')

    def test_comparison_rejects_same_week_missing_industries_and_wrong_index(self):
        current = snapshot()
        with self.assertRaises(ValueError):
            build_weekly_comparison(current, self.raw(current))
        raw = self.raw(current)
        raw['as_of'] = '2026-10-08'
        for row in raw['data']:
            row['trade_date'] = raw['as_of']
        wrong = copy.deepcopy(raw)
        wrong['index'] = '885002'
        with self.assertRaises(ValueError):
            build_weekly_comparison(current, wrong)
        raw['data'].pop()
        with self.assertRaises(ValueError):
            build_weekly_comparison(current, raw)

    def test_complete_snapshot(self):
        validate_snapshot(snapshot())

    def test_bad_responses_preserve_previous_file(self):
        valid = snapshot()
        cases = []
        incomplete = copy.deepcopy(valid)
        incomplete['industries'].pop()
        cases.append(incomplete)
        mixed = copy.deepcopy(valid)
        mixed['industries'][0]['tradeDate'] = '2026-10-09'
        cases.append(mixed)
        invalid = copy.deepcopy(valid)
        invalid['industries'][0]['wgtEq'] = float('inf')
        cases.append(invalid)
        duplicate = copy.deepcopy(valid)
        duplicate['industries'][0]['code'] = '1'
        cases.append(duplicate)
        older = copy.deepcopy(valid)
        older['asOf'] = '2026-10-09'
        for row in older['industries']:
            row['tradeDate'] = older['asOf']
        cases.append(older)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'fund.json'
            save_snapshot(valid, path)
            before = path.read_bytes()
            for bad in cases:
                with self.subTest(bad=bad['asOf']), self.assertRaises(ValueError):
                    save_snapshot(bad, path)
                self.assertEqual(before, path.read_bytes())

    def test_same_week_correction_publishes_but_check_time_does_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'fund.json'
            data = snapshot()
            self.assertTrue(save_snapshot(data, path))
            data['updatedAt'] = 'later'
            self.assertFalse(save_snapshot(data, path))
            self.assertEqual(json.loads(path.read_text())['updatedAt'], 'first')
            data['industries'][0]['name'] = 'Corrected industry'
            self.assertTrue(save_snapshot(data, path))


if __name__ == '__main__':
    unittest.main()
