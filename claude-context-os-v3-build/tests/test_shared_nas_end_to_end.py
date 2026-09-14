import json
import tempfile
import unittest
from pathlib import Path

from context_os.config import load_config, save_config
from context_os.enrollment import (
    apply_machine_enrollment,
    plan_machine_enrollment,
    rollback_machine_enrollment,
    verify_machine_enrollment,
)
from context_os.inventory import inventory_tree
from context_os.migrate import mark_semantic_review
from context_os.ops import doctor, reindex
from context_os.shared_migrate import (
    activate_shared,
    build_shared_stage,
    prepare_shared_migration,
    probe_shared_rollback,
    rollback_shared,
)
from tests.shared_nas_fixture import ROOT, make_three_machine_fixture, run_cli


class SharedNasEndToEndTests(unittest.TestCase):
    def test_three_machine_shared_lifecycle_and_primary_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            fixture = make_three_machine_fixture(base)
            machines_before = inventory_tree(fixture.machines_root)
            migration = prepare_shared_migration(fixture.topology, base / 'migration-work')
            build_shared_stage(migration, ROOT / 'template_root', ROOT)
            mark_semantic_review(migration.paths, 'end-to-end-test')
            probe_shared_rollback(migration)
            activate_shared(migration)

            runtime = base / 'local-runtime'
            config_path = fixture.shared_root / 'context-os/config/context-os.json'
            config = load_config(config_path)
            config['paths']['runtime_root'] = str(runtime)
            save_config(config_path, config)

            plan = plan_machine_enrollment(
                fixture.topology,
                'mac-mini-m4',
                fixture.facade_root,
                base / 'enrollment-work',
                runtime,
            )
            enrollment = apply_machine_enrollment(plan)
            self.assertTrue(verify_machine_enrollment(Path(enrollment['manifest']))['ok'])

            indexed = reindex(fixture.shared_root)
            self.assertEqual(Path(indexed['db']), (runtime / 'context.db').resolve())
            self.assertFalse(str(runtime).startswith(str(fixture.container_root)))

            knowledge_file = base / 'knowledge.json'
            knowledge_file.write_text(json.dumps({
                'id': 'MEM-E2E',
                'title': 'Shared NAS lifecycle',
                'summary': 'The primary runtime remains local while shared knowledge is authoritative.',
                'status': 'active',
                'verified': True,
            }), encoding='utf-8')
            added = run_cli(
                'add-knowledge', '--root', str(fixture.shared_root),
                '--file', str(knowledge_file),
            )
            self.assertEqual(added.returncode, 0, added.stderr)
            searched = run_cli(
                'search-knowledge', 'authoritative', '--root', str(fixture.shared_root),
            )
            self.assertEqual(searched.returncode, 0, searched.stderr)
            self.assertEqual(json.loads(searched.stdout)['results'][0]['id'], 'MEM-E2E')

            project = base / 'project'
            manifest = project / '.claude/project.json'
            manifest.parent.mkdir(parents=True)
            manifest.write_text(json.dumps({
                'project_id': 'shared-e2e', 'name': 'Shared E2E',
            }), encoding='utf-8')
            registered = run_cli(
                'register-project', '--root', str(fixture.shared_root),
                '--project', str(project),
            )
            self.assertEqual(registered.returncode, 0, registered.stderr)
            task = run_cli(
                'task-create', 'shared-e2e', 'Validate shared topology',
                '--root', str(fixture.shared_root),
            )
            self.assertEqual(task.returncode, 0, task.stderr)

            runtime.mkdir(parents=True, exist_ok=True)
            (runtime / 'hook-events.jsonl').write_text(json.dumps({
                'event_type': 'session.started',
                'at': '2026-09-12T00:00:00+00:00',
                'payload': {'machine_id': 'mac-mini-m4'},
            }) + '\n', encoding='utf-8')
            assistant = run_cli(
                'assistant-context', '--root', str(fixture.shared_root),
                '--cwd', str(project), '--query', 'authoritative',
                env={'CONTEXT_OS_MACHINE_PROFILE': str(
                    fixture.facade_root / 'context-os-machine.json'
                )},
            )
            self.assertEqual(assistant.returncode, 0, assistant.stderr)
            assistant_context = json.loads(assistant.stdout)
            self.assertEqual(assistant_context['machine']['machine_id'], 'mac-mini-m4')
            self.assertEqual(assistant_context['current_project_id'], 'shared-e2e')
            self.assertTrue(any(
                row['event_type'] == 'session.started'
                for row in assistant_context['recent_events']
            ))
            self.assertTrue(doctor(fixture.shared_root)['ok'])

            rollback_machine_enrollment(Path(enrollment['manifest']))
            rollback_shared(migration)
            self.assertEqual(inventory_tree(fixture.machines_root), machines_before)
            self.assertEqual(
                (fixture.shared_root / 'CLAUDE.md').read_text(encoding='utf-8'),
                fixture.original_claude,
            )


if __name__ == '__main__':
    unittest.main()
