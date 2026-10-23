import copy
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import rqdata_late_market_refresh as late


TARGET = date(2026, 10, 16)


def payload():
    return {'asOf': '2026-10-16', 'broadEtfFlow1D': 10,
            'series': [{'id': 'broad-etf-flow', 'points': [
                {'date': '2021-10-18', 'value': 5}, {'date': '2026-10-15', 'value': 10}]}],
            'etfDetails': [{'code': '510300', 'asOf': '2026-10-15', 'points': [
                {'date': '2021-10-18', 'value': 1}, {'date': '2026-10-15', 'value': 2}]}]}


def response():
    return ({'broadEtfCount': 100}, [{'date': '2026-10-15', 'value': 11},
                                   {'date': '2026-10-16', 'value': 12}],
            [{'code': '510300', 'asOf': '2026-10-16', 'points': [
                {'date': '2026-10-15', 'value': 3}, {'date': '2026-10-16', 'value': 4}]}])


class LateETFTests(unittest.TestCase):
    def test_current_header_does_not_skip_stale_etf_and_preserves_history(self):
        data = payload()
        with patch.object(late, 'fetch_etf_flows', return_value=response()) as fetch:
            self.assertTrue(late.retry_etf(data, TARGET))
        fetch.assert_called_once_with(TARGET, start_date=TARGET-timedelta(days=120))
        self.assertEqual(data['series'][0]['points'], [
            {'date': '2021-10-18', 'value': 5}, {'date': '2026-10-15', 'value': 11},
            {'date': '2026-10-16', 'value': 12}])
        self.assertEqual(data['broadEtfFlow1D'], 12)
        self.assertEqual(data['broadEtfFlow5D'], 28)
        self.assertEqual(data['broadEtfAsOf'], '2026-10-16')
        self.assertEqual(len(data['etfDetails'][0]['points']), 3)
        self.assertEqual(data['etfDetails'][0]['flow20D'], 8)

    def test_empty_or_failed_source_preserves_previous_data(self):
        for error in [None, RuntimeError('provider unavailable')]:
            data = payload()
            before = copy.deepcopy(data)
            with patch.object(late, 'fetch_etf_flows', return_value=({}, [], []), side_effect=error):
                self.assertFalse(late.retry_etf(data, TARGET))
            self.assertEqual(data, before)

    def test_real_delayed_date_is_retained_and_retried_next_time(self):
        data = payload()
        with patch.object(late, 'fetch_etf_flows', return_value=({}, [{'date': '2026-10-15', 'value': 11}], [])):
            self.assertTrue(late.retry_etf(data, TARGET))
        self.assertEqual(data['broadEtfAsOf'], '2026-10-15')
        with patch.object(late, 'fetch_etf_flows', return_value=response()) as fetch:
            self.assertTrue(late.retry_etf(data, TARGET))
        fetch.assert_called_once()
        self.assertEqual(data['broadEtfAsOf'], '2026-10-16')

    def test_current_series_and_details_do_not_repeat_provider_calls(self):
        data = payload()
        with patch.object(late, 'fetch_etf_flows', return_value=response()):
            late.retry_etf(data, TARGET)
        with patch.object(late, 'fetch_etf_flows') as fetch:
            self.assertFalse(late.retry_etf(data, TARGET))
        fetch.assert_not_called()

    def test_lagging_response_does_not_regress_a_newer_detail_close(self):
        data = payload()
        data['etfDetails'][0].update(asOf='2026-10-16', close=10)
        data['etfDetails'][0]['points'].append({'date': '2026-10-16', 'value': 4})
        before = copy.deepcopy(data['etfDetails'][0])
        metrics, points, details = response()
        details[0].update(asOf='2026-10-15', close=9)
        details[0]['points'] = details[0]['points'][:1]
        with patch.object(late, 'fetch_etf_flows', return_value=(metrics, points, details)):
            self.assertTrue(late.retry_etf(data, TARGET))
        self.assertEqual(data['etfDetails'][0], before)

    def test_null_and_future_observations_do_not_advance_date(self):
        data = payload()
        with patch.object(late, 'fetch_etf_flows', return_value=({}, [
                {'date': '2026-10-16', 'value': None}, {'date': '2026-10-19', 'value': 12}], [])):
            self.assertFalse(late.retry_etf(data, TARGET))
        self.assertEqual(late.latest_point_date(data['series'][0]['points']), '2026-10-15')

    def test_main_writes_supplement_even_when_header_is_already_current(self):
        with tempfile.TemporaryDirectory(dir=late.Path(__file__).resolve().parent) as tmp:
            path = Path(tmp) / 'snapshot.json'
            data = payload()
            ids = ['financing-activity', 'land-connect-turnover-ma20', 'star50-close',
                   *[item[1] for item in late.INDEX_FINANCING_ACTIVITY_DEFINITIONS]]
            data['series'].extend({'id': sid, 'points': [{'date': '2026-10-16', 'value': 1}]} for sid in ids)
            path.write_text(json.dumps(data), encoding='utf-8')
            with patch('sys.argv', ['late', '--output', str(path)]), \
                    patch.object(late, 'initialize_rqdata'), \
                    patch.object(late, 'completed_trading_date', return_value=TARGET), \
                    patch.object(late, 'fetch_etf_flows', return_value=response()), \
                    patch.object(late, 'fetch_index_ma_history', return_value=({}, {}, [])), \
                    patch.object(late, 'recent_trading_dates', return_value=[TARGET]), \
                    patch.object(late, 'build_index_financing_activity_series', return_value=[]), \
                    patch.object(late, 'fetch_financing', return_value=({}, [])) as finance:
                late.main()
            finance.assert_called_once()
            saved = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(saved['broadEtfAsOf'], '2026-10-16')
            self.assertEqual(saved['broadEtfFlow1D'], 12)

    def test_an_unrelated_index_failure_does_not_discard_the_etf_update(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1]) as tmp:
            path = Path(tmp) / 'snapshot.json'
            data = payload()
            ids = ['financing-activity', 'land-connect-turnover-ma20',
                   *[item[1] for item in late.INDEX_FINANCING_ACTIVITY_DEFINITIONS]]
            data['series'].extend({'id': sid, 'points': [{'date': '2026-10-16', 'value': 1}]} for sid in ids)
            path.write_text(json.dumps(data), encoding='utf-8')
            with patch('sys.argv', ['late', '--output', str(path)]), \
                    patch.object(late, 'initialize_rqdata'), \
                    patch.object(late, 'completed_trading_date', return_value=TARGET), \
                    patch.object(late, 'fetch_etf_flows', return_value=response()), \
                    patch.object(late, 'fetch_index_ma_history', side_effect=RuntimeError('index unavailable')):
                late.main()
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['broadEtfAsOf'], '2026-10-16')


if __name__ == '__main__':
    unittest.main()
