"""Runtime bridge between the legacy metadata-only session scanner and project registry."""
from __future__ import annotations

from pathlib import Path
from project_registry import graph_edges, format_projects, load_registry, project_for_folder


def project_data(data: dict, registry_path: Path, focus: str = "", session_id: str = "", demo: bool = False) -> dict:
    """Attach logical project graph while keeping the v0.1 legacy session API."""
    if demo:
        return data
    registry = load_registry(registry_path)
    for session in data["sessions"]:
        session["sourceProject"] = session["project"]
        logical = project_for_folder(session.get("cwd", ""), registry)
        if logical:
            session["project"] = logical
    data["projects"] = format_projects(data["sessions"], registry)
    data["projectGraph"] = graph_edges(registry)
    data["registry"] = registry
    data["registryPath"] = str(registry_path)
    # Explicit current session still takes precedence, consistent with v0.1.
    current = next((s for s in data["sessions"] if s["id"] == session_id), None)
    if current and current["project"].startswith("logical:"):
        data["focus"] = current["project"]
    elif focus:
        resolved = project_for_folder(focus, registry)
        if resolved and not current:
            data["focus"] = resolved
    return data