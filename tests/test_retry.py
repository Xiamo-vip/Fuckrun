import copy
import unittest
from running import RunSession, RequestFailure
from test_running import make_plan, CPS

class RetryTests(unittest.TestCase):
    def scenario(self, fail_path, failures=1, error=None, react=None):
        calls=[];events=[];clock=[1700000000000];holder={};failed=[0]
        def emit(n,d):
            events.append((n,d))
            if react:react(holder['s'],n,d)
        def send(path,payload=None):
            calls.append((path,copy.deepcopy(payload)))
            if path==fail_path and failed[0]<failures:
                failed[0]+=1
                raise error or RuntimeError('HTTP 503: synthetic')
            if path=='/login/wechat/info':return dict(data=dict(student_number='TEST'))
            if path=='/create_running_record':return dict(data=dict(record_id=7,run_session_id='SESSION',session_salt='SALT',checkpoints=CPS))
            return dict(code=200)
        def wait(sec):clock[0]+=max(1,int(sec*1000))
        s=RunSession('TOKEN',make_plan(),emit,send,lambda:clock[0],wait)
        holder['s']=s
        s.run()
        return s,calls,events

    def test_chunk_auto_retries_same_payload_and_finishes(self):
        s,calls,events=self.scenario('/upload_running_chunk',failures=3)
        chunk=[p for path,p in calls if path=='/upload_running_chunk']
        self.assertTrue(all(p==chunk[0] for p in chunk[:4]))
        self.assertEqual(sum(path=='/create_running_record' for path,_ in calls),1)
        self.assertTrue(any(n=='run_finished' for n,_ in events))
        starts={d['attempt']:d['remaining'] for n,d in reversed(events) if n=='run_retry_wait'}
        self.assertEqual(starts,{2:10,3:20,4:40})
        self.assertEqual(sum(n=='run_upload' for n,_ in events),len([p for path,p in calls if path=='/upload_running_chunk'])-3+1)

    def test_finish_retries_same_payload(self):
        _,calls,events=self.scenario('/finish_running_record')
        payloads=[p for path,p in calls if path=='/finish_running_record']
        self.assertEqual(len(payloads),2)
        self.assertEqual(payloads[0],payloads[1])
        self.assertTrue(any(n=='run_finished' for n,_ in events))

    def test_get_timeout_auto_retries(self):
        _,calls,events=self.scenario('/login/wechat/info',error=TimeoutError())
        self.assertEqual(sum(p=='/login/wechat/info' for p,_ in calls),2)
        self.assertTrue(any(n=='run_finished' for n,_ in events))

    def test_immediate_retry_skips_countdown(self):
        def react(s,n,d):
            if n=='run_retry_wait':s.retry_now()
        _,_,events=self.scenario('/upload_running_chunk',react=react)
        waits=[d for n,d in events if n=='run_retry_wait']
        self.assertEqual(len(waits),1)
        self.assertTrue(any(n=='run_finished' for n,_ in events))

    def test_stop_during_wait_does_not_finish(self):
        def react(s,n,d):
            if n=='run_retry_wait':s.stop()
        _,calls,events=self.scenario('/upload_running_chunk',react=react)
        self.assertEqual(sum(p=='/upload_running_chunk' for p,_ in calls),1)
        self.assertFalse(any(p=='/finish_running_record' for p,_ in calls))
        self.assertTrue(any(n=='run_stopped' for n,_ in events))
        self.assertFalse(any(n=='run_error' for n,_ in events))

    def test_create_ambiguous_failure_waits_for_manual_decision(self):
        def react(s,n,d):
            if n=='run_retry_wait':
                self.assertFalse(d['automatic'])
                self.assertIsNone(d['remaining'])
                s.stop()
        _,calls,_=self.scenario('/create_running_record',react=react)
        self.assertEqual(sum(p=='/create_running_record' for p,_ in calls),1)

    def test_auth_failure_waits_without_automatic_retries(self):
        def react(s,n,d):
            if n=='run_retry_wait':
                self.assertFalse(d['automatic'])
                s.stop()
        _,calls,events=self.scenario('/login/wechat/info',error=RequestFailure(401),react=react)
        self.assertEqual(len(calls),1)
        self.assertTrue(any(n=='run_stopped' for n,_ in events))

    def test_business_transient_code_retries(self):
        _,_,events=self.scenario('/upload_running_chunk',error=RequestFailure(503))
        self.assertTrue(any(n=='run_finished' for n,_ in events))
