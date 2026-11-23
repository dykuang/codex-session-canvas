"""Explicit, bounded, read-only extraction of user/assistant turns from known Codex sessions.

Never called during canvas discovery. Tool outputs/system messages are excluded.
"""
from __future__ import annotations
import hashlib
import io
import json
import uuid
from pathlib import Path

class ContextReadError(ValueError):
    pass

def _uuid(value):
    try: return str(uuid.UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise ContextReadError("Invalid session UUID") from exc

def _rollout(codex_home: Path, sid: str):
    # A validated UUID is only compared against metadata in files inside Codex home.
    matches = []
    for root in (codex_home / "sessions", codex_home / "archived_sessions"):
        if root.exists():
            matches.extend(root.rglob("*" + sid + ".jsonl"))
            matches.extend(root.rglob("*" + sid + ".jsonl.zst"))
    for path in sorted(matches, key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(codex_home.resolve()):
                continue
            with _open_rollout(path) as stream:
                record = json.loads(stream.readline(524288))
            payload = record.get("payload") or {}
            meta = payload.get("meta") or payload
            if record.get("type") == "session_meta" and _uuid(meta.get("id") or meta.get("session_id")) == sid:
                return path
        except (OSError, ValueError, KeyError, ContextReadError):
            continue
    raise ContextReadError("Local session not found or rollout unavailable")

def _open_rollout(path):
    raw = path.open("rb")
    if path.name.endswith(".zst"):
        try: import zstandard
        except ImportError:
            raw.close()
            raise ContextReadError("Compressed sessions require pip install zstandard")
        try:
            stream = zstandard.ZstdDecompressor().stream_reader(raw)
            return io.BufferedReader(stream)
        except Exception:
            raw.close()
            raise
    return raw

def revision(path: Path):
    s = path.stat()
    return hashlib.sha256((str(path.resolve()) + ":" + str(s.st_size) + ":" + str(s.st_mtime_ns)).encode()).hexdigest()

def segments(codex_home, session_id, limit=80, max_chars=48000):
    """Read only on explicit request, with strict caps and no internal/tool/system text."""
    sid = _uuid(session_id)
    if type(limit) is not int or not 1 <= limit <= 150:
        raise ContextReadError("Invalid segment limit")
    if type(max_chars) is not int or not 1 <= max_chars <= 96000:
        raise ContextReadError("Invalid character budget")
    path = _rollout(Path(codex_home).resolve(), sid)
    version = revision(path)
    output = []
    total = 0
    try:
        with _open_rollout(path) as stream:
            # Stream at most the first 32 MiB. Explicit user review may be partial.
            bytes_read = 0
            for raw in stream:
                bytes_read += len(raw)
                if bytes_read > 32 * 1024 * 1024 or len(output) >= limit or total >= max_chars:
                    break
                if len(raw) > 524288:
                    continue
                try:
                    item = json.loads(raw)
                except (ValueError, UnicodeError):
                    continue
                if item.get("type") != "response_item":
                    continue
                p = item.get("payload") or {}
                if p.get("type") != "message" or p.get("role") not in ("user", "assistant"):
                    continue
                # Exclude tool output/function_call/system/developer material.
                chunks = p.get("content") or []
                if not isinstance(chunks, list):
                    continue
                bits = [x.get("text") for x in chunks if isinstance(x, dict)
                        and x.get("type") in ("input_text", "output_text") and isinstance(x.get("text"), str)]
                val = "\n".join(bits).strip()
                if not val:
                    continue
                remaining = max_chars - total
                if len(val) > remaining:
                    val = val[:remaining]
                idx = len(output)
                output.append({"id": f"turn-{idx}", "role": p["role"], "text": val,
                               "sourceId": sid, "untrusted": True})
                total += len(val)
    except (OSError, ValueError) as exc:
        raise ContextReadError(f"Cannot decode session: {exc}") from exc
    return {"sessionId": sid, "revision": version, "segments": output,
            "truncated": total >= max_chars or len(output) >= limit}
