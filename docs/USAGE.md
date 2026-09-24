# Using Stories

Stories supports HTML presentations and structured documents with shared review.
The [installed operating guide](../src/amplifier_smart_tool_stories/SMART_TOOL.md)
is the complete CLI/library reference. The broader contracts remain the product
requirements; this release does not claim full conformance to all of them.

## Review in an MCP host

The optional `[mcp]` extra provides `stories-mcp --storage /explicit/store` and a
self-contained MCP App. Story results identify one reusable dashboard per retained
story without changing revision focus or execution authority. See [portable review and its exact capability scope](MCP.md).
It uses the same retained revisions, drafts, comments and bounded grants as the
library. Opening does not start model work; `--model-env` and a grant are both
required for generation. Native human acceptance is deliberately not exposed.

Agents and people share review navigation without choosing or accepting material:

```python
view = api.get_review_view(story)
api.update_review_view(story, expected_version=view['version'],
    request_id='review-position-1', revision_id=revision, slide=1, panel_open=True)
```

Read the view version first and reconcile stale-version conflicts. Reuse the exact
request ID only for an identical retry. The default `shared` view retains revision,
one-based slide, comparison, target, panel, expanded sections and export format.

## Import a story and open review

```python
from pathlib import Path
from amplifier_smart_tool_stories import Stories

api = Stories('/chosen/stories-state')
created = api.create_story(
    title='Quarterly update', html=Path('/chosen/update.html').read_text(),
    request_id='quarterly-import-1',
    sources=[{'id':'quarter', 'name':'Quarterly notes', 'content':'Supplied evidence'}],
)
story, revision = created['story_id'], created['revision_id']
preview = api.get_preview(story, revision)
# Inspect preview['elements'] for IDs and exact text. Never guess an anchor.
api.add_comment(story, revision, 'Please check the supporting evidence.',
    request_id='highlight-1', author='agent', anchor={'kind':'story'})
viewer = api.start_dashboard(story, revision)
print(viewer['url'])  # Private bearer URL; open it only for the intended reviewer.
```

Import retains original HTML. Media exports resolve retained asset references;
Imported scripted HTML without retained media exports unchanged. Script-free decks receive standalone slide navigation. The viewer disables source scripts,
forms and unregistered resources while allowing attached images and video. It
supplies navigation for `.slide` sections. HTML that depends on JavaScript or remote
assets may preview differently. Static model review sees video posters, not playback.

The approved interaction is material-first: the document occupies the viewport,
agent highlights reveal context, selecting text or an element offers a comment, and
the composer floats without reserving space or resizing the document. Annotations
are review state, not part of the export. The person chooses when to view a new
revision; background updates do not replace the displayed document.

## Connect intelligence

Prepare a provider once, explicitly allowing runtime module setup:

```sh
stories --provider openai prepare-runtime
stories --provider anthropic prepare-runtime
stories --provider gemini prepare-runtime
stories --model-env --provider openai test-provider
```

Use OpenAI, Anthropic and Gemini environment keys. `provider-settings` reveals only
credential readiness and variable names. ChatGPT (`chatgpt`/`openai-chatgpt`) uses
Amplifier's OAuth token cache; use `provider-login` or dashboard Sign in before generation.
Copilot (`copilot`/`github-copilot`) uses native environment tokens or explicit
`provider-login`/dashboard Sign in backed by GitHub CLI. Sign-in makes its token
available to the current process. For a later CLI process, explicitly export a
GitHub CLI token into a supported environment variable such as GH_TOKEN.
Stories never starts interactive authentication from a background worker.

```python
api = Stories('/chosen/stories-state', model_env=True,
              provider='anthropic', execution='background')
api.grant_feedback(story, {'max_operations':5, 'timeout_seconds':180}, 'review-grant-1')
viewer = api.start_dashboard(story, revision)
```

Submitted comments queue bounded model responses automatically when model access is
enabled. Without it, immediate execution retains user comments as
`awaiting_model_access` without consuming their grant or starting work that would
fail; queued execution can retain authorized work for a later model-enabled worker. Answers and
clarifications use at most two calls. Artifact production adds review against sources
and rendered images, with at most one repair and fresh review: five calls for presentations. Documents review batches of up to three pages, with
at most eleven calls including one repair.
All stages share the operation's time allowance. User drafts and caller highlights
never execute a model. Model settings are captured at operation creation; changing
settings later does not reroute existing work. No credentials are written to story
state. Provider modules own their normal OAuth and rate-limit caches.

