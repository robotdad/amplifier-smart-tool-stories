"""Packaged, provider-free operating skills for the CLI."""

import inspect
import json
import shlex
from importlib.resources import files

from .lib import Stories

MCP_GUIDANCE = """Use one explicit retained store. Read shared drafts and revisions before mutations.
Tool schemas expose bounded grants; --model-env authorizes environment access but
is not a spending grant. Comments default to agent notes; author=user is only a
caller-reported human submission. Without model access, user comments are retained
awaiting access without consuming a grant or starting work. Native human acceptance is omitted. Media and
exports use scoped resources/read chunks; export transfer snapshots last until
this server stops. Story results identify one retained dashboard across review methods;
independent stories stay separate. Closing a view does not cancel work. No MCP sampling, Tasks,
elicitation, provider login, runtime preparation or video export is exposed."""

# Examples are valid JSON inputs; retained identities must come from earlier receipts.
VALUES = {
    "expected_version": 0,
    "idea": "Explain a fictional team's handoff as a short visual sequence.",
    "brief": {"intent": "Explain the handoff", "assumptions": [], "open_questions": []},
    "storyboard": {
        "name": "Follow the request",
        "approach": "A concrete journey",
        "tradeoff": "Less system detail",
        "panels": [
            {
                "id": "arrival",
                "title": "A request arrives",
                "action": "A fictional team receives a request.",
                "visual": "Sketch of a request card",
                "asset_id": "",
                "narration": "",
                "notes": "",
                "evidence_ids": [],
            }
        ],
    },
    "script_id": "SCRIPT_ID",
    "notes": ["Here is why this change matters to the team."],
    "narration_id": "NARRATION_ID",
    "slide": 1,
    "slide_seconds": [10],
    "asset_id": "ASSET_ID",
    "asset_ids": ["ASSET_ID"],
    "name": "Demo poster",
    "mime_type": "image/png",
    "max_width": 1280,
    "max_height": 720,
    "title": "Release brief",
    "html": '<html><body><section class="slide"><h1>Release brief</h1></section></body></html>',
    "request_id": "brief-1",
    "purpose": "Explain the supplied release",
    "audience": "Team leads",
    "sources": [{"id": "s1", "name": "Release note", "content": "Version 2 adds offline reading."}],
    "document": {
        "title": "Release brief",
        "subtitle": "",
        "blocks": [
            {
                "id": "intro",
                "kind": "paragraph",
                "text": "Version 2 adds offline reading.",
                "items": [],
                "rows": [],
                "evidence_ids": [],
            }
        ],
    },
    "story_id": "STORY_ID",
    "revision_id": "REVISION_ID",
    "annotation_id": "ANNOTATION_ID",
    "operation_id": "OPERATION_ID",
    "service_id": "SERVICE_ID",
    "draft_id": "editor-1",
    "sequence": 1,
    "text": "Please clarify this point.",
    "provider": "anthropic",
    "grant": {"max_operations": 1, "timeout_seconds": 180, "max_output_tokens": 12000},
    "output_path": "/tmp/stories-brief.html",
}

