import json, os, subprocess, tempfile, unittest
from pathlib import Path

from context_os.migrate import prepare_migration, build_stage, activate_verified_stage
from context_os.verify import verify_stage
from context_os.ops import reindex, doctor, ingest_hook_events
from context_os.db import ContextDB

ROOT=Path(__file__).resolve().parents[1]

class V3MigrationOpsTests(unittest.TestCase):
    def test_legacy_managed_name_collision_is_preserved_not_overwritten(self):
        with tempfile.TemporaryDirectory() as td:
            b=Path(td); src=b/'Claude'; src.mkdir()
            (src/'skills'/'ea').mkdir(parents=True)
            (src/'skills'/'ea'/'SKILL.md').write_text('legacy assistant')
            (src/'commands').mkdir(); (src/'commands'/'ea.md').write_text('legacy ea command')
            (src/'hooks').mkdir(); (src/'hooks'/'session_start.py').write_text('legacy hook')
            paths=prepare_migration(src,b/'work')
            build_stage(paths,ROOT/'template_root',runtime_root=b/'runtime',package_root=ROOT,profile='test')
            self.assertIn('name: ea', (paths.stage/'skills'/'ea'/'SKILL.md').read_text())
            self.assertEqual((paths.stage/'context-os'/'legacy-preserved'/'native-collisions'/'skills'/'ea'/'SKILL.md').read_text(),'legacy assistant')
            self.assertEqual((paths.stage/'commands'/'ea.md').read_text(),'legacy ea command')
            self.assertEqual((paths.stage/'context-os'/'legacy-preserved'/'native-collisions'/'hooks'/'session_start.py').read_text(),'legacy hook')

    def test_network_safe_activation_copies_stage_to_destination_fs_before_swap(self):
        with tempfile.TemporaryDirectory() as td:
            b=Path(td); src=b/'mounted'/'Claude'; src.mkdir(parents=True); (src/'old').write_text('old')
            paths=prepare_migration(src,b/'different-workspace')
            build_stage(paths,ROOT/'template_root',runtime_root=b/'local-runtime',package_root=ROOT,profile='nas-test')
            # No legacy CLAUDE, semantic review not required.
            self.assertTrue(verify_stage(paths).ok)
            activate_verified_stage(paths)
            self.assertTrue((src/'context-os'/'VERSION').exists())
            self.assertTrue(paths.rollback_root.exists())
            self.assertEqual((paths.rollback_root/'old').read_text(),'old')

    def test_runtime_db_is_outside_authoritative_root_when_configured(self):
        with tempfile.TemporaryDirectory() as td:
            b=Path(td); src=b/'Claude'; src.mkdir(); runtime=b/'local-runtime'
            paths=prepare_migration(src,b/'work'); build_stage(paths,ROOT/'template_root',runtime_root=runtime,package_root=ROOT,profile='test'); activate_verified_stage(paths)
            out=reindex(src)
            self.assertEqual(Path(out['db']), (runtime/'context.db').resolve())
            self.assertFalse((src/'context-os'/'context.db').exists())

    def test_hook_events_are_ingested_from_local_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            b=Path(td); src=b/'Claude'; src.mkdir(); runtime=b/'runtime'
            paths=prepare_migration(src,b/'work'); build_stage(paths,ROOT/'template_root',runtime_root=runtime,package_root=ROOT,profile='test'); activate_verified_stage(paths); reindex(src)
            runtime.mkdir(exist_ok=True)
            (runtime/'hook-events.jsonl').write_text(json.dumps({'at':'2026-09-12T00:00:00+00:00','event_type':'session.started','payload':{'cwd':'/work'}})+'\n')
            db=ContextDB(runtime/'context.db').initialize(); result=ingest_hook_events(src,db)
            self.assertEqual(result['ingested'],1)
            self.assertEqual(db.conn.execute('SELECT COUNT(*) c FROM events').fetchone()['c'],1)
            db.close()

    def test_doctor_secret_scan_ignores_managed_runtime_scanner_source(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)/"claude"; runtime=Path(td)/"runtime"
            root.mkdir(); (root/"context-os/runtime/app/context_os").mkdir(parents=True)
            (root/"context-os/runtime/app/context_os/secrets.py").write_text("generic secret scanner")
            (root/"context-os/config").mkdir(parents=True)
            (root/"context-os/config/context-os.json").write_text(json.dumps({"version":"3.0.1","profile":"test","paths":{"runtime_root":str(runtime)}}))
            for rel in ["CLAUDE.md","settings.json","context-os/VERSION","context-os/runtime/app/contextctl.py","context-os/runtime/hooks/session_start.py","skills/ea/SKILL.md","agents/context-executive-assistant.md"]:
                q=root/rel; q.parent.mkdir(parents=True,exist_ok=True); q.write_text("x")
            (root/"context-os/integrity").mkdir(parents=True,exist_ok=True)
            from context_os.integrity import build_manifest
            from context_os.util import write_json
            write_json(root/"context-os/integrity/managed-manifest.json",build_manifest(root,[]))
            out=doctor(root)
            self.assertEqual(out["checks"]["secret_scan"]["findings"],0)

    def test_doctor_detects_runtime_db_loss_and_reindex_repairs(self):
        with tempfile.TemporaryDirectory() as td:
            b=Path(td); src=b/'Claude'; src.mkdir(); runtime=b/'runtime'
            paths=prepare_migration(src,b/'work'); build_stage(paths,ROOT/'template_root',runtime_root=runtime,package_root=ROOT,profile='test'); activate_verified_stage(paths)
            d=doctor(src); self.assertTrue(any('runtime database missing' in w for w in d['warnings']))
            reindex(src); d2=doctor(src); self.assertFalse(any('runtime database missing' in w for w in d2['warnings']))

