# Codex Session Canvas (v0.2 development)

A local, metadata-only visual navigator for Codex sessions, forks and child agents. It reads **only the first `session_meta` line** of each `.jsonl` or compressed `.jsonl.zst` rollout, plus the session-name index. It never parses conversation turns, assistant text or prompts.

## Quick start

Requires Python 3.10+, a browser, and the `zstandard` Python package to read compressed session archives. Install it in the same Python environment that runs the canvas:

```bash
python3 -m pip install zstandard
```

On Windows, use `python -m pip install zstandard`. Installing the package normally requires internet access; running the canvas does not. npm and an API key are not required. The demo and uncompressed files do not require `zstandard`, but compressed archives are skipped with a visible warning when it is missing.

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

The `--serve` mode binds **only to 127.0.0.1**, default port 8765. It has a metadata-only GET endpoint `/api/data`; v0.2 also supports a CSRF-protected, same-origin POST `/api/projects` endpoint that writes only the validated project registry. It never launches commands or modifies Codex session files. Stop it with Ctrl+C. Use `--port 0` for an OS-assigned port.

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

The installer copies `SKILL.md`, `canvas.py`, `project_registry.py`, `project_bridge.py`, `project_server.py` and `web/` into `~/.agents/skills/codex-session-canvas/` (or a destination supplied by `--destination`). It does not install Python packages. If the Skill is invoked with a different Python environment, install `zstandard` in that environment too.

The installer will not overwrite an existing installation. To update an existing copy, run `python3 install_skill.py --force` (Windows: `python .\install_skill.py --force`); this replaces the existing Skill directory. Restart or reload Codex, then ask **“打开会话画布”** or invoke **`$codex-session-canvas`**. See **Default view and session selection** below for how the current session is selected.

## Default view and session selection

The canvas uses `--session <UUID>` when supplied; otherwise it reads `CODEX_THREAD_ID`, then `CODEX_SESSION_ID`. When that session is found locally, its Git root or ChatGPT project directory determines the initial project view. For a session outside those recognised project directories, the initial view contains only that session. The sidebar still allows switching to other project groups or all projects.

If the session ID is unavailable or not found, `--project` selects its recorded project group when one matches. With no matching group, the initial view is empty rather than showing all projects. A matching current session takes precedence over `--project`. To select a known session explicitly:

```powershell
python .\canvas.py --export --open --session <session-uuid>
```

Replace `<session-uuid>` with the actual UUID (without angle brackets). The sidebar groups non-Git sessions by recorded working directory, even though an unclassified current session initially appears alone.

## UI controls

- Sidebar: switch between all recorded projects and an individual project.
- Search: filter session names, IDs and project paths. If a session matches, known ancestors remain visible for context.
- Scroll wheel: zoom; drag background: pan; drag card: reposition (browser-local persistence); Fit/Reset buttons.
- Select a card: view its ID, working directory, explicit fork/parent metadata and actions.
- **Double-click:** open `codex://threads/<uuid>` in Codex Desktop, provided the protocol is installed and the thread exists there.
- **CLI fallback:** select card and copy a `cd <cwd> && codex resume <uuid>` command. Paste into your terminal to resume.
- **Manual relations:** select the destination session → 添加手动关系 → choose handoff, reference, or other → click the source session. Multiple manual links can coexist with automatic links. 删除此会话的手动关系 removes all manual links for that destination; automatic links remain. Links and positions are stored in browser `localStorage`, not in rollouts, and are separate per browser and origin. Use 全部项目 to connect or view cross-project links.
- Refresh: fetches new metadata when launched with `--serve`; for a static `.html` snapshot, rerun the export command.

## Where metadata comes from

| Source | Used fields |
|---|---|
| `$CODEX_HOME/session_index.jsonl` | `id`, `thread_name` (latest name wins) |
| `$CODEX_HOME/sessions/**/rollout-*.jsonl[.zst]` | first line `session_meta`: session UUID, cwd, creation timestamp, `forked_from_id`, `parent_thread_id`, `thread_source` |
| `$CODEX_HOME/archived_sessions/**/*.jsonl[.zst]` | same metadata, marked archived |

