"""v0.2 integration tests against the real scanner and standalone HTML renderer."""
import json
import tempfile
import unittest
from pathlib import Path

import canvas
from project_bridge import project_data
from project_registry import save_registry


class IntegrationTests(unittest.TestCase):
    def test_two_folders_one_project_and_no_chat_leak(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            codex = root / '.codex'
            folder = codex / 'sessions' / '2026' / '11' / '22'
            folder.mkdir(parents=True)
            a = root / 'A'
            b = root / 'B'
            c1 = root / 'C1'
            c2 = root / 'C2'
            for path in [a,b,c1,c2]:
                path.mkdir()
            ids = ['123e4567-e89b-42d3-a456-42661417400'+str(i) for i in range(4)]
            for i,(sid,cwd) in enumerate(zip(ids,[a,b,c1,c2])):
                first = {"type":"session_meta","payload":{"meta":{"id":sid,"cwd":str(cwd),"timestamp":"2026-11-22T11:22:00Z"}}}
                secret = {"type":"event_msg","payload":{"message":"SECRET PRIVATE MESSAGE FROM SESSION"}}
                (folder/f'rollout-{sid}.jsonl').write_text(json.dumps(first)+'\n'+json.dumps(secret)+'\n',encoding='utf-8')
            cfgpath = root / 'projects.json'
            save_registry(cfgpath,{"version":1,"projects":[
                {"id":"A","name":"A","folders":[str(a)]},
                {"id":"B","name":"B","folders":[str(b)]},
                {"id":"C","name":"C","folders":[str(c1),str(c2)]}],
                "relationships":[{"from":"A","to":"C","type":"successor"},{"from":"B","to":"C","type":"successor"}]})
            data=project_data(canvas.build_data(codex),cfgpath,focus=str(c2))
            self.assertEqual('logical:C',data['focus'])
            self.assertEqual(4,len(data['sessions']))
            self.assertEqual(2,len([s for s in data['sessions'] if s['project']=='logical:C']))
            self.assertEqual(2,len(data['projectGraph']))
            html=canvas.render_html(data,live=False)
            self.assertIn('project-graph-toggle',html)
            self.assertNotIn('SECRET PRIVATE MESSAGE FROM SESSION',html)
            self.assertIn('logical:C',html)

    def test_no_configuration_keeps_legacy_groups(self):
        with tempfile.TemporaryDirectory() as temp:
            codex=Path(temp)/'.codex'
            codex.mkdir()
            data=project_data(canvas.build_data(codex),Path(temp)/'does-not-exist.json')
            self.assertEqual([],data['projects'])
            self.assertEqual([],data['projectGraph'])

if __name__=='__main__':
    unittest.main()