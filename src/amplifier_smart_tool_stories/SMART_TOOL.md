---
smart_tool_format: 1
name: amplifier-smart-tool-stories
version: 0.1.0
description: >-
  Create evidence-based presentations and documents with agent highlights and
  anchored comments. Use for source-backed communication and shared review.
use_cases:
  - Turn supplied evidence into an HTML presentation or structured document
  - Review a story with a person and highlight material that needs attention
  - Answer or act on anchored feedback while preserving the reader's place
platforms:
  - macos
  - linux
  - windows
requires:
  - name: mcp-host
    purpose: Optional stdio MCP and portable MCP Apps review; install the mcp extra. No host is needed for library or CLI use.
    optional: true
    install: https://github.com/robotdad/amplifier-smart-tool-stories/blob/main/docs/MCP.md
  - name: model-provider-access
    purpose: Needed for generation and intelligent comment responses; retained review works without it.
    optional: true
    install: https://github.com/robotdad/amplifier-smart-tool-stories/blob/main/docs/USAGE.md
  - name: ffmpeg
    purpose: ffmpeg with libx264 and ffprobe for video export; ffprobe also inspects imported clips.
    optional: true
    install: https://github.com/robotdad/amplifier-smart-tool-stories/blob/main/docs/USAGE.md
  - name: pango
    purpose: Native text layout for static rendered review of generated and revised artifacts.
    optional: true
    install: https://github.com/robotdad/amplifier-smart-tool-stories/blob/main/docs/USAGE.md
---
# Stories

Create evidence-based HTML stories and review them with a person. The Python
library is the product; the `stories` CLI and optional local dashboard share its
state. It supports HTML presentations with retained images/video, structured documents and anchored review.
Documents export as HTML, Letter PDF or editable Word; PowerPoint and spreadsheets
remain deferred.

## Install and prerequisites

`uv tool install 'amplifier-smart-tool-stories @ git+https://github.com/robotdad/amplifier-smart-tool-stories'`

Python 3.12+. Deterministic operations require no provider. Smart operations use
embedded amplifier-agent from main. The development lockfile records a tested
revision; new Git installs resolve the current main. No Amplifier CLI session or
Anthropic skills checkout is needed.

Before model use, explicitly prepare each selected provider's runtime:
`stories --model-env --provider openai prepare-runtime`. Preparation may fetch/install Amplifier
modules and writes to its native cache. Missing preparation produces an actionable
failure; deterministic paths never initialize an agent. If native caches are manually
removed or invalidated, prepare again. Model execution uses the selected provider's
native environment/OAuth credentials and sends the supplied story/source context to it.
No fallback provider or network research occurs.

Artifact production additionally needs Pango (on macOS: `brew install pango`).
WeasyPrint and PDFium are packaged Python dependencies. No browser download or
LibreOffice is required. Missing rendering prerequisites fail the operation; they
are never installed during generation. Imports, reading and answers do not render.

Providers: openai (OPENAI_API_KEY), anthropic (ANTHROPIC_API_KEY), gemini
(GOOGLE_API_KEY or GEMINI_API_KEY), chatgpt (Amplifier's existing OAuth device-login
cache), copilot (COPILOT_AGENT_TOKEN, COPILOT_GITHUB_TOKEN, GH_TOKEN or GITHUB_TOKEN).
Aliases openai-chatgpt and github-copilot are accepted. Stories does not perform
interactive login during a call. For Copilot, use `provider-login` or dashboard Sign in with installed GitHub CLI;
subscription/model access is required. Sign-in supplies the current process with a
token. For later CLI processes, export a token from `gh auth token` into GH_TOKEN. For ChatGPT, use `provider-login` or dashboard Sign in. `provider-settings` gives redacted readiness; it
is not proof that the account can use a model. `test-provider` explicitly checks it.

## Calling it

Global options precede the capability: `--store PATH`, `--model-env`, `--provider NAME`,
`--model ID`, `--execution queued|background|in_process`. Default execution is queued.
Default provider is openai; STORIES_PROVIDER/STORIES_MODEL provide environment defaults.
Settings affect future calls and authorized feedback in this instance, never already-queued work.
`configure-provider` is process-local: a CLI call does not save settings for the next
CLI process. Pass --provider/--model on each invocation or set STORIES_PROVIDER/STORIES_MODEL. Dashboard Settings provides the same session-local selection, model discovery, connection test, explicit runtime preparation and native ChatGPT/Copilot sign-in. Keys never belong in request JSON or retained state.

