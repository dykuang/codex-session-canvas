"""Merge strict, read-only ChatGPT metadata with Codex v0.5 project/session views."""
from __future__ import annotations
import datetime as dt
from collections import Counter
from pathlib import Path
from chatgpt_metadata import load_snapshot
from project_registry import load_registry


def merge_chatgpt(base: dict, registry_path: Path, snapshot_path: Path | None) -> dict:
    """Do not deduplicate cloud and local sessions, even with identical raw IDs/titles."""
    source = load_snapshot(snapshot_path)
    registry = load_registry(registry_path)
    mappings = {p["chatgptProjectId"]: "logical:" + p["id"]
                for p in registry["projects"] if p.get("chatgptProjectId")}
    data = dict(base)
    sessions = [dict(s, source="codex", sourceId="codex:" + s["id"],
                     navigation="codex-desktop", archivedKnown=True)
                for s in base.get("sessions", [])]
    projects = [dict(p) for p in base.get("projects", [])]
    existing = {p["id"]: p for p in projects}
    cloud_projects = {}
    for p in source["projectRecords"]:
        key = mappings.get(p["id"], "chatgpt:" + p["id"])
        name = p["title"] or ("ChatGPT · " + p["id"])
        cloud_projects[p["id"]] = key
        if key in existing:
            # A source title is authoritative for explicitly ID-matched ChatGPT mirror.
            if p["title"]:
                existing[key]["name"] = p["title"]
            existing[key]["chatgptProjectId"] = p["id"]
        else:
            item = {"id": key, "name": name, "count": 0, "folders": [],
                    "folderCount": 0, "configured": False, "source": "chatgpt",
                    "chatgptProjectId": p["id"]}
            projects.append(item)
            existing[key] = item
    unassigned = "chatgpt-group:unassigned"
    for c in source["conversationRecords"]:
        pid = cloud_projects.get(c["projectId"], unassigned)
        if pid not in existing:
            item = {"id": unassigned, "name": "ChatGPT · 未分配项目",
                    "count": 0, "folders": [], "folderCount": 0,
                    "configured": False, "source": "chatgpt"}
            projects.append(item)
            existing[pid] = item
        name = c["title"] or "ChatGPT · " + c["id"]
        stamp = c["updatedAt"] or c["createdAt"]
        try:
            unix = dt.datetime.fromisoformat(stamp).timestamp() if stamp else 0
        except ValueError:
            unix = 0
        sessions.append({
            "id": "chatgpt:" + c["id"], "sourceId": "chatgpt:" + c["id"],
            "source": "chatgpt", "name": name, "named": bool(c["title"]),
            "project": pid, "cwd": "", "created": c["createdAt"],
            "updated": stamp, "updatedUnix": unix,
            "archived": c["archived"] is True, "archivedKnown": c["archived"] is not None,
            "forkedFrom": None, "parentThread": None, "threadSource": "",
            "navigation": "none",
        })
    counts = Counter(s["project"] for s in sessions)
    for project in projects:
        project["count"] = counts.get(project["id"], 0)
    data["sessions"] = sessions
    data["projects"] = projects
    if data.get("focus") == "session:unknown" and source["conversationRecords"]:
        data["focus"] = "all"
    data["cloudRelationships"] = source["relationships"]
    data["chatgptSource"] = {
        k: source[k] for k in ("status", "complete", "source", "warnings", "pageCount")
    }
    if "exportedAt" in source:
        data["chatgptSource"]["exportedAt"] = source["exportedAt"]
    return data
