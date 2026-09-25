# Story review dashboard contract — v1 (DRAFT)

**Who builds against this:** People reviewing stories, calling agents, and authors
of the built-in dashboard or host presentation adapters.

## What it looks like

The dashboard is a built-in, optional review workspace over the Stories library.
The caller may select it at the start or open an existing story for participation.
It shares the identities and outcomes in the
[caller-interaction contract](caller-interaction.v1.md); evidence and artifact quality
follow the [storytelling contract](storytelling.v1.md).
This is a behavioral example, not API syntax:

```text
Caller creates story → identified revision becomes available
Person opens that work → previews artifact and checks relevant sources
Person submits “shorten this section” → receipt names the reviewed revision/section
Stories interprets comment → authorized answer/refinement while the person keeps reviewing
New revision available → quiet indication; review position and unfinished typing preserved
Person exports chosen revision → identified artifact; earlier versions remain available
```

Right: show feedback on revision A while B is available and resolve which base to use.
Wrong: silently apply feedback to B or export B while displaying A.

## Purpose

Give the person and calling agent a shared place to review and continue work.
The dashboard is an intended product capability, not a requirement for using the
tool. It exposes library-owned behavior rather than introducing a second workflow
or requiring a full document, spreadsheet or slide editor.

Media playback, asset isolation and export choices are specified in the
[media and delivery contract](media-delivery.v1.md). Static preview support does not
establish playback support.
Comparison of storyboard directions follows the
[storyboard exploration contract](storyboard-exploration.v1.md).

## Core (the teeth)

1. **Presentation is selected explicitly.** Callers can use the built-in dashboard,
   their own presentation surface or headless access. Selecting the dashboard with
   service authority lets Stories start or reuse it and update it as work becomes
   available, without a repeated start/approval step for each revision. Opening a
   browser or taking focus requires the corresponding scope; the caller may grant
   these together initially. Ordinary artifact creation does not imply presentation
   authority. Optional presentation failure is reported while public artifacts and
   controls remain usable. A service URL is not proof the person saw the result.
2. **The workspace shows identified work.** It opens directly on the requested
   story/revision, including work created headlessly, and exposes retained versions
   and exports. Preview, feedback, review findings and export controls clearly target
   that version. Switching or returning to work preserves its intent, sources,
   choices and saved drafts under documented retention. Older revisions do not
   silently become the current one. Missing retained material is reported explicitly.
3. **Previews represent actual artifacts.** Each supported format documents its
   available preview, navigation and limitations. The workspace distinguishes a draft,
   an actual rendered artifact and an approximate representation. A preview identifies
   its source revision; regenerated content cannot masquerade as the original export.
   Unsupported preview or failed rendering is visible and does not appear as a blank
   successful viewer. Existing artifacts and review findings can be viewed without
   model credentials. Displaying a preview is not itself a visual-quality pass.
4. **Feedback is targeted and acknowledged.** People can submit feedback on the
   displayed revision and, where supported, an identified slide, page or section.
   Draft feedback is visibly unsubmitted, can be saved, and survives refresh once
   acknowledged as saved. The UI makes unsaved changes and save failures visible.
   Drafts are not execution authority and are not discarded by background updates.
   Submission produces a durable receipt before the UI reports acceptance. Stale or
   ambiguous targets produce a visible choice or conflict, not silent retargeting.
   Refinement preserves unaffected choices and earlier accepted revisions.
5. **Human actions and execution share public state.** Submitted feedback, answers,
   revision choices and operation outcomes are observable through the library/CLI.
   The UI distinguishes accepting an action from starting and completing its work.
   Explicit submissions may start covered work within existing valid authority;
   otherwise they identify the needed input/access or pending caller action.
   Refresh, retry and event redelivery do not repeat the effect. Saving feedback
   does not promise notification delivery or automatically wake the calling agent.
