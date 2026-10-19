import copy
import json
import tempfile
import unittest
from pathlib import Path

from rqdata_fund_exposure_refresh import save_snapshot, validate_snapshot


def snapshot():
    return {'asOf': '2026-10-16', 'updatedAt': 'first', 'industries': [
        {'code': str(i), 'name': 'Industry ' + str(i), 'tradeDate': '2026-10-16',
         'wgtEq': 100 / 31, 'mkt': 100 / 31, 'overPp': 0} for i in range(31)]}


class FundExposureTests(unittest.TestCase):
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