GUIDANCE = {
    "get_review_view": (
        "Read shared review navigation.",
        "Versioned focus, slide, comparison and panel state.",
        "Provider-free; viewing is separate from choosing and acceptance.",
    ),
    "update_review_view": (
        "Change shared review navigation for people and agents.",
        "New versioned review state.",
        "Read the version first; conflicts require reconciliation. Identical request retries are safe. One-based slides, empty comparison_revision clears comparison. Omitted fields stay unchanged. No work starts.",
    ),
    "create_storyboard": (
        "Import a structured outline or illustrated storyboard for shared review.",
        "status, story_id, revision_id and direction_id. No direction is chosen automatically.",
        "Read the storyboard schema in stories skill. Supply at least one panel with stable IDs, optional still-image asset IDs and empty strings for unused text. There is no fixed panel-count cap: content dictates the count. Byte/time/model limits are separate resource budgets, not permission to truncate or merge scenes. Markup parsing is bounded to 32 MiB. Static review has 35 CPU seconds, at most 40 wall seconds (or remaining allowance), a 300 MB JSON input budget and 64 MiB combined PDF/JPEG output budget; use structured HTML/ZIP review if rendering exceeds resources. Optional production_requirements lists up to four asset/work requirements (500 characters each), exported with the storyboard; omit for outlines. Import is deterministic and does not fact-check. Fidelity is outline, mixed or illustrated; illustrated requires a retained image on every panel.",
    ),
    "generate_storyboard": (
        "Develop a rough idea with shared storyboarding expertise; sources may be empty for clearly creative work.",
        "Queued story_id/operation_id. Read get-operation for needs_input, succeeded, partial or failed; results list revision_ids and failures.",
        "Markup exceeding 32 MiB fails with markup_resource_limit, not invalid_input or a repairable quality finding. The failed candidate remains in result.failures with its full structured sequence; no model repair is spent to reduce it. Preserve that source and choose a workflow with sufficient byte capacity. "
        "Ordinary creation produces one direction. Set explore=true only when the person requests alternatives; then two substantive approaches share one deadline and at most 12 model calls, with one repair per candidate. Uses the configured Amplifier Agent provider and rendered review. Anthropic/OpenAI API request strict submissions; storyboard schemas are also checked locally with bounded correction. Printed sheets have a separate direction overview. Read-only comparison never generates. Only supplied still images are available; planned visuals are not image generation. Use answer-question for initial clarification, comments for refinement. Live output quality remains model-reviewed, not independent proof.",
    ),
    "revise_storyboard": (
        "Retain an explicit structured edit, attach supplied images, or import an explicitly requested alternative.",
        "status, story_id, revision_id and direction_id.",
        "No model use. Preserve existing panel IDs for unchanged panels. asset_ids replaces the attached asset list if supplied. Optional production_requirements supplies a portable asset brief without tracking or execution. new_direction=true branches from the exact base; otherwise a stale direction head conflicts. Earlier revisions and acceptance remain intact; new revisions have no inherited semantic/visual pass.",
    ),
    "select_direction": (
        "Record the person's expressed choice of storyboard direction at the reviewed revision.",
        "status, direction_id and revision_id; observable in shared state and changes.",
        "No model use, publication or human acceptance. Do not invoke merely to inspect/focus. Superseded-brief revisions cannot be chosen. Other directions remain retained.",
    ),
    "update_storyboard_brief": (
        "Correct common storyboard intent without silently changing alternatives.",
        "status, brief_id and count of superseded directions.",
        "Brief contains intent, assumptions and open_questions. Retains earlier briefs and marks existing directions superseded, without model use. Comment on a direction under explicit feedback authority to revise it against the updated brief; other directions stay superseded. In-flight work under the old brief cannot commit.",
    ),
    "get_comparison": (
        "Inspect one or two retained versions side by side without choosing or generating.",
        "items with exact revision/direction identities, rationale, superseded state and isolated preview payloads.",
        "Works for storyboard, document and presentation revisions in the same story. Omit revision_ids for the latest two direction heads, or latest two ordinary revisions. No assumption of matching page counts; revisions of one direction are not mislabeled as different generated approaches. Alternative generation for documents/presentations remains unavailable.",
    ),
    "prepare_narration": (
        "Prepare or refine a coherent spoken presentation, without requiring a speech provider.",
        "Operation ID; poll get-operation, then read result.script_id with get-narration-script. Retained script versions leave deck and speaker notes unchanged.",
        "Uses the configured writing provider through Amplifier Agent with model_env. Sends the selected deck, notes, retained sources, optional base script and guidance. Defaults favor audience relevance, explanation beyond bullets, supported examples, meaningful transitions and a useful ending. Optional target_seconds is approximate writing guidance, not audio timing. At most four model calls (composition, review, one repair and re-review) within the ordinary writing grant and deadline. Model review is not human approval. Never invokes speech or requires a speech key. Use background execution or queued plus run-operation; exact retries do not restart. Guided refinement names base_script_id; no silent edits to earlier scripts. Failed candidates/reviews remain on the operation.",
    ),
    "get_narration_script": (
        "Read a retained spoken script.",
        "Script identity, exact revision, ordered passages, references, limitations, timing estimate and review.",
        "Provider-free. Script references to slides/notes preserve their claims, not independent factual verification. Estimated duration is not measured audio.",
    ),
    "list_narration_scripts": (
        "Find scripts for a story and optionally one revision.",
        "Retained script versions in creation order.",
        "Read-only; no writing or synthesis occurs.",
    ),
    "save_narration_script": (
        "Save explicit spoken text or edits as a new script version.",
        "script_id for inspection or generate-narration.",
        "No model use. One nonempty string per slide, up to 4000 characters. Optional base_script_id must match the revision. Edits do not inherit model review or alter earlier scripts/audio/deck notes. Use prepare-narration for guided writing; use this for caller-authored text.",
    ),
    "narration_settings": (
        "Inspect available speech configuration.",
        "Effective store-scoped settings and credential presence.",
        "No network call. Key presence does not prove speech access. Anthropic, ChatGPT sign-in and Copilot are unsupported for speech.",
    ),
    "configure_narration": (
        "Choose speech settings independently of writing settings.",
        "Effective store-scoped narration settings.",
        "OpenAI or Gemini only. Existing native API keys are reused. Model and voice have provider defaults; Gemini uses gemini-3.1-flash-tts-preview / Kore. Explicit model choices override defaults; updated defaults do not replace saved settings. This call does not synthesize, test access or spend.",
    ),
    "get_speaker_notes": (
        "Read the notes attached to a slide revision.",
        "Revision ID and ordered note texts.",
        "Empty notes stay empty; no automatic adaptation or rewriting.",
    ),
    "list_narrations": (
        "Find retained narration or work in progress.",
        "Narration records for the story and optional revision.",
        "Read-only; never starts or resumes synthesis.",
    ),
    "generate_narration": (
        "Synthesize and retain per-slide or storyboard-panel narration.",
        "Operation and narration IDs. Inspect get-operation and get-narration; get-narration-audio returns completed WAVs.",
        "For a storyboard use source=storyboard_panels: one clip per panel in retained order, bound to stable panel IDs, direction and source revision/hash. Speaks each panel's exact narration, never action/notes/HTML sections. Every panel must have nonempty narration; omissions fail before spending. No notes/script_id overrides: revise the storyboard first. No fixed panel-count cap; speech grants are separate limits on uncached requests/characters and elapsed time, not permission to omit or merge panels. Raise the explicit grant for more than 12 distinct uncached texts; no automatic spending or allowance expansion. Panel progress/errors use completed_panels/total_panels and panel_errors; get audio by panel_id. No storyboard-to-deck conversion or automatic audio in storyboard ZIP/video export. Default source=presentation preserves the following presentation workflow. "
        "Use prepare-narration first when a spoken story needs writing, then supply script_id. Alternatively supply notes or omit both to speak existing notes verbatim. script_id and notes are mutually exclusive. Requires configured narration and model_env for new synthesis. Sends exact notes and delivery instructions to the chosen OpenAI/Gemini paid API directly, without an agent runtime. Voices are AI-generated. Defaults: 12 requests, 24000 text characters, 300 seconds; grant accepts max_requests (1–100), max_characters (1–200000), timeout_seconds (1–900). Notes must be nonempty, at most 4000 characters per slide. Identical text/settings reuse retained WAV without a provider request; settings are frozen at submission. Up to three distinct slide requests run in parallel by default (concurrency 1–8), sharing the same total request/character/deadline allowance. Duplicate text/settings share one request; partial results keep their actual slide numbers. SDK retries are disabled. Exact request retries never spend again. Partial completed audio survives failure/cancellation. Uncertain calls require a new request with retry_uncertain=true; simultaneous identical calls fail busy. Use background execution for UI or queued plus run-operation. cancel-operation prevents late commits; in-flight provider spending can occur.",
    ),
    "get_narration": (
        "Inspect narration notes, settings, progress and audio identities.",
        "Retained narration record.",
        "Read-only and provider-free; state does not imply spoken fidelity or human approval.",
    ),
    "get_narration_audio": (
        "Listen to a completed slide or storyboard panel, or reuse its audio.",
        "WAV metadata and data_base64.",
        "Supply a one-based slide number for presentation narration, or panel_id (and no slide) for storyboard narration. Panel results include the clip's position, stable ID, exact source revision/hash and direction. Completed audio remains readable after partial failure. AI-generated speech is not automatically verified for fidelity.",
    ),
    "export_video": (
        "Deliver static slides as silent or narrated video, or a post-production package.",
        "MP4 path, output/revision hashes, retained timeline, asset identities and separate decode/timing checks.",
        "Supply an .mp4 output_path and slide_seconds with one positive duration per slide, aligned to 30 fps. Requires ffmpeg (libx264), ffprobe and Pango. Encodes 1280x720 H.264 with cuts; audio is absent unless narration_id is supplied. Static HTML and retained static images only; scripts, external dependencies, animations and embedded clips are unsupported. No TTS occurs during this export. Supply narration_id to use completed audio for the same revision; embedded MP4 is the default. delivery=separate returns a ZIP with silent video, full WAV, per-slide WAVs and timing manifest. Both modes share the retained render/timing plan. With narration, omit slide_seconds to derive pacing from measured audio plus pause_seconds (default 0.5); conflicting fixed durations fail. Without narration, explicit slide_seconds is required. timeout_seconds bounds rendering, encoding and verification (default 300, maximum 900). Interrupting terminates active encoder work and removes temporary files; no partial MP4 is published. Never overwrites. Successful plans are retained in read-changes events. Inspect video before delivery; decode checks are not visual approval.",
    ),
    "import_media": (
        "Retain a supplied image, video or caption track without changing it.",
        "status, asset metadata/identity and actionable size warnings.",
        "Supply exactly one path or data_base64, plus name and MIME type. PNG/JPEG/WebP/GIF, MP4/WebM and UTF-8 WebVTT are supported. Video inspection requires ffprobe. Limits: 256 MiB per asset, 40 million decoded image pixels. No network or model use. Bind returned IDs through create-story/generate asset_ids and asset:ASSET_ID references. Large images are retained unchanged; ask the person before resize-media, or choose ZIP to keep separate assets.",
    ),
    "resize_media": (
        "Make an explicitly requested resized copy of a retained still image.",
        "New PNG asset with derived_from, transformation and size warnings; original remains available.",
        "Call only for an explicitly selected resize. Fits max_width/max_height without upscaling, preserving aspect ratio and normalizing image orientation. Animated images are rejected. Does not alter any story revision; use revise-media to bind the new asset.",
    ),
    "get_media": (
        "Retrieve media from an exact story revision.",
        "asset metadata and data_base64.",
        "Asset must belong to the selected revision. This is a read, not playback verification or authority to inspect another story.",
    ),
    "revise_media": (
        "Create a new revision with explicitly selected media and optional HTML.",
        "story_id, revision_id and size warnings.",
        "Presentation only. asset_ids is the complete desired asset list; optional html replaces the base markup. References must use asset:ASSET_ID. Bind resized copies here after an explicit resize choice. Earlier revisions remain intact; review and human acceptance are not inherited. No model use.",
    ),
    "answer_question": (
        "Continue initial generation after a question.",
        "Queued receipt with story_id, operation_id and question_operation_id.",
        "Use a needs_input generation operation ID, answer text and a new finite grant. The original provider and story are retained. The parent becomes continued with answered_by pointing to the new operation. Each question accepts one answer; identical request_id retries reuse the receipt. Use --model-env for execution; queued work needs run-operation.",
    ),
    "accept_revision": (
        "Record a person's explicitly conveyed acceptance.",
        "status and acceptance with exact revision ID, artifact hash and timestamp.",
        "Only call when the person has accepted this revision. Does not change selection, model checks, later revisions or publication authority. No model use.",
    ),
    "manifest": (
        "Discover the callable surface before composing an integration.",
        "Manifest metadata, body and capability signatures.",
        "No store or provider is opened.",
    ),
    "create_story": (
        "Import existing HTML for review.",
        "status, story_id and revision_id.",
        "HTML is literal content, not a path. Import does not fact-check. Attach retained asset_ids for images/video. Unregistered resources and scripts are suppressed in preview.",
    ),
    "create_document": (
        "Import existing structured writing for review.",
        "status, story_id and revision_id.",
        "Use title, subtitle and blocks with id/kind/text/items/rows/evidence_ids. Import accepts uncited structure; it does not certify facts.",
    ),
    "generate": (
        "Create source-backed material for a specified audience.",
        "Queued receipt with story_id and operation_id; inspect get-operation for the accepted revision or failure.",
        "kind is presentation or document. Sources require id/content with literal text; optional name, kind (source/summary/hypothesis/preference) and attribution preserve source status. grant bounds operations, timeout_seconds and max_output_tokens; optional expires_at is a Unix timestamp within 24 hours. Prepare the provider runtime first. Default queued execution needs run-operation; background and in_process execute on submission. Source context is sent to the selected provider; rendering needs Pango. No network research or fallback provider.",
    ),
    "list_stories": (
        "Find retained work to resume.",
        "Array of IDs, titles, selected_revision and latest_revision.",
        "Use returned IDs in subsequent calls.",
    ),
    "get_story": (
        "Resume review and inspect feedback outcomes.",
        "Shared story state, revision summaries, annotations, saved drafts, authority and revision-specific human acceptances.",
        "Read-only; does not start pending work. Use get-revision for artifact contents.",
    ),
    "get_revision": (
        "Inspect the exact artifact and its checks.",
        "Immutable revision including HTML, document where applicable, evidence, checks, changes and verified calculations.",
        "Name the revision explicitly; a newer revision does not replace this one.",
    ),
    "get_preview": (
        "Discover valid targets before adding an anchored comment.",
        "revision_id, isolated html, elements, kind, attached assets, media_warnings and limitations.",
        "Use returned element IDs. Text anchors use Unicode start/end offsets and the exact quote; IDs belong to this revision.",
    ),
    "select_revision": (
        "Choose which existing version shared review selects.",
        "status and revision_id.",
        "Selection does not imply approval, regenerate content or move annotations.",
    ),
    "grant_feedback": (
        "Authorize bounded future responses to person comments.",
        "status and retained grant.",
        "grant supports max_operations (1–100), timeout_seconds (1–900), max_output_tokens (128–24000), expires_at within 24 hours. Defaults: 1 operation, 180 seconds, 12000 tokens, one hour. No model spending now; prepare runtime and use --model-env when executing responses.",
    ),
    "add_comment": (
        "Leave a caller highlight or submit person feedback.",
        "status, annotation_id and optional operation_id.",
        "author=agent highlights never start model work. Default author=user uses existing feedback authority, or returns awaiting_authority. Without model access, immediate execution retains the user comment as awaiting_model_access without consuming its grant or starting work; queued execution may still retain authorized work for a later model-enabled worker. anchor defaults to {kind: story}; element anchors add element, text anchors add element/start/end/quote. Discover targets with get-preview. Comments stay outside exports.",
    ),
    "respond": (
        "Follow up on a clarification or existing annotation.",
        "status, new annotation_id and optional operation_id.",
        "Uses the original target and thread context. Default author=user conveys person feedback; explicit author=agent never spends. The MCP adapter defaults to agent. Existing feedback authority is required for user-comment model work; without model access, immediate execution retains it as awaiting_model_access without spending. It does not restart the old operation.",
    ),
    "save_draft": (
        "Retain unfinished feedback without submitting it.",
        "saved status and sequence, or stale status and existing draft.",
        "Choose draft_id per editor/session; increase sequence monotonically. No model use. Anchor syntax is described by add-comment --help.",
    ),
    "read_changes": (
        "Observe updates since the last read.",
        "changes, cursor and history_gap.",
        "Pass the previous cursor as after. Up to 500 events per read; no worker start or caller notification is promised.",
    ),
    "get_operation": (
        "Poll submitted work without executing it.",
        "Operation state, result and error when present; results include changes and calculations. An answered generation question becomes continued with answered_by identifying its continuation.",
        "Queued is not completion. Inspect failure and needs_input outcomes. Interrupted or uncertain work is never retried automatically.",
    ),
    "run_operation": (
        "Execute one previously queued operation.",
        "Operation state with result or error.",
        "Requires prepared runtime and --model-env. Uses the retained provider/model and grant. Claims once; never use polling to retry uncertain spending.",
    ),
    "cancel_operation": (
        "Stop pending work or prevent an active operation committing late results.",
        "Updated operation record.",
        "Cancellation is cooperative; an in-flight provider request may already have consumed tokens.",
    ),
    "export": (
        "Write the named artifact to an explicit destination.",
        "status, path, format metadata, hashes, checks and limitations.",
        "format is html, zip, pdf or docx. Script-free presentations include standalone buttons and keyboard slide navigation with viewport scaling. HTML embeds retained images unchanged; video/captions require ZIP with relative media paths. ZIP requires static HTML without scripts or external stylesheet/CSS resource dependencies. PDF/Word require structured documents; no PPTX or arbitrary HTML conversion. Parent directory must exist; never overwrites. Annotations are excluded. Word pagination may differ.",
    ),
    "get_export": (
        "Obtain artifact bytes without writing a file.",
        "data_base64, MIME type, revision/source/output hashes, checks and limits.",
        "format is html, zip, pdf or docx. Script-free presentations include standalone buttons and keyboard slide navigation with viewport scaling. HTML embeds retained images unchanged; video/captions require ZIP with relative media paths. ZIP requires static HTML without scripts or external stylesheet/CSS resource dependencies. PDF/Word require structured documents. Decode data_base64; annotations are excluded. Inspect format-specific limitations.",
    ),
    "storytelling_capabilities": (
        "Learn supported writing approaches and source mapping.",
        "approaches, outputs, selection and limits.",
        "Generation chooses expertise internally; describe purpose and audience. No model use.",
    ),
    "provider_settings": (
        "Check redacted setup readiness.",
        "Effective provider/model, readiness and setup instructions.",
        "Readiness is not proof of model access. Keys remain in native environments/caches.",
    ),
    "configure_provider": (
        "Set future provider/model in a persistent library or dashboard instance.",
        "Redacted provider configuration.",
        "CLI processes are short-lived: this does not persist settings for the next invocation. Use global --provider and --model on each CLI call. Existing queued operations stay fixed.",
    ),
    "prepare_runtime": (
        "Explicitly install the selected provider runtime before model use.",
        "Runtime preparation receipt.",
        "May use network and install packages into native caches. Does not generate a story or sign in.",
    ),
    "test_provider": (
        "Verify access with one small live model request.",
        "Connection test receipt.",
        "Requires --model-env and prepared runtime; spends provider tokens. timeout_seconds defaults to 60.",
    ),
    "provider_models": (
        "Discover model IDs for the selected provider.",
        "Provider model catalog.",
        "Requires --model-env and prepared runtime. Discovery may use network but does not generate; catalog presence is not proof of image/tool compatibility or account access.",
    ),
    "provider_login": (
        "Start explicit native ChatGPT/Copilot authentication.",
        "Login result or API-key setup instructions.",
        "Requires --model-env. May fetch runtime modules. Person completes device authorization; progress goes to stderr. Credentials stay in native caches. on_progress is library-only, not a JSON argument.",
    ),
    "start_dashboard": (
        "Present retained work for shared review.",
        "Owned service receipt with private loopback URL.",
        "Does not open a browser. Treat the URL as a bearer credential. Model responses require explicit feedback authority and model access. Save service_id for stop-dashboard.",
    ),
    "stop_dashboard": (
        "Release an owned review service.",
        "Service stop receipt.",
        "Cancels owned comment work and setup while retaining stories, revisions and drafts.",
    ),
}


