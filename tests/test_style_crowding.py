import copy
import unittest
import urllib.error

from aido_style_crowding_refresh import CODES, FIELDS, band, build_snapshot, build_chart, validate_snapshot
from aido_crowding_cloud_sync import publish
from test_fund_exposure_cloud_sync import FakeGitHub


def raw(day='2026-10-19'):
    return {'as_of':day, 'data':[dict({'code':code,'name':code,'category':'style','trade_date':day},
                                    **{k:50 if k=='crowding_pct' else 0 for k in FIELDS}) for code in sorted(CODES)]}


class CrowdingTests(unittest.TestCase):
    def test_chart_uses_aligned_observation_means_not_sums(self):
        histories={code:{'code':code,'category':'style','data':[{'trade_date':f'2026-09-{i:02d}','crowding_score':float(i)} for i in range(1,26)]} for code in CODES}
        chart=build_chart(histories,'2026-09-25')
        self.assertEqual([p['values']['SIZE'] for p in chart['periods']],[23,18,15.5])
        self.assertEqual([p['count'] for p in chart['periods']],[5,5,20])
        histories['SIZE']['data'][-1]['crowding_score']=None
        with self.assertRaises(ValueError):build_chart(histories,'2026-09-25')

    def test_actual_dates_changes_and_no_direction_claims(self):
        latest, previous = raw(), raw('2026-10-08')
        latest['data'][0]['crowding_score'] = 1.5
        data = build_snapshot(latest, previous)
        validate_snapshot(data)
        self.assertEqual(data['comparisonDate'],'2026-10-08')
        self.assertEqual(data['factors'][0]['change'],1.5)
        self.assertTrue(all(r['directionVerified'] is False for r in data['factors']))
        self.assertNotIn('styles',data)
        self.assertNotIn('models',data)

    def test_boundary_bands(self):
        self.assertEqual([band(v) for v in [-1.5,-1,0,1,1.5]],['显著低位','偏低位','中性','偏拥挤','显著拥挤'])

    def test_partial_mixed_and_nonfinite_rejected(self):
        for mutate in [lambda r:r['data'].pop(), lambda r:r['data'][0].update(trade_date='2026-10-16'),
                       lambda r:r['data'][0].update(crowding_score=None), lambda r:r['data'][0].update(crowding_score=float('nan')),
                       lambda r:r['data'][0].update(crowding_score=True), lambda r:r['data'][0].update(crowding_pct=101)]:
            value=raw();mutate(value)
            with self.assertRaises(ValueError):build_snapshot(value)
        with self.assertRaises(ValueError):build_snapshot(raw(),raw())

    def test_unchanged_skip_and_atomic_conflict_retry(self):
        data=build_snapshot(raw(),raw('2026-10-12'))
        github=FakeGitHub(data)
        self.assertFalse(publish(github,data)['changed'])
        old=copy.deepcopy(data);old['factors'][0]['crowding_score']=.1
        github=FakeGitHub(old,conflict=True)
        self.assertTrue(publish(github,data)['changed'])
        trees=[d for _,p,d in github.calls if p=='/git/trees']
        self.assertEqual(len(trees),2)
        self.assertTrue(all(len(t['tree'])==1 and t['tree'][0]['path']=='style-crowding.json' for t in trees))
        self.assertTrue(all(d['force'] is False for m,_,d in github.calls if m=='PATCH'))

    def test_newer_remote_never_regresses(self):
        github=FakeGitHub({'asOf':'2026-10-20'})
        with self.assertRaises(ValueError):publish(github,build_snapshot(raw()))
        self.assertTrue(all(m=='GET' for m,_,_ in github.calls))


if __name__=='__main__':unittest.main()
