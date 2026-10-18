import tempfile
from pathlib import Path
import unittest
from core import Settings,APP_VERSION,DEFAULT_TENCENT_KEY,DEFAULT_KEY_NOTICE
class ReleaseTests(unittest.TestCase):
    def test_version_and_notice(self):
        self.assertEqual(APP_VERSION,'1.0.1')
        self.assertIn('未来可能无法使用',DEFAULT_KEY_NOTICE)
        self.assertIn('自行申请',DEFAULT_KEY_NOTICE)
    def test_new_config_default_key(self):
        with tempfile.TemporaryDirectory() as d:
            s=Settings(Path(d)/'config.json')
            self.assertEqual(s.data['tencent_key'],DEFAULT_TENCENT_KEY)
            self.assertEqual(s.data['tencent_js_key'],DEFAULT_TENCENT_KEY)
    def test_existing_custom_keys_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'config.json'
            p.write_text('{"tencent_key":"OWN-WS","tencent_js_key":"OWN-JS","other":123}',encoding='utf-8')
            s=Settings(p)
            self.assertEqual(s.data['tencent_key'],'OWN-WS')
            self.assertEqual(s.data['tencent_js_key'],'OWN-JS')
            self.assertEqual(s.data['other'],123)
    def test_old_empty_config_defaults_and_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'config.json';p.write_text('{"tencent_key":"","tasktoken":"LOCAL"}',encoding='utf-8')
            s=Settings(p);s.save()
            self.assertEqual(Settings(p).data['tasktoken'],'LOCAL')
            self.assertEqual(Settings(p).data['tencent_key'],DEFAULT_TENCENT_KEY)
