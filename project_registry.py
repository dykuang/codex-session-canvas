"""Versioned logical-project registry and validated project dependency DAG.

A registry is explicit user configuration. Reading sessions remains metadata-only.
The data file does not contain chat messages, prompts or other rollout contents.
"""
from __future__ import annotations

import json
import ntpath
import os
import re
import shutil
import tempfile
from pathlib import Path

VERSION = 1
MAX_REGISTRY_BYTES = 262144
PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
WIN_DRIVE = re.compile(r"^[a-zA-Z]:[/\\]")


class RegistryError(ValueError):
    """Invalid registry, path assignment or DAG edge."""


def empty_registry() -> dict:
    return {"version": VERSION, "projects": [], "relationships": []}


def path_key(value: str) -> str:
    """Portable canonical comparison key; no filesystem access or I/O.

    Windows drive/UNC paths match case-insensitively regardless of host OS.
    POSIX paths retain case distinction. Path prefix checks need a separator.
    """
    if not isinstance(value, str) or not value or "\x00" in value:
        raise RegistryError("Folder must be a non-empty absolute path")
    if WIN_DRIVE.match(value) or value.startswith("\\\\") or value.startswith("//"):
        p = ntpath.normpath(value.replace("/", "\\"))
        if not ntpath.isabs(p):
            raise RegistryError(f"Not an absolute Windows path: {value!r}")
        return "win:" + p.replace("\\", "/").casefold().rstrip("/")
    if not value.startswith("/"):
        raise RegistryError(f"Not an absolute path: {value!r}")
    p = os.path.normpath(value)
    return "posix:" + p.rstrip("/") if p != "/" else "posix:/"


def _is_under(folder: str, parent: str) -> bool:
    return folder == parent or folder.startswith(parent.rstrip("/") + "/")


def validate_registry(raw: object) -> dict:
    if not isinstance(raw, dict):
        raise RegistryError("Registry must be a JSON object")
    if raw.get("version") != VERSION or isinstance(raw.get("version"), bool):
        raise RegistryError(f"Unsupported registry version (expected {VERSION})")
    projects, relationships = raw.get("projects"), raw.get("relationships")
    if not isinstance(projects, list) or len(projects) > 1000:
        raise RegistryError("projects must be an array of at most 1000 entries")
    if not isinstance(relationships, list) or len(relationships) > 5000:
        raise RegistryError("relationships must be an array of at most 5000 entries")
    ids: set[str] = set()
    folders_seen: dict[str, str] = {}
    clean_projects = []
    for item in projects:
        if not isinstance(item, dict):
            raise RegistryError("Project must be an object")
        pid, name, folders = item.get("id"), item.get("name"), item.get("folders")
        if not isinstance(pid, str) or not PROJECT_ID.fullmatch(pid) or pid in ("all", "session"):
            raise RegistryError(f"Invalid project id: {pid!r}")
        if pid in ids:
            raise RegistryError(f"Duplicate project id: {pid}")
        ids.add(pid)
        if not isinstance(name, str) or not name.strip() or len(name) > 120:
            raise RegistryError(f"Invalid name for project {pid}")
        if not isinstance(folders, list) or len(folders) > 64:
            raise RegistryError(f"folders for {pid} must be an array (at most 64)")
        clean_folders = []
        for folder in folders:
            if not isinstance(folder, str) or len(folder) > 4096:
                raise RegistryError(f"Invalid folder path for {pid}")
            key = path_key(folder)
            if key in folders_seen:
                raise RegistryError(f"Folder {folder!r} is already assigned to {folders_seen[key]}")
            folders_seen[key] = pid
            clean_folders.append(folder)
        clean_projects.append({"id": pid, "name": name.strip(), "folders": clean_folders})
    clean_edges = []
    seen_edges: set[tuple[str, str]] = set()
    graph: dict[str, list[str]] = {pid: [] for pid in ids}
    for edge in relationships:
        if not isinstance(edge, dict):
            raise RegistryError("Relationship must be an object")
        src, dst, kind = edge.get("from"), edge.get("to"), edge.get("type")
        if kind != "successor" or src not in ids or dst not in ids:
            raise RegistryError(f"Invalid successor relationship: {edge!r}")
        if src == dst:
            raise RegistryError(f"Self-loop is not allowed: {src}")
        if (src, dst) in seen_edges:
            raise RegistryError(f"Duplicate project relationship: {src} -> {dst}")
        seen_edges.add((src, dst))
        graph[src].append(dst)
        clean_edges.append({"from": src, "to": dst, "type": "successor"})
    visiting, visited = set(), set()

    def walk(pid: str):
        if pid in visiting:
            raise RegistryError(f"Project dependency cycle detected involving {pid}")
        if pid in visited:
            return
        visiting.add(pid)
        for child in graph[pid]:
            walk(child)
        visiting.remove(pid)
        visited.add(pid)

    for pid in ids:
        walk(pid)
    return {"version": VERSION, "projects": clean_projects, "relationships": clean_edges}


