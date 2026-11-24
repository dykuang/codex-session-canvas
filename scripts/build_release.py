#!/usr/bin/env python3
"""Build the self-contained v0.6.0 Codex Session Canvas distribution ZIP."""
from __future__ import annotations

import argparse
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "LICENSE", "README.md", "SKILL.md", "canvas.py", "install_skill.py",
    "codex_runtime.py", "context_engine.py", "context_graph.py",
    "context_reader.py", "context_service.py",
    "linked_context.py", "linked_refresh.py",
    "project_bridge.py", "project_registry.py", "project_server.py",
    "chatgpt_metadata.py", "chatgpt_bridge.py", "docs/chatgpt-snapshot-v1.md",
    "docs/v0.6-access-decision.md", "docs/releases/v0.6.0.md", "examples/chatgpt-metadata-v1.json",
    "docs/releases/v0.5.0.md",
)
PREFIX = "codex-session-canvas/"


def build(destination: Path) -> Path:
    destination = destination.expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    included = [ROOT / name for name in FILES]
    included.extend(sorted(p for p in (ROOT / "web").rglob("*") if p.is_file()))
    for path in included:
        if not path.is_file() or not path.resolve().is_relative_to(ROOT.resolve()):
            raise FileNotFoundError(f"Missing or unsafe distribution input: {path}")
    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as package:
        for path in included:
            package.write(path, PREFIX + path.relative_to(ROOT).as_posix())
    with ZipFile(destination) as check:
        if check.testzip() is not None:
            raise RuntimeError("Distribution ZIP CRC verification failed")
    return destination


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path,
                        default=ROOT / "dist" / "codex-session-canvas-v0.6.0.zip")
    args = parser.parse_args()
    print(build(args.output))
