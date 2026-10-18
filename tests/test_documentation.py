import ast
from pathlib import Path
import re
import struct
import unittest

ROOT = Path(__file__).resolve().parents[1]


class DocumentationTests(unittest.TestCase):
    def test_all_readme_images_exist(self):
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        images = re.findall(r'!\[[^\]]*\]\(([^)]+)\)', readme)
        self.assertEqual(len(images), 13)
        for image in images:
            with self.subTest(image=image):
                self.assertTrue((ROOT / image).is_file())

    def test_current_interface_screenshots_have_four_numbered_arrows(self):
        source = (ROOT / 'tests/capture_material_docs.py').read_text(encoding='utf-8')
        tree = ast.parse(source)
        scenes = next(ast.literal_eval(node.value) for node in tree.body
                      if isinstance(node, ast.Assign) and any(
                          isinstance(target, ast.Name) and target.id == 'SCENES'
                          for target in node.targets))
        self.assertEqual(len(scenes), 5)
        for scene, (_, name, marks) in scenes.items():
            with self.subTest(scene=scene):
                self.assertEqual([mark[0] for mark in marks], [1, 2, 3, 4])
                data = (ROOT / 'docs/screenshots' / name).read_bytes()
                self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
                self.assertEqual(struct.unpack('>II', data[16:24]), (1380, 880))
        self.assertIn('c.lineTo(tx,ty)', source)
        self.assertIn('QQuickWindow.grabWindow(window)', source)

    def test_readme_matches_current_ui_and_certificate_fix(self):
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        for value in ('2026-10-19', 'PEM', 'DER', 'ValueError', '1–4 编号',
                      'docs/screenshots/04-settings.png', '左下角 **设置**'):
            self.assertIn(value, readme)
        self.assertNotIn('右上角 **设置**', readme)


if __name__ == '__main__':
    unittest.main()
