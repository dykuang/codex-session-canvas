"""v0.5 linked refresh: synthetic data only; no real Codex execution."""
import json
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import context_service
from context_engine import evaluate
from context_graph import GraphError
from context_service import ContextService
from linked_context import LinkStore, diff_snapshots, valid_uuid


def sid(number):
    return str(uuid.UUID(int=number))


def fixture(root):
    cwd = root / "work"
    cwd.mkdir()
    codex_home = root / ".codex"
    src = sid(5001)
    target = sid(5002)
    folder = codex_home / "sessions" / "2026" / "11" / "23"
    folder.mkdir(parents=True)
    path = folder / ("rollout-x-" + src + ".jsonl")
    def write(body):
        path.write_text("\n".join(json.dumps(record) for record in [
            {"type": "session_meta", "payload": {"meta": {"id": src, "cwd": str(cwd)}}},
            {"type": "response_item", "payload": {"type": "message", "role": "user",
              "content": [{"type": "input_text", "text": body}]}}
        ]) + "\n", encoding="utf-8")
    write("PRIVATE INITIAL RESEARCH")
    graph = {"version": 1, "id": "linked", "projectId": "C", "revision": 0,
             "nodes": [
                 {"id": "src", "type": "session_source", "x": 0, "y": 0,
                  "config": {"sessionId": src}},
                 {"id": "sel", "type": "selector", "x": 100, "y": 0,
                  "config": {"mode": "selected", "segmentIds": ["turn-0"]}},
                 {"id": "dest", "type": "new_session", "x": 200, "y": 0,
                  "config": {"cwd": str(cwd), "task": "ORIGINAL TASK MUST NOT REPEAT", "budget": 4000}}
             ], "edges": [
                 {"from": "src", "to": "sel", "out": "out", "in": "source"},
                 {"from": "sel", "to": "dest", "out": "out", "in": "in"}]}
    return codex_home, cwd, src, target, path, graph, write


class LinkedContextTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="canvas-linked-tests-")
        self.root = Path(self.tmp.name)
        self.home, self.cwd, self.src, self.target, self.source, self.graph, self.write = fixture(self.root)
        self.service = ContextService(self.root / "projects.json", self.home,
                                      lambda: [{"id": self.src, "cwd": str(self.cwd)}])
        self.graph = self.service.post("/api/context/graph", {"graph": self.graph})["graph"]
        self.package = evaluate(self.graph, self.home, [{"id": self.src}], consent=True)
        self.run_id = sid(5003)

    def tearDown(self):
        self.tmp.cleanup()

    def create_link(self):
        return self.service.links.link(self.package, self.run_id, self.target)

    def test_metadata_only_immutable_snapshot_and_provenance(self):
        link = self.create_link()
        path = self.service.links.snapshots / (link["latestSnapshot"] + ".json")
        initial = path.read_text()
        self.assertNotIn("PRIVATE INITIAL RESEARCH", initial)
        self.assertNotIn("ORIGINAL TASK", initial)
        self.assertEqual(len(link["history"]), 1)
        self.assertEqual(self.service.links.get(self.run_id), link)
        snap = self.service.links.get_snapshot(link["latestSnapshot"])
        self.assertEqual(snap["segments"][0]["sourceId"], self.src)
        self.assertEqual(len(snap["segments"][0]["contentHash"]), 64)
        with self.assertRaises(GraphError):
            self.service.links.link(self.package, self.run_id, self.target)
        with self.assertRaises(GraphError):
            self.service.links.get("../wrong")
        with self.assertRaises(GraphError):
            self.service.links.get_snapshot("../wrong")
        self.assertEqual(path.read_text(), initial)

    def test_explicit_preview_and_change_detection(self):
        link = self.create_link()
        with patch("context_engine.read_segments", side_effect=AssertionError("body read!")):
            self.assertEqual(len(self.service.get("/api/context/links", {})["links"]), 1)
            self.assertEqual(self.service.get("/api/context/link", {"id": [self.run_id]})["link"], link)
        with self.assertRaises(GraphError):
            self.service.post("/api/context/refresh-preview", {"runId": self.run_id, "consent": False})
        check = self.service.post("/api/context/refresh-preview",
                                  {"runId": self.run_id, "consent": True})
        self.assertTrue(check["unchanged"])
        self.write("PRIVATE REVISED RESEARCH")
        check = self.service.post("/api/context/refresh-preview",
                                  {"runId": self.run_id, "consent": True})
        self.assertFalse(check["unchanged"])
        self.assertIn("PRIVATE REVISED RESEARCH", check["prompt"])
        self.assertNotIn("ORIGINAL TASK MUST NOT REPEAT", check["prompt"])
        self.assertTrue(check["diff"]["changed"])
        self.assertTrue(check["diff"]["revisions"])
        self.assertNotIn("PRIVATE REVISED RESEARCH", str(check["diff"]))
        self.assertEqual(self.service.links.get(self.run_id), link)
        self.assertFalse(any("PRIVATE REVISED" in p.read_text()
                             for p in self.service.links.root.rglob("*.json")))

    def test_approved_followup_existing_thread_only(self):
        self.create_link()
        self.write("PRIVATE UPDATED REFERENCE")
        preview = self.service.post("/api/context/refresh-preview",
                                    {"runId": self.run_id, "consent": True})
        with self.assertRaises(GraphError):
            self.service.post("/api/context/refresh-apply",
                              {"approvalToken": preview["approvalToken"],
                               "approved": False, "promptHash": preview["promptHash"]})
        # Bad hash consumes one-time token, requiring another preview.
        with self.assertRaises(GraphError):
            self.service.post("/api/context/refresh-apply",
                              {"approvalToken": preview["approvalToken"],
                               "approved": True, "promptHash": "bad"})
        preview = self.service.post("/api/context/refresh-preview",
                                    {"runId": self.run_id, "consent": True})
        commands = []
        def fake_continue(prompt, cwd, thread_id):
            commands.append((prompt, cwd, thread_id))
            return {"threadId": thread_id, "status": "completed"}
        with patch("linked_refresh.available", return_value=True), patch(
                "linked_refresh.continue_thread", side_effect=fake_continue):
            applied = self.service.post("/api/context/refresh-apply", {
                "approvalToken": preview["approvalToken"],
                "approved": True, "promptHash": preview["promptHash"]})
            job = applied["run"]["id"]
            for _ in range(100):
                run = self.service.get("/api/context/run", {"id": [job]})["run"]
                if run["status"] != "starting":
                    break
                time.sleep(.01)
        self.assertEqual(run["status"], "completed")
        self.assertEqual(len(commands), 1)
        self.assertEqual(commands[0][2], self.target)
        self.assertEqual(commands[0][1], str(self.cwd))
        self.assertNotIn("ORIGINAL TASK MUST NOT REPEAT", commands[0][0])
        self.assertEqual(len(self.service.links.get(self.run_id)["history"]), 2)
        self.assertEqual(len(self.service.get("/api/context/links", {})["links"]), 1)
        with self.assertRaises(GraphError):
            self.service.post("/api/context/refresh-apply", {
                "approvalToken": preview["approvalToken"],
                "approved": True, "promptHash": preview["promptHash"]})

    def test_runtime_resumes_existing_thread_without_creating(self):
        import sys
        from codex_runtime import continue_thread
        with tempfile.TemporaryDirectory() as tmp:
            mock_app = Path(tmp) / "fake_codex.py"
            code = (
                "import json,sys\n"
                "for line in sys.stdin:\n"
                " m=json.loads(line)\n"
                " if m.get('id')==1: print(json.dumps({'id':1,'result':{}}),flush=True)\n"
                " if m.get('id')==2:\n"
                "  assert m['method']=='thread/resume'\n"
                "  assert m['params']['threadId']=='%s'\n"
                "  print(json.dumps({'id':2,'result':{'thread':{'id':'%s'}}}),flush=True)\n"
                " if m.get('id')==3:\n"
                "  assert m['method']=='turn/start'\n"
                "  assert m['params']['threadId']=='%s'\n"
                "  assert m['params']['input'][0]['text']=='UPDATE'\n"
                "  print(json.dumps({'id':3,'result':{'turn':{'id':'one'}}}),flush=True)\n"
                "  print(json.dumps({'method':'turn/completed','params':{'threadId':'%s','turn':{'status':'completed'}}}),flush=True)\n"
            ) % ((self.target,) * 4)
            mock_app.write_text(code, encoding="utf-8")
            result = continue_thread("UPDATE", str(self.cwd), self.target,
                                     command=[sys.executable, str(mock_app)], timeout=10)
            self.assertEqual(result["threadId"], self.target)
            self.assertEqual(result["status"], "completed")

    def test_backfill_completed_v04_run_and_snapshot_history(self):
        self.service.manifests.mkdir(parents=True)
        old_run = {"id": self.run_id, "status": "completed",
                   "threadId": self.target}
        from context_engine import sanitize_package
        old_run.update(sanitize_package(self.package))
        path = self.service.manifests / (self.run_id + ".json")
        path.write_text(json.dumps(old_run), encoding="utf-8")
        with self.assertRaises(GraphError):
            self.service.post("/api/context/link-existing", {
                "runId": self.run_id, "threadId": self.target, "approved": False})
        result = self.service.post("/api/context/link-existing", {
            "runId": self.run_id, "threadId": self.target, "approved": True})
        link = result["link"]
        snap = self.service.get("/api/context/snapshot",
                                {"id": [link["latestSnapshot"]]})["snapshot"]
        self.assertEqual(snap["deliveredPromptHash"], self.package["promptHash"])
        self.assertNotIn("PRIVATE INITIAL RESEARCH", str(snap))
        with self.assertRaises(GraphError):
            self.service.post("/api/context/link-existing", {
                "runId": self.run_id, "threadId": self.target, "approved": True})

    def test_redacted_delivery_hash_preserves_context_comparison(self):
        self.create_link()
        self.write("PRIVATE REVISED RESEARCH")
        preview = self.service.post("/api/context/refresh-preview",
                                    {"runId": self.run_id, "consent": True})
        redacted = preview["prompt"].replace("PRIVATE REVISED RESEARCH", "[REDACTED]")
        result = self.service.post("/api/context/refresh-redact", {
            "approvalToken": preview["approvalToken"], "editedPrompt": redacted})
        self.assertNotEqual(result["promptHash"], preview["promptHash"])
        with patch("linked_refresh.available", return_value=True), patch(
                "linked_refresh.continue_thread",
                return_value={"status": "completed", "threadId": self.target}):
            run = self.service.post("/api/context/refresh-apply", {
                "approvalToken": preview["approvalToken"],
                "approved": True, "promptHash": result["promptHash"]})["run"]
            for _ in range(100):
                job = self.service.get("/api/context/run", {"id": [run["id"]]})["run"]
                if job["status"] != "starting":
                    break
                time.sleep(.01)
        self.assertEqual(job["status"], "completed")
        link = self.service.links.get(self.run_id)
        snap = self.service.links.get_snapshot(link["latestSnapshot"])
        self.assertEqual(snap["deliveredPromptHash"], result["promptHash"])
        self.assertNotEqual(snap["promptHash"], result["promptHash"])
        again = self.service.post("/api/context/refresh-preview", {
            "runId": self.run_id, "consent": True})
        self.assertTrue(again["unchanged"], "Redaction must not force endless refresh prompts")

    def test_stale_source_blocks_execution(self):
        self.create_link()
        self.write("FIRST CHANGED REFERENCE")
        preview = self.service.post("/api/context/refresh-preview",
                                    {"runId": self.run_id, "consent": True})
        self.write("SECOND CHANGED REFERENCE")
        with patch("linked_refresh.available", return_value=True), patch(
                "linked_refresh.continue_thread", side_effect=AssertionError("must not send")):
            with self.assertRaises(GraphError):
                self.service.post("/api/context/refresh-apply", {
                    "approvalToken": preview["approvalToken"],
                    "approved": True, "promptHash": preview["promptHash"]})
        self.assertEqual(len(self.service.links.get(self.run_id)["history"]), 1)


if __name__ == "__main__":
    unittest.main()
