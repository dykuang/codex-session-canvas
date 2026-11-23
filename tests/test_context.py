"""v0.3-v0.4 Context Graph regression, privacy, storage and mocked Codex protocol."""
import json
import os
import sys
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from context_graph import GraphError, GraphStore, validate_graph, validate_ready, empty_graph
from context_reader import ContextReadError, segments
from context_engine import evaluate, sanitize_package
from codex_runtime import CodexRuntimeError, launch


def idstr(n):
    return str(uuid.UUID(int=n))


def graph_for(sid, cwd):
    return {
        "version": 1, "id": "demo", "projectId": "logical:C", "revision": 0,
        "nodes": [
            {"id": "s1", "type": "session_source", "x": 10, "y": 0, "config": {"sessionId": sid}},
            {"id": "select1", "type": "selector", "x": 110, "y": 0, "config": {"mode": "selected", "segmentIds": ["turn-0"]}},
            {"id": "note1", "type": "note", "x": 110, "y": 100, "config": {"text": "Human note"}},
            {"id": "merge1", "type": "merge", "x": 250, "y": 30, "config": {"budget": 2000}},
            {"id": "target1", "type": "new_session", "x": 400, "y": 40, "config": {"cwd": str(cwd), "task": "Do an experiment", "projectId": "logical:C", "budget": 2000}}
        ],
        "edges": [
            {"from": "s1", "to": "select1", "out": "out", "in": "source"},
            {"from": "select1", "to": "merge1", "out": "out", "in": "in"},
            {"from": "note1", "to": "merge1", "out": "out", "in": "in"},
            {"from": "merge1", "to": "target1", "out": "out", "in": "in"}
        ]
    }