Every capability accepts `--input '{...}'`, `--input @file.json`, or `--input -`.
File input loads the exact JSON content; HTML/source contents are explicit strings,
not implicitly resolved filesystem paths or URLs. `stories CAPABILITY --help` gives
its operating skill: inputs, worked invocation, results, execution and sharp edges. Results are JSON on stdout; failure is nonzero with a
code and remedy. `stories manifest` is a provider-free smoke check. `-h` and `--help`
print this complete operating guide.

```python
from amplifier_smart_tool_stories import Stories

api = Stories("/chosen/state")
receipt = api.create_story(
    title="Overview",
    html=html_string,
    sources=[{"id": "s1", "name": "Source", "content": "Source text"}],
    request_id="import-1",
)
story_id, revision_id = receipt["story_id"], receipt["revision_id"]
# Inspect revision-local element IDs and exact text before choosing an anchor.
preview = api.get_preview(story_id, revision_id)
api.add_comment(
    story_id, revision_id, "Please check this claim.", "highlight-1", anchor={"kind": "story"}, author="agent"
)
viewer = api.start_dashboard(story_id, revision_id)
```

Open the returned private loopback URL only when authorized. No browser is opened
implicitly. It is a bearer capability for this story; do not share it. The opaque
iframe suppresses source scripts, forms and unregistered resources. It displays
HTML/CSS and explicitly attached media, with review-owned navigation for `.slide`
sections. Original markup is retained; media exports resolve its asset references.
Browser annotations and drafts never enter exports. Static rendered review uses
video posters and does not certify playback or audio.

Use `get-preview` to discover anchors. Text anchors contain kind=text, element,
start/end (Unicode character offsets within that element), and exact quote. Element
anchors contain kind=element and element. Whole-story anchors contain kind=story.
Anchors never silently migrate to another revision. Person text selection and element
clicking use the same public validation. Comments open in a floating overlay and
must not alter material geometry. Agent highlights never initiate model work.

For direct comment handling, authorize a bounded number of future operations:
```python
api = Stories("/chosen/state", model_env=True, provider="anthropic", execution="background")
api.grant_feedback(story_id, {"max_operations": 5, "timeout_seconds": 180}, "grant-1")
viewer = api.start_dashboard(story_id, revision_id)
```
Each user comment consumes one operation allowance when queued. In immediate execution,
if model access is not enabled, Stories retains the comment as `awaiting_model_access`
without consuming a grant or launching work that would fail; queued execution can retain
authorized work for a later model-enabled worker. Typing/saving drafts never spends. A grant expires after one hour by default, at most 24 hours, and limits
operations, time per operation and output tokens per call. Each operation uses at most
five presentation model calls, or eleven for documents reviewed in batches of up to
three pages: evidence/planning, composition, source/page review, and at most one repair
with fresh review. Answers and clarifications use at most two. It can answer,
revise or ask for clarification. Clarifications are visible `needs_input` outcomes; use `respond` for comment questions
and `answer-question` for initial generation. They are not automatically resumed. Grants are not dollar limits. No automatic retries occur.

To generate a new story, call `generate` with title, purpose, audience, source objects,
grant and request_id. Optional kind is presentation (default) or document. The receipt identifies story and operation. Call `run-operation`
explicitly for queued execution, or choose background/in_process at submission.
Background workers survive caller exit; read operations never start workers.
Provider preparation requires explicit setup. Model access requires `--model-env`.
Sources remain identifiable by hash and evidence quotes are verified against supplied
text. New and revised artifacts require model review against sources and images of
every static rendered page (maximum 12, 1280x720 presentations or Letter documents). Mechanical findings cannot
be overridden by a model pass. Records identify exact HTML and rendered-page hashes;
an edit invalidates the old review. Rendering is bounded to 40 seconds per attempt
within the operation deadline, with external/file resource fetching disabled.
Persistent review failure retains an unaccepted candidate on the failed operation,
not a selected revision. Imports keep semantic/visual review as not_performed.
Static WeasyPrint rendering approximates browser layout; model review is neither
human approval nor independent factual verification. Generated outputs remain drafts.

## Capabilities

All exist as methods on Stories (hyphens become underscores):

