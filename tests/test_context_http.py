"""Local HTTP Context Graph flow: CSRF, opt-in reads, preview, execute and provenance."""
import http.client
import json
import socket
import sys
import tempfile
import threading
import time
import types
import unittest
import uuid
from pathlib import Path
from unittest import mock

import context_service
import project_server


class ContextHttpTests(unittest.TestCase):
    def test_api_optin_and_execution_manifest(self):
        sid = str(uuid.UUID(int=100))
        created_id = str(uuid.UUID(int=101))
        with tempfile.TemporaryDirectory() as root:
            folder = Path(root)
            home = folder / ".codex"
            work = folder / "work"
            work.mkdir()
            place = home / "sessions" / "2026" / "11" / "23"
            place.mkdir(parents=True)
            (place / ("rollout-x-" + sid + ".jsonl")).write_text("\n".join([
                json.dumps({"type": "session_meta", "payload": {"meta": {"id": sid, "cwd": str(work)}}}),
                json.dumps({"type": "response_item", "payload": {"type": "message", "role": "user", "content": [
                    {"type": "input_text", "text": "Selected history text"}]}}),
                json.dumps({"type": "response_item", "payload": {"type": "message", "role": "system", "content": [
                    {"type": "input_text", "text": "HIDDEN SYSTEM DATA"}]}})
            ]) + "\n", encoding="utf-8")
            fake = types.ModuleType("canvas")
            fake.build_data = lambda *a: {"sessions": [{"id": sid, "cwd": str(work), "project": str(work)}],
                                           "projects": [], "focus": "all", "demo": False}
            fake.render_html = lambda d,live: "<html>csrf=" + d["csrfToken"] + "</html>"
            old = sys.modules.get("canvas")
            sys.modules["canvas"] = fake
            port_sock = socket.socket()
            port_sock.bind(("127.0.0.1", 0))
            port = port_sock.getsockname()[1]
            port_sock.close()
            graph = {
                "version": 1, "id": "main", "projectId": "all", "revision": 0,
                "nodes": [
                    {"id": "s", "type": "session_source", "x": 1, "y": 1, "config": {"sessionId": sid}},
                    {"id": "a", "type": "selector", "x": 20, "y": 1, "config": {"mode": "selected", "segmentIds": ["turn-0"]}},
                    {"id": "t", "type": "new_session", "x": 40, "y": 1, "config": {"cwd": str(work), "task": "Review context", "budget": 2000}}
                ],
                "edges": [
                    {"from": "s", "to": "a", "out": "out", "in": "source"},
                    {"from": "a", "to": "t", "out": "out", "in": "in"}
                ]
            }
            try:
                def fake_launch(prompt, cwd, *, on_started, **kwargs):
                    self.assertIn("Selected history text", prompt)
                    self.assertNotIn("HIDDEN SYSTEM DATA", prompt)
                    self.assertEqual(cwd, str(work))
                    on_started(created_id, "thread_created")
                    on_started(created_id, "turn_started")
                    return {"threadId": created_id, "turnId": "test-turn", "status": "completed"}

                with mock.patch.object(context_service, "available", return_value=True), mock.patch.object(
                    context_service, "launch", side_effect=fake_launch):
                    thread = threading.Thread(target=project_server.run_server, args=(
                        "127.0.0.1", port, home, "", False, False, "", folder / "projects.json"), daemon=True)
                    thread.start()
                    for _ in range(80):
                        try:
                            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
                            conn.request("GET", "/")
                            resp = conn.getresponse()
                            html = resp.read().decode()
                            conn.close()
                            if resp.status == 200:
                                break
                        except OSError:
                            time.sleep(.025)
                    else:
                        self.fail("Server did not start")
                    self.assertNotIn("Selected history text", html)
                    token = html.split("csrf=")[1].split("<")[0]

                    def post(route, payload, *, origin=True, token_value=token):
                        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
                        headers = {"Content-Type": "application/json", "X-Canvas-CSRF": token_value,
                                   "Origin": "http://127.0.0.1:" + str(port) if origin else "https://evil.example"}
                        conn.request("POST", route, json.dumps(payload), headers=headers)
                        r = conn.getresponse()
                        status = r.status
                        body = json.loads(r.read())
                        conn.close()
                        return status, body

                    code, _ = post("/api/context/source", {"consent": True, "sessionId": sid}, origin=False)
                    self.assertEqual(403, code)
                    code, _ = post("/api/context/source", {"consent": False, "sessionId": sid})
                    self.assertEqual(400, code)
                    code, data = post("/api/context/source", {"consent": True, "sessionId": sid})
                    self.assertEqual(200, code)
                    self.assertEqual(len(data["segments"]), 1)
                    self.assertNotIn("HIDDEN SYSTEM DATA", str(data))
                    code, data = post("/api/context/graph", {"graph": graph})
                    self.assertEqual(200, code)
                    self.assertEqual(data["graph"]["revision"], 1)
                    code, _ = post("/api/context/preview", {"graphId": "main", "consent": False})
                    self.assertEqual(400, code)
                    code, data = post("/api/context/preview", {"graphId": "main", "consent": True})
                    self.assertEqual(200, code)
                    package = data["package"]
                    self.assertIn("Selected history text", package["prompt"])
                    code, _ = post("/api/context/execute", {"approved": True, "approvalToken": data["approvalToken"],
                                                            "promptHash": "WRONG HASH"})
                    self.assertEqual(400, code)
                    code, fresh = post("/api/context/preview", {"graphId": "main", "consent": True})
                    self.assertEqual(200, code)
                    code, launched = post("/api/context/execute", {"approved": True, "approvalToken": fresh["approvalToken"],
                                                                "promptHash": fresh["package"]["promptHash"]})
                    self.assertEqual(200, code)
                    rid = launched["run"]["id"]
                    for _ in range(80):
                        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
                        conn.request("GET", "/api/context/run?id=" + rid)
                        res = conn.getresponse()
                        run = json.loads(res.read())["run"]
                        conn.close()
                        if run["status"] == "completed":
                            break
                        time.sleep(.025)
                    self.assertEqual(run["status"], "completed")
                    self.assertEqual(run["threadId"], created_id)
                    manifests = list((folder / "context-runs").glob("*.json"))
                    self.assertEqual(len(manifests), 1)
                    txt = manifests[0].read_text()
                    self.assertNotIn("Selected history text", txt)
                    self.assertNotIn("Review context", txt)
                    self.assertIn(created_id, txt)
                    code, _ = post("/api/context/execute", {"approved": True, "approvalToken": fresh["approvalToken"],
                                                            "promptHash": fresh["package"]["promptHash"]})
                    self.assertEqual(400, code)
            finally:
                if old is None:
                    sys.modules.pop("canvas", None)
                else:
                    sys.modules["canvas"] = old


if __name__ == "__main__":
    unittest.main()
