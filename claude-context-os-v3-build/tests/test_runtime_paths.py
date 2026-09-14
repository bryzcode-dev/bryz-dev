import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from context_os.knowledge import add_knowledge, search_knowledge
from context_os.ops import runtime_for
from context_os.registry import find_projects, register_project

ROOT = Path(__file__).resolve().parents[1]


class RuntimePathTests(unittest.TestCase):
    def test_runtime_for_expands_shared_template_under_current_home(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td); root = base / 'shared'; home = base / 'home'
            config = root / 'context-os/config/context-os.json'
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps({'paths': {
                'runtime_root': '~/Library/Application Support/ClaudeContextOS/home'
            }}))
            with mock.patch('context_os.config.Path.home', return_value=home):
                self.assertEqual(
                    runtime_for(root),
                    (home / 'Library/Application Support/ClaudeContextOS/home').resolve(),
                )

    def test_runtime_for_rejects_nas_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / 'shared'
            config = root / 'context-os/config/context-os.json'
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps({'paths': {
                'runtime_root': '/Volumes/BryzConfig/Claude/runtime'
            }}))
            with self.assertRaisesRegex(RuntimeError, 'runtime path must be local'):
                runtime_for(root)

    def test_compatibility_helpers_use_expanded_local_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td); root = base / 'shared'; home = base / 'home'
            config = root / 'context-os/config/context-os.json'
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps({'paths': {
                'runtime_root': '~/Library/Application Support/ClaudeContextOS/home'
            }}))
            item = {
                'id': 'MEM-PORTABLE', 'title': 'Portable runtime',
                'summary': 'The knowledge index stays on local storage.',
                'status': 'active', 'verified': True,
            }
            with mock.patch('context_os.config.Path.home', return_value=home):
                add_knowledge(root, item)
                self.assertEqual(search_knowledge(root, 'portable')[0]['id'], 'MEM-PORTABLE')
                register_project(root, {'project_id': 'portable-project'}, str(base / 'project'))
                self.assertEqual(find_projects(root, 'portable')[0]['project_id'], 'portable-project')
            runtime = home / 'Library/Application Support/ClaudeContextOS/home'
            self.assertTrue((runtime / 'context.db').exists())
            self.assertFalse((Path.cwd() / '~').exists())

    def test_service_plist_expands_portable_runtime_template(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td); root = base / 'shared'; home = base / 'home'
            config = root / 'context-os/config/context-os.json'
            template = root / 'context-os/runtime/launchd/com.contextos.v3.maintain.plist.template'
            config.parent.mkdir(parents=True)
            template.parent.mkdir(parents=True)
            config.write_text(json.dumps({'paths': {
                'runtime_root': '~/Library/Application Support/ClaudeContextOS/home'
            }}))
            template.write_text('__RUNTIME_ROOT__')
            output = base / 'maintain.plist'
            env = os.environ.copy(); env['HOME'] = str(home)
            result = subprocess.run([
                'python3', str(ROOT / 'contextctl.py'), 'service-plist',
                '--root', str(root), '--output', str(output),
            ], text=True, capture_output=True, env=env, cwd=ROOT)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                output.read_text(),
                str((home / 'Library/Application Support/ClaudeContextOS/home').resolve()),
            )


if __name__ == '__main__':
    unittest.main()