- `answer-question`: answer a pending initial-generation question with an explicit grant.
- `accept-revision`: record person acceptance of an exact revision separately from model review.

- `manifest`: structured capability names, signatures and model-use classifications.
- `create-story`: import supplied HTML with title, optional sources, purpose and audience.
- `create-document`: import uncited title/subtitle/blocks structure without model use.
- `generate`: queue a presentation or document from supplied sources with a finite grant.
- `list-stories`, `get-story`: retained identities, sources, revisions, drafts and annotations.
- `get-revision`: exact immutable artifact, evidence, hash, limitations and check statuses.
- `get-preview`: isolated static HTML and revision-local element/text anchor catalog.
- `select-revision`: explicitly change the shared selected version; no approval implied.
- `grant-feedback`: bounded future user-comment authority; no spending on grant creation.
- `add-comment`: submit a user comment or caller-authored highlight, with revision and anchor.
- `respond`: user follow-up on an existing annotation's exact target; prior related comments supplied.
- `save-draft`: observed-version content CAS for shared drafts; legacy sequence ordering only for unprotected drafts, no model use.
- `read-changes`: ordered events and next cursor; no model use or notification guarantee.
- `get-operation`: status/result/error; no worker restart. An elapsed running operation is
  reported interrupted/uncertain; cancel it before explicitly creating replacement work.
- `run-operation`: claim and execute one queued operation exactly once.
- `cancel-operation`: prevent late commits and cooperatively stop active model work.
- `export`: write a named revision to a new output_path; format html (default), zip, pdf or docx.
- `get-export`: base64 bytes, MIME type, revision and source/output hashes, checks and limits.
  PDF/Word support structured documents only; no arbitrary HTML conversion.
- `storytelling-capabilities`: provider-free writing approaches and upstream mapping.
- `provider-models`: discover native model IDs; access and compatibility are not guaranteed.
- `provider-login`: explicit ChatGPT/Copilot native sign-in or API-key setup guidance.
- `provider-settings`: redacted effective settings and credential readiness.
- `configure-provider`: process-local future settings; no credential storage or spending.
- `prepare-runtime`: explicit dependency preparation, network/package/cache writes.
- `test-provider`: one small live model request, with explicit model-env.
- `start-dashboard`: owned loopback service for a named story, no automatic browser opening.
- `stop-dashboard`: release owned service, cancel its comment operations, retain all data.
- `skill`: CLI convenience printing these instructions; package resource accessible in Python.

## Continuity and limitations

Mutating submissions use caller request_id; identical retries return the original
receipt, changed payloads conflict. Request IDs are global to the selected store.
A retry receipt does not rerun failed or interrupted work. Saved operations snapshot
provider/model and grants. Cancelling prevents late commits but a provider request
already in flight may have consumed tokens. Uncertain spending is never retried silently.
A revision branches from the specified base; viewing does not implicitly advance to a
new result. The dashboard shows a quiet new-version button, preserving view, comment and
draft until explicit switching. Draft IDs should be unique per editor/session; sequence
numbers prevent older saves overwriting newer ones. Browser local draft recovery is a
convenience, while acknowledged saves are available through the library.

State and events are retained without automatic expiration in the chosen local store
(default ~/.local/share/stories). Single-host SQLite; not a multi-user hosted service.
No automatic publication, notification, caller wake-up, repository access, commits or pushes.
Only supplied content is available to intelligence. HTML with external assets or source
scripts may preview differently; exported originals may contain their original active
content. Independent semantic/visual grading, production brand systems, document images/equations,
general conversion remain outside this slice.


## Structured documents

Generate with `kind="document"`. The retained `get-revision` result includes `document`:
`{title, subtitle, blocks}`. Each block has `{id, kind, text, items, rows, evidence_ids}`;
kinds are heading, paragraph, quote, list, table. IDs are unique safe identifiers and
remain stable on unaffected blocks. Unused arrays are empty. Paragraphs/quotes have
at most 1400 characters; lists eight items (300 characters each); tables eight equal
rows, five columns, 160-character cells and 1600 characters total. Maximum 100 blocks.
The library validates evidence references and renders self-contained HTML. Sources,
uncertainty and citations remain visible. Direct import accepts uncited structure;
it does not claim factual review. Inspect the current signature with capability help.

