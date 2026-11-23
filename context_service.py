"""Local-only Context Graph HTTP service.

No historical text is persisted automatically. Approval tokens and generated
prompts live in process memory and expire; execution manifests are metadata-only.
"""
from __future__ import annotations
import json
import secrets
import threading
import time
import uuid
from pathlib import Path

from context_graph import GraphError, GraphStore
from context_reader import ContextReadError, segments
from context_engine import evaluate, sanitize_package
from codex_runtime import CodexRuntimeError, available, launch


class ContextService:
    def __init__(self, config_path, codex_home, discover_sessions):
        self.store = GraphStore(Path(config_path).expanduser().parent / "context-graphs")
        self.manifests = self.store.root.parent / "context-runs"
        self.codex_home = codex_home
        self.discover_sessions = discover_sessions
        self.pending = {}
        self.runs = {}
        self.lock = threading.RLock()

    def get(self, path, params):
        if path == "/api/context/graphs":
            return {"graphs": self.store.list(), "runtimeAvailable": available()}
        if path == "/api/context/graph":
            return {"graph": self.store.get(params.get("id", ["main"])[0])}
        if path == "/api/context/runs":
            if not self.manifests.is_dir():
                return {"runs": []}
            stored = []
            for f in sorted(self.manifests.glob("*.json"), reverse=True)[:100]:
                if f.is_symlink():
                    continue
                try:
                    stored.append(json.loads(f.read_text(encoding="utf-8")))
                except (OSError, ValueError):
                    continue
            return {"runs": stored}
        if path == "/api/context/run":
            rid = params.get("id", [""])[0]
            with self.lock:
                result = self.runs.get(rid)
            if result is None:
                try:
                    uuid.UUID(rid)
                    saved = self.manifests / (rid + ".json")
                    if saved.exists() and not saved.is_symlink():
                        result = json.loads(saved.read_text(encoding="utf-8"))
                except (ValueError, OSError):
                    pass
            if result is None:
                raise GraphError("Run not found")
            return {"run": dict(result)}
        raise GraphError("Unknown Context Graph endpoint")

    def post(self, path, body, *, demo=False):
        if demo:
            raise GraphError("Demo mode is read-only")
        if not isinstance(body, dict):
            raise GraphError("Request must be a JSON object")
        if path == "/api/context/graph":
            with self.lock:
                return {"graph": self.store.save(body.get("graph"))}
        if path == "/api/context/delete":
            with self.lock:
                self.store.delete(body.get("id"), body.get("revision"))
            return {"ok": True}
        if path == "/api/context/source":
            if body.get("consent") is not True:
                raise GraphError("Explicit user consent is required to read session history")
            sid = body.get("sessionId")
            if sid not in {s["id"] for s in self.discover_sessions()}:
                raise GraphError("Unknown local Session ID")
            # Deliberate source-open action only.
            return segments(self.codex_home, sid)
        if path == "/api/context/preview":
            if body.get("consent") is not True:
                raise GraphError("Explicit user consent is required for context preview")
            gid = body.get("graphId", "main")
            graph = self.store.get(gid)
            package = evaluate(graph, self.codex_home, self.discover_sessions(), consent=True)
            token = secrets.token_urlsafe(32)
            with self.lock:
                now = time.monotonic()
                self.pending = {k: v for k, v in self.pending.items() if v["expires"] > now}
                self.pending[token] = {"expires": now + 900, "package": package}
            return {"package": package, "approvalToken": token, "expiresSeconds": 900}
        if path == "/api/context/execute":
            if body.get("approved") is not True:
                raise GraphError("Execution must be explicitly confirmed")
            token = body.get("approvalToken")
            if not isinstance(token, str):
                raise GraphError("Missing approval token")
            with self.lock:
                pending = self.pending.pop(token, None)
            if pending is None or pending["expires"] <= time.monotonic():
                raise GraphError("Approval expired or already used; preview again")
            package = pending["package"]
            if body.get("promptHash") != package["promptHash"]:
                raise GraphError("Approval does not match the previewed content")
            # Detect historical source changes before starting anything.
            latest = evaluate(self.store.get(package["graphId"]), self.codex_home,
                              self.discover_sessions(), consent=True)
            if (latest["promptHash"] != package["promptHash"] or
                latest["graphHash"] != package["graphHash"] or
                latest["sourceRevisions"] != package["sourceRevisions"]):
                raise GraphError("Graph or source changed since preview; review and approve again")
            if not available():
                raise GraphError("Codex app-server unavailable; install Codex CLI and restart server")
            rid = str(uuid.uuid4())
            run = {"id": rid, **sanitize_package(package), "status": "starting",
                   "threadId": None, "createdAt": time.time()}
            with self.lock: self.runs[rid] = run
            threading.Thread(target=self._worker, args=(rid, package), daemon=True).start()
            return {"run": dict(run)}
        raise GraphError("Unknown Context Graph write endpoint")

    def _worker(self, rid, package):
        def update(thread_id, status):
            with self.lock:
                self.runs[rid]["threadId"] = thread_id
                self.runs[rid]["status"] = status
            self._write_manifest(rid)
        try:
            result = launch(package["prompt"], package["cwd"], on_started=update)
            update(result["threadId"], result["status"])
        except (CodexRuntimeError, OSError, ValueError) as exc:
            with self.lock:
                self.runs[rid]["status"] = "error"
                self.runs[rid]["error"] = str(exc)
                if getattr(exc, "thread_id", None):
                    self.runs[rid]["threadId"] = exc.thread_id
            self._write_manifest(rid)

    def _write_manifest(self, rid):
        from context_graph import KEY
        if not KEY.fullmatch(rid):
            return
        with self.lock:
            record = json.dumps(self.runs[rid], indent=2, ensure_ascii=False) + "\n"
        self.manifests.mkdir(parents=True, exist_ok=True)
        path = self.manifests / (rid + ".json")
        tmp = self.manifests / ("." + rid + ".tmp")
        tmp.write_text(record, encoding="utf-8")
        tmp.replace(path)
