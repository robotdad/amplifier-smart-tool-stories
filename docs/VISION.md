# Stories — Vision (DRAFT)

*The intended experience; specific promises live in `contracts/`.*

## What Stories is

Stories turns source material into clear, useful communication without asking the
caller to become a researcher, writer, designer and tool integrator. A person states
the purpose, audience and desired output. An application or agent supplies the same
request as data and receives artifacts it can use.

The expertise travels with the tool. Research, narrative planning, technical and
public writing, executive communication, case studies, community stories, data
presentations and adaptation are parts of one storytelling capability. Presentations,
documents and data-backed outputs serve different audiences; the product is not
defined by a single rendering format.
Stories brings together writing, images, and video to create communication people
can read, present, or watch.

Stories also helps people develop rough ideas into visual sequences. The caller
carries the conversation; the tool brings expertise in audience, narrative, visual
explanation, pacing and evidence. A person need not know storyboarding terminology
or arrive with a completed brief. Creation normally develops one direction across
storyboards, documents and presentations. When the person steers toward exploring
alternatives, Stories offers meaningful directions to compare and develop. Uncertainty
can prompt a suggestion to compare, not automatic generation of multiple artifacts.
Outlines, partly illustrated sequences and
visual storyboards are useful stages of the same work; detail serves the decision
rather than a mandatory production sequence. Choosing a direction focuses effort
without erasing alternatives or implying acceptance of a finished revision.

Storyboarding serves different media and purposes, including comics, motion graphics,
technical explanations and customer stories. Shared storytelling expertise supports
these uses without requiring a separate mode for each. A storyboard plans an
experience; it does not imply production of the finished video, animation or comic.
Image generation is a shared media capability for storyboards, documents and
presentations. Supplied, generated and planned visuals remain distinguishable, and
reviewed images are retained rather than regenerated when work is reopened.

Stories is a Smart Tool: a reusable library with a thin command-line interface and
its own model-backed execution. Its callers use `stories` or import its Python
library without adopting a particular agent environment or supplying specialist
instructions of their own.

The caller retains control of sources, permitted actions and output destinations.
The result identifies the created artifacts, their supporting evidence, missing
information and checks performed. The same documented promises govern the library,
the CLI and any other adapter.

Stories includes a built-in dashboard for reviewing and refining stories with a
calling agent. A person can inspect the actual artifact, give feedback on an
identified revision, explore its sources and review findings, return to earlier
versions, and export the result they reviewed. Supported formats provide appropriate
previews and make preview limitations visible. Provider/model settings and output
preferences use the same public capabilities as the library and CLI.

The dashboard is part of the product and optional to use. A caller may work headlessly,
select the built-in dashboard, or provide its own presentation surface. Work begun
headlessly can open in the dashboard without regeneration or conversation replay.
The built-in HTML dashboard and MCP App provide the same review experience:
one shared frontend, with transport adapters rather than independently maintained
interfaces. Controls, format support and retained review context do not become a
reduced subset merely because the workspace is opened through MCP. Transport and
host security requirements remain explicit; parity does not grant provider access,
authenticate a caller-reported person, or authorize spending.
The person and calling agent share the same story state: submitted feedback,
answers and changes are observable to the caller; unsubmitted drafts remain distinct
from instructions. Recording an action does not promise to wake the calling agent.
Existing valid authority can cover requested refinement without repeated approval.

The review workspace supports comparing alternatives side by side, focusing on one
without selecting it, and explicitly choosing a direction. Each format has its own
appropriate view within that shared interaction. Storyboard exploration introduces
this comparison workflow; generating alternative documents and presentations remains
a later capability, separate from their support in the comparison viewer.