def load_registry(filename: Path) -> dict:
    filename = Path(filename).expanduser()
    if not filename.is_file():
        return empty_registry()
    if filename.stat().st_size > MAX_REGISTRY_BYTES:
        raise RegistryError("Project registry is too large")
    try:
        return validate_registry(json.loads(filename.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, UnicodeError) as exc:
        raise RegistryError(f"Invalid registry JSON: {exc}") from exc


def save_registry(filename: Path, raw: object) -> dict:
    """Write only validated configuration; previous file remains on failed writes."""
    registry = validate_registry(raw)
    encoded = (json.dumps(registry, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(encoded) > MAX_REGISTRY_BYTES:
        raise RegistryError("Project registry is too large")
    filename = Path(filename).expanduser()
    filename.parent.mkdir(parents=True, exist_ok=True)
    # Do not replace a damaged or invalid existing file without user intervention.
    if filename.exists():
        load_registry(filename)
    tempname = None
    try:
        fd, tempname = tempfile.mkstemp(prefix=".projects-", suffix=".tmp", dir=filename.parent)
        with os.fdopen(fd, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        if filename.exists():
            shutil.copy2(filename, filename.with_suffix(filename.suffix + ".bak"))
        os.replace(tempname, filename)
        tempname = None
    finally:
        if tempname is not None:
            Path(tempname).unlink(missing_ok=True)
    return registry


def project_for_folder(folder: str, registry: dict) -> str | None:
    """Return logical:<id> using longest matching directory prefix."""
    try:
        key = path_key(folder)
    except RegistryError:
        return None
    candidates = []
    for item in registry["projects"]:
        for configured in item["folders"]:
            parent = path_key(configured)
            if _is_under(key, parent):
                candidates.append((len(parent), item["id"]))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    tied = {id for length, id in candidates if length == candidates[0][0]}
    if len(tied) > 1:
        raise RegistryError("Ambiguous project folder assignment: " + folder)
    return "logical:" + candidates[0][1]


def format_projects(sessions: list[dict], registry: dict) -> list[dict]:
    """Keep declared projects even when they contain no local sessions."""
    from collections import Counter
    counts = Counter(s["project"] for s in sessions)
    configured = [
        {"id": "logical:" + p["id"], "logicalId": p["id"], "name": p["name"],
         "folders": p["folders"], "folderCount": len(p["folders"]),
         "configured": True, "count": counts.pop("logical:" + p["id"], 0)}
        for p in registry["projects"]
    ]
    legacy = [
        {"id": key, "name": Path(key).name if key != "(unknown cwd)" else key,
         "folders": [key] if key != "(unknown cwd)" else [], "folderCount": 1,
         "configured": False, "count": count}
        for key, count in counts.items()
    ]
    return configured + sorted(legacy, key=lambda x: (-x["count"], x["name"].casefold()))


def graph_edges(registry: dict) -> list[dict]:
    return [{"from": "logical:" + r["from"], "to": "logical:" + r["to"], "type": "successor"}
            for r in registry["relationships"]]