import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from map_view import map_html
from updater import is_newer, latest_release, version_tuple
from proxy_capture import (capture_error_message, certificate_info, certificate_status,
                           proxy_option_values, proxy_options, repair_certificate, rotate_invalid_ca)


class MaterialInterfaceTests(unittest.TestCase):
    def test_all_pages_use_a_borderless_layout_container(self):
        qml = (ROOT / 'ui/Main.qml').read_text(encoding='utf-8')
        self.assertIn('component SurfacePage: Item {}', qml)
        self.assertNotIn('component SurfacePage: Rectangle', qml)
        self.assertEqual(qml.count('                SurfacePage {'), 6)
        self.assertIn('component MetricCard: MD3.Card', qml)

    def test_material_components_are_vendored_from_requested_project(self):
        upstream = (ROOT / 'third_party/material-components-pyside/UPSTREAM.md').read_text(encoding='utf-8-sig')
        self.assertIn('sudoevolve/material-components-pyside', upstream)
        self.assertIn('d58599ed510d3939238ecfba61206423fa5c5275', upstream)
        self.assertTrue((ROOT / 'third_party/material-components-pyside/src/Core/Controls/Button.qml').exists())
        self.assertTrue((ROOT / 'third_party/material-components-pyside/src/md3/Core/qmldir').exists())
        self.assertFalse((ROOT / 'third_party/material-components-pyside/src/Extras').exists())

    def test_qml_uses_material_components_and_native_web_engine(self):
        qml = (ROOT / 'ui/Main.qml').read_text(encoding='utf-8')
        for text in ('import md3.Core as MD3', 'MD3.NavigationRail', 'MD3.Card', 'MD3.Button', 'WebEngineView'):
            self.assertIn(text, qml)
        self.assertNotIn('Tkinter', qml)
        self.assertIn('settings.localStorageEnabled: true', qml)
        self.assertNotIn('settings.localStorageEnabled: false', qml)
        for label in ('验证证书', '安装证书', '一键修复', '安装并验证'):
            self.assertIn(label, qml)

    def test_map_document_has_full_viewport_and_resize_hook(self):
        html = map_html('SYNTHETIC', [[25, 118], [25.001, 118.001]], [])
        self.assertIn('#map{position:absolute;inset:0', html)
        self.assertIn('GHOSTRUNNER_FORCE_RESIZE', html)
        self.assertIn('ResizeObserver', html)
        self.assertIn('api/gljs?v=1&key=', html)
        self.assertNotIn('fitBounds(', html)

    def test_packaged_qt_icu_conflict_is_removed_before_pyside_import(self):
        hook = (ROOT / 'packaging/pyi_rth_qt_icu.py').read_text(encoding='utf-8')
        self.assertIn('root.name.startswith("_MEI")', hook)
        self.assertIn('"icuuc.dll"', hook)
        build = (ROOT / 'build.ps1').read_text(encoding='utf-8')
        self.assertIn("--runtime-hook 'packaging/pyi_rth_qt_icu.py'", build)


class UpdateTests(unittest.TestCase):
    def test_version_ordering(self):
        self.assertEqual(version_tuple('v1.2.10'), (1, 2, 10))
        self.assertTrue(is_newer('v1.1', '1.0'))
        self.assertFalse(is_newer('1.0.0', '1.0'))
        self.assertFalse(is_newer('0.9.9', '1.0'))

    def test_release_normalization(self):
        payload = json.dumps({'tag_name': 'v1.2.0', 'html_url': 'https://github.com/Xiamo-vip/Fuckrun/releases/tag/v1.2.0',
                              'name': 'GhostRunner 1.2', 'body': 'changes'}).encode()
        value = latest_release('1.0', fetch=lambda request: payload)
        self.assertEqual(value['version'], '1.2.0')
        self.assertEqual(value['notes'], 'changes')

    def test_non_github_or_old_release_is_ignored(self):
        old = json.dumps({'tag_name': 'v1.0', 'html_url': 'https://github.com/Xiamo-vip/Fuckrun/releases/tag/v1.0'}).encode()
        bad = json.dumps({'tag_name': 'v9.0', 'html_url': 'https://example.test/update'}).encode()
        self.assertIsNone(latest_release('1.0', fetch=lambda request: old))
        self.assertIsNone(latest_release('1.0', fetch=lambda request: bad))