For generation, pass explicit source strings, purpose, audience and a grant to
`generate`. Its receipt names an operation and story. `run-operation` drives queued
work; `--execution background` starts an owned worker immediately. Status reads
never restart work. A failed or interrupted operation needs explicit new intent to
spend again; an identical request_id returns its old receipt. A new revision remains
tied to its base, and the user's selected revision does not silently advance.

## Artifact quality review

Install Pango for static text layout (`brew install pango` on macOS). WeasyPrint and
PDFium are package dependencies. Rendering needs no browser download or LibreOffice;
missing prerequisites produce an actionable failure instead of installing anything.
Standard Homebrew library locations are detected on macOS; a custom installation can
set `DYLD_FALLBACK_LIBRARY_PATH` explicitly.

Narrative and design guidance adapts the bundle's audience mapping, evidence discipline,
visual hierarchy and readability guidance. The reviewer sees source texts, the request,
the exact proposed HTML and images of every rendered page. Code checks text bounds,
minimum type size, page counts and blocked resource dependencies. A model cannot
override mechanical failures. Each review records the artifact hash, rendered image
hashes, provider/model, findings and limits. Review is performed again after a repair.

The renderer runs in a cancellable subprocess, at most 40 seconds per attempt, and
cannot fetch external or local resources. It supports at most 12 static pages on a
1280x720 presentation canvas or Letter document pages. It approximates browser layout; it does not certify every viewport.
Model review is labeled as such and is not independent verification or human approval.
The selected model must support native tool submissions and image input for artifact
review. Text-only models can still answer comments but cannot complete artifact production.
If the repair still fails, the operation retains `candidate.html` and `candidate.reviews`
for inspection without committing a revision. Imported artifacts remain unreviewed.

## Export and cleanup

```python
api.export(story, revision, '/chosen/new-output.html')
api.stop_dashboard(viewer['service_id'])
```

Export refuses overwrites and contains the exact chosen artifact without annotations.
Stopping the dashboard cancels comment work it accepted, closes only its own server,
and preserves revisions, comments and drafts. Closing a browser tab does not stop the
service. CLI/API cancellation prevents late commits; a request already sent to a
provider may still be billed. There is no automatic publication or caller wake-up.

## Current limits

- HTML presentations and structured documents. Document PDF and editable Word exports
  are separate outputs with explicit layout limits. PowerPoint and spreadsheet work remain deferred.
- Review sources are supplied text; no repository/session/network research connectors.
- Isolated previews suppress source active content and unregistered assets. Native text anchors
  are Unicode character offsets, scoped to an exact revision. No automatic anchor
  reassociation between revisions.
- Semantic and static rendered-quality review are model judgments with recorded
  limits. Imported artifacts still report these as `not_performed`.
- `needs_input` is a visible clarification outcome. Use `respond` for a comment
  question or `answer-question` with a new grant for initial generation. The latter
  marks its parent `continued` and exposes `answered_by`; no implicit model continuation.
- One local host and a private loopback viewer; no remote multi-user service.
- Provider settings are session-local. ChatGPT/Copilot account authorization requires the person to complete the provider’s sign-in flow.
- macOS is the validated platform. Other platforms are not advertised yet.

## Documents

Pass `kind="document"` to `generate` (the default remains `presentation`). The model
submits content rather than CSS: title, subtitle and ordered blocks with stable IDs.
Supported block kinds are heading, paragraph, quote, list and table. Each has `id`,
`kind`, `text`, `items`, `rows`, and `evidence_ids`; unused arrays are empty. Citations
refer to the extracted evidence, with source references included in generated HTML.
Use `create-document` to import uncited structure deterministically. `get-revision`
returns the structure alongside exact HTML; `get-story` returns revision summaries.

Documents have at most 100 blocks and 12 rendered pages. Text blocks are limited to
1400 characters; lists to eight short items; tables to eight rows, five columns and
1600 characters total. Split dense material into smaller blocks. These boundaries
keep the first document renderer predictable; images, equations, inline rich text,
custom branding and arbitrary Word import are not supported.

