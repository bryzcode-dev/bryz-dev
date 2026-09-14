import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from context_os.db import ContextDB
from context_os.registry import ProjectRegistry

ROOT = Path(__file__).resolve().parents[1]
HOOKS = ROOT / 'template_root' / 'hooks'


def run_hook(name, payload, cwd=None, env=None):
    e = os.environ.copy()
    e.setdefault('CONTEXT_OS_ACTIVITY_LOG', os.devnull)
    if env:
        e.update(env)
    return subprocess.run(
        ['python3', str(HOOKS / name)],
        input=json.dumps(payload), text=True, capture_output=True, cwd=cwd, env=e
    )


class HookTests(unittest.TestCase):
    def test_hook_runtime_rejects_nas_path_in_config(self):
        with tempfile.TemporaryDirectory() as td:
            home = Path(td) / 'context-os'
            config = home / 'config' / 'context-os.json'
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps({'paths': {
                'runtime_root': '/Volumes/BryzConfig/Claude/runtime'
            }}))
            hook_dir = ROOT / 'template_root/context-os/runtime/hooks'
            code = (
                'import sys; '
                f'sys.path.insert(0,{str(hook_dir)!r}); '
                'import _common; print(_common.runtime_root())'
            )
            env = os.environ.copy(); env['CONTEXT_OS_HOME'] = str(home)
            result = subprocess.run(
                ['python3', '-c', code], text=True, capture_output=True, env=env
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('runtime path must be local', result.stderr)

    def test_pretool_allows_safe_command(self):
        p = run_hook('pre_tool_guard.py', {'tool_name': 'Bash', 'tool_input': {'command': 'git status'}})
        self.assertEqual(p.returncode, 0)
        self.assertEqual(p.stdout.strip(), '')

    def test_pretool_denies_destructive_command(self):
        p = run_hook('pre_tool_guard.py', {'tool_name': 'Bash', 'tool_input': {'command': 'git reset --hard HEAD~1'}})
        self.assertEqual(p.returncode, 0)
        out = json.loads(p.stdout)
        self.assertEqual(out['hookSpecificOutput']['permissionDecision'], 'deny')

    def test_session_start_emits_project_context(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / '.claude').mkdir()
            (root / '.claude' / 'project.json').write_text(json.dumps({
                'project_id': 'demo', 'name': 'Demo', 'type': ['GAS', 'BigQuery'],
                'protected_surfaces': ['production deployment']
            }))
            (root / '.claude' / 'state.md').write_text('# Current Project State\n\n## Current Objective\nFix joins\n')
            p = run_hook('session_start.py', {}, cwd=root, env={'CLAUDE_PROJECT_DIR': str(root)})
            self.assertEqual(p.returncode, 0)
            self.assertIn('demo', p.stdout)
            self.assertIn('Fix joins', p.stdout)

    def test_session_start_expands_portable_runtime_for_registered_project(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td); root = base / 'shared'; home = base / 'home'
            project = base / 'registered-project'; project.mkdir()
            context_home = root / 'context-os'
            config = context_home / 'config/context-os.json'
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps({'paths': {
                'runtime_root': '~/Library/Application Support/ClaudeContextOS/home'
            }}))
            runtime = home / 'Library/Application Support/ClaudeContextOS/home'
            db = ContextDB(runtime / 'context.db').initialize()
            ProjectRegistry(root, db).register({
                'project_id': 'registered', 'name': 'Registered Project',
                'path': str(project),
            })
            db.close()
            p = run_hook('session_start.py', {}, cwd=project, env={
                'CLAUDE_PROJECT_DIR': str(project),
                'CONTEXT_OS_HOME': str(context_home),
                'HOME': str(home),
                'PYTHONPATH': str(ROOT),
            })
            self.assertEqual(p.returncode, 0, p.stderr)
            self.assertIn('Registered Project', p.stdout)

    def test_posttool_log_does_not_write_tool_output(self):
        with tempfile.TemporaryDirectory() as td:
            log = Path(td) / 'activity.jsonl'
            payload = {'tool_name': 'Bash', 'tool_input': {'command': 'echo hello'}, 'tool_response': {'secret': 'TOPSECRET'}}
            p = run_hook('post_tool_log.py', payload, env={'CONTEXT_OS_ACTIVITY_LOG': str(log)})
            self.assertEqual(p.returncode, 0)
            text = log.read_text()
            self.assertNotIn('TOPSECRET', text)
            self.assertIn('Bash', text)