def fixture(home, sid, cwd):
    root = home / "sessions" / "2026" / "11" / "23"
    root.mkdir(parents=True)
    file = root / ("rollout-2026-11-23T00-00-00-" + sid + ".jsonl")
    records = [
        {"type": "session_meta", "payload": {"meta": {"id": sid, "cwd": str(cwd)}}},
        {"type": "response_item", "payload": {"type": "message", "role": "system", "content": [{"type": "input_text", "text": "PRIVATE SYSTEM"}]}},
        {"type": "response_item", "payload": {"type": "function_call", "name": "exec", "arguments": "TOOL SECRET"}},
        {"type": "response_item", "payload": {"type": "message", "role": "user", "content": [{"type": "input_text", "text": "Research result one"}]}},
        {"type": "response_item", "payload": {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": "Confirmed result two"}]}}
    ]
    file.write_text("\n".join(map(json.dumps, records)) + "\n", encoding="utf-8")
    return file


class ContextTests(unittest.TestCase):
    def test_graph_contract_and_toposort(self):
        g = graph_for(idstr(10), "/project")
        normalized, order = validate_graph(g)
        self.assertLess(order.index("s1"), order.index("select1"))
        self.assertEqual("target1", order[-1])
        self.assertEqual(normalized["edges"], g["edges"])
        validate_ready(g)
        bad = json.loads(json.dumps(g))
        bad["edges"].append({"from": "merge1", "to": "select1", "out": "out", "in": "source"})
        with self.assertRaises(GraphError):
            validate_graph(bad)
        bad = json.loads(json.dumps(g))
        bad["edges"].append({"from": "merge1", "to": "merge1", "out": "out", "in": "in"})
        with self.assertRaises(GraphError):
            validate_graph(bad)

    def test_fan_in_and_cycle(self):
        g = graph_for(idstr(11), "/project")
        g["edges"].append({"from": "note1", "to": "target1", "out": "out", "in": "in"})
        validate_graph(g)
        g["edges"].append({"from": "merge1", "to": "merge1", "out": "out", "in": "in"})
        with self.assertRaises(GraphError):
            validate_graph(g)

    def test_store_revision_conflict_and_no_body(self):
        with tempfile.TemporaryDirectory() as d:
            store = GraphStore(Path(d) / "graphs")
            g = graph_for(idstr(12), "/project")
            first = store.save(g)
            self.assertEqual(first["revision"], 1)
            self.assertEqual(store.get("demo")["revision"], 1)
            self.assertEqual(len(store.list()), 1)
            with self.assertRaises(GraphError):
                store.save(g)
            new = store.save(first)
            self.assertEqual(new["revision"], 2)
            self.assertFalse(any("Research result one" in p.read_text() for p in store.root.glob("*.json")))
            with self.assertRaises(GraphError):
                store.delete("demo", 1)
            store.delete("demo", 2)
            self.assertEqual(store.list(), [])

    def test_opt_in_reader_and_evaluator(self):
        with tempfile.TemporaryDirectory() as d:
            cwd = Path(d) / "work"
            cwd.mkdir()
            home = Path(d) / ".codex"
            sid = idstr(13)
            fixture(home, sid, cwd)
            found = segments(home, sid)
            self.assertEqual([x["id"] for x in found["segments"]], ["turn-0", "turn-1"])
            text = str(found)
            self.assertNotIn("PRIVATE SYSTEM", text)
            self.assertNotIn("TOOL SECRET", text)
            g = graph_for(sid, cwd)
            known = [{"id": sid, "cwd": str(cwd)}]
            with self.assertRaises(GraphError):
                evaluate(g, home, known, consent=False)
            package = evaluate(g, home, known, consent=True)
            self.assertIn("Research result one", package["prompt"])
            self.assertNotIn("Confirmed result two", package["prompt"])
            self.assertIn("Human note", package["prompt"])
            self.assertIn("Do an experiment", package["prompt"])
            self.assertNotIn("Research result one", str(sanitize_package(package)))
            second = evaluate(g, home, known, consent=True)
            self.assertEqual(package["promptHash"], second["promptHash"])
            with self.assertRaises(GraphError):
                evaluate(g, home, [], consent=True)
            with self.assertRaises(ContextReadError):
                segments(home, idstr(99))

    def test_summary_requires_approval(self):
        g = graph_for(idstr(13), "/project")
        g["nodes"].insert(-1, {"id": "summary", "type": "summarize", "x": 0, "y": 0, "config": {"text": "Curated", "approved": False}})
        g["edges"] = [e for e in g["edges"] if not (e["from"] == "select1" and e["to"] == "merge1")]
        g["edges"].extend([
            {"from": "select1", "to": "summary", "out": "out", "in": "in"},
            {"from": "summary", "to": "merge1", "out": "out", "in": "in"}
        ])
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "work").mkdir()
            home = root / ".codex"
            fixture(home, idstr(13), root / "work")
            with self.assertRaises(GraphError):
                evaluate(g, home, [{"id": idstr(13)}], consent=True)
            g["nodes"][-2]["config"]["approved"] = True
            package = evaluate(g, home, [{"id": idstr(13)}], consent=True)
            self.assertIn("Curated", package["prompt"])
            self.assertNotIn("Research result one", package["prompt"])

    def test_mock_app_server_protocol(self):
        with tempfile.TemporaryDirectory() as d:
            script = Path(d) / "mock_server.py"
            script.write_text(
                "import json,sys\n"
                "for line in sys.stdin:\n"
                " m=json.loads(line)\n"
                " if m.get('id')==1: print(json.dumps({'id':1,'result':{}}),flush=True)\n"
                " if m.get('id')==2: print(json.dumps({'id':2,'result':{'thread':{'id':'" + idstr(15) + "'}}}),flush=True)\n"
                " if m.get('id')==3:\n"
                "  assert m['params']['input'][0]['text']=='SAFE'\n"
                "  print(json.dumps({'id':3,'result':{'turn':{'id':'turn-test'}}}),flush=True)\n"
                "  print(json.dumps({'method':'turn/completed','params':{'threadId':'" + idstr(15) + "','turn':{'status':'completed'}}}),flush=True)\n",
                encoding="utf-8")
            result = launch("SAFE", d, command=[sys.executable, str(script)], timeout=10)
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["threadId"], idstr(15))

if __name__ == "__main__":
    unittest.main()
