"""Context Graph v1: typed, directed, versioned configuration and safe persistence.

Independent of the v0.2 Project DAG and Session fork/reference metadata.
Graph configs never store historic Codex conversation bodies.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from pathlib import Path

VERSION = 1
MAX_GRAPH_BYTES = 262144
MAX_GRAPHS = 128
KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")
PORTS = {
    "session_source": ({}, {"out": "session"}),
    "selector": ({"source": "session"}, {"out": "context"}),
    "summarize": ({"in": "context"}, {"out": "context"}),
    "note": ({}, {"out": "context"}),
    "merge": ({"in": "context"}, {"out": "context"}),
    "new_session": ({"in": "context"}, {}),
}
MULTI = {("merge", "in"), ("new_session", "in")}


class GraphError(ValueError):
    pass


def empty_graph(graph_id="main", project_id="all"):
    return {"version": VERSION, "id": graph_id, "projectId": project_id,
            "revision": 0, "nodes": [], "edges": []}


def validate_graph(raw):
    if not isinstance(raw, dict) or raw.get("version") != VERSION:
        raise GraphError("Unsupported Context Graph schema version")
    gid = raw.get("id")
    if not isinstance(gid, str) or not KEY.fullmatch(gid):
        raise GraphError("Invalid graph id")
    pid = raw.get("projectId", "all")
    if not isinstance(pid, str) or len(pid) > 4096 or not pid:
        raise GraphError("Invalid project id")
    revision = raw.get("revision", 0)
    if type(revision) is not int or revision < 0:
        raise GraphError("Invalid graph revision")
    nodes, edges = raw.get("nodes"), raw.get("edges")
    if not isinstance(nodes, list) or len(nodes) > 240:
        raise GraphError("nodes must be a list (max 240)")
    if not isinstance(edges, list) or len(edges) > 1000:
        raise GraphError("edges must be a list (max 1000)")
    clean_nodes = []
    by_id = {}
    for n in nodes:
        if not isinstance(n, dict):
            raise GraphError("Node must be an object")
        nid, kind = n.get("id"), n.get("type")
        if not isinstance(nid, str) or not KEY.fullmatch(nid) or nid in by_id:
            raise GraphError("Invalid or duplicate node id")
        if kind not in PORTS:
            raise GraphError("Unknown node type: " + str(kind))
        x, y = n.get("x", 0), n.get("y", 0)
        if any(type(v) not in (int, float) or not math.isfinite(v) or abs(v) > 100000 for v in (x, y)):
            raise GraphError("Invalid node coordinates")
        config = n.get("config", {})
        if not isinstance(config, dict) or len(json.dumps(config, ensure_ascii=False)) > 24000:
            raise GraphError("Node config must be a small object")
        allowed = {
            "session_source": {"sessionId"},
            "selector": {"segmentIds", "mode"},
            "summarize": {"text", "approved"},
            "note": {"text"},
            "merge": {"budget", "separator"},
            "new_session": {"projectId", "cwd", "task", "budget"},
        }[kind]
        if set(config) - allowed:
            raise GraphError(f"Unexpected config key for {kind}")
        if kind == "session_source":
            import uuid
            try:
                config["sessionId"] = str(uuid.UUID(str(config.get("sessionId", ""))))
            except ValueError as exc:
                raise GraphError("Session source needs a valid UUID") from exc
        if kind == "selector":
            if config.get("mode", "selected") not in ("selected", "all", "references"):
                raise GraphError("Unknown selector mode")
            if not isinstance(config.get("segmentIds", []), list) or len(config.get("segmentIds", [])) > 500:
                raise GraphError("Too many segment IDs")
            if any(not isinstance(s, str) or len(s) > 100 for s in config.get("segmentIds", [])):
                raise GraphError("Invalid segment ID")
        for key in ("text", "task", "cwd", "projectId", "separator"):
            if key in config and (not isinstance(config[key], str) or len(config[key]) > 16000):
                raise GraphError(f"Invalid config field: {key}")
        if "budget" in config and (type(config["budget"]) is not int or not 200 <= config["budget"] <= 200000):
            raise GraphError("Token budget must be from 200 to 200000")
        clean = {"id": nid, "type": kind, "x": x, "y": y, "config": dict(config)}
        clean_nodes.append(clean)
        by_id[nid] = clean
    clean_edges, seen, ports_used = [], set(), set()
    adjacency = {n: [] for n in by_id}
    for e in edges:
        if not isinstance(e, dict):
            raise GraphError("Edge must be an object")
        src, dst = e.get("from"), e.get("to")
        output, inp = e.get("out", "out"), e.get("in")
        if src not in by_id or dst not in by_id or src == dst:
            raise GraphError("Dangling or self-connected edge")
        src_type, dst_type = by_id[src]["type"], by_id[dst]["type"]
        op = PORTS[src_type][1].get(output)
        ip = PORTS[dst_type][0].get(inp)
        if op is None or ip is None or op != ip:
            raise GraphError(f"Incompatible ports: {src}.{output} -> {dst}.{inp}")
        ident = (src, dst, output, inp)
        if ident in seen:
            raise GraphError("Duplicate edge")
        seen.add(ident)
        if (dst_type, inp) not in MULTI:
            if (dst, inp) in ports_used:
                raise GraphError("Input socket already connected")
            ports_used.add((dst, inp))
        adjacency[src].append(dst)
        clean_edges.append({"from": src, "to": dst, "out": output, "in": inp})
    # Deterministic topo sort, including standalone unused nodes.
    incoming = {nid: 0 for nid in by_id}
    for e in clean_edges:
        incoming[e["to"]] += 1
    ready = sorted(n for n, deg in incoming.items() if deg == 0)
    order = []
    while ready:
        n = ready.pop(0)
        order.append(n)
        for target in adjacency[n]:
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
                ready.sort()
    if len(order) != len(by_id):
        raise GraphError("Context Graph contains a cycle")
    return {"version": VERSION, "id": gid, "projectId": pid,
            "revision": revision, "nodes": clean_nodes, "edges": clean_edges}, order


def validate_ready(graph):
    graph, order = validate_graph(graph)
    targets = [n for n in graph["nodes"] if n["type"] == "new_session"]
    if len(targets) != 1:
        raise GraphError("Execution requires exactly one NewSession node")
    target = targets[0]
    if not isinstance(target["config"].get("task"), str) or not target["config"]["task"].strip():
        raise GraphError("NewSession requires a task")
    if not isinstance(target["config"].get("cwd"), str) or not target["config"]["cwd"].strip():
        raise GraphError("NewSession requires a concrete working directory")
    if not any(e["to"] == target["id"] for e in graph["edges"]):
        raise GraphError("NewSession must receive at least one context edge")
    return graph, order, target


def graph_digest(graph):
    canonical = json.dumps(graph, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class GraphStore:
    def __init__(self, root):
        self.root = Path(root).expanduser()

    def _path(self, gid):
        if not isinstance(gid, str) or not KEY.fullmatch(gid):
            raise GraphError("Invalid graph id")
        return self.root / (gid + ".json")

    def get(self, gid):
        path = self._path(gid)
        if not path.exists():
            return empty_graph(gid)
        if path.stat().st_size > MAX_GRAPH_BYTES:
            raise GraphError("Graph config too large")
        try:
            graph = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise GraphError(f"Invalid graph JSON: {exc}") from exc
        return validate_graph(graph)[0]

    def list(self):
        if not self.root.is_dir():
            return []
        files = sorted(self.root.glob("*.json"))
        if len(files) > MAX_GRAPHS:
            raise GraphError("Too many graphs")
        return [{"id": (g := self.get(f.stem))["id"], "projectId": g["projectId"],
                 "revision": g["revision"], "nodes": len(g["nodes"])} for f in files]

    def save(self, raw):
        graph = validate_graph(raw)[0]
        path = self._path(graph["id"])
        old = self.get(graph["id"])
        if path.exists() and graph["revision"] != old["revision"]:
            raise GraphError("Graph was changed elsewhere; refresh before saving")
        if not path.exists() and graph["revision"] != 0:
            raise GraphError("New graph must start at revision 0")
        graph["revision"] = old["revision"] + 1 if path.exists() else 1
        data = (json.dumps(graph, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if len(data) > MAX_GRAPH_BYTES:
            raise GraphError("Graph config too large")
        self.root.mkdir(parents=True, exist_ok=True)
        temp = None
        try:
            fd, temp = tempfile.mkstemp(prefix=".context-", dir=self.root)
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            if path.exists():
                shutil.copy2(path, path.with_suffix(".json.bak"))
            os.replace(temp, path)
            temp = None
        finally:
            if temp:
                Path(temp).unlink(missing_ok=True)
        return graph

    def delete(self, gid, revision):
        path = self._path(gid)
        if not path.exists():
            raise GraphError("Graph not found")
        if type(revision) is not int or self.get(gid)["revision"] != revision:
            raise GraphError("Stale graph revision")
        path.unlink()
