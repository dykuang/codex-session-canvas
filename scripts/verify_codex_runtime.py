#!/usr/bin/env python3
"""Optional Windows/desktop Codex App Server smoke test.

By default only prints availability. --run explicitly opts into creating one
real, read-only, minimal Codex thread/turn (may consume your Codex plan quota).
"""
import argparse
import json
import tempfile
from pathlib import Path

from codex_runtime import CodexRuntimeError, available, launch


def main():
    parser = argparse.ArgumentParser(description="Opt-in Codex App Server integration smoke")
    parser.add_argument("--run", action="store_true", help="Create a real Codex read-only test thread")
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args()
    print("Codex on PATH:", available())
    if not args.run:
        print("No session created. Run with --run to test the real App Server protocol.")
        return
    if not available():
        raise SystemExit("Codex CLI unavailable in this environment")
    with tempfile.TemporaryDirectory(prefix="codex-session-canvas-smoke-") as temp:
        path = Path(temp)
        print("Read-only temporary destination:", path)
        try:
            result = launch(
                "This is an explicit read-only interoperability smoke test for Codex Session Canvas. "
                "Reply in one sentence that the test thread is alive. Do not execute tools or modify any files.",
                str(path), timeout=args.timeout,
                on_started=lambda sid, status: print("Codex status:", status, sid, flush=True),
            )
        except CodexRuntimeError as exc:
            print("SMOKE FAILURE:", exc)
            if exc.thread_id:
                print("Thread may already exist:", exc.thread_id)
            raise SystemExit(1) from exc
        print("SMOKE SUCCESS:", json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
