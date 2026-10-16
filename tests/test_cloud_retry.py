import os
import sys
import types
import unittest
from datetime import date
from unittest.mock import patch

import cloud_daily_update as cloud


class CloudRetryTests(unittest.TestCase):
    def test_current_core_still_retries_optional_data_and_rebuilds(self):
        dashboard = types.SimpleNamespace(ENABLE_RQDATA_REFRESH=True,
            _build_payload=lambda **kwargs: {'asOf': '2026-10-13', 'cards': [1], 'series': [{'id':'sample','points':[]}],
                                            'cycleComparison': {'points': [{'date':'2026-10-13','sentiment':50}]}},
            save_page_cache=lambda payload: None)
        with patch.dict(os.environ, {'RQDATAC_CONF': 'test', 'AIDO_API_KEY': '', 'RQDATA_AS_OF': ''}), \
                patch.dict(sys.modules, {'rqdatac': types.SimpleNamespace(get_trading_dates=lambda *args: []), 'broad_sentiment': dashboard}), \
                patch.object(cloud, 'initialize_rqdata'), \
                patch.object(cloud, 'completed_trading_date', return_value=date(2026, 10, 13)), \
                patch.object(cloud, 'caches_current', return_value=True), \
                patch.object(cloud, 'refresh_core_snapshots') as core, \
                patch.object(cloud, 'verify_core_dates'), \
                patch('data_freshness.write_report', return_value={'currentDailyCount':1,'dailyCount':1}), \
                patch.object(cloud, 'run_stage', return_value=True) as stage:
            cloud.main()
        core.assert_not_called()
        scripts = [call.args[0] for call in stage.call_args_list]
        self.assertIn('rqdata_options_refresh.py', scripts)
        self.assertIn('rqdata_late_market_refresh.py', scripts)
        self.assertFalse(dashboard.ENABLE_RQDATA_REFRESH)


if __name__ == '__main__':
    unittest.main()
