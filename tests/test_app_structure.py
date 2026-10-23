import re
import unittest
from pathlib import Path


class AppStructureTests(unittest.TestCase):
    def test_frappe_cloud_discovery_requirements(self):
        root = Path(__file__).resolve().parents[1]
        app = root / 'vortexus_discount_matrix'
        self.assertTrue((root / 'pyproject.toml').is_file())
        for name in ('__init__.py', 'hooks.py', 'patches.txt', 'modules.txt'):
            self.assertTrue((app / name).is_file(), f'Missing Frappe app file: {name}')
        hooks = (app / 'hooks.py').read_text(encoding='utf-8')
        self.assertRegex(hooks, r'app_title = "[^"]+"')
        self.assertIn('[post_model_sync]', (app / 'patches.txt').read_text(encoding='utf-8'))

    def test_custom_doctype_scripts_load_with_desk(self):
        # Frappe skips doctype_js for custom DocTypes; these must use app_include_js.
        app = Path(__file__).resolve().parents[1] / 'vortexus_discount_matrix'
        hooks = (app / 'hooks.py').read_text(encoding='utf-8')
        for script in ('approval', 'simulation'):
            self.assertIn(f'"/assets/vortexus_discount_matrix/js/{script}.js"', hooks)
            self.assertTrue((app / 'public' / 'js' / f'{script}.js').is_file())
        self.assertNotIn('doctype_js["VDM', hooks)