if __name__=='__main__':unittest.main()

class LiveRootSnapshotTests(unittest.TestCase):
    def test_prepare_migration_preserves_symlink_when_copytree_would_dereference_it(self):
        from unittest.mock import patch
        import context_os.migrate as migrate_mod
        with tempfile.TemporaryDirectory() as td:
            b=Path(td); src=b/'Claude'; src.mkdir(); (src/'CLAUDE.md').write_text('rules')
            (src/'AGENTS.md').symlink_to('CLAUDE.md')
            real_copytree=migrate_mod.shutil.copytree
            def dereferencing_copytree(source, destination, *args, **kwargs):
                kwargs['symlinks']=False
                return real_copytree(source, destination, *args, **kwargs)
            with patch.object(migrate_mod.shutil,'copytree',side_effect=dereferencing_copytree):
                paths=prepare_migration(src,b/'work')
            copied_link=paths.backup/'AGENTS.md'
            self.assertTrue(copied_link.is_symlink())
            self.assertEqual(copied_link.readlink(),Path('CLAUDE.md'))

    def test_prepare_migration_retries_transient_copy_error(self):
        from unittest.mock import patch
        import context_os.migrate as migrate_mod
        with tempfile.TemporaryDirectory() as td:
            b=Path(td); src=b/'Claude'; src.mkdir(); (src/'stable.txt').write_text('stable')
            calls={'count':0}
            real_copy_snapshot=migrate_mod._copy_snapshot_tree
            def fail_once(source, destination, rows):
                calls['count'] += 1
                if calls['count'] == 1:
                    raise FileNotFoundError('source changed during copy')
                return real_copy_snapshot(source, destination, rows)
            with patch.object(migrate_mod,'_copy_snapshot_tree',side_effect=fail_once):
                paths=prepare_migration(src,b/'work')
            verification=json.loads((paths.workspace/'backup-verification.json').read_text())
            self.assertEqual(calls['count'],2)
            self.assertIn('source changed during copy', verification['attempts'][0]['copy_error'])
            self.assertEqual(verification['attempts'][1]['matched_boundary'],'pre-copy')

    def test_prepare_migration_accepts_source_change_after_copy_when_backup_matches_pre_copy_snapshot(self):
        from unittest.mock import patch
        import context_os.migrate as migrate_mod
        with tempfile.TemporaryDirectory() as td:
            b=Path(td); src=b/'Claude'; src.mkdir(); (src/'projects').mkdir(); live=src/'projects'/'live.jsonl'; live.write_text('before')
            real_copy_snapshot=migrate_mod._copy_snapshot_tree
            def copy_then_mutate(source, destination, rows):
                out=real_copy_snapshot(source, destination, rows)
                live.write_text('after')
                return out
            with patch.object(migrate_mod,'_copy_snapshot_tree',side_effect=copy_then_mutate):
                paths=prepare_migration(src,b/'work')
            self.assertEqual((paths.backup/'projects'/'live.jsonl').read_text(),'before')
            snap=json.loads((paths.workspace/'source-manifest.json').read_text())
            row=next(r for r in snap if r['path']=='projects/live.jsonl')
            self.assertEqual(row['sha256'], __import__('hashlib').sha256(b'before').hexdigest())
            drift=json.loads((paths.workspace/'live-drift.json').read_text())
            self.assertIn('projects/live.jsonl', drift['changed_paths'])

    def test_verify_stage_uses_frozen_snapshot_not_live_source(self):
        with tempfile.TemporaryDirectory() as td:
            b=Path(td); src=b/'Claude'; src.mkdir(); (src/'projects').mkdir(); live=src/'projects'/'live.jsonl'; live.write_text('before')
            paths=prepare_migration(src,b/'work')
            build_stage(paths,ROOT/'template_root',runtime_root=b/'runtime',package_root=ROOT,profile='test')
            live.write_text('changed after backup')
            result=verify_stage(paths)
            self.assertTrue(result.ok, result.errors)