6. **Evidence and review are inspectable.** The person can inspect supporting sources,
   material assumptions, missing information and review findings associated with the
   displayed revision through the same public records available to the caller.
   Structural, source-fidelity and rendered-usability checks remain separate;
   unperformed or stale checks are visible. These details need not dominate the
   artifact preview. Human acceptance is recorded separately from model review and
   does not certify factual truth or grant publication authority.
7. **Settings use shared capabilities.** Provider/model selection and supported
   output preferences use library configuration with redacted effective state and
   explicit persistence scope. Changes affect future operations, preserve work and
   drafts, and do not silently mutate an active operation. The workspace provides
   actionable provider setup/status and explicit connection testing or login where
   supported. Tests that spend tokens are labeled; generation never unexpectedly
   launches authentication. Credentials and session access secrets do not enter
   generated artifacts, story records or ordinary browser settings storage.
   Applying a writing provider also applies to subsequently submitted authorized
   feedback, without extending its grant or rerouting existing operations.
   Narration provider, speech model, voice, delivery instructions and speech
   availability use the same shared configuration capabilities. Writing-provider
   changes do not silently alter narration settings or regenerate audio. Native sign-in,
   runtime preparation, discovery and testing are explicit background actions; the
   person can keep reading and saving drafts while they run.
   A deadline or cancellation request does not release setup exclusion before
   owned cleanup settles or owner loss is established independently of PID reuse.
8. **Export delivers the chosen revision.** Download/export identifies the selected
   revision, actual format, artifact and current findings or limitations. An existing
   artifact can be downloaded without a model call. Creating a different format is
   a distinct documented operation with its own prerequisites and checks; its result
   does not silently replace the displayed original. Export never applies unsubmitted
   feedback, overwrites an earlier result without permission, or publishes content.
   Narration preparation uses writing settings independently of speech support.
   People can prepare a script with defaults, guide refinement, edit passages and
   return to earlier script versions on the selected revision. Incoming writing
   results preserve newer unsent edits; opening controls never starts writing.
   Narrated export distinguishes generating new speech from reusing retained audio
   or downloading an existing video. The selected notes, narration settings and
   timing choices remain identifiable; opening export controls does not synthesize
   speech or initiate spending.
9. **Activity and lifecycle are honest.** The workspace and caller can distinguish
   preparation, available material, refinement, waiting for input/access and terminal
   outcomes, without exposing private model reasoning. They can cancel work and
   distinguish acknowledgement from completed cleanup. Finishing one generation
   leaves review available; export alone does not stop the workspace. Closing a tab
   disconnects its viewer and does not imply cancellation, approval or additional
   spending authority. An explicit workspace stop releases owned live resources,
   prevents stale submissions from reviving work, and reports cleanup failures.
   Retained artifacts, accepted feedback and saved drafts survive under the retention
   policy. Reopening restores work without automatically restarting model spending.
10. **Generated content is separate from workspace controls.** The built-in service
    is authenticated and local by default; wider exposure is not implicit. It serves
    authorized artifacts through identified references, not arbitrary filesystem
    paths. Generated HTML, embedded content and source text cannot acquire dashboard
    credentials, operate decision/settings controls or read unrelated story data.
    Viewing content grants no extra network or source access. Isolation and rendering
    failures are reported without being mistaken for human decisions. Cleanup affects
    only owned resources, not unrelated browser tabs or host services.
11. **Every domain action remains library-accessible.** Preview access, evidence
    review, saved feedback, submissions, revision selection, settings, export and
    operation control use the public library; the CLI exposes the same domain
   capabilities. The built-in HTML dashboard and MCP App share the same frontend,
   controls and review behavior through transport adapters. Third-party presenters
   may expose a subset without changing domain semantics; that does not permit a
   reduced built-in MCP experience.