```python
receipt = api.generate(
    title="Adoption brief", purpose="Explain the evidence and recommended next steps",
    audience="Engineering leaders", sources=source_objects,
    grant={"timeout_seconds": 600, "max_output_tokens": 12000},
    request_id="document-1", kind="document",
)
```

The document viewer defaults to continuous flow. The small **View & comments** tab
reveals controls on hover, click or keyboard focus. It offers paginated view, zoom,
fit width and navigation across both user and agent comments. Comments use existing
margin space when it is sufficient and otherwise float over the page. They never
reserve space or change document geometry. Page/zoom changes preserve the logical
passage and saved drafts. Moving away from an anchored comment closes its composer;
return through comment navigation to reopen it. Whole-story comments remain available.
Native text selection (including a range across blocks) targets exact revision-local
Unicode offsets. Stable block IDs aid position continuity; comments never silently
retarget a new revision, even when IDs remain the same.

### Document export

HTML is the exact retained artifact. `export(..., format="pdf")` produces a Letter
PDF from that HTML using the same static renderer, with text-coverage and bounds
checks. `format="docx"` produces editable paragraphs, lists and tables from the
retained structure using python-docx; no LibreOffice or skill checkout is required.
`get-export` returns base64 bytes, MIME type, revision/source/output hashes, checks
and limitations for adapters. The dashboard provides the same three download choices.
Exports do not include review annotations, and output paths are never overwritten.

Browser pagination approximates print layout. Word may wrap or paginate differently
because its renderer and available fonts differ. Inspect the exported target before
delivery: HTML model review is not advertised as Word visual review. Per-export
visual checks are explicitly `not_performed`; the PDF also reports its mechanical
checks. These are document exports, not general HTML-to-Office conversion.

## Provider settings

Open **Settings** in the presentation bar or document’s **View & comments** toolbar.
Choose Anthropic, OpenAI, Gemini, ChatGPT or GitHub Copilot, then select a model or
leave it blank for the provider default. **Apply for this session** changes future
operations and authorized feedback submitted through this viewer. It does not change
queued operations, renew feedback authority, or affect other callers. Closing and
reopening Settings preserves the applied choice; restarting the viewer uses its
launch configuration. Credentials and settings are never written to browser storage.

**Discover models** queries the prepared provider without generation. The returned
catalog does not guarantee account access or suitability for images and tools.
**Test connection** sends one small model request to the chosen provider/model;
it does not apply the selection. **Prepare runtime** explicitly downloads/installs
provider modules and checks mounting without generating a story. Preparation status
can become stale after runtime/cache changes; prepare again if instructed.

API keys stay in the native environment. **Sign in** for ChatGPT displays provider
instructions and uses its OAuth cache. Copilot uses an existing GitHub CLI login or
starts its device flow; `gh` must be installed and the account needs Copilot access.
GitHub CLI owns the login cache; the token is available in the running viewer only.
Neither sign-in nor preparation happens implicitly during generation. Setup and
checks run in the background; closing Settings does not cancel them. They time out
or stop with the viewer. While setup is active, reading and draft saving continue;
comment submission waits until it finishes. Setup is refused while story work is queued/running.

The same capabilities are available before a story exists:

```sh
stories provider-settings
stories --model-env provider-login --input '{"provider":"chatgpt"}'
stories --model-env provider-login --input '{"provider":"copilot"}'
stories --provider anthropic prepare-runtime
stories --model-env provider-models --input '{"provider":"anthropic"}'
stories --model-env --provider anthropic test-provider
```

`provider-login` relays device instructions to stderr and a JSON receipt to stdout.
Library hosts can supply an `on_progress(text)` callback. Provider login/discovery and
testing require `model_env`; merely reading or applying settings makes no network call.

## Writing for different purposes

Describe the communication goal in `generate.purpose` and its readers in `audience`.
Use `kind="document"` for prose; use `kind="presentation"` for slides. For example,
ask for release notes from supplied change descriptions, a case study from project
notes, a public feature article, a community digest, an executive brief, or an
editorial plan. No specialist-name parameter is required. `storytelling-capabilities`
returns the available approaches and their reference-bundle mapping.

For an audience adaptation, supply the existing story text as a source in a new
`generate` request, or submit a targeted comment on a retained revision. Comment
revisions keep their original artifact kind. A format change uses a new generation
request with explicit source content and desired kind; it is not a fidelity-preserving
conversion of arbitrary uploaded files. See [coverage and limits](STORYTELLING.md).

