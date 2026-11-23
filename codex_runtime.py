"""Codex App Server adapter. Never executes arbitrary graph commands.

Creates a real thread and starts its initial turn only after local user approval.
The adapter waits for turn completion so the child app-server is not killed mid-turn.
"""
from __future__ import annotations
import json
import queue
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path


class CodexRuntimeError(RuntimeError):
    def __init__(self, message, *, thread_id=None):
        super().__init__(message)
        self.thread_id = thread_id


def available():
    return bool(shutil.which("codex"))


def _valid_id(value):
    try: return str(uuid.UUID(str(value)))
    except (ValueError, TypeError):
        # Codex may return a protocol-specific thread string in some versions.
        if isinstance(value, str) and value.startswith("thr_") and len(value) < 128:
            return value
        raise CodexRuntimeError("Unexpected thread ID from Codex")


def launch(prompt, cwd, *, timeout=180, command=None, on_started=None, existing_thread_id=None):
    """Return (thread id, status) after turn completed. Fail closed on protocol errors.

    Can be injected a fake app-server command in tests. stdout is read by a
    dedicated thread for Windows compatibility (select() does not work on pipes).
    """
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 160000:
        raise CodexRuntimeError("Invalid approved prompt")
    folder = Path(cwd)
    if not folder.is_absolute() or not folder.is_dir():
        raise CodexRuntimeError("Target working directory does not exist")
    executable = shutil.which("codex")
    if command is None:
        if not executable:
            raise CodexRuntimeError("Codex CLI is not installed or is not on PATH")
        command = [executable, "app-server"]
    proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, text=True, encoding="utf-8", bufsize=1)
    rx = queue.Queue(maxsize=1500)
    thread_id = None

    def pump():
        try:
            for line in proc.stdout:
                if len(line) > 2_000_000:
                    continue
                try: obj = json.loads(line)
                except ValueError: continue
                try: rx.put(obj, timeout=2)
                except queue.Full: return
        finally:
            try: rx.put_nowait({"_eof": True})
            except queue.Full: pass
    threading.Thread(target=pump, daemon=True).start()
    deadline = time.monotonic() + timeout

    def send(payload):
        proc.stdin.write(json.dumps(payload, ensure_ascii=False) + "\n")
        proc.stdin.flush()

    def receive(predicate):
        while time.monotonic() < deadline:
            try: event = rx.get(timeout=min(1.0, max(.01, deadline - time.monotonic())))
            except queue.Empty:
                if proc.poll() is not None:
                    raise CodexRuntimeError("Codex app-server exited unexpectedly", thread_id=thread_id)
                continue
            if "_eof" in event:
                raise CodexRuntimeError("Codex app-server closed the connection", thread_id=thread_id)
            if predicate(event):
                if "error" in event:
                    raise CodexRuntimeError(f"Codex protocol error: {event['error']}", thread_id=thread_id)
                return event
        raise CodexRuntimeError("Codex request timed out; inspect the thread before retrying", thread_id=thread_id)

    try:
        send({"id": 1, "method": "initialize", "params": {
            "clientInfo": {"name": "codex_session_canvas", "title": "Codex Session Canvas", "version": "0.4.0"}}})
        receive(lambda e: e.get("id") == 1)
        send({"method": "initialized", "params": {}})
        if existing_thread_id is None:
            send({"id": 2, "method": "thread/start", "params": {
                "cwd": str(folder), "sandbox": "readOnly", "approvalPolicy": "never"}})
        else:
            expected_id = _valid_id(existing_thread_id)
            send({"id": 2, "method": "thread/resume", "params": {"threadId": expected_id}})
        msg = receive(lambda e: e.get("id") == 2)
        thread_id = _valid_id((msg.get("result") or {}).get("thread", {}).get("id"))
        if existing_thread_id is not None and thread_id != expected_id:
            raise CodexRuntimeError("Resumed thread does not match linked session")
        if on_started: on_started(thread_id, "thread_created")
        send({"id": 3, "method": "turn/start", "params": {
            "threadId": thread_id, "input": [{"type": "text", "text": prompt}]}})
        response = receive(lambda e: e.get("id") == 3)
        turn = (response.get("result") or {}).get("turn") or {}
        turn_id = turn.get("id")
        if not isinstance(turn_id, str) or not turn_id:
            raise CodexRuntimeError("Codex did not accept the initial turn", thread_id=thread_id)
        if on_started: on_started(thread_id, "turn_started")
        while True:
            event = receive(lambda e: e.get("method") == "turn/completed" and (
                (e.get("params") or {}).get("threadId") == thread_id))
            turn = (event.get("params") or {}).get("turn") or {}
            status = turn.get("status")
            if status == "completed":
                return {"threadId": thread_id, "turnId": turn_id, "status": "completed"}
            raise CodexRuntimeError(f"Codex turn did not complete successfully: {status}", thread_id=thread_id)
    finally:
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            proc.kill()
            proc.wait(timeout=5)
        finally:
            if proc.stdin: proc.stdin.close()
            if proc.stdout: proc.stdout.close()


def continue_thread(prompt, cwd, thread_id, *, timeout=180, command=None, on_started=None):
    """Continue an existing linked Codex thread; never starts another thread."""
    return launch(prompt, cwd, timeout=timeout, command=command,
                  on_started=on_started, existing_thread_id=_valid_id(thread_id))