Without an explicit logical-project registry, the sidebar groups sessions by Git root if detectable; otherwise by recorded working folder (`cwd`). Unknown parentage is **not fabricated**: independent sessions are separate roots. If a session has no explicitly assigned name, its node displays `Session · <short UUID>`, not a preview from chat history.


## v0.2 — Multi-folder logical projects and Project DAG

In local server mode (`python canvas.py --serve --open`), click **Project Graph** in the top toolbar. Create a new project, add one absolute working directory per line, and click **保存项目配置**. Select a project and press **连线 → 选择后继项目**, then click the successor node to connect predecessor → successor. Multiple predecessors can target the same project (A → C and B → C); cycles, duplicate folder ownership, and invalid IDs are rejected by the server. Double-click a project to switch to its aggregated Session Graph. Double-click a Session to open Codex Desktop as before. Project and Session relations are distinct data layers.

The default registry is `~/.codex-session-canvas/projects.json`. Override with `--config path/to/projects.json`. A minimal Windows example is:

```json
{
  "version": 1,
  "projects": [
    {"id": "A", "name": "Project A", "folders": ["C:/Research/A"]},
    {"id": "B", "name": "Project B", "folders": ["C:/Research/B"]},
    {"id": "C", "name": "Project C", "folders": ["D:/Research/C", "E:/Experiments/C"]}
  ],
  "relationships": [
    {"from": "A", "to": "C", "type": "successor"},
    {"from": "B", "to": "C", "type": "successor"}
  ]
}
```

Projects have stable user-defined IDs, independent of folder paths. For matching, Windows drive and UNC paths are case-insensitive; POSIX paths retain case sensitivity. When folder mappings are nested, the longest valid directory-prefix wins. An unmatched session remains in the automatically discovered Git-root/cwd grouping. Empty configured projects remain visible. One Session has one primary logical project but many sessions may share a project. The config persists independently of browser-local Session annotations and node positions. A `projects.json.bak` backup is retained on subsequent saves.

A standalone `--export` HTML snapshot is **read-only** for project settings; use **导出 JSON** and import it by placing the validated JSON at the `--config` path (or use the local server editor). Keep project paths and session names private. The server binds only to `127.0.0.1`; write requests require the exact loopback Origin, JSON content type and a per-process CSRF token. Neither the editor nor project relation edges read chat bodies. The v0.3 Context Graph is implemented on the v0.3-v0.4 development branch, and still requires validation before release.

**Windows development verification** (PowerShell):

```powershell
python .\\canvas.py --serve --open --project (Get-Location).Path
python -m unittest discover -s tests -v
```

For backward compatibility, launch with no registry and the original Session Graph works. To revert project grouping, back up and remove `projects.json`; existing Codex session files are never modified.

## v0.3 + v0.4 (development branch) — Context Node Editor and executable workflow

**Important:** v0.3/v0.4 are under active development. Before a release, verify the installed Windows Codex CLI's exact App Server protocol and check CI. Do not assume this branch has been merged into main.

Start the **local server** (required for graph edits and reading selected history):

```powershell
python .\canvas.py --serve --open --project (Get-Location).Path
```

Click **Context Graph** at the top of the Session Canvas. The third relationship layer is independent of Project DAG successor edges and of Fork/parent/manual Session links. Create a graph using **+ Graph** or edit the default **main** graph. The graph is stored separately as `~/.codex-session-canvas/context-graphs/<graph-id>.json` with a version/revision and atomic save. It stores node settings, project IDs, source session UUIDs, selection IDs, human-authored notes/approved summaries and wire topology, **not raw historical turns** by default.

A validated A1+B2+A3 → Selector/Summary/Note → Merge → new Session C example is available in [`examples/context-three-source.json`](examples/context-three-source.json); replace the example Session UUIDs and target working folder before using it. The file contains no historical conversation bodies.

### Typical cross-project workflow