Operation results retain selected guidance IDs and hashes under
`provenance.expertise`, alongside the internal narrative plan. That trace proves
which guidance was used, not semantic correctness. Source and rendered review are
still required. Contributor guidance in [AGENTS.md](../AGENTS.md) covers the opt-in
live scenario suite and how to interpret its results.

## CLI operating skills

`stories --help` (or `-h`) prints the complete operating skill. Every capability's
`--help` and `-h` prints a focused skill with input fields, a worked JSON invocation,
result guidance, execution effects and failure handling. Both identify the installed
package resource directory; no checkout, provider access or state initialization is
needed. `stories skill` prints the same top-level skill. Global options go before
the command. Library-only callbacks are not CLI JSON inputs.

## Completing questions and inspecting accountability

Read `stories answer-question --help` for initial-generation continuation, and
`stories accept-revision --help` for explicit human acceptance. Both have library
methods with the same names using underscores. A continuation requires a new bounded
grant, keeps the original provider and story, and records its parent question. Read
its operation receipt; queued submission alone is not completion.

Sources now accept `kind` and `attribution`; use summary/hypothesis/preference to
preserve their distinction from original source text. Read the packaged operating
skill for values and defaults. Inspect `changes` and `calculations` through
get-operation/get-revision or Story details. Mechanical calculation verification does
not establish the semantic appropriateness of inputs or completeness of disclosure.

Acceptance belongs to shared story state, is tied to an exact revision/hash, and
never alters the artifact or its review findings. Calling agents record acceptance
only when explicitly conveyed by the person. Later revisions remain unaccepted.


## Images, video and packaged presentations

```python
poster = api.import_media("Demo poster", "image/png", "poster-1", path="/supplied/poster.png")
clip = api.import_media("Demo clip", "video/mp4", "clip-1", path="/supplied/demo.mp4")
image_id, video_id = poster["asset"]["id"], clip["asset"]["id"]
html = f'''<html><body><section class="slide"><h1>Demo</h1>
<video controls src="asset:{video_id}" poster="asset:{image_id}" width="640"></video>
<p>Supplied demonstration.</p></section></body></html>'''
created = api.create_story("Demo", html, "demo-1", asset_ids=[image_id, video_id])
api.export(created["story_id"], created["revision_id"], "/chosen/demo.zip", format="zip")
```

The CLI accepts the same fields as JSON; read each command's help. `generate` accepts
asset_ids too. Media composition currently applies to presentations, not structured
documents. Video inspection requires ffprobe. Playback happens inside the isolated
review frame, without exposing workspace credentials. Native playback controls remain
usable with review enabled; changing slides pauses clips on other slides.

Large images produce warnings, not silent transformations. Keep the original,
choose ZIP to avoid embedding, or explicitly request `resize_media(asset_id,
max_width, max_height, request_id)` and use its new identity in `revise_media` with
updated HTML. The original remains retained. Exported ZIP assets are byte-for-byte
originals unless the revision explicitly references a derivative. Single HTML embeds
images; video/captions require ZIP. The package uses relative paths and includes
extraction instructions. Browser file:// playback verification remains outstanding;
review-workspace playback and package contents have separate checks.

Use `get_media(story_id, revision_id, asset_id)` to retrieve exact bytes as base64.
Asset replacement creates a new delivery hash and revision; old acceptance and checks
are not inherited. Static rendering can inspect images and posters but not video
content, audio or caption synchronization. No model provider is needed for imports,
resizing, retained playback or packaging. See the packaged operating skill for supported
formats, budgets, portable-markup restrictions and limits.

Presentation HTML and ZIP exports include standalone slide navigation when the
revision has no scripts: previous/next buttons, arrow and Page Up/Down keys,
Home/End, and viewport scaling. Imported scripted decks retain their own controls.
Structured document exports remain scrolling documents. No Stories service is needed.

## Storyboards

Start with `stories generate-storyboard --help`. Ordinary creation develops one
sequence; `explore=true` is reserved for a user's request to compare alternatives.
The same shared expertise handles different audiences and media without choosing a
mandatory technical-demo or marketing mode. Sources may be empty for creative work.
Generation uses the configured provider, a shared deadline, and at most 12 model
calls including evidence planning, candidate review and one repair per candidate.

