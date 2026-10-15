from pathlib import Path
import importlib.util
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from map_view import ResizeGuard


class EmbeddingTests(unittest.TestCase):
    def test_unchanged_size_does_not_resize(self):
        guard=ResizeGuard()
        self.assertTrue(guard.changed(800,500))
        self.assertTrue(all(not guard.changed(800,500) for _ in range(100)))
        self.assertTrue(guard.changed(900,500))
        self.assertFalse(guard.changed(900,500))

    def test_minimum_dimensions(self):
        guard=ResizeGuard()
        self.assertTrue(guard.changed(0,0))
        self.assertEqual(guard.previous,(1,1))
        self.assertFalse(guard.changed(-5,0))
