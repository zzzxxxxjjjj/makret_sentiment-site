import json
import tempfile
import unittest
from pathlib import Path

from market_data_sync import apply_market_data_sync
from rqdata_options_refresh import calculate_ratios
import pandas as pd


class OptionSyncTests(unittest.TestCase):
    def test_pcr_is_ratio_of_sums_and_missing_side_is_not_zero(self):
        contracts = pd.DataFrame({'order_book_id': ['p1', 'p2', 'c1'], 'option_type': ['P', 'P', 'C']})
        raw = pd.DataFrame({'order_book_id': ['p1', 'p2', 'c1'], 'date': ['2026-10-13'] * 3,
                            'open_interest': [30, 70, 50], 'total_turnover': [60, 40, 25], 'volume': [5, 5, 20]})
        ratios = calculate_ratios(raw, contracts)
        self.assertEqual(ratios['oi'][-1]['value'], 2)
        self.assertEqual(ratios['amount'][-1]['value'], 4)
        self.assertEqual(ratios['volume'][-1]['value'], .5)
        self.assertFalse(calculate_ratios(raw.iloc[:2], contracts)['oi'])
        raw.loc[0, 'open_interest'] = None
        self.assertFalse(calculate_ratios(raw, contracts)['oi'])

    def test_overlay_extends_pcr_but_keeps_shares_real_date_and_unit(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as tmp:
            directory = Path(tmp)
            dates = ['2026-10-09', '2026-10-12', '2026-10-13']
            incoming = [{'id': f'pcr-{metric}-sz50', 'points': [{'date': dt, 'value': value}
                          for dt, value in zip(dates, values)]}
                        for metric, values in [('oi', [1, 2, 3]), ('amount', [2, 4, 6]), ('volume', [1, 1, 1])]]
            (directory/'rqdata-options-pcr.json').write_text(json.dumps({'asOf': dates[-1], 'series': incoming}))
            payload = {'asOf': dates[-1], 'series': [
                {'id': 'pcr-oi-sz50', 'points': [{'date': '2026-10-08', 'value': .5}]},
                {'id': 'new-equity-fund-shares', 'unit': '�ڷ�', 'points': [{'date': '2026-09-30', 'value': 8}]},
            ]}
            result = apply_market_data_sync(payload, directory)
            series = {item['id']: item for item in result['series']}
            self.assertEqual(len(series['pcr-oi-sz50']['points']), 4)
            self.assertEqual(series['pcr-oi-ma3-sz50']['points'][-1]['value'], 2)
            # Existing definition is inverse AFTER taking the mean, not mean of inverses.
            self.assertEqual(series['pcr-amount-volume-ma3-sz50']['points'][-1]['value'], .25)
            shares = series['new-equity-fund-shares']
            self.assertEqual(shares['unit'], '�ڷ�')
            self.assertEqual(shares['updateInfo']['asOf'], '2026-09-30')
            self.assertEqual(shares['updateInfo']['status'], 'manual')
            missing = next(item for item in result['freshness']['items'] if item['id'] == 'sse50-financing-activity')
            self.assertEqual(missing['status'], 'missing')


if __name__ == '__main__':
    unittest.main()