A storyboard has `name`, `approach`, `tradeoff` and at least one panel. There is no
fixed panel-count cap: the content determines how many panels are needed. Every panel supplies
`id`, `title`, `action`, `visual`, `asset_id`, `narration`, `notes`, `evidence_ids`.
Optional text is an empty string, unused citations an empty list. `asset_id` refers
to a retained still image; `visual` alone describes a planned visual. `outline` and
`mixed` permit missing images; `illustrated` requires an image on every panel.
This operation does not generate new images. Use explicit fictional labeling and
supply evidence for factual claims.

Byte, time, model and speech budgets are execution limits, not a panel quota or
permission to omit or merge scenes. Markup parsing is bounded to 32 MiB. Static
storyboard review rasterizes pages individually at the existing scale, with no
page-count cap: 35 worker CPU seconds, at most 40 wall seconds (or remaining
operation allowance), 300 MB JSON input and 64 MiB combined PDF/JPEG output.
Resource exhaustion fails explicitly without returning truncated review or
automatically rewriting the sequence to fit. Use retained structured HTML/ZIP
review, or explicitly reduce media bytes where appropriate. Model output/context
allowances remain finite and provider-dependent. This is not an unlimited-capacity
promise. Document and presentation page budgets are unchanged.

Markup beyond the parsing budget returns `markup_resource_limit`, not
`invalid_input` or a repairable quality finding. A generated candidate remains
intact in `result.failures` with its full structured sequence and resource cause;
no model repair is spent to reduce it. Retain that source and choose a workflow
with sufficient byte capacity. HTML/ZIP paths using the same parser cannot
bypass this budget.

For one speech clip per panel, configure narration as below, then call the shared
speech operation with an explicit source:

```sh
stories --store /path/to/store --model-env --execution background generate-narration --input '{"story_id":"STORY_ID","revision_id":"REVISION_ID","source":"storyboard_panels","grant":{"max_requests":70,"max_characters":84000,"timeout_seconds":300},"request_id":"panel-speech-1"}'
stories --store /path/to/store get-narration --input '{"story_id":"STORY_ID","narration_id":"NARRATION_ID"}'
stories --store /path/to/store get-narration-audio --input '{"story_id":"STORY_ID","narration_id":"NARRATION_ID","panel_id":"arrival"}'
```

`source="storyboard_panels"` speaks each retained panel's exact `narration` text.
Every panel must have nonempty text; validation identifies missing panel IDs before
spending. No silent skips, action/production-note fallback, `notes` override,
`script_id`, or storyboard-to-deck conversion. Revise the storyboard to edit speech.
The default `source="presentation"` keeps the existing presentation workflow.

The narration record retains `panel_ids` in source order, direction, revision ID
and source hash. Clips identify stable `panel_id`, one-based `position`, audio
identity/hash, sample count and measured duration. Get WAV metadata/base64 by
`panel_id`, never slide number. Partial failure retains completed clips;
`panel_errors` identify failed panel IDs/positions, and progress uses
`completed_panels`/`total_panels`. Reordering preserves panel IDs while rebuilding
the ordered mapping for the new revision. Unchanged text/settings reuse exact
cached bytes, including across panels; changed text/settings require fresh audio.

The same saved settings, grants, concurrency, exact-retry and cancellation rules
apply as for presentation speech. Defaults are not expanded automatically: beyond
12 distinct uncached texts, explicitly grant more requests and enough input
characters. The example grants 70 requests and 84000 characters, not a panel cap.
A single speech operation permits at most 100 uncached requests, 200000 input
characters and 900 seconds; cache reuse and duplicate text do not add requests.
An insufficient grant fails before spending, never drops panels. Storyboard HTML/ZIP exports do not
include synthesized audio; retrieve clips separately for production. Script
preparation, dashboard speech controls and video export remain presentation-only.

`create-storyboard` imports structure. `revise-storyboard` applies an explicit edit,
optionally attaches different assets or creates `new_direction=true`. Panel IDs
survive reordering. A direction has its own immutable revision history; a new revision
does not inherit semantic checks or acceptance. Old-head edits must explicitly branch.

The dashboard compares retained versions of all three artifact kinds. Focus & comment
opens one without choosing. Continue with this direction records storyboard selection
through `select-direction`; acceptance remains separate. `get-comparison` exposes the
same previews to headless callers. Document/presentation alternative generation is
not provided. Background revisions do not replace the version being read.