Review defaults to continuous flow, with paginated view and zoom/fit width behind a
small hover/click/focus reveal tab. User and agent comment navigation shares the same
state. Comments anchor in available whitespace or float; never change material width.
View changes preserve the reading passage and drafts. An offscreen anchored composer
closes without discarding its draft. New revisions remain explicitly selected.

PDF exports use the retained HTML and checked Letter layout. Word exports use native
editable paragraphs, lists and tables; python-docx is packaged. No LibreOffice or
external skill checkout is a product dependency. Browser pagination is approximate;
Word line/page breaks vary with renderer/fonts. Export limitations and unperformed
visual checks are explicit. Inspect the actual target before delivery, rather than
assuming HTML review certifies another format. Annotations never enter exports.

## Provider discovery and sign-in

`provider-models(provider=None, timeout_seconds=60)` reads native model IDs from a
prepared provider without generation. Catalog presence does not guarantee access or
image/tool compatibility. `provider-login(provider=None, timeout_seconds=300)` starts
explicit ChatGPT/Copilot login; API-key providers return setup guidance. Both require
`--model-env`. Login may fetch runtime modules; device authorization remains with the
person. CLI progress goes to stderr; library hosts may pass `on_progress(text)`.
Credentials stay in native environment/provider caches, never story records.

In Dashboard Settings, testing/discovery/login do not apply the selection. Apply
changes future work in that session, preserving existing operations and grant limits.
Setup runs asynchronously; close Settings to keep reading. Sending comments waits
for setup to finish while drafts remain saved. Stop the viewer to cancel owned setup.

## Storytelling expertise

`storytelling-capabilities` lists the supported writing approaches and upstream
mapping without model access. `generate` still takes purpose, audience, sources and
kind; callers need not choose a specialist. Evidence planning selects one or two
allowlisted approaches, then composition, review and repair load that guidance.
The operation result's `provenance.expertise` records IDs, guidance hashes and
upstream resource paths; `provenance.plan` records the audience/narrative plan.
Comments can change the selected approach (for example, a leadership adaptation)
without changing the artifact kind or losing the existing revision.

Approaches: grounded narrative, case study/feature journey, release notes/migration
explanation, technical explanation, public feature communication, community
spotlight/digest, executive brief, audience adaptation, editorial planning, and
metrics/evaluation explanation. These are writing capabilities over supplied text,
not repository scanners, executable code verification, platform publishing,
spreadsheet calculation or arbitrary file conversion. All use the existing supported
presentation/document outputs and quality review, within the existing call allowance.

## Questions, source status and acceptance

`answer-question` takes operation_id, text, grant and request_id to answer a pending
initial-generation question. It creates a correlated bounded continuation in the
same story with the original provider/model and retained question/answer history.
The answered operation becomes `continued` and exposes `answered_by`; its question
is retained, while the child operation carries execution status.
Supply a new finite grant explicitly; no extra spending is inferred from the old
question. A question accepts one answer; identical request retries return the same
receipt. Default execution is queued. Comment questions still use `respond`.

Source objects accept optional `kind` (source, summary, hypothesis, preference;
default source) and `attribution` text. A source is supplied material, not certified
truth. Summary originals are not implicitly inspected. Classification and attribution
travel with the extracted evidence; preferences and hypotheses are not original
observations. Existing sources without these fields retain the source default.

Generated results and revisions expose `changes` with summary, material_changes,
omissions and assumptions, plus `calculations`. Revision review compares the base
and proposed content and checks disclosures. Calculation entries identify quoted
inputs, operation, result, decimal_places and unit. Decimal arithmetic is verified;
semantic relevance, coverage and units still require model/human review. Supported
operations are sum, difference, product, ratio and percent_change (old then new).
Rounding is half up at 0–12 decimal places. Unsupported derivations must be omitted
with a limitation or clarified. Story details exposes these records alongside sources.

`accept-revision` takes story_id, revision_id and request_id. Call only to record a
person's explicitly conveyed acceptance of that exact version. The dashboard offers
Accept this revision in Story details. Acceptance records timestamp and artifact hash,
and appears in shared story state/events. It does not change model checks, select a
version, accept later revisions, modify exports, authorize work or grant publication.


## Supplied presentation media and portable delivery

Read `stories import-media --help`, `resize-media --help`, `revise-media --help`
and `get-media --help`. Import explicit local `path` or `data_base64` with name,
MIME type and optional attribution. The returned asset ID is retained with exact
bytes. PNG/JPEG/WebP/GIF, MP4/WebM and UTF-8 WebVTT are supported; video inspection
requires ffprobe from ffmpeg. Imports do not fetch URLs or call a model.

