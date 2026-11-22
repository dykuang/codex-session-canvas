#!/usr/bin/env python3
"""Codex Session Canvas: a local, metadata-only visual session navigator.

Reads only the FIRST LINE of each Codex rollout JSONL (session_meta) and
session_index.jsonl for explicit user-assigned names. Never loads chat turns.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
import uuid
import io
import webbrowser
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

APP_DIR = Path(__file__).resolve().parent
WEB_DIR = APP_DIR / "web"


def canonical_id(value: object) -> str | None:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def project_root(cwd: str) -> str:
    """Group per Git root where it exists, else exact recorded working folder."""
    if not cwd:
        return "(unknown cwd)"
    folder = Path(os.path.expanduser(cwd))
    if not folder.is_absolute():
        return cwd
    folder = folder.resolve(strict=False)
    for path in (folder, *folder.parents):
        if (path / ".git").exists():
            return str(path)
    return str(folder)


def read_name_index(codex_home: Path) -> dict[str, str]:
    names = {}
    index_path = codex_home / "session_index.jsonl"
    if not index_path.is_file():
        return names
    try:
        with index_path.open("r", encoding="utf-8", errors="replace") as stream:
            for line in stream:
                try:
                    item = json.loads(line)
                    sid = canonical_id(item.get("id"))
                    name = item.get("thread_name")
                    if sid and isinstance(name, str) and name.strip():
                        names[sid] = name.strip()
                except (ValueError, AttributeError, TypeError):
                    continue
    except OSError:
        pass
    return names


def meta_from_file(path: Path, names: dict[str, str], archived: bool = False) -> dict | None:
    try:
        # Strictly one line only. We never load messages or prompts.
        with path.open("rb") as raw:
            if path.name.endswith(".zst"):
                import zstandard
                with zstandard.ZstdDecompressor().stream_reader(raw) as reader:
                    line = io.BufferedReader(reader).readline(512 * 1024).decode("utf-8", errors="replace")
            else:
                line = raw.readline(512 * 1024).decode("utf-8", errors="replace")
        obj = json.loads(line)
        if obj.get("type") != "session_meta":
            return None
        payload = obj.get("payload") or {}
        meta = payload.get("meta") or payload
        sid = canonical_id(meta.get("id") or meta.get("session_id"))
        if not sid:
            return None
        cwd = meta.get("cwd") or ""
        if not isinstance(cwd, str):
            cwd = ""
        project = project_root(cwd)
        ts = meta.get("timestamp") or obj.get("timestamp") or ""
        if not isinstance(ts, str):
            ts = ""
        mtime = path.stat().st_mtime
        thread_source = meta.get("thread_source")
        if not isinstance(thread_source, str):
            thread_source = ""
        return {
            "id": sid,
            "name": names.get(sid) or f"Session · {sid[:8]}",
            "named": sid in names,
            "cwd": cwd,
            "project": project,
            "created": ts,
            "updated": dt.datetime.fromtimestamp(mtime, tz=dt.timezone.utc).isoformat(),
            "updatedUnix": mtime,
            "forkedFrom": canonical_id(meta.get("forked_from_id")),
            "parentThread": canonical_id(meta.get("parent_thread_id")),
            "threadSource": thread_source,
            "archived": archived,
            "_path": str(path),
        }
    except (OSError, json.JSONDecodeError, TypeError, AttributeError, ValueError, OverflowError):
        return None


def build_data(codex_home: Path, focus: str = "", demo: bool = False, session_id: str = "") -> dict:
    if demo:
        return demo_data(focus)
    names = read_name_index(codex_home)
    by_id: dict[str, dict] = {}
    skipped_compressed = 0
    try:
        import zstandard  # noqa: F401
        has_zstandard = True
    except ImportError:
        has_zstandard = False
    for dirname, archived in (("sessions", False), ("archived_sessions", True)):
        base = codex_home / dirname
        if not base.exists():
            continue
        for path in list(base.rglob("*.jsonl")) + list(base.rglob("*.jsonl.zst")):
            if path.name.endswith(".zst") and not has_zstandard:
                skipped_compressed += 1
                continue
            session = meta_from_file(path, names, archived)
            if session:
                previous = by_id.get(session["id"])
                if previous is None or session["updatedUnix"] > previous["updatedUnix"]:
                    by_id[session["id"]] = session

    sessions = sorted(by_id.values(), key=lambda x: x["updatedUnix"], reverse=True)
    for session in sessions:
        session.pop("_path", None)
    projects = make_projects(sessions)
    focused = project_root(focus) if focus else ""
    current = by_id.get(canonical_id(session_id)) if session_id else None
    if current:
        folder = Path(current["project"])
        is_project = (folder / ".git").exists() or ".chatgpt-projects" in folder.parts
        focused = current["project"] if is_project else "session:" + current["id"]
    elif not focused:
        focused = "session:" + (canonical_id(session_id) or "unknown")
    return {
        "sessions": sessions,
        "projects": projects,
        "focus": focused,
        "demo": False,
        "skippedCompressed": skipped_compressed,
        "scannedAt": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def make_projects(sessions: list[dict]) -> list[dict]:
    grouped = Counter(s["project"] for s in sessions)
    return [{"id": key, "name": Path(key).name if key != "(unknown cwd)" else key, "count": count}
            for key, count in sorted(grouped.items(), key=lambda kv: (-kv[1], kv[0].casefold()))]


def demo_data(focus: str = "") -> dict:
    main = "/projects/Fe-Ni-Si-EOS"
    eeg = "/projects/EEG-CGFNO"
    design = "/projects/Island-3D"
    ids = [f"00000000-0000-4000-8000-{i:012d}" for i in range(1, 15)]
    rows = [
        (0, "EOS 物理模型 · 总体框架", main, None, None),
        (1, "Vinet + MGD 方案", main, ids[0], None),
        (2, "ExVol-Net 实验", main, ids[0], None),
        (3, "c/a 预测策略", main, ids[1], None),
        (4, "AIH 数据分析", main, None, ids[1]),
        (5, "误差与 UQ 评估", main, ids[2], None),
        (6, "CGFNO · 模型设计", eeg, None, None),
        (7, "双分支图编码", eeg, ids[6], None),
        (8, "谱耦合与图算子", eeg, ids[6], None),
        (9, "试次级投票器", eeg, None, ids[8]),
        (10, "实验与消融", eeg, ids[8], None),
        (11, "东澳岛交互游园", design, None, None),
        (12, "3D 地形与卡通风格", design, ids[11], None),
        (13, "活动与小游戏模块", design, ids[11], None),
    ]
    sessions = []
    for i, name, project, fork, parent in rows:
        stamp = (dt.datetime(2026, 11, 13, tzinfo=dt.timezone.utc) - dt.timedelta(days=i)).isoformat()
        sessions.append({"id": ids[i], "name": name, "named": True, "project": project,
                         "cwd": project, "created": stamp, "updated": stamp, "updatedUnix": 1794500000-i*70000,
                         "forkedFrom": fork, "parentThread": parent, "threadSource": "subagent" if parent else "",
                         "archived": i in (5,)})
    return {"sessions": sessions, "projects": make_projects(sessions), "focus": focus if focus in (main,eeg,design) else main,
            "demo": True, "skippedCompressed": 0, "scannedAt": dt.datetime.now(dt.timezone.utc).isoformat()}


def render_html(data: dict, live: bool) -> str:
    template = (WEB_DIR / "index.html").read_text(encoding="utf-8")
    styles = (WEB_DIR / "style.css").read_text(encoding="utf-8")
    script = (WEB_DIR / "app.js").read_text(encoding="utf-8")
    project_script = (WEB_DIR / "project.js").read_text(encoding="utf-8")
    project_styles = (WEB_DIR / "project.css").read_text(encoding="utf-8")
    init = json.dumps({**data, "live": live}, ensure_ascii=False, separators=(",", ":"))
    init = init.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return (template.replace("/* CSS_INJECTION */", styles + "\n" + project_styles)
            .replace("/* JS_INJECTION */", script + "\n" + project_script)
            .replace("__CANVAS_DATA__", init)


def run_server(host: str, port: int, codex_home: Path, focus: str, demo: bool, should_open: bool, session_id: str = ""):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            route = urlsplit(self.path).path
            if route == "/":
                data = render_html(build_data(codex_home, focus, demo, session_id), live=True).encode("utf-8")
                mime = "text/html; charset=utf-8"
            elif route == "/api/data":
                data = json.dumps(build_data(codex_home, focus, demo, session_id), ensure_ascii=False).encode("utf-8")
                mime = "application/json; charset=utf-8"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; img-src data:; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format, *args):
            return

    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{server.server_address[1]}/"
    print(f"Codex Session Canvas: {url}", flush=True)
    if should_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Visual Codex session graph (metadata only, no chat contents)")
    parser.add_argument("--codex-home", type=Path, default=Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")))
    parser.add_argument("--config", type=Path, default=Path.home() / ".codex-session-canvas" / "projects.json", help="Versioned logical-project registry")
    parser.add_argument("--project", default="", help="Current project directory (initial focus)")
    parser.add_argument("--session", default=os.environ.get("CODEX_THREAD_ID") or os.environ.get("CODEX_SESSION_ID", ""), help="Current session UUID")
    parser.add_argument("--demo", action="store_true", help="Use example data; no Codex files read")
    parser.add_argument("--serve", action="store_true", help="Run locally with live refresh")
    parser.add_argument("--export", action="store_true", help="Export single standalone HTML (default)")
    parser.add_argument("--output", type=Path, help="HTML destination for --export")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--open", action="store_true", help="Open in default browser")
    args = parser.parse_args(argv)
    codex_home = args.codex_home.expanduser().resolve(strict=False)
    if args.serve:
        from project_server import run_server as run_project_server
        run_project_server("127.0.0.1", args.port, codex_home, args.project, args.demo, args.open, args.session, args.config)
        return 0
    output = args.output or (Path.home() / ".codex-session-canvas" / "index.html")
    output = output.expanduser().resolve(strict=False)
    output.parent.mkdir(parents=True, exist_ok=True)
    from project_bridge import project_data
    data = project_data(build_data(codex_home, args.project, args.demo, args.session), args.config, args.project, args.session, args.demo)
    output.write_text(render_html(data, live=False), encoding="utf-8")
    print(f"Canvas exported: {output}")
    print(f"Sessions: {len(data['sessions'])} | Projects: {len(data['projects'])}")
    if data["skippedCompressed"]:
        print(f"Warning: {data['skippedCompressed']} compressed JSONL archives were skipped; install zstandard with python -m pip install zstandard")
    if args.open:
        webbrowser.open(output.as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