class CertificatePreflightTests(unittest.TestCase):
    def test_missing_and_untrusted_certificate_diagnostics(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = certificate_status(directory, trust_checker=lambda *_args, **_kwargs: False)
            self.assertEqual(missing['state'], 'missing')
            self.assertFalse(missing['ok'])

    def test_capture_error_keeps_known_setup_reason_but_hides_unknown_details(self):
        self.assertIn('端口 8080', capture_error_message(OSError(10048, 'occupied')))
        self.assertIn('代理启动失败', capture_error_message(RuntimeError('代理启动失败')))
        message = capture_error_message(RuntimeError('Authorization: Bearer SECRET'))
        self.assertNotIn('SECRET', message)
        self.assertIn('一键修复', message)

    def test_repair_backs_up_and_regenerates_ca_without_enabling_proxy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            confdir, backups = root / 'conf', root / 'backups'
            confdir.mkdir()
            (confdir / 'mitmproxy-ca-cert.cer').write_bytes(b'broken-certificate')
            (confdir / 'mitmproxy-ca.pem').write_bytes(b'broken-private-set')
            trusted = {'ok': True, 'state': 'trusted', 'message': '已验证'}
            with patch('proxy_capture.install_cert', return_value={'store': 'CurrentUser'}), \
                 patch('proxy_capture.certificate_status', return_value=trusted):
                result = repair_certificate(confdir, backups)
            backup = Path(result['backup'])
            self.assertEqual((backup / 'mitmproxy-ca-cert.cer').read_bytes(), b'broken-certificate')
            self.assertEqual((backup / 'mitmproxy-ca.pem').read_bytes(), b'broken-private-set')
            thumbprint, _ = certificate_info(confdir / 'mitmproxy-ca-cert.cer')
            self.assertEqual(len(thumbprint), 40)

    def test_repair_restores_original_files_when_installation_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            confdir = root / 'conf'
            confdir.mkdir()
            original = b'original-ca-set'
            (confdir / 'mitmproxy-ca.pem').write_bytes(original)
            with patch('proxy_capture.install_certificate', side_effect=RuntimeError('证书安装失败')):
                with self.assertRaises(RuntimeError):
                    repair_certificate(confdir, root / 'backups')
            self.assertEqual((confdir / 'mitmproxy-ca.pem').read_bytes(), original)
    def test_proxy_option_shape_rejects_removed_mitmproxy_setting(self):
        """proxy_options must silently defer unknown option names instead of
        raising KeyError, so that cross-version mitmproxy compatibility works."""
        seen = {}
        deferred = {}
        class FlexibleOptions:
            def __init__(self, **values):
                seen.update(values)
            def update_defer(self, **values):
                allowed = {'listen_host', 'listen_port', 'confdir', 'allow_hosts'}
                for k, v in values.items():
                    if k in allowed:
                        seen[k] = v
                    else:
                        deferred[k] = v
        options = proxy_options('state/mitmproxy', options_type=FlexibleOptions)
        self.assertIsInstance(options, FlexibleOptions)
        self.assertNotIn('connection_strategy', proxy_option_values('state/mitmproxy'))
        self.assertEqual(seen['listen_port'], 8080)

    def test_mitmproxy_12_options_do_not_use_removed_connection_strategy(self):
        with tempfile.TemporaryDirectory() as directory:
            options = proxy_options(directory)
            self.assertEqual(options.listen_host, '127.0.0.1')
            self.assertEqual(options.listen_port, 8080)
            self.assertEqual(options.allow_hosts, [r'^campusrun\.mzwu\.edu\.cn(?::\d+)?$'])

    def test_valid_ca_is_accepted_and_invalid_set_is_rotated(self):
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import rsa
        from cryptography.x509.oid import NameOID
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
            name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'GhostRunner Test CA')])
            now = datetime.now(timezone.utc)
            cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
                    .serial_number(x509.random_serial_number()).not_valid_before(now - timedelta(days=1))
                    .not_valid_after(now + timedelta(days=30)).add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
                    .sign(key, hashes.SHA256()))
            path = root / 'mitmproxy-ca-cert.cer'
            path.write_bytes(cert.public_bytes(serialization.Encoding.DER))
            thumbprint, expires = certificate_info(path)
            self.assertEqual(len(thumbprint), 40)
            self.assertGreater(expires, now)
            self.assertFalse(rotate_invalid_ca(root))
            # mitmproxy 12 writes mitmproxy-ca-cert.cer in PEM format.  The
            # extension must not make certificate_info force the DER parser.
            path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
            pem_thumbprint, pem_expires = certificate_info(path)
            self.assertEqual(pem_thumbprint, thumbprint)
            self.assertEqual(pem_expires, expires)
            self.assertFalse(rotate_invalid_ca(root))
            path.write_bytes(b'not-a-certificate')
            (root / 'mitmproxy-ca.pem').write_text('stale', encoding='utf-8')
            self.assertTrue(rotate_invalid_ca(root))
            self.assertFalse(path.exists())
            self.assertFalse((root / 'mitmproxy-ca.pem').exists())