1. Select a historical Session A1 from the Session dropdown, click **+ Source**. Repeat for B2 and A3; add one **Selector** for each, then **Merge** and **New Session**.
2. Connect **Source output → Selector input**, **Selector output → Merge input** (three sources), **Merge output → New Session input**. Click output then input, or drag between sockets.
3. Select a Selector and explicitly click **授权读取**. The local reader only fetches that Session after approval, returns bounded user/assistant text segments, and excludes system messages and tool execution/output by default. Tick chosen turn IDs, or explicitly choose the limited **all** mode.
4. Add **Context Note** for extra instructions; optionally insert an editable **Summarize** node after a Selector. Summaries are **manual/curated** in this release, not an automatically connected paid model call; mark them approved.
5. Configure a Merge budget, then select a **real destination working folder** and initial task in **New Session**. The destination folder is one folder from the logical project, not the entire folder set.
6. **保存 → 预览**. Inspect the **exact** untrusted-reference prompt text, source UUIDs, estimated token budget and SHA-256 fingerprint. No context is sent to Codex before final confirmation. Edit/exclude sensitive material in source/selector/note/summary and re-preview, or directly redact the Context preview and click **应用脱敏修改** to rebind the one-time approval to the edited hash. Editing the preview invalidates prior approval, and the task/safety preamble cannot be silently changed through the redaction endpoint.
7. **创建 Session** requires a *second confirmation* and a short-lived, one-time server approval token. The server re-checks source revisions and package hash. If the Codex CLI App Server is available, it invokes `thread/start` and `turn/start` with the approved snapshot, **read-only sandbox**, and a supplied task in the selected directory. The UI displays actual thread/turn statuses, never inventing a UUID.
8. **运行记录** shows metadata-only manifests with the target thread ID, source UUIDs/revisions, graph/package hash and status. On restart, records remain available; graph config and manifests are distinct from Codex rollouts.

### Security and runtime boundaries

- Merely opening/searching/refreshing Project, Session or Context Graph does **not** read chat bodies. Reading requires user action and same-origin, CSRF-protected localhost POST. No cloud backend or API key is needed to run the canvas, but using Codex to execute a new turn requires a working installed/authenticated Codex CLI.
- Historical material may include inaccurate or malicious instructions; it is supplied as **untrusted reference data** inside the explicit new-user-task prompt. This is not a complete technical prompt-injection guarantee. Review and redact confidential content before approving.
- The local App Server adapter is version-dependent. It launches a child `codex app-server` with safe argv (no shell commands from graph data). It can report an actual thread creation followed by a failed or timed-out turn; inspect Codex before retrying to avoid duplicate sessions. The integration does **not** claim to focus an existing Codex Desktop tab.
- Context bodies live in process memory only while preview/approval executes. Approval expires after 15 minutes or first execution. Exports are metadata-only by default and static HTML cannot execute workflows.
- Source fetching is limited to known local Codex session UUIDs and first 32 MiB per selected rollout; compressed archives need `zstandard`. Cloud-only sessions are not supported by the JSONL fallback.
- The runtime defaults to `sandbox: readOnly`, `approvalPolicy: never`, so the initial turn cannot silently modify repository files. A future explicit permission selection is required for code-changing tasks.
- To roll back, install the previous v0.2 Skill and avoid running this branch. Context graph data and provenance are isolated under their own folders; v0.2 `projects.json` remains unchanged.

### Validation

```powershell
python -m unittest discover -s tests -v
node --check web/context.js
```

The cross-platform GitHub Actions workflow checks Linux and Windows against Python 3.11 and Node 22. A real Codex Desktop/CLI integration check is separate and must run on a configured Windows machine.

For that final Windows acceptance check, use the following **explicit opt-in** smoke command from a PowerShell prompt with an authenticated Codex CLI installed:

```powershell
python .\scripts\verify_codex_runtime.py
python .\scripts\verify_codex_runtime.py --run
```

The first command only prints whether Codex is on PATH. The second creates **one real, read-only test session** in a temporary folder, may use plan quota, prints the actual thread UUID and status, and never modifies your project. Do not assume a successful mocked CI test is equivalent to this live Windows verification.

## Limitations

- This MVP supports local JSONL and compressed `.jsonl.zst` rollouts, but not cloud-only conversations. Reading compressed archives requires the `zstandard` Python package.
- Handoff and reference links are manual: conversation bodies are not read to discover them.
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
