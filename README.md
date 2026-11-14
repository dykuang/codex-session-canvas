# Codex Session Canvas (MVP)

A local, metadata-only visual navigator for Codex sessions, forks and child agents. It reads **only the first `session_meta` line** of each `.jsonl` or compressed `.jsonl.zst` rollout, plus the session-name index. It never parses conversation turns, assistant text or prompts.

## Quick start

Requires Python 3.10+, a browser, and the `zstandard` Python package to read compressed session archives. Install it in the same Python environment that runs the canvas:

```bash
python3 -m pip install zstandard
```

On Windows, use `python -m pip install zstandard`. Installing the package normally requires internet access; running the canvas does not. npm and an API key are not required. The demo and uncompressed files do not require `zstandard`, but scanning a compressed archive without it currently raises an error.

```bash
# Generate a self-contained HTML snapshot and open it
python3 canvas.py --export --open --project "$PWD"

# Interactive server (refreshes current local metadata on demand)
python3 canvas.py --serve --open --project "$PWD"

# Demo mode, without reading any real Codex sessions
python3 canvas.py --demo --export --output ./demo.html --open
```

On Windows PowerShell, substitute `python` and `(Get-Location).Path`:

```powershell
python .\canvas.py --export --open --project (Get-Location).Path
```

The default HTML snapshot path is `~/.codex-session-canvas/index.html`. You can override it with `--output path/to/canvas.html`. For a nonstandard Codex data folder, add `--codex-home path/to/.codex` (or set the `CODEX_HOME` environment variable).

The `--serve` mode binds **only to 127.0.0.1**, default port 8765. It has a metadata-only GET endpoint `/api/data`; it never launches commands or modifies Codex files. Stop it with Ctrl+C. Use `--port 0` for an OS-assigned port.

## Install as a Codex Skill

From the extracted project directory, install the dependency and then the Skill using the **same Python environment**:

```bash
python3 -m pip install zstandard
python3 install_skill.py
```

On Windows PowerShell:

```powershell
python -m pip install zstandard
python .\install_skill.py
```

The installer copies `SKILL.md`, `canvas.py`, and `web/` into `~/.agents/skills/codex-session-canvas/` (or a destination supplied by `--destination`). It does not install Python packages. If the Skill is invoked with a different Python environment, install `zstandard` in that environment too.

The installer will not overwrite an existing installation. To update an existing copy, run `python3 install_skill.py --force` (Windows: `python .\install_skill.py --force`); this replaces the existing Skill directory. Restart or reload Codex, then ask **“打开会话画布”** or invoke **`$codex-session-canvas`**. The Skill exports and opens a map focused on the active directory.

## UI controls

- Sidebar: switch between all recorded projects and an individual project.
- Search: filter session names, IDs and project paths. If a session matches, known ancestors remain visible for context.
- Scroll wheel: zoom; drag background: pan; drag card: reposition (browser-local persistence); Fit/Reset buttons.
- Select a card: view its ID, working directory, explicit fork/parent metadata and actions.
- **Double-click:** open `codex://threads/<uuid>` in Codex Desktop, provided the protocol is installed and the thread exists there.
- **CLI fallback:** select card and copy a `cd <cwd> && codex resume <uuid>` command. Paste into your terminal to resume.
- **Manual relations:** select a child card → 指定父节点 → click a parent. Custom links are stored in browser `localStorage`, never in the Codex rollout.
- Refresh: fetches new metadata when launched with `--serve`; for a static `.html` snapshot, rerun the export command.

## Where metadata comes from

| Source | Used fields |
|---|---|
| `$CODEX_HOME/session_index.jsonl` | `id`, `thread_name` (latest name wins) |
| `$CODEX_HOME/sessions/**/rollout-*.jsonl[.zst]` | first line `session_meta`: session UUID, cwd, creation timestamp, `forked_from_id`, `parent_thread_id`, `thread_source` |
| `$CODEX_HOME/archived_sessions/**/*.jsonl[.zst]` | same metadata, marked archived |

Projects are grouped by Git root if detectable; otherwise by recorded working folder (`cwd`). Unknown parentage is **not fabricated**: independent sessions are separate roots. If a session has no explicitly assigned name, its node displays `Session · <short UUID>`, not a preview from chat history.

## Limitations

- This MVP supports local JSONL and compressed `.jsonl.zst` rollouts, but not cloud-only conversations. Reading compressed archives requires the `zstandard` Python package.
- Fork and subagent parent fields are version-dependent, and some side chats may not expose a stable parent in the first metadata record; these remain independent roots until linked manually.
- Opening via Codex Desktop URI depends on the `codex://` handler being installed and the session being locally accessible. It does not promise which desktop window Codex will reuse. It also cannot force an existing Codex CLI/VS Code tab to switch; `codex resume` starts/continues the session in a terminal you choose.
- Static HTML exports contain session titles, IDs and local project paths. Keep exported snapshots private even though **no chat body** is included.
- Local annotations are per browser/origin. They are not yet synced between browser profiles or PCs.

## Run tests

```bash
python3 -m unittest discover -s tests -v
```

## Development roadmap

A VS Code Webview panel + command palette integration, persistent external graph annotations, and streaming updates from the official app-server `thread/list` interface can improve this without ever processing conversation bodies. Keep the stable metadata-only scanner and Codex Desktop deep-link navigation as the initial foundation.

## License

[MIT](LICENSE) © 2026 Dongyang Kuang
