"""Release-candidate walkthroughs simulating real user choices with disposable data.

No installed Codex, real project folders, user sessions, network or model calls.
All files are written under TemporaryDirectory and removed after every round.
"""
from __future__ import annotations

import json
import tempfile
import time
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

import canvas
from context_graph import GraphError
from context_service import ContextService
from project_bridge import project_data
from project_registry import save_registry


def uid(n):
    return str(uuid.UUID(int=n))


class V05UserSimulations(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="v05-user-simulation-")
        self.root = Path(self.tmp.name)
        self.home = self.root / ".codex"
        self.registry = self.root / "projects.json"
        self.folders = {n: self.root / n for n in ("A", "B", "C", "C-extra")}
        for p in self.folders.values():
            p.mkdir()
        save_registry(self.registry, {
            "version": 1, "projects": [
                {"id": "A", "name": "Theory", "folders": [str(self.folders["A"])]},
                {"id": "B", "name": "Experiment", "folders": [str(self.folders["B"])]},
                {"id": "C", "name": "Combined", "folders": [
                    str(self.folders["C"]), str(self.folders["C-extra"])]}
            ],
            "relationships": [{"from": "A", "to": "C", "type": "successor"},
                              {"from": "B", "to": "C", "type": "successor"}]})
        self.sessions = [uid(5201), uid(5202), uid(5203)]
        self.paths = {}
        self.private = ["PRIVATE A1 THEORY", "PRIVATE B2 RESULT", "PRIVATE A3 DESIGN"]
        for sid, project, secret in zip(self.sessions, ("A", "B", "A"), self.private):
            p = self.home / "sessions" / "2026" / "11" / "23" / ("rollout-demo-" + sid + ".jsonl")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("\n".join(map(json.dumps, [
                {"type": "session_meta", "payload": {"id": sid, "cwd": str(self.folders[project])}},
                {"type": "response_item", "payload": {"type": "message", "role": "user",
                  "content": [{"type": "input_text", "text": secret}]}},
                {"type": "response_item", "payload": {"type": "function_call_output",
                  "output": "PRIVATE TOOL OUTPUT IGNORE"}},
            ])) + "\n", encoding="utf-8")
            self.paths[sid] = p
        self.service = ContextService(self.registry, self.home, self.known)
        g = {"version": 1, "id": "release-candidate", "projectId": "logical:C",
             "revision": 0, "nodes": [], "edges": []}
        for i, sid in enumerate(self.sessions):
            g["nodes"].extend([
                {"id": f"source{i}", "type": "session_source", "x": i*200, "y": 30,
                 "config": {"sessionId": sid}},
                {"id": f"sel{i}", "type": "selector", "x": i*200, "y": 180,
                 "config": {"mode": "selected", "segmentIds": ["turn-0"]}}
            ])
            g["edges"].extend([
                {"from": f"source{i}", "to": f"sel{i}", "out": "out", "in": "source"},
                {"from": f"sel{i}", "to": "merge", "out": "out", "in": "in"}
            ])
        g["nodes"].extend([
            {"id": "merge", "type": "merge", "x": 850, "y": 200, "config": {"budget": 3000}},
            {"id": "target", "type": "new_session", "x": 1100, "y": 200,
             "config": {"cwd": str(self.folders["C-extra"]),
                        "projectId": "logical:C", "task": "Create a new hypothesis",
                        "budget": 3000}}
        ])
        g["edges"].append({"from": "merge", "to": "target", "out": "out", "in": "in"})
        self.service.post("/api/context/graph", {"graph": g})
        self.target = uid(5299)
        self.run_id = None

    def tearDown(self):
        directory = self.root
        self.tmp.cleanup()
        self.assertFalse(directory.exists(), "Test artifacts escaped cleanup")

    def known(self):
        base = canvas.build_data(self.home, focus=str(self.folders["C-extra"]))
        return project_data(base, self.registry)["sessions"]

    def preview(self):
        return self.service.post("/api/context/preview", {
            "graphId": "release-candidate", "consent": True})

    def wait(self, run_id):
        for _ in range(150):
            run = self.service.get("/api/context/run", {"id": [run_id]})["run"]
            if run["status"] in ("completed", "error"):
                return run
            time.sleep(.01)
        self.fail("Timed out waiting for simulated Codex adapter")

    def create_target(self):
        review = self.preview()
        self.assertEqual(set(review["package"]["sources"]), set(self.sessions))
        for secret in self.private:
            self.assertIn(secret, review["package"]["prompt"])
        self.assertNotIn("PRIVATE TOOL OUTPUT IGNORE", review["package"]["prompt"])
        calls = []
        def fake_launch(prompt, cwd, on_started):
            calls.append((prompt, cwd))
            on_started(self.target, "thread_created")
            on_started(self.target, "turn_started")
            return {"status": "completed", "threadId": self.target, "turnId": "turn-one"}
        with patch("context_service.available", return_value=True), patch(
                "context_service.launch", side_effect=fake_launch):
            started = self.service.post("/api/context/execute", {
                "approved": True, "approvalToken": review["approvalToken"],
                "promptHash": review["package"]["promptHash"]})["run"]
            self.assertEqual(self.wait(started["id"])["status"], "completed")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], str(self.folders["C-extra"]))
        self.run_id = started["id"]
        return self.service.links.get(self.run_id)

    def change_source(self, sid, text):
        path = self.paths[sid]
        rows = path.read_text(encoding="utf-8").splitlines()
        item = json.loads(rows[1])
        item["payload"]["content"][0]["text"] = text
        rows[1] = json.dumps(item)
        # Bump size even when mtime resolution is coarse.
        path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    def refresh(self, redacted=False, fail=False):
        pending = self.service.post("/api/context/refresh-preview", {
            "runId": self.run_id, "consent": True})
        self.assertFalse(pending["unchanged"])
        if redacted:
            text = pending["prompt"].replace("PRIVATE B2 UPDATED", "[REDACTED]")
            response = self.service.post("/api/context/refresh-redact", {
                "approvalToken": pending["approvalToken"], "editedPrompt": text})
            pending["promptHash"] = response["promptHash"]
        received = []
        def fake_resume(prompt, cwd, thread_id):
            received.append((prompt, cwd, thread_id))
            if fail:
                raise RuntimeError("simulated offline runtime")
            return {"status": "completed", "threadId": thread_id}
        with patch("linked_refresh.available", return_value=True), patch(
                "linked_refresh.continue_thread", side_effect=fake_resume):
            job = self.service.post("/api/context/refresh-apply", {
                "approvalToken": pending["approvalToken"],
                "approved": True, "promptHash": pending["promptHash"]})["run"]
            outcome = self.wait(job["id"])
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0][2], self.target)
        self.assertNotIn("Create a new hypothesis", received[0][0])
        return pending, outcome

    def test_round_one_create_across_multiple_projects_and_restart(self):
        """A + B -> C-extra, no content leak on persistence or reload."""
        self.assertEqual({s["project"] for s in self.known()},
                         {"logical:A", "logical:B"})
        link = self.create_target()
        self.assertEqual(link["threadId"], self.target)
        self.assertEqual(len(link["history"]), 1)
        restarted = ContextService(self.registry, self.home, self.known)
        self.assertEqual(restarted.links.get(self.run_id), link)
        self.assertEqual(restarted.get("/api/context/links", {})["links"], [link])
        self.assertTrue(restarted.post("/api/context/refresh-preview", {
            "runId": self.run_id, "consent": True})["unchanged"])
        contents = [p.read_text(encoding="utf-8") for root in (
            self.service.manifests, self.service.links.root
        ) for p in root.rglob("*.json")]
        for secret in self.private:
            self.assertNotIn(secret, "".join(contents))
        self.assertNotIn("Create a new hypothesis", "".join(contents))

    def test_round_two_multiple_changes_and_provenance_history(self):
        """User iterates A then B; only changed selected passages are sent."""
        self.create_target()
        self.change_source(self.sessions[0], "PRIVATE A1 UPDATED")
        preview, run = self.refresh()
        self.assertEqual(run["status"], "completed")
        self.assertEqual([seg["sourceId"] for seg in preview["diff"]["changed"]], [self.sessions[0]])
        self.assertEqual(len(self.service.links.get(self.run_id)["history"]), 2)
        self.change_source(self.sessions[1], "PRIVATE B2 UPDATED")
        preview, run = self.refresh(redacted=True)
        self.assertEqual(run["status"], "completed")
        self.assertEqual(len(self.service.links.get(self.run_id)["history"]), 3)
        self.assertEqual(preview["diff"]["changed"][0]["sourceId"], self.sessions[1])
        self.assertTrue(self.service.post("/api/context/refresh-preview", {
            "runId": self.run_id, "consent": True})["unchanged"])

    def test_round_three_user_cancels_or_source_changes_mid_approval(self):
        """Opt-out, stale approval and replay leave history unchanged."""
        self.create_target()
        self.change_source(self.sessions[0], "PENDING A1 UPDATE")
        with self.assertRaises(GraphError):
            self.service.post("/api/context/refresh-preview", {"runId": self.run_id})
        check = self.service.post("/api/context/refresh-preview", {
            "runId": self.run_id, "consent": True})
        self.change_source(self.sessions[0], "FURTHER A1 UPDATE")
        with patch("linked_refresh.available", return_value=True), patch(
                "linked_refresh.continue_thread", side_effect=AssertionError("should not resume")):
            with self.assertRaises(GraphError):
                self.service.post("/api/context/refresh-apply", {
                    "approvalToken": check["approvalToken"], "promptHash": check["promptHash"],
                    "approved": True})
        self.assertEqual(len(self.service.links.get(self.run_id)["history"]), 1)
        with self.assertRaises(GraphError):
            self.service.post("/api/context/refresh-apply", {
                "approvalToken": check["approvalToken"], "promptHash": check["promptHash"],
                "approved": True})

    def test_round_four_runtime_failure_does_not_advance_snapshot(self):
        """Offline continuation does not present a false successful update."""
        self.create_target()
        self.change_source(self.sessions[1], "PRIVATE B2 UPDATED")
        _, run = self.refresh(fail=True)
        self.assertEqual(run["status"], "error")
        self.assertEqual(len(self.service.links.get(self.run_id)["history"]), 1)
        # Retrying requires fresh, explicit preview and one new approval.
        _, again = self.refresh()
        self.assertEqual(again["status"], "completed")
        self.assertEqual(len(self.service.links.get(self.run_id)["history"]), 2)

    def test_round_five_unauthorized_metadata_access_and_cleanup(self):
        """Browsing graphs never opens history, even across multiple views."""
        self.create_target()
        with patch("context_engine.read_segments", side_effect=AssertionError("unexpected body read")):
            self.service.get("/api/context/graphs", {})
            self.service.get("/api/context/links", {})
            self.service.get("/api/context/link", {"id": [self.run_id]})
            self.service.get("/api/context/run", {"id": [self.run_id]})
            self.service.get("/api/context/snapshot", {
                "id": [self.service.links.get(self.run_id)["latestSnapshot"]]})
        self.assertTrue(self.root.exists())


if __name__ == "__main__":
    unittest.main()
