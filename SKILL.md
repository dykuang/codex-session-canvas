---
name: codex-session-canvas
description: Open a visual, metadata-only map of Codex session histories grouped by project, with fork and child-session relationships. Use when asked for session canvas, 会话画布, session map, 会话关系图, or to navigate other Codex threads.
---

# Codex Session Canvas

When the user asks to view a session canvas / 会话画布 / 项目会话总览 / session map:

1. Identify the absolute directory containing this `SKILL.md` file. Run the bundled `canvas.py` in that same directory using Python 3.
2. Execute `python3 "<skill-dir>/canvas.py" --project "<current-working-directory>" --export --open` (on Windows, use `python` rather than `python3` if required).
3. The script uses `CODEX_THREAD_ID` or `CODEX_SESSION_ID` to focus the current session. If the current session ID is known but not present in the environment, add `--session "<session-uuid>"`. A matched session takes precedence over `--project`; an unclassified session appears alone. If no session or project matches, the initial view is empty.
4. The script reads the first metadata line of each local Codex rollout and the session-name index. It does not read message bodies. Do not independently inspect conversation body text for this task.
5. Tell the user how to open the exported HTML if their system did not launch a browser automatically.
6. For continuously updated sessions, suggest running `python3 "<skill-dir>/canvas.py" --project "<cwd>" --serve --open` in a regular local terminal, leaving it running as a local HTTP server.

If compressed archives are skipped, report the warning and explain that `python -m pip install zstandard` must use the same Python environment as the canvas.

**Never infer fork links just because sessions were created close together.** Real edges come from `forked_from_id` and `parent_thread_id`, with manually created links shown distinctly.

The Codex Desktop app supports `codex://threads/<uuid>` deep links. The canvas also provides a `codex resume <uuid>` CLI fallback. These do not guarantee reuse of an already-open CLI terminal or IDE editor tab.