`update-storyboard-brief` records corrected common intent and supersedes existing
directions. It neither generates nor spends. Revise a chosen base through authorized
comments to apply the corrected brief, retaining sibling histories. Operations started
before a brief correction cannot commit afterward. `answer-question` retains the
requested direction count and original question context for initial clarification.

A generation can finish `partial`; inspect the completed revision IDs and retained
candidate failures, then request new work explicitly. Do not mistake one available
direction for a complete requested comparison. ZIP delivery preserves structured
content in `storyboard.json` and exact assets alongside HTML; HTML alone is review-only.
No finished video, PDF or Word storyboard export is advertised. Human review of
narrative usefulness and audience comprehension remains necessary.

### Optional production requirements

Panels may include `production_requirements`: up to four short strings (500 characters
each) describing the assets or work needed, their communication purpose and relevant
constraints. Omit the field or use `[]` for ordinary outlines. Request these requirements
when preparing a portable handoff. They are included in review HTML and structured ZIP
exports; there are no statuses, assignees, dependency tracking or required return to
Stories. Tool selection and execution remain with the caller. Requirements describe
what to produce, not a claim that footage, narration or animation already exists.

Storyboard execution may correct one malformed candidate submission within the same
shared call and time limits. Schema-declared JSON containers returned as encoded text
are decoded before validation; invalid content is never committed merely because it
can be parsed.
## Silent presentation video

Use `stories export-video` (or `Stories.export_video`) for a static presentation
with retained images. This deterministic operation requires Pango and `ffmpeg`
with `libx264` plus `ffprobe` on PATH (`brew install ffmpeg` on macOS). It never
loads a model or synthesizes speech. Without a narration ID it produces no audio track.

```sh
stories --store /path/to/store export-video --input '{"story_id":"STORY_ID","revision_id":"REVISION_ID","output_path":"/path/to/deck.mp4","slide_seconds":[10,20,20,20,20,10],"timeout_seconds":300}'
```

Supply exactly one duration per slide, in whole 30-fps frames (for example 10 or
10.1 seconds). The output is 1280×720 H.264/yuv420p MP4 with cuts between slides.
Pacing is explicit, not estimated from notes. Speaker notes are retained in the
export timeline; this silent invocation does not speak them. The result and `video_exported` event identify
the source revision, original assets, frame hashes, timeline and output hash.

Scripts, CSS animations, animated images and embedded audio/video are rejected;
this version cannot flatten a clip and call it playback. Use HTML/ZIP for those
presentations. Static rendering can differ from browser layout. Successful full
video decoding, expected frame count/duration and absence of audio are checked
separately from visual/semantic review and human acceptance.

Encoding and verification share the requested timeout (1–900 seconds, default
300); timed-out or interrupted subprocesses are terminated and temporary files
removed. The completed MP4 is published only after verification, and an existing
output is never replaced. CLI interrupts use Ctrl-C; this synchronous deterministic
export does not create a cancellable model operation. Video export is available
through the library/CLI. Narrated video also has a dashboard flow described below.


## Narration and video with audio

Narration uses direct OpenAI or Gemini speech APIs, independently of the writing
provider and Amplifier Agent. Configure speech separately for each Stories store:

```sh
stories --store /path/to/store narration-settings
stories --store /path/to/store configure-narration --input '{"provider":"openai","voice":"marin","request_id":"voice-1"}'
stories --store /path/to/store get-speaker-notes --input '{"story_id":"STORY_ID","revision_id":"REVISION_ID"}'
stories --store /path/to/store --model-env --execution background generate-narration --input '{"story_id":"STORY_ID","revision_id":"REVISION_ID","grant":{"max_requests":12,"max_characters":24000,"timeout_seconds":300},"request_id":"narration-1"}'
```

OpenAI uses `OPENAI_API_KEY` (default model `gpt-4o-mini-tts`, voice `marin`).
Gemini uses `GOOGLE_API_KEY`, falling back to `GEMINI_API_KEY` (default model
`gemini-3.1-flash-tts-preview`, voice `Kore`). Model, voice and delivery instructions
are configurable. Updated defaults do not replace saved narration settings or
explicit model choices. Key presence does not prove speech access. Anthropic, ChatGPT
and Copilot credentials are not speech credentials. Never send keys in JSON inputs.

