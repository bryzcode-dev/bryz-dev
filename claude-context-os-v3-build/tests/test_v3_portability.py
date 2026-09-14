import json, os, re, subprocess, tempfile, unittest, zipfile
from pathlib import Path
from context_os.local_only import audit_runtime_code

ROOT=Path(__file__).resolve().parents[1]

class PortabilityTests(unittest.TestCase):
    def test_runtime_code_has_no_network_client_dependency(self):
        r=audit_runtime_code(ROOT)
        self.assertTrue(r['ok'],r['findings'])

    def test_export_portable_excludes_personal_knowledge(self):
        with tempfile.TemporaryDirectory() as td:
            out=Path(td)/'v3-portable.zip'
            p=subprocess.run(['python3',str(ROOT/'contextctl.py'),'export-portable','--output',str(out)],capture_output=True,text=True)
            self.assertEqual(p.returncode,0,p.stderr)
            self.assertTrue(out.exists())
            with zipfile.ZipFile(out) as z:
                names=z.namelist()
                self.assertTrue(any(x.endswith('contextctl.py') for x in names))
                self.assertTrue(any('/template_root/skills/ea/SKILL.md' in x for x in names))
                knowledge=[x for x in names if '/context-os/knowledge/' in x]
                self.assertTrue(all(x.endswith('README.md') for x in knowledge))

    def test_ea_skill_is_user_only_forked_background_agent(self):
        text=(ROOT/'template_root'/'skills'/'ea'/'SKILL.md').read_text()
        self.assertIn('disable-model-invocation: true',text)
        self.assertIn('context: fork',text)
        self.assertIn('background: true',text)
        self.assertIn('agent: context-executive-assistant',text)

    def test_ea_snapshot_runs_in_enrolled_environment_without_context_os_home(self):
        with tempfile.TemporaryDirectory() as td:
            home=Path(td); facade=home/'.claude'; context_home=facade/'context-os'
            (context_home/'runtime').mkdir(parents=True)
            (context_home/'runtime'/'app').symlink_to(ROOT, target_is_directory=True)
            (context_home/'config').mkdir()
            (context_home/'config'/'context-os.json').write_text(json.dumps({
                'assistant': {'name': 'Avery'},
                'paths': {'runtime_root': str(home/'runtime')},
            }))
            text=(ROOT/'template_root'/'skills'/'ea'/'SKILL.md').read_text()
            command=re.search(r'^!`(.+)`$',text,re.MULTILINE).group(1)
            self.assertNotIn('$',command)
            env=os.environ.copy(); env['HOME']=str(home); env.pop('CONTEXT_OS_HOME',None)
            result=subprocess.run(command,shell=True,cwd=ROOT,env=env,capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertEqual(json.loads(result.stdout)['assistant']['assistant'],'Avery')

    def test_ea_agent_has_no_write_tools(self):
        text=(ROOT/'template_root'/'agents'/'context-executive-assistant.md').read_text()
        self.assertIn('tools: Read, Grep, Glob, Bash',text)
        self.assertNotIn('tools: Read, Grep, Glob, Bash, Write',text)
        self.assertIn('disallowedTools: Write, Edit, NotebookEdit',text)

if __name__=='__main__':unittest.main()
