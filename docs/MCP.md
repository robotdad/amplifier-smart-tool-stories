# Optional MCP and MCP Apps adapter

Install the `[mcp]` extra and register a stdio server with an MCP host:

```sh
uv tool install 'amplifier-smart-tool-stories[mcp] @ git+https://github.com/robotdad/amplifier-smart-tool-stories'
stories-mcp --storage /absolute/path/to/stories
```

The store is explicit. Connecting discovers capabilities and starts no dashboard,
opens no browser, and makes no provider request. Import, retained review, comments,
drafts, selection and exports work without provider credentials. The server owns
its library client; the host does not supply hidden conversation state or models.

Generation requires restarting with `--model-env` and an explicit bounded grant on
its tool call. `--provider` and `--model` configure writing. Speech has separate
store-scoped settings and request/character bounds. The host must explicitly pass
any required provider environment variables. A tool may spawn its own background
worker; closing the App or stdio transport does not cancel that work. Use
`stories_get_operation` and `stories_cancel_operation`. Nothing automatically replays
an interrupted request. MCP sampling, Tasks and elicitation are not advertised.

## Shared review

Tool names start with `stories_` and expose typed JSON schemas. The library validates
storyboard/document structures and anchors as well. Each review-capable tool declares
`_meta.ui.resourceUri: ui://stories/review`, visible to both model and App. A host reads
that HTML resource and renders it through the standard MCP Apps bridge. The same
library and durable story/revision IDs serve both callers. No host-specific imports,
URLs, cookies or access tokens are required.

Read `stories_get_story` before continuing. Sources, annotations, selected revision,
selected direction and saved drafts are shared state. Drafts are context, not model
instructions or execution permission. Mutation `request_id` values identify exact
intent: reuse the original ID to retry that exact input, choose a new ID for new
intent. `stories_save_draft` uses a monotonically ordered `sequence` per draft.
Observing state or receiving a submission receipt does not wake a calling agent.

The App presents the actual retained, sanitized preview. A second preview can compare
another revision without selecting it. “Choose revision/direction” is an explicit
library action, separate from artifact acceptance or generation. Submitted comments
may consume an existing finite feedback grant when model access is enabled; without
one they await authority. With no `--model-env`, user submissions are still retained,
but await model access without consuming a grant or starting a worker. Exact retries
retain the same receipt, even after model access is enabled. To request execution,
enable model access, confirm a valid allowance, then submit an explicit follow-up
with a new request ID; reopening alone never starts the waiting comment.
Caller notes default to `author=agent` and never initiate model work. `author=user`
means the caller reports an actual human submission. MCP does **not** authenticate a
person or verify this claim. The portable adapter omits native human acceptance.

After an uncertain authorization response, the open App retains the original grant
and request ID for retry. Restore its input values to retry it, or use **Authorize
new feedback** to deliberately replace the allowance. Pending authorization IDs
are local to that App session; after a reload, inspect retained authority before
authorizing again.

The reviewer may select text or an identified element in the preview to target a
comment. Saved drafts survive reconnects. Incoming changes update shared metadata
without replacing the viewed revision on content updates or discarding unsaved typing.
`stories_get_review_view` and `stories_update_review_view` share revision focus,
one-based slide, comparison, selected anchor, review panel, expanded sections and
export format between agents and people. Read the current version before updating;
stale versions conflict instead of overwriting another participant. Reopening
restores this position. A view change is distinct from choosing a direction.
The browser follows explicit shared view changes, including agent navigation.
Audio playback position/volume, browser download handling, scrolling and unsubmitted
grant input fields remain local presentation state; the actual underlying narration,
export and grant actions are public tools. Preview content is nested
in a separate opaque frame, with no App bridge, credentials or network authority.
A failure loading media is visible; successful display is not a quality review.

## Binary resources and downloads

The App uses standard `resources/read`; hosts need the MCP Apps `serverResources`
capability. Media, narration and export tools return `resource_uri`, `bytes` and
`chunk_bytes` instead of base64 in model context. Read offsets 0, 524288, 1048576, ...
until `bytes` is satisfied. Each URI returns a binary resource of at most 512 KiB.
The chunk MIME type is `application/octet-stream`; the descriptor identifies the
original media/export MIME type. Reconstruct bytes before creating a browser Blob.
No URI accepts a filesystem path or reads media outside its exact retained revision.

- `stories://media/{story}/{revision}/{asset}/{offset}` reads immutable attached media.
- `stories://audio/{story}/{narration}/{slide}/{offset}` reads retained slide narration.
- `stories://export/{sha256}/{offset}` reads one prepared export snapshot.

Export snapshots retain one exact byte sequence, including ZIP/PDF/Word formats
whose serializers may vary between preparations. The returned `transfer_sha256`
identifies those bytes. They last for the current MCP server process only, with a
128 MiB total cache and no silent eviction. An expired transfer gives a remedy:
prepare another export. The normal library `export` capability remains available
for durable files and larger deliveries. The App buffers at most 128 MiB per item;
this is a presenter limit, not the library's artifact limit. Reads do not publish,
regenerate media, apply drafts, or alter revision acceptance.

## Validated capability scope

| Capability | MCP tools | Portable App |
| --- | --- | --- |
| Presentations, documents and storyboard import/generation | Yes; generation needs explicit model access and grants | Review retained results |
| Exact preview, revision history, sources and checks | Yes | Yes |
| Side-by-side revision comparison and explicit direction choice | Yes | Yes |
| Versioned review navigation, focus and panel state | Yes | Yes; reconnect restores position |
| Anchored/whole-story comments and saved drafts | Yes | Yes |
| Finite feedback authority | Yes | Explicit control; disabled without model access |
| Writing/speech settings and narration preparation/synthesis | Yes | Redacted status and retained-audio listening |
| Retained images/video and chunked HTML/ZIP/PDF/Word delivery | Yes, subject to library format support | Preview and download |
| Native human acceptance | Library/CLI only | Deliberately omitted; no verified-human claim |
| Provider login, runtime preparation and video export | Library/CLI only | Not exposed |
| Automatic image generation, notifications or caller wake-up | Not added by this adapter | Not promised |

The browser uses the official MCP Apps SDK, bundled into a self-contained packaged
resource with third-party license notices. Maintainers build it with `npm ci --prefix
mcp-app` and `npm run build --prefix mcp-app`; users need no Node installation.
Provider-free tests verify portable interaction, persistence, resource boundaries
and a separate host. They do not establish model output quality or provider access.

`respond` preserves the original annotation target and accepts explicit `author`.
Library/CLI retain their user-submission default for compatibility; the portable
MCP adapter defaults both `add_comment` and `respond` to agent notes, which never
consume feedback authority. User attribution is a caller assertion, not proof of
human identity.

Story-scoped MCP results include optional `_meta["amplifier/presentationId"]`
metadata with value `stories:story:<story_id>`. Hosts can reuse the same dashboard
across review methods while retaining exact revision links. Independent stories
have distinct identities; global status and failed calls do not invent one. This
metadata does not open a viewer, select a revision or grant execution authority.