The material fills the review surface; review controls stay secondary. Opening a
comment never moves or resizes the material. An optional review overlay lets the
person select text or an element directly and leave a comment,
or comment on the story overall. The caller can also highlight material and attach
questions or explanations for the person. These annotations belong to shared review
state, not the document, and are absent from artifact exports. Stories' internal
intelligence interprets submitted comments in context and can answer, refine or ask
for clarification within existing authority without a round trip through the caller.
The person can keep reviewing while work proceeds; updates preserve their position,
selection, open comment and unfinished typing. A new revision is quietly made
available without forcing a disruptive refresh. The caller can observe the resulting
comments, actions and revisions later.

## Principles

### 1. **Evidence sets the limits of the story.**

Numbers, attribution and impact claims stay tied to sources. Missing evidence remains
visible; a persuasive narrative does not turn estimates into measurements.
Fictional scenes, visual metaphors and imagined possibilities may be created as such;
they do not become evidence of real events or product behavior.

### 2. **The expertise lives inside the tool.**

The caller specifies an outcome rather than rehearsing specialist prompts or routing
agents. Stories owns the research-to-artifact workflow and discloses its limits.

### 3. **The library is the product.**

Every capability is callable without the command line or dashboard. Both adapt
inputs and outputs rather than owning hidden functionality. Human participation
and agent-driven work operate on the same identified stories and revisions.

### 4. **Model use is deliberate.**

Smart operations use the embedded agent runtime. Deterministic operations need no
model credentials. Missing configuration produces a remedy, not a disguised fallback.

### 5. **Creation does not imply publication.**

Making a story does not implicitly open applications, start a service, modify unrelated
repositories, install software or send content to an audience. An explicitly selected
dashboard can start or update within granted presentation scope; opening a viewer
remains a separate choice. Network research and model use have explicit scope;
publication is a distinct decision.

### 6. **Quality claims name their evidence.**

A file existing is not the same as a useful story. Structural checks, source review
and visual review answer different questions and remain distinguishable.

### 7. **Portability preserves capability, not host assumptions.**

Stories works without assumptions about a caller's local paths, session layout
or deployment site. Unsupported outcomes fail explicitly.

### 8. **Review continues the same work.**

Feedback targets what the person saw. Refinement preserves unaffected choices and
earlier revisions, and export identifies the delivered version. Viewing retained
artifacts requires no model credentials. Closing the viewer does not erase work
or imply that execution has stopped; stopping releases owned live resources while
preserving retained results for a later return.

## What this deliberately resists

- A bag of converters presented as storytelling — synthesis is part of the product.
- A tool that only works inside one configured agent environment.
- Invented metrics, unsupported impact claims and misleading validation badges.
- Automatic deployment, PR creation or runtime installation hidden in generation.
- Universal file conversion or support for every platform without verification.
- Building a general-purpose agent platform instead of a storytelling tool.
- Requiring a full document or slide editor before people can review and refine work.

## How you can tell it is working

- A person with a rough idea can compare meaningful story directions and develop a
  sequence without supplying specialist prompts or learning storyboard terminology.
- The same foundation supports different communication purposes and levels of visual
  detail without forcing every story into a demo, film or marketing template.
- A caller obtains a usable artifact in their own environment without importing
  Stories expertise into their own prompts.
- A reader can trace factual claims to sources and see what remains unknown.
- An application consumes the result without extracting paths from conversational prose.
- An operator can inspect and check supported artifacts without model credentials.
- A maintainer can distinguish verified support from planned capabilities.
- A person reviews an artifact in the dashboard, submits targeted feedback, and the
  calling agent continues from that exact revision without screen scraping.
- A person returns to earlier work and exports the reviewed version without losing
  revisions or accidentally applying an unsubmitted draft.

## Changelog

- **2026-09-24** — Recorded the requested identical HTML/MCP experience and approved
  shared-frontend approach. This is intended direction, not a verified parity claim.
- **2026-09-18** — Added general-purpose storyboard exploration, shared comparison
  and image generation across formats as intended capabilities, not support claims.
- **2026-09-16** — Added the optional built-in review workspace, shared caller state,
  provider settings, revision continuity and explicit presentation lifecycle.
- **2026-09-09** — First draft; no lock or implementation claim.
