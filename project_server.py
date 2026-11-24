"""Local-only project registry editor API with CSRF/origin protection."""
from __future__ import annotations

import json
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from context_graph import GraphError
from context_reader import ContextReadError
from context_service import ContextService

from project_bridge import project_data
from project_registry import MAX_REGISTRY_BYTES, RegistryError, save_registry


def run_server(host: str, port: int, codex_home: Path, focus: str, demo: bool,
               should_open: bool, session_id: str, registry_path: Path, chatgpt_snapshot: Path | None = None):
    if host != "127.0.0.1":
        raise ValueError("Only 127.0.0.1 can be used for the editing server")
    import canvas
    csrf = secrets.token_urlsafe(32)
    context = ContextService(registry_path, codex_home, lambda: canvas.build_data(codex_home, focus, demo, session_id)['sessions'])

    class Handler(BaseHTTPRequestHandler):
        def _headers(self, status: int, data: bytes, mime: str):
            self.send_response(status)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def _json(self, status: int, payload: dict):
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._headers(status, data, "application/json; charset=utf-8")

        def _local_host(self):
            return self.headers.get("Host", "") == f"127.0.0.1:{self.server.server_address[1]}"

        def _data(self):
            base = canvas.build_data(codex_home, focus, demo, session_id)
            from chatgpt_bridge import merge_chatgpt
            return merge_chatgpt(project_data(base, registry_path, focus, session_id, demo), registry_path, chatgpt_snapshot)

        def do_GET(self):
            route = urlsplit(self.path).path
            if not self._local_host():
                self._json(403, {"error": "Invalid Host header"})
                return
            try:
                if route == "/":
                    data = self._data()
                    data["csrfToken"] = csrf
                    html = canvas.render_html(data, live=True).encode("utf-8")
                    self._headers(200, html, "text/html; charset=utf-8")
                elif route == "/api/data":
                    self._json(200, self._data())
                elif route.startswith("/api/context/"):
                    self._json(200, context.get(route, parse_qs(urlsplit(self.path).query)))
                else:
                    self._json(404, {"error": "Not found"})
            except (RegistryError, OSError) as exc:
                self._json(500, {"error": str(exc)})
            except (GraphError, ContextReadError) as exc:
                self._json(400, {"error": str(exc)})

        def do_POST(self):
            port = self.server.server_address[1]
            same_origin = self.headers.get("Origin") == f"http://127.0.0.1:{port}"
            safe_fetch = self.headers.get("Sec-Fetch-Site", "same-origin") in ("same-origin", "none")
            if (not self._local_host() or not same_origin or not safe_fetch or
                    self.headers.get("X-Canvas-CSRF") != csrf or
                    self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json"):
                self._json(403, {"error": "Forbidden origin, content type or token"})
                return
            route = urlsplit(self.path).path
            if (route != "/api/projects" and not route.startswith("/api/context/")) or demo:
                self._json(404, {"error": "Endpoint not found or demo mode"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not (0 < length <= MAX_REGISTRY_BYTES):
                    self._json(413, {"error": "Invalid configuration size"})
                    return
                raw = json.loads(self.rfile.read(length).decode("utf-8"))
                if route == "/api/projects":
                    saved = save_registry(registry_path, raw)
                    self._json(200, {"ok": True, "registry": saved, "data": self._data()})
                else:
                    self._json(200, context.post(route, raw, demo=demo))
            except (ValueError, UnicodeError, RegistryError, GraphError, ContextReadError) as exc:
                self._json(400, {"error": str(exc)})
            except OSError as exc:
                self._json(500, {"error": str(exc)})

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer((host, port), Handler)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Codex Session Canvas v0.6: {url}", flush=True)
    if should_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()