FIELD_HELP = {
    "source": "Speech source: presentation (default, notes/script) or storyboard_panels (exact retained panel narration; no notes/script_id)",
    "panel_id": "Stable panel ID from storyboard narration; mutually exclusive with slide",
    "view_id": "Shared review identity; default shared",
    "expected_version": "Exact version from get-review-view; stale changes conflict",
    "comparison_revision": "Exact comparison revision, or empty string to clear",
    "panel_open": "Whether the shared review panel is visible",
    "export_format": "Retained export format choice: html, zip, pdf or docx",
    "sections": "Expanded review sections: sources, grant, export, work",
    "idea": "Rough creative intent and explicitly supplied conversation context",
    "storyboard": "name, approach, tradeoff and panels; each panel has id, title, action, visual, asset_id, narration, notes, evidence_ids",
    "brief": "Shared intent text plus assumptions and open_questions text lists",
    "explore": "Enable only for user-requested alternatives; default false develops one direction",
    "fidelity": "outline, mixed or illustrated; illustrated requires retained images for every panel",
    "new_direction": "Explicitly branch an imported structured edit as a separate direction",
    "revision_ids": "One or two exact revision IDs in this story; omitted uses latest direction heads or versions",
    "concurrency": "Maximum simultaneous distinct speech requests (1–8, default 3); one shared grant",
    "draft_notes": "Optional editable starting passages, one per slide; empty entries allowed; up to 4000 characters each",
    "script_id": "Exact retained spoken-script ID for this revision; mutually exclusive with notes",
    "base_script_id": "Earlier script for guided refinement or manual edit lineage, on the same revision",
    "guidance": "Optional tone, audience emphasis or refinement request (up to 8000 characters)",
    "target_seconds": "Approximate total spoken duration, 10–7200 seconds; omitted uses content-led pacing",
    "narration_id": "Retained narration identity matching the exact revision",
    "notes": "Optional explicit list of narration texts, one per slide; omitted reads retained speaker notes",
    "instructions": "Speech delivery instructions, separate from the text to speak",
    "voice": "Provider speech voice identifier",
    "slide": "One-based slide number",
    "retry_uncertain": "Explicitly authorize another attempt after an uncertain potentially billed request",
    "delivery": "embedded (default MP4) or separate (post-production ZIP)",
    "pause_seconds": "Silence after each slide narration, default 0.5 seconds",
    "slide_seconds": "One positive duration per slide, in seconds aligned to 30 fps",
    "asset_id": "Retained asset identity returned by import-media or resize-media",
    "asset_ids": "Complete list of retained assets available to this presentation; reference them as asset:ASSET_ID",
    "name": "Human-readable media name",
    "mime_type": "Actual supported image/video MIME type, or text/vtt",
    "path": "Explicit local media file to read; mutually exclusive with data_base64",
    "data_base64": "Base64-encoded media bytes; mutually exclusive with path",
    "attribution": "Supplied source/credit text retained with the asset",
    "max_width": "Maximum derivative width in pixels (1–10000)",
    "max_height": "Maximum derivative height in pixels (1–10000)",
    "title": "Short display title",
    "purpose": "Desired communication outcome",
    "audience": "Intended readers",
    "html": "Literal HTML content",
    "sources": "List of source objects: required id/content; optional name, kind (source/summary/hypothesis/preference), attribution",
    "document": "Structured title, subtitle and blocks object; block text supports optional marks [{start,end,bold,href}]",
    "request_id": "Caller-chosen unique mutation identity",
    "story_id": "Retained story ID",
    "revision_id": "Exact retained revision ID",
    "operation_id": "Operation ID returned by submission",
    "annotation_id": "Existing annotation ID",
    "service_id": "Owned dashboard service ID",
    "grant": "Finite execution authority object",
    "anchor": "Revision-local story, element or text target",
    "author": "user for feedback; agent for a non-spending highlight",
    "text": "Comment or draft text",
    "draft_id": "Unique editor/session draft identity",
    "sequence": "Nonnegative increasing draft version",
    "after": "Previous event cursor, or zero",
    "kind": "presentation or document",
    "format": "html or zip for presentations/storyboards; storyboard ZIP includes structured content; html, pdf or docx for documents",
    "output_path": "New destination file in an existing directory",
    "provider": "Provider alias; null uses current selection where accepted",
    "model": "Provider model ID; null uses its default",
    "timeout_seconds": "Maximum time allowed for the operation",
}