Pass `asset_ids` to `create-story` or `generate` (presentations only). Reference them
as `<img src="asset:ASSET_ID" alt="Description">` or
`<video controls src="asset:VIDEO_ID" poster="asset:IMAGE_ID"></video>` with a
visible caption. A WebVTT track uses `<track kind="captions" src="asset:TRACK_ID"
srclang="en" label="English">` inside the video; use the actual language.
Metadata/descriptions do not establish that Stories inspected a clip's contents.
Generation/review sends rendered images and posters to the configured model, not
video/audio streams. Every revision retains its asset bindings and delivery hash.

Large image warnings appear above 2 MiB or 2560×1440 dimensions (twice the review
canvas). Explain keep-original, explicitly resized-copy and ZIP choices. Never call
resize-media without a selected resize. It creates a PNG derivative of a still image,
retains attribution/provenance and leaves the original intact. `revise-media` accepts
the complete desired asset_ids and optional replacement HTML; it creates an
unreviewed, unaccepted revision rather than modifying the base.

HTML export embeds referenced images unchanged. Video or captions require ZIP;
ZIP contains index.html, assets/, manifest.json and extraction instructions. Extract
and open index.html with assets/ alongside it. Static media packages reject source
scripts, frames, external stylesheets and CSS resource URLs rather than claiming to
bundle them. Images and video loaded in the local workspace have been browser-tested;
file:// playback from an extracted package is not yet verified. Codec compatibility
is browser-dependent. Imported scripted HTML without retained media exports unchanged,
with unretained media references disclosed; ZIP refuses missing media.

Operational budgets: 32 MiB markup parsing, 256 MiB per media asset, 40 million
pixels per image, 100 attached assets, 64 MiB encoded images per static rendering.
These are separate budgets; the old 2 MB total-HTML restriction is removed. Video
bytes stay outside model context and static rendering. Animated image review sees
only a static frame. Silent static-slide video export is available through export-video.

Presentation HTML and ZIP exports include standalone slide navigation when the
revision has no scripts: previous/next buttons, arrow and Page Up/Down keys,
Home/End, and viewport scaling. Imported scripted decks retain their own controls.
Structured document exports remain scrolling documents. No Stories service is needed.

## Storyboards and user-directed comparison

`generate-storyboard` develops one direction from `title`, `idea`, `audience`, a
finite `grant` and `request_id`. Optional `sources` may be empty for explicitly
creative work. Do not turn uncertainty into automatic alternatives: set `explore`
to true only when the person asks to explore or compare approaches. Two directions
then share one deadline and at most 12 model calls, with one repair per candidate.
The configured Amplifier Agent provider receives supplied context and rendered
review images. No new image-generation provider is invoked by storyboard work.

Use `fidelity`: `outline` (default), `mixed`, or `illustrated`. Panels can reference
supplied retained still images through `asset_id`; visual descriptions with an empty
asset ID remain visibly planned. Illustrated delivery requires images for every
panel. Missing images may lead to clarification or explicit failure, never fabricated
asset IDs. Image generation across formats is still a separate planned capability.

The structured `storyboard` used by `create-storyboard` and `revise-storyboard` is:

```json
{"name":"Follow the request","approach":"A concrete journey","tradeoff":"Less system detail","panels":[{"id":"arrival","title":"A request arrives","action":"A fictional team receives a request.","visual":"Sketch of a request card","asset_id":"","narration":"","notes":"","evidence_ids":[]}]}
```

The content dictates panel count, with at least one panel and no fixed maximum.
Keep IDs stable when reordering or revising. Resource limits are separate from
content: no truncation or scene merging to satisfy a panel quota.

