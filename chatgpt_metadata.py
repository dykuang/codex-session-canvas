"""Read-only, strict, versioned ChatGPT metadata snapshot adapter.

This is NOT a ChatGPT client, does not parse raw account exports, does not read chat
bodies, and never obtains cookies, credentials, or browser state.
"""
from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

SCHEMA = "codex-session-canvas.chatgpt-metadata"
MAX_BYTES = 1024 * 1024
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,199}$")
REL_TYPES = frozenset(("fork", "parent", "handoff", "reference", "manual"))


class SnapshotError(ValueError):
    pass


def _object(value, required, optional=()):
    if not isinstance(value, dict):
        raise SnapshotError("Expected object")
    unknown = set(value) - set(required) - set(optional)
    missing = set(required) - set(value)
    if unknown or missing:
        raise SnapshotError(f"Unknown or missing fields: {sorted(unknown)}, {sorted(missing)}")
    return value


def _id(value):
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        raise SnapshotError("Invalid metadata ID")
    return value


def _title(value):
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > 200 or "\x00" in value:
        raise SnapshotError("Invalid metadata title")
    return value.strip()


def _time(value):
    if not isinstance(value, str) or len(value) > 64:
        raise SnapshotError("Timestamp must be ISO 8601 with timezone")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise SnapshotError("Invalid timestamp") from exc
    if parsed.tzinfo is None:
        raise SnapshotError("Timestamp must include timezone")
    return parsed.astimezone(dt.timezone.utc)


def _optional_time(item, key):
    return _time(item[key]).isoformat() if key in item else ""


def validate_snapshot(raw):
    _object(raw, ("schema", "version", "exportedAt", "scope", "pages"))
    if (raw["schema"] != SCHEMA or type(raw["version"]) is not int or
            raw["version"] != 1 or raw["scope"] != "user-provided-metadata"):
        raise SnapshotError("Unsupported schema/version/scope")
    stamp = _time(raw["exportedAt"])
    pages = raw["pages"]
    if not isinstance(pages, list) or not 1 <= len(pages) <= 200:
        raise SnapshotError("pages must contain 1–200 entries")
    projects, conversations, relationships = {}, {}, {}
    incomplete = False
    for n, page in enumerate(pages, 1):
        _object(page, ("page", "complete", "projects", "conversations"), ("relationships",))
        if type(page["page"]) is not int or page["page"] != n:
            raise SnapshotError("Pages must be ordered and contiguous from 1")
        if type(page["complete"]) is not bool:
            raise SnapshotError("Page completeness must be boolean")
        incomplete |= not page["complete"]
        for key in ("projects", "conversations", "relationships"):
            arr = page.get(key, [])
            if not isinstance(arr, list) or len(arr) > 10000:
                raise SnapshotError(f"Invalid {key} array")
        for item in page["projects"]:
            _object(item, ("id",), ("title",))
            pid = _id(item["id"])
            projects[pid] = {"id": pid, "title": _title(item.get("title"))}
        for item in page["conversations"]:
            _object(item, ("id",), ("title", "projectId", "createdAt", "updatedAt", "archived"))
            cid = _id(item["id"])
            pid = _id(item["projectId"]) if "projectId" in item else None
            if "archived" in item and type(item["archived"]) is not bool:
                raise SnapshotError("archived must be true/false or omitted")
            conversations[cid] = {
                "id": cid, "title": _title(item.get("title")), "projectId": pid,
                "createdAt": _optional_time(item, "createdAt"),
                "updatedAt": _optional_time(item, "updatedAt"),
                "archived": item.get("archived"),
            }
        for item in page.get("relationships", []):
            _object(item, ("from", "to", "type", "evidence"), ("provenance",))
            src, dst = _id(item["from"]), _id(item["to"])
            kind, evidence = item["type"], item["evidence"]
            if src == dst or kind not in REL_TYPES or not isinstance(evidence, str) or not evidence.strip() or len(evidence) > 160:
                raise SnapshotError("Invalid relationship provenance or endpoints")
            if "provenance" in item and (not isinstance(item["provenance"], str) or len(item["provenance"]) > 160):
                raise SnapshotError("Invalid provenance")
            relationships[(src, dst, kind)] = {
                "from": "chatgpt:" + src, "to": "chatgpt:" + dst, "type": kind,
                "evidence": evidence.strip(), "provenance": item.get("provenance") or "snapshot",
            }
    # Explicit missing membership is unresolved, never guessed.
    warnings = []
    for chat in conversations.values():
        pid = chat["projectId"]
        if pid is not None and pid not in projects:
            warnings.append("Conversation references an unavailable project ID")
            chat["projectId"] = None
    valid_ids = set(conversations)
    edges = [e for (src, dst, _kind), e in relationships.items() if src in valid_ids and dst in valid_ids]
    if len(edges) < len(relationships):
        warnings.append("Some relations had unavailable endpoints and were omitted")
    age = (dt.datetime.now(dt.timezone.utc) - stamp).total_seconds()
    return {
        "schema": SCHEMA, "version": 1, "exportedAt": stamp.isoformat(),
        "status": "incomplete" if incomplete else ("stale" if age > 86400 * 30 else "complete"),
        "complete": not incomplete, "source": "user-provided metadata snapshot",
        "projectRecords": list(projects.values()), "conversationRecords": list(conversations.values()),
        "relationships": edges, "warnings": sorted(set(warnings)), "pageCount": len(pages),
    }


def load_snapshot(path: Path | None):
    if path is None:
        return {"status": "unconfigured", "complete": False, "source": "none",
                "projectRecords": [], "conversationRecords": [], "relationships": [],
                "warnings": ["No ChatGPT metadata snapshot configured"], "pageCount": 0}
    path = Path(path).expanduser()
    try:
        size = path.stat().st_size
        if size > MAX_BYTES:
            raise SnapshotError("Snapshot exceeds 1 MiB metadata-only limit")
        if not size:
            raise SnapshotError("Snapshot is empty")
        raw = json.loads(path.read_text(encoding="utf-8"))
        return validate_snapshot(raw)
    except FileNotFoundError:
        status, detail = "unavailable", "Configured metadata snapshot not found"
    except (SnapshotError, UnicodeError, json.JSONDecodeError, OSError, ValueError):
        status, detail = "invalid", "Metadata snapshot failed strict validation"
    return {"status": status, "complete": False, "source": "user-provided metadata snapshot",
            "projectRecords": [], "conversationRecords": [], "relationships": [],
            "warnings": [detail], "pageCount": 0}