12. **Annotations are an optional review overlay.** People and calling agents can
    highlight selected material and attach comments, questions or explanations.
    The same comment mechanism supports a whole-story target without a selection.
    Format support determines whether selection identifies text, an element or a
    visual region; its precision is explicit. Annotations and replies live in review
    state, identify their author and original revision/target, and can be shown or
    hidden without changing the artifact. They are not embedded in generated
    documents or artifact exports. References retain enough selected text or visual
    context to understand the original target. Reassociation across revisions is
    shown only when established; uncertain or removed targets remain visibly tied
    to the original instead of silently moving. A new revision alone does not imply
    that a comment was addressed or resolved.
13. **Comments can drive an immediate, contextual response.** Submitting an individual
    user comment brings it into the shared interaction. Stories' internal intelligence
    can interpret and respond within existing authority without waiting for the caller
    or for a batch of feedback. The person need not classify a comment as a question
    versus a change request or use a separate revision control. Context determines
    whether to answer, explain, revise or seek clarification; ambiguity with material
    consequences is not silently guessed. Draft typing never starts work. The UI
    reports accepted comments, active work, responses and failures, and correlates
    resulting revisions. Conflicting comments or changes preserve their targets and
    produce a clarification or conflict rather than overwriting intervening work.
14. **Background work preserves the person's review flow.** Submitting a comment,
    receiving a reply or completing a revision does not reset the viewer to the top,
    change the selected page/slide, steal focus, close the active comment or discard
    unfinished typing. The person can keep reviewing and commenting on the identified
    version while work proceeds. New revisions receive a quiet availability indication.
    An in-place update is allowed only when review context can be preserved; otherwise
    the person chooses when to view the revision. If their target no longer exists,
    show that fact and offer navigation rather than guessing a new position. Export
    continues to identify the chosen revision even when a newer one is available.

15. **Material comes first and stays fixed during commenting.** The artifact occupies
    the review surface. Caller highlights reveal relevant material in context. Native
    text selection or an element selection offers a clear comment action without a
    separate pencil mode. Opening, typing in or closing the composer must not move,
    resize, rescale or reflow the material. Controls and comments form an optional
    overlay, with plain author labels and no robot icon in agent feedback.

16. **Document reading controls stay secondary.** Continuous flow is the default;
    paginated reading, zoom and fit width are available through a small discoverable
    tab that reveals controls on hover, click or keyboard focus. The toolbar stays
    available during interaction and can be dismissed without closing a comment.
    Navigating comments includes both person and caller annotations. Use existing
    whitespace for anchored comments when sufficient; otherwise use a floating
    overlay. Explicit view/zoom changes preserve the logical reading passage and
    drafts. Leaving a comment's passage closes its composer without discarding the
    draft. Browser page boundaries are approximate and must not be represented as
    proof of Word or PDF pagination.

17. **Comparison is shared across formats.** The workspace supports side-by-side
    alternatives, focused inspection of either and return to comparison, with
    format-appropriate views for storyboards, HTML presentations and documents.
    Storyboard views support outlines, mixed sequences and illustrated panels.
    Comparison does not assume matching panel/page counts or imply correspondence
    merely from position. Supporting document/presentation views does not require
    generating alternatives for those formats; that capability remains deferred.
    Comparison is available when requested, not the default creation/review flow for
    any format. Opening its controls does not itself generate additional directions.
18. **Focus, direction choice and acceptance remain distinct.** Inspecting an
    alternative does not select it. Explicit direction selection is observable to
    the caller and retains other alternatives and their revision histories. It does
    not accept an artifact or initiate uncovered work. Comments, saved drafts and
    exports identify their actual direction/revision and material target. Background
    results do not switch the focused alternative. Explicit comparison/focus changes
    may change layout while preserving review context and drafts; opening a comment
    still must not move or resize the material.

## Stories acceptance checks

Proposed checks only; these do not establish current support:

- Compare outlines and mixed storyboards, focus either direction, return and choose
  explicitly. Retrieve the choice and correctly targeted comments through the CLI.