Markup parsing has a 32 MiB budget. Static storyboard review rasterizes one page at
a time at the existing scale, without a page-count cap. It retains the 35-second
worker CPU and at-most-40-second wall-time limits (also bounded by the remaining
operation allowance), with 300 MB of JSON input and 64 MiB of combined PDF/JPEG
output. Resource exhaustion fails explicitly; it does not report partial sheets
as a complete review or spend on rewriting the sequence to fit. Use retained
structured HTML/ZIP review, or explicitly reduce media bytes as appropriate.
Model output/context and speech grants remain separate bounded resources, not a
promise of unlimited capacity. Document/presentation page budgets are unchanged.
Exceeding the markup parsing budget returns `markup_resource_limit`, distinct
from invalid HTML. Generated candidates remain intact in `result.failures` with
their resource cause; no model repair is spent to shrink them. Retain that complete
structured source for a workflow with sufficient byte capacity—HTML/ZIP paths
using the same parser cannot bypass its byte budget.
`create-storyboard` imports this structure without a model. `revise-storyboard`
retains explicit edits and optional replacement `asset_ids`; `new_direction=true`
creates an explicitly requested alternative from the identified base. Ordinary edits
require the latest revision of that direction; old revisions are preserved.

`get-comparison` reads one or two `revision_ids` in the same story, or the latest
heads by default. It works with storyboard, document and presentation previews,
without implying matching page counts. The dashboard's Compare action supports
side-by-side inspection and Focus & comment; neither chooses a direction. Only
`select-direction` records a choice. Selection is not acceptance or model authority.
Generating alternative documents or presentations remains deferred.

Read `get-operation`: initial questions use `answer-question` with fresh bounded
authority; comments use the existing feedback grant. `partial` means some requested
directions failed. Inspect `result.revision_ids`, `failures` and `review_attempts`;
failed candidate submissions are retained for diagnosis. The CLI exits nonzero for
partial execution. Never retry an acknowledged request to restart spending.

`update-storyboard-brief` accepts `brief` with `intent`, `assumptions` and
`open_questions`; it retains prior briefs and marks old directions superseded without
generation. Comment-driven revision can apply the new brief under existing authority;
other directions remain superseded. In-flight old-brief work cannot commit.

Storyboard HTML is a review-only export. ZIP includes `index.html`, editable
`storyboard.json`, a delivery manifest and exact referenced assets. Planned images
remain planned; required assets are verified. Storyboards do not export finished
video, animation, speech, PDF or Word. Model review is not human acceptance, proof
of meaningful alternatives, or evidence that an audience understood the sequence.

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
## Silent video delivery

`export-video` / `Stories.export_video` writes a static presentation to 1280×720,
30-fps H.264 MP4. Supply the exact story/revision, a new `.mp4` output path and
`slide_seconds` (one positive duration per slide aligned to 30 fps). Requires
Pango, ffmpeg with libx264, and ffprobe on PATH; `brew install ffmpeg` on macOS.
Without a narration ID there is no audio track. Notes are retained as provenance; timing
is explicit rather than estimated. Scripts, CSS animation, animated images and
embedded clips are rejected. Use HTML/ZIP for interactive or playable media.

The result identifies output/source hashes, assets, timing and separate decode,
duration and no-audio checks. Successful exports retain this record in a
`video_exported` change event. Visual review and acceptance do not transfer from
the deck. `timeout_seconds` bounds work (default 300, 1–900); interruption stops
subprocesses and cleans temporary files. Existing outputs are never overwritten.
Encoding is synchronous and does not perform speech synthesis.


## Narrated delivery

Use `narration-settings` and `configure-narration` for store-scoped speech settings,
separate from writing settings. Providers: `openai` (`OPENAI_API_KEY`, defaults
`gpt-4o-mini-tts` / `marin`) and `gemini` (`GOOGLE_API_KEY` then `GEMINI_API_KEY`,
defaults `gemini-3.1-flash-tts-preview` / `Kore`). Updated defaults do not replace
saved narration settings or explicit model choices. Key presence is not verified speech
access; Anthropic, ChatGPT and Copilot authentication do not authorize these APIs.
Speech goes directly to the provider, without an Amplifier Agent session.

`generate-narration` requires exact story/revision, a request ID and a speech grant
(`max_requests`, `max_characters`, `timeout_seconds`; defaults 12 / 24000 / 300,
maxima 100 / 200000 / 900). New speech also requires `--model-env`. Omitted `notes`
reads each slide's `.notes` or `[data-speaker-notes]`; supplied `notes` is one string
per slide and is retained as an explicit adaptation. Each must be nonempty and at
most 4000 characters. Do not invent missing notes or silently rewrite them.

