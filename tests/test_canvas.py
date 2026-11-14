import json
import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import canvas


class SessionCanvasTest(unittest.TestCase):
    def test_metadata_only_and_relationships(self):
        with tempfile.TemporaryDirectory() as folder:
            home = Path(folder) / '.codex'
            root = Path(folder) / 'project'
            (root / '.git').mkdir(parents=True)
            (root / 'subdir').mkdir()
            session_dir = home / 'sessions' / '2026' / '11' / '13'
            session_dir.mkdir(parents=True)
            first = '123e4567-e89b-42d3-a456-426614174000'
            second = '123e4567-e89b-42d3-a456-426614174001'
            contents = ['SECRET MESSAGE IN CHAT SHOULD NOT APPEAR', 'very private token']
            for i, id in enumerate([first, second]):
                meta = {"type":"session_meta","timestamp":"2026-11-13T10:00:00Z", "payload":{
                    "meta":{"id":id,"cwd":str(root/'subdir'),"timestamp":"2026-11-13T10:00:00Z",
                            "forked_from_id":first if i == 1 else None}}}
                (session_dir/f'rollout-2026-11-13T10-00-0{i}-{id}.jsonl').write_text(
                    json.dumps(meta) + '\n' + json.dumps({"type":"event_msg","payload":{
                        "message":contents[i]}}) + '\n', encoding='utf-8')
            (home / 'session_index.jsonl').write_text('\n'.join([
                json.dumps({'id':first,'thread_name':'First name'}),
                json.dumps({'id':first,'thread_name':'最新主会话'}),
                json.dumps({'id':second,'thread_name':'Side test session'})
            ]), encoding='utf-8')
            data = canvas.build_data(home, focus=str(root/'subdir'))
            self.assertEqual(2, len(data['sessions']))
            self.assertEqual(1, len(data['projects']))
            self.assertEqual(root.resolve(), Path(data['focus']).resolve())
            sessions = {s['id']:s for s in data['sessions']}
            self.assertEqual('最新主会话', sessions[first]['name'])
            self.assertEqual(first, sessions[second]['forkedFrom'])
            exported = canvas.render_html(data,live=False)
            self.assertNotIn(contents[0], exported)
            self.assertNotIn(contents[1], exported)
            self.assertIn('最新主会话', exported)

    def test_escape_html_and_unknown_roots(self):
        data = canvas.demo_data()
        data['sessions'][0]['name']='</script><img src=x onerror=alert(1)>'
        exported = canvas.render_html(data,live=False)
        self.assertNotIn('</script><img',exported)
        self.assertIn('\\u003c',exported)
        self.assertEqual('/projects/Fe-Ni-Si-EOS',data['focus'])

    def test_archived_scan_and_missing_title(self):
        with tempfile.TemporaryDirectory() as folder:
            home=Path(folder)
            archived=home/'archived_sessions'
            archived.mkdir()
            sid='123e4567-e89b-42d3-a456-426614174002'
            (archived/f'rollout-2026-11-13T00-00-00-{sid}.jsonl').write_text(
                json.dumps({'type':'session_meta','payload':{'meta':{'id':sid,'cwd':folder}}})+'\n')
            result=canvas.build_data(home)
            self.assertEqual(1,len(result['sessions']))
            self.assertTrue(result['sessions'][0]['archived'])
            self.assertTrue(result['sessions'][0]['name'].startswith('Session ·'))


if __name__ == '__main__':
    unittest.main()
