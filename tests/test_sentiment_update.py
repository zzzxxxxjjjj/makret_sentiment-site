import os
import unittest
from unittest.mock import patch
from datetime import datetime
import broad_sentiment as broad
from sentiment_update import synthesis_status


class SynthesisTests(unittest.TestCase):
    def test_medium_lag_is_identified_even_when_page_header_is_current(self):
        p = {'asOf':'2026-10-13','cycleComparison':{'points':[{'date':'2026-10-13','sentiment':50}]},
             'series':[{'id':'medium-term-sentiment','points':[{'date':'2026-10-09','value':40}]},
                       {'id':'medium-erp-score','points':[{'date':'2026-10-09','value':10}]}]}
        s = synthesis_status(p,'2026-10-13')
        self.assertTrue(s['shortTerm']['current'])
        self.assertFalse(s['mediumTerm']['current'])
        self.assertIn('medium-erp-score',s['mediumTerm']['laggingInputs'])

    def test_excel_rows_exclude_uncompleted_dates(self):
        class Sheet:
            max_row = 2
            def iter_rows(self,**kwargs):
                return iter([(datetime(2026,10,13),1),(datetime(2026,10,14),999)])
        with patch.dict(os.environ,{'RQDATA_AS_OF':'2026-10-13'}):
            points = broad.read_series(Sheet(),1,{'value':2},start_row=1,end_row=2)
        self.assertEqual(len(points),1)
        self.assertEqual(points[0]['value'],1)