Poll the returned operation with `get-operation`; cancel with `cancel-operation`.
`get-speaker-notes`, `list-narrations`, `get-narration` and `get-narration-audio`
provide deterministic inspection. Completed slide audio survives partial failure.
Exact request retries do not spend again. Reuse is keyed by text and frozen speech
settings; only changed clips require synthesis. Uncertain attempts require a new
request ID and explicit `retry_uncertain: true`; do not retry blindly. Cancellation
cannot reverse a provider charge already in flight. Audio is disclosed as AI-generated.

Pass the completed `narration_id` to `export-video`. Default `delivery: "embedded"`
produces MP4 with AAC audio; `delivery: "separate"` requires a new `.zip` path and
packages silent MP4, a full aligned WAV, original slide WAVs, notes/settings/timing
manifest and README. Both use the same retained audio and render plan, without
new synthesis or credentials. Actual speech duration plus `pause_seconds` (default
0.5, allowed 0–60) determines whole-frame timing. Optional `slide_seconds` must fit
speech and pause; conflicts fail without truncating or accelerating speech.
The original revision, audio and timing remain retained. Static video limitations
still apply. Audio decoding is not a listening or pronunciation-quality check.

The dashboard's **Narration & video** dialog provides the same settings, explicit
notes adaptation, generation/cancellation, audio listening and two export modes.
Its generation grant is 12 requests / 48000 characters / 300 seconds. The viewer
needs provider-use authority for uncached speech. Exports require no new API calls.


## Storyboard-panel speech

Use the same `generate-narration` operation with `source: "storyboard_panels"`.
It reads each panel's exact `narration` text from the identified revision, not
rendered sections, action, production notes or an adapted presentation. Every
panel must have nonempty narration: missing text is reported by panel ID before
spending. Do not supply `notes` or `script_id`; revise the storyboard to change
what is spoken. Default `source: "presentation"` preserves existing slide behavior.

The retained record identifies source revision/hash, direction and ordered
`panel_ids`. Each clip has `panel_id`, one-based `position`, audio identity/hash,
sample count and measured duration. Retrieve WAV bytes with `get-narration-audio`
using `panel_id` instead of `slide`. Progress uses `completed_panels`/`total_panels`;
`panel_errors` identify incomplete panels. Identical text/settings share cached
audio, but every panel retains its own clip mapping, including after reordering.
Saved speech settings, bounded grants, exact retries, uncertainty and cancellation
use the same speech pipeline. For more than 12 distinct uncached texts, explicitly
raise `grant.max_requests`; larger text totals may also require raising
`max_characters` above the unchanged 24000 default. Grants bound uncached requests,
input characters and time, not storyboard length: a request that exceeds its
allowance fails before spending, never silently omits panels. A single speech
operation supports grants of at most 100 uncached requests, 200000 characters and
900 seconds; cached or duplicate text does not consume additional requests.
Those are speech execution limits, not a panel-count ceiling or automatic authority.

```sh
stories --store /path/to/store --model-env --execution background generate-narration --input '{"story_id":"STORY_ID","revision_id":"REVISION_ID","source":"storyboard_panels","grant":{"max_requests":70,"max_characters":84000,"timeout_seconds":300},"request_id":"panel-speech-1"}'
stories --store /path/to/store get-narration-audio --input '{"story_id":"STORY_ID","narration_id":"NARRATION_ID","panel_id":"arrival"}'
```

This is library/CLI/MCP speech, not a storyboard-to-deck conversion. Storyboard
HTML/ZIP exports still deliver the structured plan and visuals, not synthesized
audio. Retrieve clips separately for production. Presentation-only script writing,
dashboard speech controls can synthesize and play exact retained panel text.
Presentation script adaptation and video export do not become storyboard capabilities.

## Preparing narration independently of speech

Use `prepare-narration` when a narrated video needs a spoken story, or when the caller
wants a script alone. This is optional; normal presentation generation need not
produce a voiceover. Uses the writing provider through Amplifier Agent, independently
of configured speech provider/key. Inputs are exact story/revision, ordinary writing
`grant`, request ID, optional `guidance`, approximate `target_seconds` and
`base_script_id` for refinement. Optional `draft_notes` supplies current editable
passages, including gaps, without discarding unsaved text. Native writing-provider access and model authority
are required. The whole selected deck, notes and retained sources are disclosed to
that provider. Background mode runs immediately; queued mode needs `run-operation`.