Speech requires explicit `--model-env` authority and a bounded grant. Defaults are
12 requests, 24,000 text characters and 300 seconds; allowed maxima are 100 requests,
200,000 characters and 900 seconds. Settings changes alone incur no speech call.
Each slide must have nonempty notes of at most 4,000 characters. Omit `notes` to read
`.notes` or `[data-speaker-notes]` from each `.slide`; alternatively supply a string
array, one entry per slide, as an explicit narration adaptation. Stories retains
that text without rewriting the revision or inventing missing notes.

The example starts a background worker. The default execution mode is `queued`;
for that mode explicitly call `run-operation` with provider-use authority. The
receipt identifies an operation and narration. Use `get-operation` to poll and
`cancel-operation` to stop; `list-narrations`, `get-narration` and
`get-narration-audio` retrieve retained results, including completed slides after a
partial failure. Audio is AI-generated, mono 24 kHz, 16-bit WAV. Review it before
sharing: successful synthesis and decoding do not certify faithful pronunciation.

Each operation freezes its text and voice settings. Identical text/settings reuse
completed audio, even without credentials; only changed slides require new speech.
Exact request retries return their original receipt. SDK retries are disabled.
An uncertain provider response is not automatically resubmitted: another attempt
requires a new request ID and `retry_uncertain: true`, which may incur another charge.
Cancellation cannot undo a provider charge already in flight.

Export an exact revision and its completed narration:

```sh
stories --store /path/to/store export-video --input '{"story_id":"STORY_ID","revision_id":"REVISION_ID","narration_id":"NARRATION_ID","output_path":"/path/to/narrated.mp4"}'
stories --store /path/to/store export-video --input '{"story_id":"STORY_ID","revision_id":"REVISION_ID","narration_id":"NARRATION_ID","delivery":"separate","output_path":"/path/to/post-production.zip"}'
```

The default `delivery: "embedded"` produces H.264 MP4 with AAC audio. `separate`
produces a ZIP containing `video.mp4` (silent), `narration.wav` (aligned full track),
`slides/slide-NNN.wav` (original per-slide speech), `manifest.json` and a README.
The manifest records notes, voice settings, audio hashes and sample/frame timing.
Both modes reuse the same retained speech and render plan, with no new synthesis.

Automatic timing uses actual speech duration plus `pause_seconds` (default 0.5,
0–60), rounded up to whole 30-fps frames. Optional `slide_seconds` must leave room
for that speech and pause; conflicting timing fails rather than truncating or
speeding up audio. Notes remain tied to the selected revision. The static-rendering
limits from silent export still apply. Encoding, stream inspection and full decoding
are checked separately from visual review, listening and human acceptance.

In the dashboard, open **Story details → Narration & video**. Review or edit each
slide's narration, save speech settings, generate and listen to retained audio,
and select embedded MP4 or a separate-assets ZIP. **Generate narration & export
video** performs both steps. The viewer must have provider-use authority to generate
new speech; export from retained speech needs none. Dashboard generation authorizes
up to 12 calls, 48,000 text characters and 300 seconds. Closing the dialog preserves
its notes draft for the session; it does not cancel an active operation.


## Preparing a spoken story

Presentation generation preserves supplied speaker notes but does not automatically
create a voiceover. `prepare-narration` is an optional writing operation, using the
configured writing provider through Amplifier Agent. It works with any supported
writing-provider setup; OpenAI/Gemini speech support is only needed for synthesis.
It does not call TTS, alter the deck, or replace its speaker notes.

```sh
stories --store /path/to/store --model-env --execution background prepare-narration --input '{"story_id":"STORY_ID","revision_id":"REVISION_ID","grant":{"max_operations":1,"timeout_seconds":180,"max_output_tokens":12000},"request_id":"script-1"}'
stories --store /path/to/store get-operation --input '{"operation_id":"OPERATION_ID"}'
stories --store /path/to/store get-narration-script --input '{"story_id":"STORY_ID","script_id":"SCRIPT_ID"}'
```

The default script establishes why the audience should care, develops one main point
per slide with explanation beyond its bullets, connects slides meaningfully, and
ends with a supported takeaway. It uses concrete, speakable language and allocates
attention by importance. It does not impose a sales pitch, invent personal experiences
or read presenter cues. The entire deck, notes and retained sources go to the writing
provider. Source/slide/notes references and limitations remain in script metadata;
references to imported claims are not independent factual verification.

