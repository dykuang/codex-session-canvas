"""Metadata-only durable linked Context records and immutable provenance snapshots.

No historical turns, prompts, task text or user-authored notes are persisted here.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from pathlib import Path

from context_graph import GraphError

MAX_BYTES = 128_000


def valid_uuid(value):
    try:
        return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise GraphError("Invalid linked context identifier") from exc


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode("utf-8")).hexdigest()


def snapshot_of(package, *, run_id, thread_id, previous=None):
    """Build a reproducible, text-free description of an approved Context Package."""
    from context_engine import sanitize_package
    info = sanitize_package(package)
    parts = [{
        "sourceId": part.get("sourceId"),
        "segmentId": part.get("segmentId"),
        "role": part.get("role"),
        "derived": part.get("derived"),
        "contentHash": part.get("contentHash"),
    } for part in info.get("segments", [])]
    payload = {
        "graphId": info["graphId"], "graphRevision": info["graphRevision"],
        "graphHash": info["graphHash"], "promptHash": info["promptHash"],
        "sourceRevisions": dict(sorted(info["sourceRevisions"].items())),
        "segments": parts, "cwd": info["cwd"], "projectId": info["projectId"],
    }
    result = {
        "version": 1, "id": fingerprint(payload), "runId": valid_uuid(run_id),
        "threadId": valid_uuid(thread_id), "previous": previous,
        "fingerprint": fingerprint(payload), **payload,
    }
    # A snapshot id is a content digest. Immutable reuse across runs only works
    # when content and identifiers agree; distinct run/thread references are stored
    # in link history, not silently overwritten in the same file.
    return result


def diff_snapshots(old, new):
    """Compare content-free provenance, including changed segments and revisions."""
    def index(record):
        return {(s["sourceId"], s["segmentId"], s["role"], bool(s["derived"])): s.get("contentHash")
                for s in record.get("segments", [])}
    before, after = index(old), index(new)
    stringify = lambda key: {"sourceId": key[0], "segmentId": key[1],
                              "role": key[2], "derived": key[3]}
    keys_before, keys_after = set(before), set(after)
    added = [stringify(k) for k in sorted(keys_after - keys_before, key=str)]
    removed = [stringify(k) for k in sorted(keys_before - keys_after, key=str)]
    changed = [stringify(k) for k in sorted(keys_before & keys_after, key=str)
               if before[k] != after[k]]
    revisions = [{"sourceId": sid, "before": old.get("sourceRevisions", {}).get(sid),
                  "after": new.get("sourceRevisions", {}).get(sid)}
                 for sid in sorted(set(old.get("sourceRevisions", {})) |
                                   set(new.get("sourceRevisions", {})))
                 if old.get("sourceRevisions", {}).get(sid) != new.get("sourceRevisions", {}).get(sid)]
    return {"unchanged": old.get("id") == new.get("id"), "added": added,
            "removed": removed, "changed": changed, "revisions": revisions,
            "graphChanged": old.get("graphHash") != new.get("graphHash"),
            "promptChanged": old.get("promptHash") != new.get("promptHash")}


class LinkStore:
    def __init__(self, config_root):
        self.root = Path(config_root).expanduser() / "context-links"
        self.snapshots = self.root / "snapshots"

    def _path(self, run_id):
        return self.root / (valid_uuid(run_id) + ".json")

    @staticmethod
    def _read(path):
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
            raise GraphError("Missing, unsafe or oversized linked Context record")
        try:
            result = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise GraphError("Invalid linked Context JSON") from exc
        if not isinstance(result, dict):
            raise GraphError("Invalid linked Context record")
        return result

    @staticmethod
    def _write_new(path, value):
        """Use exclusive creation: immutable snapshot/links cannot be overwritten."""
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        if len(text.encode("utf-8")) > MAX_BYTES:
            raise GraphError("Linked Context record too large")
        try:
            with path.open("x", encoding="utf-8") as f:
                f.write(text)
        except FileExistsError as exc:
            raise GraphError("Linked Context record already exists") from exc

    @staticmethod
    def _replace(path, value):
        if path.is_symlink():
            raise GraphError("Unsafe linked Context record")
        path.parent.mkdir(parents=True, exist_ok=True)
        data = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        if len(data) > MAX_BYTES:
            raise GraphError("Linked Context record too large")
        fd, tmp = tempfile.mkstemp(prefix=".linked-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            if path.is_symlink():
                raise GraphError("Unsafe linked Context record")
            os.replace(tmp, path)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def snapshot(self, package, run_id, thread_id):
        # store identity is content hash + run id; same package in another run
        # gets its own immutable artifact without overwriting attribution.
        record = snapshot_of(package, run_id=run_id, thread_id=thread_id)
        record["snapshotId"] = record["id"] + "-" + valid_uuid(run_id)
        path = self.snapshots / (record["snapshotId"] + ".json")
        if path.exists():
            old = self._read(path)
            if old != record:
                raise GraphError("Snapshot digest collision or altered immutable snapshot")
            return record
        self._write_new(path, record)
        return record

    def get_snapshot(self, snapshot_id):
        if not isinstance(snapshot_id, str) or len(snapshot_id) != 101:
            raise GraphError("Invalid Context snapshot id")
        try:
            digest, uid = snapshot_id.split("-", 1)
            if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise ValueError
            uid = valid_uuid(uid)
        except (ValueError, GraphError) as exc:
            raise GraphError("Invalid Context snapshot id") from exc
        snap = self._read(self.snapshots / (digest + "-" + uid + ".json"))
        if snap.get("snapshotId") != snapshot_id or snap.get("id") != digest:
            raise GraphError("Snapshot integrity check failed")
        return snap

    def link(self, package, run_id, thread_id):
        run_id, thread_id = valid_uuid(run_id), valid_uuid(thread_id)
        record = self.snapshot(package, run_id, thread_id)
        link = {"version": 1, "runId": run_id, "threadId": thread_id,
                "graphId": package["graphId"], "cwd": package["cwd"],
                "projectId": package["projectId"], "sources": sorted(package["sourceRevisions"]),
                "latestSnapshot": record["snapshotId"], "history": [record["snapshotId"]],
                "status": "linked", "revision": 1}
        self._write_new(self._path(run_id), link)
        return link

    def get(self, run_id):
        run_id = valid_uuid(run_id)
        link = self._read(self._path(run_id))
        if link.get("runId") != run_id or link.get("version") != 1:
            raise GraphError("Invalid linked Context metadata")
        valid_uuid(link.get("threadId"))
        return link

    def list(self):
        if not self.root.exists():
            return []
        result = []
        for path in sorted(self.root.glob("*.json"), reverse=True)[:200]:
            if path.is_symlink():
                continue
            result.append(self.get(path.stem))
        return result

    def advance(self, run_id, expected_revision, snapshot_id):
        link = self.get(run_id)
        if link["revision"] != expected_revision:
            raise GraphError("Linked Context was updated elsewhere; preview again")
        snap = self.get_snapshot(snapshot_id)
        if snap["threadId"] != link["threadId"]:
            raise GraphError("Snapshot target does not match linked thread")
        if snapshot_id in link["history"]:
            raise GraphError("Snapshot already applied")
        link["history"].append(snapshot_id)
        link["latestSnapshot"] = snapshot_id
        link["revision"] += 1
        self._replace(self._path(run_id), link)
        return link