- Exercise storyboard, presentation and document comparison views with unequal
  lengths. Preserve drafts and exact export targets during view changes and incoming
  revisions; no model work occurs merely to inspect retained alternatives.
- Create headlessly, open by identity, inspect the actual artifact, submit feedback,
  retrieve the receipt through the CLI, refine and export the selected revision.
- Refresh after saving a draft and after submitting feedback. Preserve both with
  distinct states; neither refresh nor retries duplicate generation. Report failed
  saves honestly and keep a concurrent update from discarding unsent work.
- Submit feedback from an older view while another revision exists. Preserve the
  target or report a conflict; never silently change or export a different revision.
- With no provider configured, view retained artifacts, evidence, versions and
  existing exports. Missing preview dependencies yield explicit limitations.
- Show failed, stale and unperformed checks accurately; human acceptance does not
  change their results or imply publication permission.
- Change provider/output settings through both adapters and inspect effective scope.
  Preserve running operations and drafts; no login or model request occurs merely
  from viewing or changing settings.
- Exercise service startup failure, disconnect, cancellation, stop and reopen.
  Preserve retained work, report cleanup outcomes and reject obsolete submissions.
  Headless usage starts no dashboard service or viewer.
- Attempt dashboard-control access from generated content and arbitrary-path access
  through artifact routes. Neither can reach credentials or unauthorized resources.
- Add a highlight through the public caller interface, reply through the overlay,
  and retrieve both with their authors and targets. Hide the overlay and export:
  the artifact contains no review annotations and its underlying bytes are unchanged
  by annotation-only actions.
- Submit anchored and overall comments that respectively ask a question, request
  a revision and need clarification. Under valid authority, internal intelligence
  responds without caller mediation or requiring users to categorize their comments.
- While reviewing a later slide/page with a selection, open thread and unsent text,
  complete a background revision. Preserve position, focus and input; when safe
  in-place preservation is impossible, leave the reviewed version visible until
  the person chooses to switch. Test changed and removed annotation targets.

HTTP success alone does not establish usable review.

## What v1 deliberately does NOT freeze

- Dashboard framework, visual layout, theme choices or service implementation.
- Exact API names, event transport, identifiers, retention duration or conflict UI.
- The preview mechanism and feedback granularity for each output format; advertise
  these only after demonstrated artifact and interaction checks.
- Selection/anchor representation, revision reassociation algorithms and the exact
  revision-availability interaction. No elaborate comment workflow is required.
- Persistent provider preferences versus process-local settings; the chosen behavior
  must be explicit and consistent across public interfaces.
- Full content editing, real-time coauthoring, hosted multi-user access or automatic
  caller wake-up. None is a prerequisite for the initial review workspace.

## Changelog

- **2026-09-18** — Added shared alternative comparison, format-appropriate views
  and explicit direction selection, distinct from focus and revision acceptance.
- **2026-09-16** — Added optional bidirectional annotation overlays, contextual
  comment handling by internal intelligence and uninterrupted review during updates.
- **2026-09-16** — First draft defining the optional built-in story review workspace,
  shared actions/settings, artifact fidelity and presentation lifecycle.

## Optional portable presenter

The MCP Apps presenter is governed by [mcp-app.v1.md](mcp-app.v1.md) and uses the
same review frontend as the HTML dashboard. Identical supported controls include
settings, narration, acceptance and export; host or runtime prerequisites remain
visible rather than becoming silent omissions. Transport adapters preserve their
own authentication and isolation boundaries. An acceptance record does not prove
the human identity of an MCP caller, and merely opening either surface grants no
provider access or spending authority.

Parity checks exercise both transports with the same retained material, viewport
and theme: presentation, document and storyboard reading; reopening threads;
either comparison direction; stable-panel narration; format-correct downloads;
settings and explicit provider jobs; acceptance; draft/view continuity and
recovery after failed or lost acknowledgements. Shared source alone is not proof
that both surfaces work. Until those checks pass, parity remains unverified.