def example(name):
    parameters = inspect.signature(getattr(Stories, name)).parameters
    data = {
        key: VALUES[key]
        for key, parameter in parameters.items()
        if key != "self" and parameter.default is inspect.Parameter.empty
    }
    if name == "generate_narration":
        data["grant"] = {"max_requests": 12, "max_characters": 24000, "timeout_seconds": 300}
    if name == "configure_narration":
        data["provider"] = "openai"
    if name == "get_narration_audio":
        data["slide"] = 1
    if name == "export_video":
        data["slide_seconds"] = [10]
        data["output_path"] = "/tmp/stories-brief.mp4"
    if name == "import_media":
        data["path"] = "/tmp/poster.png"
    if name == "add_comment":
        data["author"] = "agent"
    return data


def skill_help(name=None):
    root = files("amplifier_smart_tool_stories")
    if name is None or name == "skill":
        body = root.joinpath("SMART_TOOL.md").read_text().split("---", 2)[2].strip()
        label = "stories"
    else:
        label = "stories-" + name.replace("_", "-")
        purpose, result, limits = GUIDANCE[name]
        params = inspect.signature(getattr(Stories, name)).parameters
        fields = []
        for key, param in params.items():
            if key in {"self", "on_progress"}:
                continue
            required = (
                "required"
                if param.default is inspect.Parameter.empty
                else "optional; default " + json.dumps(param.default)
            )
            fields.append(f"- `{key}` — {FIELD_HELP[key]}; {required}.")
        flags = (
            " --model-env"
            if name
            in {
                "generate",
                "generate_storyboard",
                "answer_question",
                "run_operation",
                "test_provider",
                "provider_models",
                "provider_login",
            }
            else ""
        )
        invocation = f"stories --store /tmp/stories-review{flags} {name.replace('_', '-')} --input {shlex.quote(json.dumps(example(name)))}"
        body = f"""# {label}

## When to use

{purpose}

{getattr(Stories, name).__doc__}

## Inputs and invocation

Global options precede the command: --store PATH, --model-env, --provider NAME,
--model ID, --execution queued|background|in_process (default queued).
Provider choices: openai, anthropic, gemini, chatgpt, copilot.
Pass a JSON object with --input '{{...}}', --input @file.json, or --input - for stdin.
Replace uppercase identity placeholders with IDs from earlier receipts.

{chr(10).join(fields) or "No JSON fields; omit --input or use an empty object."}

```bash
{invocation}
```

## Result and next steps

{result}

## Execution and sharp edges

{limits}

Required request_id values identify mutations across the store: reuse only for an
identical retry; changed payloads conflict. A retry does not rerun failed work.

## Failures

Results and structured errors go to stdout as JSON. Provider login progress goes to
stderr. Exit 0 means the invocation succeeded, not that queued model work finished.
Exit 1 reports a named failure; exit 2 reports invalid input (parser diagnostics go
to stderr). Inspect error.code, message and remedy; never silently retry uncertain
model spending. Read stories --help for the complete workflow and prerequisites.
"""
    return (
        f'<skill_content name="{label}">\nSkill directory: {root}\n'
        "Relative resource paths are relative to this installed package.\n\n"
        f"{body}\n\n<skill_resources>\n  <file>SMART_TOOL.md</file>\n"
        "  <file>lib.py</file>\n</skill_resources>\n</skill_content>"
    )