Defaults establish audience relevance, add explanation beyond bullet recitation,
connect the slides and end with a useful takeaway. Spoken language, supported
examples and content-led pacing serve the purpose; a dramatic or sales structure
is not mandatory. Presenter cues are adapted, not read aloud. No invented motives,
experiences, benefits or image observations. User guidance steers tone, emphasis
and length. A duration estimate at 140 words/minute is not measured audio timing.

Poll the returned operation, then read result.script_id with `get-narration-script`.
`list-narration-scripts` lists retained versions. Each has ordered passages,
references, limitations, source revision, guidance and review. Composition and
source-fidelity/spoken-story model review permit at most one repair and re-review
(up to four calls within the writing grant). Failed candidates remain inspectable;
model review is not human approval, a listening test or independent truth.

`save-narration-script` retains explicit text edits without a model; edits create a
new identity and invalidate prior review. Preparing/refining leaves slides, speaker
notes, earlier scripts and audio intact. Pass `script_id` to `generate-narration` to
speak its exact text; do not also pass `notes`. Synthesis and video retain the script
identity/hash. Existing verbatim notes input remains available for finished scripts.
No new approval ceremony is required between steps when the caller has authorized
the full narrated export. The dashboard exposes preparation, guidance, versions,
manual editing and synthesis separately, using these same public capabilities.


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

## Optional MCP / MCP Apps

Story-scoped results identify one retained dashboard across review methods;
independent stories remain separate. The optional metadata grants no authority.

Install `amplifier-smart-tool-stories[mcp]` from this Git repository and run
`stories-mcp --storage /explicit/store`. Add `--model-env` only with authority to
use configured providers; generation still requires a bounded grant. Tool schemas
and the optional `ui://stories/review` App use the same public library and state.
Read shared drafts before continuing. Comments default to agent notes; `author=user`
is caller-reported human submission, not authenticated identity. The portable
adapter uses the native HTML/CSS and review, comparison, settings and narration
controllers through an MCP transport. Acceptance remains caller-reported, not
authenticated human identity. Explicit `start-provider-job` accepts kind
prepare/test/models/login, provider/model and request_id; `get-provider-job`
observes its durable receipt and bounded progress without replay. Jobs require
model_env, exclude concurrent setup/work and have a 310-second execution deadline.
An expired claimed job is timing_out until cleanup settles or its kernel ownership
lease proves owner loss; PID reuse does not establish ownership. Unsettled cleanup
keeps exclusion in place. Runtime
preparation may install modules; login writes provider-owned credential caches;
test sends a small model request. Writing settings remain instance-scoped, speech
settings store-scoped. `cancel-provider-job` stops the exact job, not prior effects.
`get-video-export` returns path-free bytes from retained presentation narration
(embedded MP4 or separate ZIP); no speech is implicitly generated.
Media/audio/export getters return scoped, bounded MCP resource chunks; export
transfer snapshots expire when the MCP server stops. The native library/CLI remains
available for durable file exports. No MCP sampling, Tasks or caller wake-up is
implied. See the repository's `docs/MCP.md` for supported scope and host requirements.

Portable navigation is shared library state. Read `get-review-view`, then
`update-review-view` with its exact `expected_version`, a stable request ID and
revision/one-based slide/comparison/anchor/panel/sections/export-format changes.
Conflicts require rereading and reconciling; viewing never selects a direction,
accepts content or grants work. The App follows these changes and restores them
on reopen. A conflicting view update stops further view writes and submissions
until the workspace is reopened for reconciliation; current typing remains in
the open view. Acknowledged document passage/mode/zoom, comments, pending exact
intents and narration edits are public retained context, not browser storage.
Audio playback/volume and download handling remain local presentation controls.
Shared comment drafts use content CAS via `save-draft.expected_version`, read from
the draft's `version` in `get-story` (zero if absent). Stale editors conflict before
changing content regardless of timestamp skew. Exact retries return the accepted
version. Sequence-only legacy writes work only on drafts not yet CAS-protected.
Narration asynchronous replies are scoped to the original story, revision and
dialog opening; acknowledged operation identities remain on their original target.
Metadata refresh does not replace unchanged playing audio nodes.

`respond` preserves the original annotation target and accepts explicit `author`.
Library/CLI retain their user-submission default for compatibility; the portable
MCP adapter defaults both `add_comment` and `respond` to agent notes, which never
consume feedback authority. User attribution is a caller assertion, not proof of
human identity.

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
