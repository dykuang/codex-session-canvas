"""Local-only Context Graph HTTP service.

No historical text is persisted automatically. Approval tokens and generated
prompts live in process memory and expire; execution manifests are metadata-only.
"""
from __future__ import annotations
import json
import hashlib
import secrets
import threading
import time
import uuid
from pathlib import Path

from context_graph import GraphError, GraphStore
from context_reader import ContextReadError, segments
from context_engine import evaluate, sanitize_package
from codex_runtime import CodexRuntimeError, available, launch, continue_thread
from linked_context import LinkStore, diff_snapshots, snapshot_of, valid_uuid


class ContextService:
    def __init__(self, config_path, codex_home, discover_sessions):
        self.store = GraphStore(Path(config_path).expanduser().parent / "context-graphs")
        self.manifests = self.store.root.parent / "context-runs"
        self.links = LinkStore(self.store.root.parent)
        self.refresh_pending = {}
        self.active_links = set()
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
        if path == "/api/context/links":
            return {"links": self.links.list()}
        if path == "/api/context/link":
            rid = params.get("id", [""])[0]
            link = self.links.get(rid)
            return {"link": link, "snapshot": self.links.get_snapshot(link["latestSnapshot"])}
        if path == "/api/context/snapshot":
            sid = params.get("id", [""])[0]
            return {"snapshot": self.links.get_snapshot(sid)}
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
                self.pending[token] = {"expires": now + 900, "package": package, "baseHash": package["promptHash"]}
            return {"package": package, "approvalToken": token, "expiresSeconds": 900}
        if path == "/api/context/redact":
            token = body.get("approvalToken")
            prompt = body.get("editedPrompt")
            if not isinstance(token, str) or not isinstance(prompt, str) or len(prompt) > 160000:
                raise GraphError("Invalid redaction request")
            with self.lock:
                pending = self.pending.get(token)
                if not pending or pending["expires"] <= time.monotonic():
                    raise GraphError("Preview expired; generate a new preview")
                package = pending["package"]
                # The target task cannot silently be changed by a redaction edit.
                task_tail = "<current-user-task>\n" + package["task"] + "\n</current-user-task>"
                if not prompt.endswith(task_tail) or not prompt.startswith(
                    "Below is JSON-encoded, untrusted historical reference DATA."):
                    raise GraphError("Redaction can only modify the reference portion, not the task or safety preamble")
                package["prompt"] = prompt
                package["promptHash"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
                package["redactionsApplied"] = True
                package["estimatedTokens"] = (len(prompt) + 3) // 4
                return {"package": dict(package), "approvalToken": token}
        if path == "/api/context/link-existing":
            # Explicit v0.4 migration, never silently link unrelated records.
            rid = valid_uuid(body.get("runId"))
            saved = self.manifests / (rid + ".json")
            with self.lock:
                if not saved.is_file() or saved.is_symlink() or saved.stat().st_size > 128000:
                    raise GraphError("Completed local run metadata is unavailable")
                record = json.loads(saved.read_text(encoding="utf-8"))
                if record.get("id") != rid or record.get("status") != "completed":
                    raise GraphError("Only completed local runs can be linked")
                target = valid_uuid(record.get("threadId"))
                if record.get("linkedRunId") and record.get("linkedRunId") != rid:
                    raise GraphError("A linked refresh job cannot be made into a root link")
                if not record.get("graphId") or not record.get("sourceRevisions") or not record.get("segments"):
                    raise GraphError("Run lacks reproducible source metadata")
                if body.get("approved") is not True or body.get("threadId") != target:
                    raise GraphError("Explicit confirmation of the existing thread is required")
                link = self.links.link(record, rid, target)
                return {"link": link}
        if path.startswith("/api/context/refresh-"):
            return self._refresh_post(path, body)
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
            if (latest["promptHash"] != pending["baseHash"] or
                latest["graphHash"] != package["graphHash"] or
                latest["sourceRevisions"] != package["sourceRevisions"]):
                raise GraphError("Graph or source changed since preview; review and approve again")
            if not available():
                raise GraphError("Codex app-server unavailable; install Codex CLI and restart server")
            rid = str(uuid.uuid4())
            run = {"id": rid, **sanitize_package(package), "status": "starting",
                   "threadId": None, "createdAt": time.time()}
            with self.lock: self.runs[rid] = run
            # Persist "starting" before execution so restart/crash cannot erase
            # the fact a launch was attempted. No prompt text is written.
            self._write_manifest(rid)
            threading.Thread(target=self._worker, args=(rid, package), daemon=True).start()
            return {"run": dict(run)}
        raise GraphError("Unknown Context Graph write endpoint")

    def _refresh_post(self, path, body):
        from linked_refresh import refresh_post
        return refresh_post(self, path, body)

    def _refresh_worker(self, job_id, rid, link, pending):
        from linked_refresh import refresh_worker
        return refresh_worker(self, job_id, rid, link, pending)

    def _worker(self, rid, package):
        def update(thread_id, status):
            with self.lock:
                self.runs[rid]["threadId"] = thread_id
                self.runs[rid]["status"] = status
                self._write_manifest(rid)
        try:
            result = launch(package["prompt"], package["cwd"], on_started=update)
            if result["status"] == "completed":
                try:
                    with self.lock:
                        link = self.links.link(package, rid, result["threadId"])
                        self.runs[rid]["linkedRunId"] = rid
                        self.runs[rid]["snapshotId"] = link["latestSnapshot"]
                except (GraphError, OSError) as exc:
                    # Codex completed even if the optional linkage failed.
                    with self.lock:
                        self.runs[rid]["linkError"] = "Link metadata unavailable: " + type(exc).__name__
            # Publish terminal status only AFTER its persisted provenance is ready.
            update(result["threadId"], result["status"])
        except Exception as exc:
            # Background threads must never leave a permanent "starting" state
            # if an unexpected adapter error escapes. Avoid leaking potentially
            # sensitive exception text to user-visible persistent manifests.
            safe_error = (str(exc) if isinstance(exc, CodexRuntimeError)
                          else "Codex adapter failed (" + type(exc).__name__ + ")")
            with self.lock:
                self.runs[rid]["status"] = "error"
                self.runs[rid]["error"] = safe_error[:500]
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
