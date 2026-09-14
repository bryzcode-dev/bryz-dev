import copy
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from context_os.config import expand_path_template
from context_os.settings import apply_security_permissions, merge_context_os_settings, portable_hook_paths


class SettingsTests(unittest.TestCase):
    def test_expands_runtime_template_for_each_machine_home(self):
        self.assertEqual(
            expand_path_template(
                '~/Library/Application Support/ClaudeContextOS/home',
                Path('/Users/tester'),
            ),
            Path('/Users/tester/Library/Application Support/ClaudeContextOS/home'),
        )

    def test_shared_settings_use_guarded_portable_facade_hook_commands(self):
        merged = merge_context_os_settings(
            {'theme': 'dark'}, portable_hook_paths('$HOME/.claude/context-os')
        )
        command = merged['hooks']['SessionStart'][-1]['hooks'][0]['command']
        self.assertIn('$HOME/.claude/context-os/runtime/hooks/session_start.py', command)
        self.assertIn('test ! -f', command)
        self.assertNotIn('CONTEXT_OS_HOME', merged.get('env', {}))

    def test_unenrolled_portable_hook_command_is_safe_noop(self):
        with tempfile.TemporaryDirectory() as td:
            merged = merge_context_os_settings(
                {}, portable_hook_paths('$HOME/.claude/context-os')
            )
            command = merged['hooks']['SessionStart'][-1]['hooks'][0]['command']
            env = os.environ.copy(); env['HOME'] = td
            result = subprocess.run(command, shell=True, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(list(Path(td).rglob('context.db')), [])

    def test_shared_ea_permission_rule_uses_statically_analyzable_facade_path(self):
        secured = apply_security_permissions({}, '$HOME/.claude/context-os')
        self.assertIn(
            'Bash(python3 ~/.claude/context-os/runtime/app/contextctl.py assistant-context *)',
            secured['permissions']['allow'],
        )

    def test_merge_preserves_unrelated_keys_and_is_idempotent(self):
        existing = {'theme': 'dark', 'permissions': {'allow': ['Bash(git status)']}}
        hooks = {
            'session_start': '/x/session_start.py',
            'pre_tool_guard': '/x/pre_tool_guard.py',
            'post_tool_log': '/x/post_tool_log.py',
        }
        once = merge_context_os_settings(copy.deepcopy(existing), hooks)
        twice = merge_context_os_settings(copy.deepcopy(once), hooks)
        self.assertEqual(once, twice)
        self.assertEqual(once['theme'], 'dark')
        self.assertEqual(once['permissions'], existing['permissions'])
        self.assertIn('SessionStart', once['hooks'])
        self.assertIn('PreToolUse', once['hooks'])
        self.assertIn('PostToolUse', once['hooks'])
