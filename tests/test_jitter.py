import copy
import math
import tempfile
from pathlib import Path
import unittest
from core import Settings
from running import generate_plan, jitter_config, jitter_points, route_length, distance
from test_running import CPS

class JitterTests(unittest.TestCase):
    def plan(self, **config):
        return generate_plan(CPS,'OFFLINE',1,leg=lambda a,b:{'points':[a,b]},jitter=config)

    def test_default_and_zero_unchanged(self):
        p=self.plan()
        self.assertEqual(p['points'],p['base_points'])
        self.assertEqual(p['km'],1)
        zero=self.plan(enabled=True,amplitude_m=0)
        self.assertEqual(zero['points'],p['points'])

    def test_bound_and_finite(self):
        for amplitude in (.01,3,20):
            p=self.plan(enabled=True,amplitude_m=amplitude,seed='42')
            offsets=[distance(a,b) for a,b in zip(p['base_points'],p['points'])]
            self.assertGreater(max(offsets),0)
            self.assertLessEqual(max(offsets),amplitude+1e-6)
            self.assertTrue(all(math.isfinite(x) for pt in p['points'] for x in pt))
            self.assertEqual(len(p['points']),len(p['base_points']))

    def test_anchors_and_original_not_mutated(self):
        p=self.plan(enabled=True,seed='42')
        self.assertEqual(p['points'][0],p['base_points'][0])
        self.assertEqual(p['points'][-1],p['base_points'][-1])
        for cp in CPS:
            center=(cp['latitude'],cp['longitude'])
            i=min(range(len(p['points'])),key=lambda i:distance(center,p['base_points'][i]))
            self.assertEqual(p['points'][i],p['base_points'][i])
        before=copy.deepcopy(p['base_points'])
        jitter_points(p['base_points'],CPS,p['jitter'])
        self.assertEqual(before,p['base_points'])

    def test_seed_reproducible_and_auto_seed_saved(self):
        p=self.plan(enabled=True,seed='42')
        self.assertEqual(p['points'],self.plan(enabled=True,seed='42')['points'])
        self.assertNotEqual(p['points'],self.plan(enabled=True,seed='43')['points'])
        auto=self.plan(enabled=True)
        self.assertTrue(auto['jitter']['seed'].isdecimal())
        self.assertEqual(auto['points'],self.plan(**auto['jitter'])['points'])

    def test_smoothing_limits_adjacent_offset_change(self):
        points=[(25+i*.00004,118) for i in range(1000)]
        def movement(span):
            shifted,_=jitter_points(points,[],dict(enabled=True,amplitude_m=20,smooth_points=span,seed='42'))
            offsets=[((b[0]-a[0])*111320,(b[1]-a[1])*111320*math.cos(math.radians(25))) for a,b in zip(points,shifted)]
            return max(math.dist(a,b) for a,b in zip(offsets,offsets[1:]))
        self.assertLess(movement(100),movement(2))
        self.assertLess(movement(100),1)

    def test_actual_distance_duration_consistent(self):
        p=self.plan(enabled=True,amplitude_m=20,seed='42')
        self.assertEqual(p['requested_km'],1)
        self.assertAlmostEqual(p['km']*1000,route_length(p['points']))
        self.assertEqual(p['duration_seconds'],int(p['km']*p['pace_seconds']))

    def test_validation(self):
        for field,values in [('amplitude_m',[-1,21,'nan','inf','bad']),('smooth_points',[0,1,101,2.5,'nan']),('seed',['-1','4294967296','x','1.2'])]:
            for value in values:
                with self.subTest(field=field,value=value),self.assertRaises(ValueError):
                    jitter_config({field:value})

    def test_config_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            s=Settings(Path(d)/'config.json')
            s.data['route_jitter']=jitter_config(dict(enabled=True,amplitude_m=4.5,smooth_points=20,seed='42'))
            s.save()
            self.assertEqual(Settings(s.path).data['route_jitter'],s.data['route_jitter'])

    def test_serialized_points_match_preview(self):
        from protocol import prepare_tasks
        p=self.plan(enabled=True,amplitude_m=5,seed='42')
        ctx=dict(record_id=1,run_session_id='OFFLINE',student_number='TEST',session_salt='SALT',start_ms=1700000000000,checkpoints=CPS)
        tasks=prepare_tasks(ctx,p['points'],p['km'],p['pace_seconds'],p['cadence'])
        uploaded=[(point['latitude'],point['longitude']) for _,path,payload in tasks if path=='/upload_running_chunk' for point in payload['points']]
        expected=[(round(a,6),round(b,6)) for a,b in p['points']]
        self.assertEqual(uploaded,expected)
        self.assertEqual(tasks[-1][2]['client_distance'],p['km'])
