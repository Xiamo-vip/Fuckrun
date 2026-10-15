import copy
import json
from pathlib import Path
import tempfile
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from core import Settings, token_text, summarize, valid_record, CampusClient, AuthExpired, coordinate, plan_route
from proxy_capture import ProxyLease, NAMES, extract_token
from map_view import map_html


class FakeRegistry:
    def __init__(self,values):
        self.values=copy.deepcopy(values)
        self.notifications=0
    def read(self,name):
        return copy.deepcopy(self.values.get(name,{'exists':False}))
    def write(self,name,state):
        self.values[name]=copy.deepcopy(state)
    def notify(self):
        self.notifications+=1


class DesktopTests(unittest.TestCase):
    def test_token_normalization(self):
        self.assertEqual(token_text(' Bearer sample-token '),'sample-token')
        for bad in ('','Bearer ','Bearer one two','one\ntwo'):
            with self.assertRaises(ValueError): token_text(bad)

    def test_exact_capture_host(self):
        self.assertEqual(extract_token('campusrun.mzwu.edu.cn','Bearer sample-token'),'sample-token')
        for host in ('campusrun.mzwu.edu.cn.evil.test','evil.test','campusrun.mzwu.edu.cn@evil.test'):
            self.assertIsNone(extract_token(host,'Bearer sample-token'))
        self.assertIsNone(extract_token('campusrun.mzwu.edu.cn','Basic sample-token'))
        self.assertIsNone(extract_token('campusrun.mzwu.edu.cn',None))

    def test_config_roundtrip_preserves_other_fields(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'config.json'
            path.write_text('{"other":123}',encoding='utf-8')
            s=Settings(path)
            s.data['tasktoken']='sample-token'
            s.save()
            self.assertEqual(Settings(path).data['tasktoken'],'sample-token')
            self.assertEqual(Settings(path).data['other'],123)
            self.assertFalse(path.with_suffix('.json.tmp').exists())

    def test_corrupt_config(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'config.json'
            path.write_text('[]',encoding='utf-8')
            with self.assertRaises(ValueError): Settings(path)

    def test_summary_validity_and_weighted_pace(self):
        rows=[{'distance':3,'duration':900,'is_completed':True},
              {'distance':1,'duration':420,'is_completed':True,'has_cheating':True},
              {'distance':'nan','duration':'oops'}]
        result=summarize(rows)
        self.assertEqual(result,{'distance':'4.00 km','count':'3','pace':'5′30″ /km','valid':'1'})
        self.assertIsNone(valid_record({}))
        self.assertFalse(valid_record({'is_completed':'0'}))

    def test_original_proxy_restored_exactly(self):
        values={'ProxyEnable':{'exists':True,'value':1,'type':4},
                'ProxyServer':{'exists':True,'value':'old-proxy:3128','type':1},
                'ProxyOverride':{'exists':False},
                'AutoConfigURL':{'exists':True,'value':'http://localhost/config.pac','type':1},
                'AutoDetect':{'exists':True,'value':1,'type':4}}
        with tempfile.TemporaryDirectory() as d:
            reg=FakeRegistry(values)
            lease=ProxyLease(reg,Path(d)/'backup.json')
            lease.begin(8080)
            self.assertEqual(reg.values['ProxyServer']['value'],'127.0.0.1:8080')
            self.assertFalse(reg.values['AutoConfigURL']['exists'])
            ProxyLease(reg,lease.journal).restore()
            self.assertEqual(reg.values,values)
            lease.restore()
            self.assertFalse(lease.journal.exists())

    def test_missing_registry_fields_restored(self):
        values={n:{'exists':False} for n in NAMES}
        with tempfile.TemporaryDirectory() as d:
            reg=FakeRegistry(values)
            lease=ProxyLease(reg,Path(d)/'backup.json')
            lease.begin(8080)
            with self.assertRaises(RuntimeError): lease.begin(8080)
            lease.restore()
            self.assertEqual(reg.values,values)

    def test_partial_write_failure_restored(self):
        values={n:{'exists':False} for n in NAMES}
        class Failure(FakeRegistry):
            once=True
            def write(self,name,state):
                if name=='ProxyServer' and self.once:
                    self.once=False
                    raise OSError('simulated write error')
                super().write(name,state)
        with tempfile.TemporaryDirectory() as d:
            reg=Failure(values)
            lease=ProxyLease(reg,Path(d)/'backup.json')
            with self.assertRaises(OSError): lease.begin(8080)
            self.assertEqual(reg.values,values)
            self.assertFalse(lease.journal.exists())

    def test_dashboard_get_only_pagination_dedup(self):
        urls=[]
        def fetch(url,token):
            urls.append(url)
            self.assertEqual(token,'sample-token')
            if '/login/' in url:return {'code':200,'data':{'student_name':'Demo'}}
            if '/get_student_running_record?' in url:
                return {'code':200,'records':[{'running_record':{'id':1,'distance':3}}]}
            return {'code':200,'current_user_rank':{'rank':2},'rank_list':[]}
        data=CampusClient('sample-token',fetch).dashboard()
        self.assertEqual(len(data['records']),1)
        self.assertEqual(len(urls),4)
        self.assertTrue(any('record_type=makeup' in u for u in urls))
        self.assertFalse(any('create_running' in u or 'upload' in u for u in urls))

    def test_empty_summary(self):
        self.assertEqual(summarize([])['pace'],'—')

    def test_route_decode_and_validation(self):
        def fetch(url):
            self.assertIn('from=25.0%2C118.0',url)
            return {'status':0,'result':{'routes':[{'distance':50,'duration':1,'polyline':[25,118,100,200]}]}}
        route=plan_route('sample-key','25,118','25.1,118.1',fetch)
        self.assertAlmostEqual(route['points'][1][0],25.0001)
        self.assertAlmostEqual(route['points'][1][1],118.0002)
        for bad in ('nan,1','91,2','0,181','1','a,b'):
            with self.assertRaises(ValueError):coordinate(bad)

    def test_map_key_is_escaped(self):
        html=map_html('</script><script>bad()</script>',[(25,118)])
        self.assertNotIn('<script>bad()',html)
        self.assertIn('new TMap.Map',html)


if __name__=='__main__':
    unittest.main()
