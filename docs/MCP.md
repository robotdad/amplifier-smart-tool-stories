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
intent. `stories_save_draft` accepts the observed `expected_version` (zero when
absent) and returns the new draft `version`. The shared frontend uses this content
CAS at the actual write boundary: a stale clock-skewed editor cannot overwrite a
newer acknowledged draft before a later navigation conflict. Its unsaved text
stays in its open composer for reconciliation. Exact retries are idempotent.
Sequence-only legacy callers keep their old ordering for legacy draft identities;
after CAS is used on a draft, an omitted version conflicts rather than bypassing it.
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
person or verify this claim. `stories_accept_revision` records explicitly conveyed
acceptance of the exact revision with the same caller-reported limitation.

Both surfaces compile the same native HTML, CSS, review, comparison, settings and
narration controllers. HTTP and MCP adapters supply bootstrap, public API calls,
binary transfer, external links and host context; neither adapter owns a second UI.
Feedback authority is supplied through the public library/tool, not an MCP-only
authorization panel. Exact grant retries still return their original receipt and
never replenish a consumed allowance.

Pending user mutation payloads and request IDs are inert retained review context.
An uncertain response keeps the original intent for explicit retry, including
after reconnect. Changed intent cannot silently reuse or replace that request.
Definite library rejection releases it for corrected input. Saved drafts, document
view settings and composer context do not require iframe localStorage or a shared
browser profile. The shared review identity is not an authenticated person.

The reviewer may select text or an identified element in the preview to target a
comment. Saved drafts survive reconnects. Incoming changes update shared metadata
without replacing the viewed revision on content updates or discarding unsaved typing.
`stories_get_review_view` and `stories_update_review_view` share revision focus,
one-based slide, comparison, selected anchor, review panel, expanded sections and
export format between agents and people. Read the current version before updating;
stale versions conflict instead of overwriting another participant. Reopening
restores this position. A view change is distinct from choosing a direction.
The browser follows explicit shared view changes, including agent navigation.
Audio playback position/volume and browser download handling remain local
presentation state; document passage/zoom/mode, acknowledged drafts and the underlying narration,
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
- `stories://panel-audio/{story}/{narration}/{panel}/{offset}` reads stable-panel narration.
- `stories://export/{sha256}/{offset}` reads one prepared export snapshot.

Export snapshots retain one exact byte sequence, including ZIP/PDF/Word formats
whose serializers may vary between preparations. The returned `transfer_sha256`
identifies those bytes. They last for the current MCP server process only, with a
128 MiB total cache and no silent eviction. An expired transfer gives a remedy:
prepare another export. The normal library `export` capability remains available
for durable files and larger deliveries. The App buffers at most 128 MiB per item;
this is a presenter limit, not the library's artifact limit. Reads do not publish,
regenerate media, apply drafts, or alter revision acceptance.

## Implemented capability scope

| Capability | MCP tools | Portable App |
| --- | --- | --- |
| Presentations, documents and storyboard import/generation | Yes; generation needs explicit model access and grants | Review retained results |
| Exact preview, revision history, sources and checks | Yes | Yes |
| Side-by-side revision comparison and explicit direction choice | Yes | Yes |
| Versioned review navigation, focus and panel state | Yes | Yes; reconnect restores position |
| Anchored/whole-story comments and saved drafts | Yes | Yes |
| Finite feedback authority | Yes | Uses existing authority, exactly like native review |
| Writing/speech settings and narration preparation/synthesis | Yes | Shared native dialog, scripts, generation, cancellation and playback |
| Retained images/video and chunked HTML/ZIP/PDF/Word delivery | Yes, subject to library format support | Preview and download |
| Caller-reported acceptance | Yes | Exact-revision acceptance; no verified-human claim |
| Provider login, runtime preparation, discovery and test | Durable public jobs | Shared settings controls; model access required |
| Video export from retained presentation narration | Path-free bounded bytes | Shared native export controls, no implicit synthesis |
| Automatic image generation, notifications or caller wake-up | Not added by this adapter | Not promised |

The browser uses the official MCP Apps SDK, bundled into a self-contained packaged
resource with third-party license notices. Maintainers build it with `npm ci --prefix
mcp-app` and `npm run build --prefix mcp-app`; users need no Node installation.
Provider-free tests cover paired native/independent-host storyboard review,
document view controls, acknowledged draft recovery, delayed typing, lost comment
acknowledgement, comparison and resource isolation. Both browser transports also
exercise script editing, deterministic synthetic speech, retained audio and real
FFmpeg video download. These checks do not establish live provider access or model output quality,
nor exhaustive browser coverage of every narration/provider interaction.

`stories_start_provider_job` accepts `kind` (prepare/test/models/login), provider,
model and request_id. Poll `stories_get_provider_job` using its job_id; explicit
`stories_cancel_provider_job` stops the owned worker's provider work. Setup is
given a 310-second execution deadline, progress to 30 messages of 2,000 characters. Admission and
receipt are durable before dispatch; a failed dispatch or expired job is never
automatically replayed. A claimed expired job becomes `timing_out`, not completed:
exclusion remains until the owner finishes cleanup or loss of its kernel file
lease proves that owner exited. `cancelling` likewise distinguishes a stop request
from settled cleanup. A reused PID is not ownership evidence. A lost owner is
reported failed without replay; an expired unclaimed admission is fenced before
any late worker can start. Cleanup that does not settle remains visibly blocking.
Setup excludes concurrent store work and configuration
changes. A test does not apply writing settings. Writing configuration belongs to
the server instance; speech settings remain store-scoped. Preparing runtime modules
can install dependencies; login can update native credential caches; test sends
one small model request. All require explicit model access.

`stories_get_video_export` wraps library `export_video` in owned temporary output,
requiring exact retained narration. It returns a process-lifetime immutable export
transfer, not a host path. It does not synthesize speech. Storyboard audio speaks
exact panel text by panel ID; script adaptation and video delivery remain
presentation-only. Storyboard artifact exports remain HTML/ZIP.
Temporary video output paths are omitted at event creation as well as from the
immediate response; explicit library file exports still record their caller-chosen
durable destination. Narration continuations carry story/revision/opening identity:
late receipts are retained on their original target and never control a newly opened
dialog. Metadata-only audio refresh preserves existing playable clip elements.

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
