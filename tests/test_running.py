import copy
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import CampusClient
from running import generate_plan, route_length, target_km, RunSession, distance

CPS=[{'id':1,'latitude':25.,'longitude':118.,'radius':10},
     {'id':2,'latitude':25.001,'longitude':118.001,'radius':10}]


def make_plan(variant=0,km=1):
    return generate_plan(CPS,'SYNTHETIC_KEY',km,variant,leg=lambda a,b:{'points':[a,b]})


class RunningTests(unittest.TestCase):
    def test_fetch_checkpoints_get_only(self):
        calls=[]
        def fetch(url,token):
            calls.append(url)
            return {'code':200,'data':CPS}
        self.assertEqual(len(CampusClient('SYNTHETIC_TOKEN',fetch).checkpoints()),2)
        self.assertEqual(len(calls),1)
        self.assertTrue(calls[0].endswith('/get_checkpoints'))

    def test_plan_hits_checkpoints_distance_and_density(self):
        p=make_plan()
        self.assertAlmostEqual(route_length(p['points']),1000,delta=.1)
        self.assertTrue(all(distance(a,b)<=4.51 for a,b in zip(p['points'],p['points'][1:])))
        for cp in CPS:
            self.assertLess(min(distance((cp['latitude'],cp['longitude']),point) for point in p['points']),cp['radius'])
        self.assertEqual(p['duration_seconds'],int(p['km']*p['pace_seconds']))

    def test_refresh_returns_different_route(self):
        self.assertNotEqual(make_plan(1)['points'],make_plan(2)['points'])

    def test_target_validation_and_short_target(self):
        for bad in ('nan','inf','bad',0,100):
            with self.assertRaises(ValueError):target_km(bad)
        with self.assertRaises(ValueError):make_plan(km=.1)

    def test_no_embedded_personal_map_key(self):
        import protocol
        self.assertFalse(hasattr(protocol,'MAP_KEY'))

    def session(self,override=None,cancel_at=None):
        plan=make_plan()
        clock=[1700000000000]
        calls=[];events=[]
        holder={}
        def emit(name,data):events.append((name,data))
        def transport(path,payload=None):
            calls.append((path,payload))
            if path=='/login/wechat/info':return {'data':{'student_number':'TEST'}}
            if path=='/create_running_record':
                return {'data':{'record_id':7,'run_session_id':'SESSION','session_salt':'SALT','checkpoints':override or CPS}}
            if path==cancel_at:holder['session'].stop()
            return {'code':200}
        def wait(seconds):clock[0]+=max(1,int(seconds*1000))
        s=RunSession('SYNTHETIC_TOKEN',plan,emit,transport,lambda:clock[0],wait)
        holder['session']=s
        return s,calls,events

    def test_full_run_orders_chunks_and_finish(self):
        session,calls,events=self.session()
        session.run()
        paths=[p for p,_ in calls]
        self.assertEqual(paths[:2],['/login/wechat/info','/create_running_record'])
        self.assertEqual(paths[-1],'/finish_running_record')
        self.assertEqual(paths.count('/create_running_record'),1)
        self.assertTrue(all(p=='/upload_running_chunk' for p in paths[2:-1]))
        self.assertTrue(any(n=='run_finished' for n,_ in events))
        finish=calls[-1][1]
        self.assertEqual(finish['client_distance'],1)
        self.assertTrue(all(c['reached'] for c in finish['client_checkpoint_data']))

    def test_cancel_after_chunk_does_not_finish(self):
        session,calls,events=self.session(cancel_at='/upload_running_chunk')
        session.run()
        self.assertFalse(any(p=='/finish_running_record' for p,_ in calls))
        self.assertTrue(any(n=='run_stopped' for n,_ in events))

    def test_changed_checkpoint_stops_before_upload(self):
        other=[{'id':9,'latitude':30,'longitude':120,'radius':10}]
        session,calls,events=self.session(override=other)
        session.run()
        self.assertEqual(len(calls),2)
        self.assertTrue(any(n=='run_error' for n,_ in events))

    def test_transport_failure_waits_until_stopped(self):
        session,calls,events=self.session()
        original=session.transport
        failures=[]
        def failing(path,payload=None):
            if path=='/upload_running_chunk':
                failures.append(path)
                raise RuntimeError('synthetic network failure')
            return original(path,payload)
        session.transport=failing
        original_emit=session.emit
        def emit(n,d):
            original_emit(n,d)
            if n=='run_retry_wait':session.stop()
        session.emit=emit
        session.run()
        self.assertEqual(len(failures),1)
        self.assertTrue(any(n=='run_retry_wait' for n,_ in events))
        self.assertTrue(any(n=='run_stopped' for n,_ in events))

    def test_cancel_before_start_does_not_create(self):
        session,calls,events=self.session()
        session.stop();session.run()
        self.assertFalse(calls)

    def test_changed_checkpoint_first_confirmation_finishes_same_record(self):
        other=[{'id':9,'latitude':30.,'longitude':120.,'radius':10}]
        session,calls,events=self.session(override=other)
        session.replan=lambda cps:generate_plan(cps,'SYNTHETIC_KEY',1,4,leg=lambda a,b:{'points':[a,b]},jitter=dict(enabled=True,seed='42'))
        session.run()
        self.assertTrue(any(n=='run_plan_updated' for n,_ in events))
        self.assertTrue(any(n=='run_finished' for n,_ in events))
        self.assertFalse(any(n in ('run_error','run_replanned') for n,_ in events))
        self.assertEqual(sum(p=='/create_running_record' for p,_ in calls),1)
        self.assertEqual(calls[-1][0],'/finish_running_record')
        self.assertEqual(calls[-1][1]['record_id'],7)
        self.assertEqual(calls[-1][1]['client_checkpoint_data'][0]['id'],9)
        self.assertTrue(calls[-1][1]['client_checkpoint_data'][0]['reached'])
        self.assertEqual(session.plan['jitter']['seed'],'42')
        order=[n for n,_ in events]
        self.assertLess(order.index('run_plan_updated'),order.index('run_started'))

    def test_invalid_replan_does_not_upload_or_create_again(self):
        session,calls,events=self.session(override=[dict(id=9,latitude=30.,longitude=120.,radius=10)])
        session.replan=lambda cps:make_plan()
        session.run()
        self.assertEqual(len(calls),2)
        ready=next(d for n,d in events if n=='run_replanned')
        self.assertIsNone(ready['plan'])
        self.assertEqual(ready['session']['record_id'],7)

    def test_cancel_during_replan_does_not_upload(self):
        session,calls,events=self.session(override=[dict(id=9,latitude=30.,longitude=120.,radius=10)])
        def replan(cps):
            session.stop()
            return generate_plan(cps,'OFFLINE',1,leg=lambda a,b:{'points':[a,b]})
        session.replan=replan
        session.run()
        self.assertEqual(len(calls),2)
        self.assertTrue(any(n=='run_stopped' for n,_ in events))
        self.assertFalse(any(n=='run_started' for n,_ in events))

    def test_replan_failure_preserves_session_for_km_adjustment(self):
        session,calls,events=self.session(override=[{'id':9,'latitude':30.,'longitude':120.,'radius':10}])
        def replan(cps):raise ValueError('increase km')
        session.replan=replan
        session.run()
        ready=next(d for n,d in events if n=='run_replanned')
        self.assertIsNone(ready['plan'])
        self.assertEqual(ready['session']['record_id'],7)
        self.assertEqual(ready['message'],'increase km')

    def test_request_log_contains_metadata_not_sensitive_payload(self):
        import json
        session,calls,events=self.session()
        session.run()
        logs=[d for n,d in events if n=='request_log']
        self.assertEqual(len(logs),2*len(calls))
        self.assertTrue(all(d['phase'] in ('sending','success') for d in logs))
        text=json.dumps(logs)
        for secret in ('SYNTHETIC_TOKEN','SESSION','SALT','Authorization','chunk_hash','"points"'):
            self.assertNotIn(secret,text)
        uploads=[d for d in logs if d['path']=='/upload_running_chunk' and d['phase']=='success']
        self.assertTrue(uploads)
        self.assertTrue(all(d['point_count']>0 and d['chunk_seq']>0 for d in uploads))

    def test_http_failure_logged_without_echoed_token_waits_for_user(self):
        session,calls,events=self.session()
        session.transport=lambda *args:(_ for _ in ()).throw(RuntimeError('HTTP 401 Bearer SYNTHETIC_TOKEN'))
        original_emit=session.emit
        def emit(n,d):
            original_emit(n,d)
            if n=='run_retry_wait':
                self.assertFalse(d['automatic'])
                session.stop()
        session.emit=emit
        session.run()
        failures=[d for n,d in events if n=='request_log' and d['phase']=='error']
        self.assertEqual(len(failures),1)
        self.assertEqual(failures[0]['code'],401)
        self.assertNotIn('SYNTHETIC_TOKEN',str(events))