Optional `guidance` (up to 8000 characters) steers tone, emphasis or changes.
`draft_notes` may provide current editable passages, one per slide, including empty
entries; preparation uses them rather than silently reverting to an older script.
`target_seconds` (10–7200) gives an approximate total writing target; omitted means
content-led pacing. Results include a rough estimate at 140 words/minute, not actual
speech duration. Source-fidelity and spoken-story model review share the writing
allowance, with one repair and re-review at most: up to four model calls. Failed
candidates and findings remain on the operation. This review is not human approval,
a listening check or evidence of audience comprehension. Poll/cancel as for other
writing operations. Queued mode requires explicit `run-operation`; retries never
restart completed or uncertain work.

Refine with `prepare-narration` using `base_script_id` and new guidance/request ID.
Or use `save-narration-script` with an ordered `notes` string array and optional
`base_script_id` to retain direct edits without a model call. Edits create new script
identities and do not inherit prior model review. `list-narration-scripts` lists
versions for a story or exact revision. Earlier scripts and audio remain available.

```sh
stories --store /path/to/store --model-env --execution background prepare-narration --input '{"story_id":"STORY_ID","revision_id":"REVISION_ID","base_script_id":"SCRIPT_ID","guidance":"Make the opening warmer and focus on why the work matters.","target_seconds":120,"grant":{},"request_id":"script-2"}'
stories --store /path/to/store --model-env --execution background generate-narration --input '{"story_id":"STORY_ID","revision_id":"REVISION_ID","script_id":"SCRIPT_ID","grant":{"max_requests":12,"max_characters":24000,"timeout_seconds":300},"request_id":"speech-from-script-1"}'
```

For a narrated-video request, prepare a script when the notes are not already a
finished spoken story, then synthesize the selected script and export its audio.
Preparation does not impose an additional approval gate: continue under the caller's
existing authority. `script_id` and explicit `notes` are mutually exclusive in
`generate-narration`; omitting both preserves the existing verbatim-speaker-notes
behavior. Speech and video identify the selected script and hash. Changing a script
requires an explicit new synthesis operation, reusing unchanged slide audio.

The dashboard provides **Prepare / refine script**, optional guidance and duration,
script versions, editable passages and **Save script edits**. This is separate from
speech settings and generation; preparing never synthesizes. New results cannot
overwrite text edited while writing was in progress. Scripts can be prepared and
read without a speech API key. Use writing Settings to choose the writing provider.


Speech synthesis runs up to three distinct slide requests concurrently by default.
Set `concurrency` (1–8) on `generate-narration` to change that limit. All requests
share the same total request/character budget and operation deadline. Identical
text and voice settings within a run share one synthesis request. Completed audio
is retained by its actual slide number, even when earlier slides fail or finish
later; video assembly uses slide order. One failed request does not discard or
cancel successful work on other slides. Cancellation stops all active requests
and prevents waiting work from starting; in-flight provider charges may still occur.


Storyboard reliability: Anthropic and OpenAI API submissions request native strict
schemas through Amplifier; other adapters retain their supported tool-submission
behavior. Storyboard responses are also schema-validated locally, with at most one
structured correction per submission within the shared 12-call operation limit.
Generation can produce a storyboard or ask for clarification, not return an answer
in place of the requested artifact. Strict structure is not evidence of factual or
creative quality. Review receives code-computed narration counts and provisional
spoken-time estimates, not model-estimated word counts. Printed storyboard sheets begin with a separate direction overview,
then the panel sequence. Production requirements stay optional and concise; timing
is a provisional narration/visual budget, not a promise of produced video duration.

Inline document formatting: blocks may include `marks`, an ordered, nonoverlapping
list of `{start, end, bold, href}` ranges over the block's `text`. Offsets count
Unicode characters, end exclusive. Use `bold: true` for emphasis and an absolute
HTTP(S) `href` without credentials, or `""` for no link. Omit `marks` or use `[]`
for plain text. Formatting is supported in block text, including headings, list
introductions and table captions; list items, table cells, title and subtitle
remain plain text. Recompute marks when changing text. HTML/PDF/Word exports
preserve the formatting. Review links open separately (through the host's link
request in MCP Apps); selecting text still supports anchored comments. Raw HTML
and Markdown in text remain literal content.
