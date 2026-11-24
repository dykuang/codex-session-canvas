# ChatGPT metadata snapshot v1 (v0.6)

This format is an **explicit user-created metadata-only interchange**, not a ChatGPT API response or proof that raw ChatGPT exports contain these fields. Use only data you can legitimately verify and are authorized to access. Raw ChatGPT ZIP / conversations.json is **not accepted** because it may contain chat bodies.

Import via `python canvas.py --chatgpt-snapshot path/to/metadata.json --serve --open`, or use the local application's explicit Import control and Refresh button. The source file is read afresh on refresh. File size limit: 1 MiB.

## Example

```json
{
  "schema": "codex-session-canvas.chatgpt-metadata",
  "version": 1,
  "exportedAt": "2026-11-24T12:00:00Z",
  "scope": "user-provided-metadata",
  "pages": [
    {
      "page": 1,
      "complete": true,
      "projects": [
        {"id": "chatgpt-project-123", "title": "AI-Skills/Agents"}
      ],
      "conversations": [
        {"id": "chat-789", "projectId": "chatgpt-project-123", "title": "Architecture Notes", "archived": false}
      ],
      "relationships": [
        {"from": "chat-789", "to": "chat-999", "type": "handoff",
         "evidence": "user-confirmed", "provenance": "manual"}
      ]
    }
  ]
}
```

Fields `id`, `title`, `projectId` are sourced **only from the supplied metadata**. Project ID and title may be absent; missing membership stays unresolved. The importer never deduces project from a conversation title.

- `schema` literal `codex-session-canvas.chatgpt-metadata`; `version` integer 1.
- `exportedAt`: valid ISO 8601 timestamp with explicit timezone. Describes snapshot age, **not last successful cloud API sync**.
- `scope`: literal `user-provided-metadata`. This discourages representing an unverified snapshot as an authenticated connector.
- `pages`: array of ordered numbered pages starting at 1. A single page is valid. Every page has `complete` boolean; false means list is incomplete. The final overall source status is `complete` only when page numbers are contiguous and all pages are complete.
- `projects`: `{id,title?}`; duplicate project IDs in later pages allowed only for deterministic last-write-wins metadata updates; empty title falls back to an ID label.
- `conversations`: `{id,title?,projectId?,createdAt?,updatedAt?,archived?}`. `archived` omitted = unknown. No body fields are permitted. Duplicate IDs in later pages replace earlier records, even when titles change. Missing project membership is shown under Unassigned ChatGPT rather than guessed.
- `relationships`: `{from,to,type,evidence,provenance?}`. Supported types: `parent`, `fork`, `handoff`, `reference`, `manual`. `evidence` is an explicit statement of provenance, e.g., `user-confirmed` or `source-verified`, not an inferred confidence value. Both endpoints must exist in the supplied cloud conversations; missing endpoint edges are omitted with a diagnostic. Edges do not modify any real chat.
- No access tokens, authentication data, prompt, message, content, turns, body, HTML or export payloads. Unknown object keys are rejected, not silently persisted.
- Per-source canonical node IDs: `chatgpt:<conversation-id>`; local Codex IDs remain UUIDs in the v0.5 frontend for backwards compatibility but gain `sourceId=codex:<uuid>`. This keeps identical raw IDs across sources distinct.
- Explicit mirror mapping may be set in the existing logical project registry using optional `chatgptProjectId` on a configured project. Missing mapping is unassigned; duplicated mappings are rejected. **Never match solely by title.**

## Failure behavior

Invalid schema, unknown keys, oversized file, invalid unicode/JSON or duplicated conflicting identities => status `invalid`, retaining all local Codex data. Missing file => `unavailable`. Old snapshot timestamp => `stale` status with age; it can still show valid records. Partial pages => `incomplete` status. The UI must report source and collection counts. No incomplete import is declared complete.

`archived` and relationship fields are not guaranteed by ChatGPT account exports. Missing metadata must not be invented. If cloud access is unavailable, produce a small manually curated metadata-only JSON (titles/IDs you know) or leave the source unconfigured; do not scrape private endpoints.

## Migration

Existing `projects.json` v1 remains readable. `chatgptProjectId` is optional; all existing project IDs, names, folder assignments, project successor edges and v0.5 manual session links stay intact. Exported HTML contains only allowlisted metadata. The local snapshot is never modified by the viewer.
