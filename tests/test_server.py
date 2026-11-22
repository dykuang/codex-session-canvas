import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
import project_server
from project_registry import load_registry


class FakeData:
    def __init__(self, host, cfg):
        self.host, self.cfg = host, cfg


class ServerTests(unittest.TestCase):
    def test_server_url_and_security(self):
        # HTTP requests use a temporary in-process server using project_server's
        # real handler; a stub canvas avoids local Codex file access.
        import sys, types
        original = sys.modules.get('canvas')
        fake = types.ModuleType('canvas')
        fake.build_data = lambda *a: {'sessions': [], 'projects': [], 'focus': 'all', 'demo': False}
        fake.render_html = lambda d,live: '<html>csrf=' + d['csrfToken'] + '</html>'
        sys.modules['canvas'] = fake
        try:
            with tempfile.TemporaryDirectory() as t:
                import socket
                socket0 = socket.socket()
                socket0.bind(('127.0.0.1', 0))
                port = socket0.getsockname()[1]
                socket0.close()
                cfgpath = Path(t)/'projects.json'
                runner = threading.Thread(target=project_server.run_server,
                    args=('127.0.0.1',port,Path(t),'',False,False,'',cfgpath),daemon=True)
                runner.start()
                import time
                for attempt in range(40):
                    try:
                        conn=http.client.HTTPConnection('127.0.0.1',port,timeout=1)
                        conn.request('GET','/')
                        resp=conn.getresponse();html=resp.read().decode();conn.close()
                        break
                    except ConnectionError:
                        time.sleep(.025)
                self.assertEqual(200,resp.status)
                token=html.split('csrf=')[1].split('<')[0]
                payload=json.dumps({'version':1,'projects':[{'id':'A','name':'A','folders':['C:/A']}], 'relationships':[]})
                conn=http.client.HTTPConnection('127.0.0.1',port)
                conn.request('POST','/api/projects',payload,headers={'Origin':'https://evil.example','Content-Type':'application/json','X-Canvas-CSRF':token})
                blocked=conn.getresponse();blocked.read();self.assertEqual(403,blocked.status);conn.close()
                self.assertFalse(cfgpath.exists())
                conn=http.client.HTTPConnection('127.0.0.1',port)
                conn.request('POST','/api/projects',payload,headers={'Origin':f'http://127.0.0.1:{port}','Content-Type':'application/json','X-Canvas-CSRF':token})
                allowed=conn.getresponse();allowed.read();self.assertEqual(200,allowed.status);conn.close()
                self.assertEqual(1,len(load_registry(cfgpath)['projects']))
        finally:
            if original is None:sys.modules.pop('canvas',None)
            else:sys.modules['canvas']=original