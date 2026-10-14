import json
import tempfile
import unittest
from pathlib import Path

from market_data_sync import apply_market_data_sync
from rqdata_options_refresh import calculate_ratios
import pandas as pd


class OptionSyncTests(unittest.TestCase):
    def test_newer_rqdata_turnover_replaces_stale_wind_history(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as tmp:
            directory = Path(tmp)
            (directory/'rqdata-broad-sentiment.json').write_text(json.dumps({'series': [
                {'id': 'hs300-turnover', 'name': '沪深300换手率', 'unit': '%', 'points': [
                    {'date': '2026-10-12', 'value': 1.1},
                    {'date': '2026-10-13', 'value': 1.2},
                ]},
            ]}))
            payload = {'asOf': '2026-10-13', 'series': [
                {'id': 'hs300-turnover', 'source': 'Wind插件', 'points': [
                    {'date': '2026-09-30', 'value': 9.9},
                ]},
                {'id': 'windall-turnover', 'source': 'Wind插件', 'points': [
                    {'date': '2026-09-30', 'value': 2.5},
                ]},
            ]}
            result = apply_market_data_sync(payload, directory)
            by_id = {item['id']: item for item in result['series']}
            self.assertEqual([p['value'] for p in by_id['hs300-turnover']['points']], [1.1, 1.2])
            self.assertEqual(by_id['hs300-turnover']['source'], 'RQData')
            self.assertEqual(by_id['hs300-turnover']['updateInfo']['status'], 'current')
            self.assertEqual(by_id['windall-turnover']['updateInfo']['status'], 'manual')

    def test_damaged_cached_labels_are_repaired_without_changing_observations(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as tmp:
            payload = {'asOf': '2026-10-13', 'series': [
                {'id': 'land-connect-turnover-ma20', 'name': '\ufffd', 'unit': '\ufffd',
                 'points': [{'date': '2026-10-13', 'value': 2583.48}]},
                {'id': 'new-equity-fund-shares', 'name': '\ufffd', 'unit': '\ufffd',
                 'points': [{'date': '2026-10-12', 'value': 5.27}]}]}
            result = apply_market_data_sync(payload, Path(tmp))
            items = {s['id']: s for s in result['series']}
            self.assertEqual(items['land-connect-turnover-ma20']['unit'], '\u4ebf\u5143')
            self.assertEqual(items['new-equity-fund-shares']['unit'], '\u4ebf\u4efd')
            self.assertEqual(items['land-connect-turnover-ma20']['points'][0]['value'], 2583.48)
            self.assertNotIn('\ufffd', json.dumps(result, ensure_ascii=False))

    def test_saved_wind_values_update_shares_card_without_changing_20d_definition(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as tmp:
            directory = Path(tmp)
            data = {'series': [{'id': 'new-equity-fund-shares', 'unit': '\u4ebf\u4efd',
                               'points': [{'date': '2026-10-12', 'value': 3}]}],
                    'fundShares': {'asOf': '2026-10-12', 'shares': 3, 'shares5D': 7, 'shares20D': 12}}
            (directory/'wind-market-supplement.json').write_text(json.dumps(data))
            payload = {'asOf': '2026-10-13', 'series': [], 'cards': [
                {'id': 'new-equity-fund-shares', 'asOf': '2026-09-30', 'value': 5,
                 'submetrics': [{'label': '\u5f53\u65e5', 'value': 0}]}]}
            result = apply_market_data_sync(payload, directory)
            self.assertEqual(result['cards'][0]['value'], 12)
            self.assertEqual(result['cards'][0]['asOf'], '2026-10-12')
            self.assertEqual(result['cards'][0]['submetrics'][0]['value'], 3)

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
                {'id': 'new-equity-fund-shares', 'unit': '亿份', 'points': [{'date': '2026-09-30', 'value': 8}]},
            ]}
            result = apply_market_data_sync(payload, directory)
            series = {item['id']: item for item in result['series']}
            self.assertEqual(len(series['pcr-oi-sz50']['points']), 4)
            self.assertEqual(series['pcr-oi-ma3-sz50']['points'][-1]['value'], 2)
            # Existing definition is inverse AFTER taking the mean, not mean of inverses.
            self.assertEqual(series['pcr-amount-volume-ma3-sz50']['points'][-1]['value'], .25)
            shares = series['new-equity-fund-shares']
            self.assertEqual(shares['unit'], '亿份')
            self.assertEqual(shares['updateInfo']['asOf'], '2026-09-30')
            self.assertEqual(shares['updateInfo']['status'], 'manual')
            missing = next(item for item in result['freshness']['items'] if item['id'] == 'sse50-financing-activity')
            self.assertEqual(missing['status'], 'missing')


if __name__ == '__main__':
    unittest.main()
