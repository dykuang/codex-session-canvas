"""Three isolated real-user journeys; never operate on real Codex home.

All workspaces, mock sessions and context-run manifests are inside TemporaryDirectory
and removed after each test. Fake App Server transport never uses network/model quota.
"""
import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from context_graph import GraphError
from context_service import ContextService
from project_bridge import project_data
from project_registry import save_registry
import canvas


def sid(i):
    return str(uuid.UUID(int=i))


def make_session(home, sid_value, cwd, text, *, archived=False):
    folder = home / ("archived_sessions" if archived else "sessions") / "2026" / "11" / "23"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ("rollout-test-" + sid_value + ".jsonl")
    events = [
        {"type": "session_meta", "payload": {"id": sid_value, "cwd": str(cwd)}},
        {"type": "response_item", "payload": {"type": "message", "role": "user",
                                               "content": [{"type": "input_text", "text": text}]}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant",
                                               "content": [{"type": "output_text", "text": "Conclusions"}]}},
        {"type": "response_item", "payload": {"type": "function_call_output",
                                               "output": "SHOULD_NOT_BE_CONTEXT_SECRET"}},
    ]
    path.write_text("\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    return path


def node(id, type, config):
    return {"id": id, "type": type, "x": 100, "y": 100, "config": config}


def edge(src, dst, port="in"):
    return {"from": src, "to": dst, "out": "out", "in": port}


class ThreeUserJourneys(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="codex-canvas-simulation-")
        self.root = Path(self.temp.name)
        self.home = self.root / ".codex"
        self.config = self.root / "projects.json"
        a, b, c, c2 = (self.root / n for n in ("A", "B", "C", "C-aux"))
        for x in (a, b, c, c2):
            x.mkdir()
        self.folders = (a, b, c, c2)
        save_registry(self.config, {
            "version": 1, "projects": [
                {"id": "A", "name": "A", "folders": [str(a)]},
                {"id": "B", "name": "B", "folders": [str(b)]},
                {"id": "C", "name": "C", "folders": [str(c), str(c2)]}
            ],
            "relationships": [
                {"from": "A", "to": "C", "type": "successor"},
                {"from": "B", "to": "C", "type": "successor"}
            ]
        })
        self.paths = [
            make_session(self.home, sid(1101), a, "A1: independent theory"),
            make_session(self.home, sid(1102), b, "B2: experimental reference", archived=True),
            make_session(self.home, sid(1103), a, "A3: architecture note"),
        ]
        self.service = ContextService(self.config, self.home, self.known)
        self.saved = None

    def tearDown(self):
        path = self.root
        self.temp.cleanup()
        self.assertFalse(path.exists(), "Simulation left a temporary Codex workspace")

    def known(self):
        base = canvas.build_data(self.home, focus=str(self.folders[2]))
        return project_data(base, self.config)["sessions"]

    def configure(self):
        g = {"version": 1, "id": "cross-project", "revision": 0,
             "projectId": "logical:C", "nodes": [], "edges": []}
        for i in range(3):
            src, sel = "src" + str(i), "sel" + str(i)
            g["nodes"].append(node(src, "session_source", {"sessionId": sid(1101 + i)}))
            g["nodes"].append(node(sel, "selector", {"mode": "selected", "segmentIds": ["turn-0"]}))
            g["edges"].append(edge(src, sel, "source"))
            g["edges"].append(edge(sel, "merge"))
        g["nodes"].extend([
            node("merge", "merge", {"budget": 4000}),
            node("note", "note", {"text": "Human-approved note"}),
            node("target", "new_session", {
                "cwd": str(self.folders[3]),
                "projectId": "logical:C",
                "task": "Draft the next stage of project C",
                "budget": 4000
            })
        ])
        g["edges"].extend([edge("note", "merge"), edge("merge", "target")])
        self.saved = self.service.post("/api/context/graph", {"graph": g})["graph"]
        return self.saved

    def test_journey_one_cross_project_three_sources_preview(self):
        """User references A1/B2/A3 while working in C's second folder."""
        sessions = self.known()
        self.assertEqual(len(sessions), 3)
        self.assertEqual({s["project"] for s in sessions},
                         {"logical:A", "logical:B"})
        graph = self.configure()
        self.assertEqual(graph["revision"], 1)
        self.assertEqual(len(self.service.get("/api/context/graphs", {})["graphs"]), 1)
        with self.assertRaises(GraphError):
            self.service.post("/api/context/preview", {"graphId": graph["id"]})
        with self.assertRaises(GraphError):
            self.service.post("/api/context/source", {"sessionId": sid(1101), "consent": False})
        view = self.service.post("/api/context/preview", {
            "graphId": "cross-project", "consent": True
        })
        payload = view["package"]
        self.assertEqual(payload["cwd"], str(self.folders[3]))
        self.assertEqual(len(payload["sources"]), 3)
        for phrase in ("A1: independent theory", "B2: experimental reference",
                       "A3: architecture note", "Human-approved note"):
            self.assertIn(phrase, payload["prompt"])
        self.assertNotIn("SHOULD_NOT_BE_CONTEXT_SECRET", payload["prompt"])
        self.assertNotIn("A1: independent theory",
                         (self.service.store.root / "cross-project.json").read_text())
        self.assertTrue(view["approvalToken"])
        self.assertFalse(self.service.manifests.exists())
        # User opens graph again, selections persist, historical text does not.
        loaded = self.service.get("/api/context/graph", {"id": ["cross-project"]})["graph"]
        self.assertEqual(loaded["revision"], 1)
        self.assertEqual(len(loaded["edges"]), 8)

    def test_journey_two_invalid_actions_do_not_corrupt_graph(self):
        """Broken links, cycle, concurrent update, source mutation all fail safely."""
        graph = self.configure()
        invalid = json.loads(json.dumps(graph))
        invalid["edges"].append(edge("target", "src0"))
        with self.assertRaises(GraphError):
            self.service.post("/api/context/graph", {"graph": invalid})
        self.assertEqual(self.service.store.get("cross-project"), graph)
        stale = json.loads(json.dumps(graph))
        stale["revision"] = 0
        with self.assertRaises(GraphError):
            self.service.post("/api/context/graph", {"graph": stale})
        first = self.service.post("/api/context/preview", {
            "graphId": "cross-project", "consent": True
        })
        self.paths[0].write_text(self.paths[0].read_text() + '{"type":"event_msg","payload":{"x":"updated"}}\n')
        with patch("context_service.available", return_value=True), \
             patch("context_service.launch") as fake_launch:
            with self.assertRaisesRegex(GraphError, "changed since preview"):
                self.service.post("/api/context/execute", {
                    "approved": True, "approvalToken": first["approvalToken"],
                    "promptHash": first["package"]["promptHash"]
                })
            fake_launch.assert_not_called()
        self.assertEqual(self.service.runs, {})
        self.assertFalse(self.service.manifests.exists())

    def test_journey_three_launch_failure_stays_non_successful(self):
        """User approves, worker fails: no phantom thread or persisted chat text."""
        import time
        graph = self.configure()
        first = self.service.post("/api/context/preview", {
            "graphId": graph["id"], "consent": True
        })
        with patch("context_service.available", return_value=True), \
             patch("context_service.launch", side_effect=RuntimeError("fake transport fail")):
            result = self.service.post("/api/context/execute", {
                "approved": True, "approvalToken": first["approvalToken"],
                "promptHash": first["package"]["promptHash"]
            })
            rid = result["run"]["id"]
            for _ in range(100):
                status = self.service.get("/api/context/run", {"id": [rid]})["run"]
                if status["status"] != "starting":
                    break
                time.sleep(.01)
            self.assertNotEqual(status["status"], "completed")
            # A real user must not be able to reuse the same one-time approval.
            with self.assertRaises(GraphError):
                self.service.post("/api/context/execute", {
                    "approved": True, "approvalToken": first["approvalToken"],
                    "promptHash": first["package"]["promptHash"]
                })


if __name__ == "__main__":
    unittest.main()
