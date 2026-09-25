# Portable invocation contract — v1 (DRAFT)

**Who builds against this:** People running `stories`, Python applications importing
`amplifier_smart_tool_stories`, and agents invoking the CLI.
The external baseline is [Smart Tools at fd3c634](https://github.com/microsoft/amplifier-smart-tools/tree/fd3c63416d1c9b0eb6e55981b248d1b2b5c64452/spec).
Its upstream conformance kit checks only part of these promises.

## What it looks like

A caller installs Stories, supplies a request and receives a usable result without
setting up an Amplifier CLI session. These are illustrative outcomes, not API syntax:

```text
Right: help succeeds without a provider; generation without one fails with a remedy.
Wrong: importing Stories boots an agent and fails because no provider is configured.
```

## Purpose

Stories is usable independently of the harness that hosts its caller.
The same capability is available to programs and command-line users.
Failures and side effects are predictable enough to compose safely.
The [caller-interaction contract](caller-interaction.v1.md) defines context,
clarification and revision continuity; the
[internal execution contract](internal-execution.v1.md) defines enforcement behind
that public boundary.
The [storyboard exploration](storyboard-exploration.v1.md) and
[media and delivery](media-delivery.v1.md) contracts use this same boundary. Their
draft requirements do not advertise implemented commands, image providers or export
formats; public help and manifests describe only supported, validated behavior.

## Core (the teeth)

1. **The package is independently installable from Git.** The distribution is
   `amplifier-smart-tool-stories`, the import is `amplifier_smart_tool_stories`,
   and the command is `stories`; a source checkout is not required at invocation.
2. **The library owns every capability.** The CLI only adapts arguments and I/O.
   No capability exists only in an adapter. The library may invoke a renderer or
   other subprocess internally, with documented prerequisites and failure behavior.
3. **Self-description follows the pinned Smart Tools baseline.** The distribution
   has `smart-tool.json`, one `SMART_TOOL.md`, structured library manifest access,
   both help flags, truthful prerequisites and a provider-free smoke invocation.
   Library documentation and CLI help explain arguments, result shapes and which
   capabilities use AI; complete CLI help covers every supported capability.
4. **Deterministic use does not boot the agent runtime or execute a model.** Import,
   help, manifest access and advertised deterministic checks need no model credentials.
5. **Story composition and reasoning embed `amplifier-agent`.** Callers need neither
   the Amplifier CLI nor an existing host session, agent catalog or Stories bundle
   installation. Speech synthesis may call a provider API directly without booting
   the agent runtime, under the same library-controlled disclosure, spending and
   execution boundaries. Provider requirements remain explicit; runtime dependencies
   are not concealed.
   Smart-call documentation identifies the selected provider and that source content
   can be sent to it; invoking that call authorizes only the documented provider use.
   Content is not sent to other destinations through telemetry or unrequested research.
6. **Source inputs and optional additional context contain data.** Each capability
   documents required source inputs separately from optional context. CLI file
   options load the selected content before calling the library without silently
   summarizing it. Callers may supply summaries, hypotheses and preferences as
   explicitly identified context; these do not become inspected original evidence.
   Stories' own research is separate:
   repository or network inspection needs documented, explicitly selected scope.
7. **Results and failures are machine-usable.** Results identify artifacts and
   completion status; machine output uses stdout and progress uses stderr.
   Failures exit nonzero with a cause and remedy; missing providers never produce
   a silent fallback, and stdin-closed invocation never waits for a prompt.
8. **Writes and external actions stay within the requested operation.** Outputs go
   to selected destinations, state to platform user locations and temporary data to
   temporary directories. Creation does not auto-install, auto-open, commit, push,
   publish or implicitly start a service, and leaves existing files intact unless
   overwrite was explicitly permitted. An explicitly selected dashboard may start
   or reuse its service within granted presentation scope under the
   [dashboard contract](dashboard.v1.md); opening a viewer is separately controlled.

## What v1 deliberately does NOT freeze

- Function signatures and command verbs beyond `stories` — promote when caller
  examples and the first capability contract establish their compatibility needs.
- Supported platforms and independently verified provider authentication paths —
  the initial adapter supports OpenAI, ChatGPT, Copilot, Anthropic and Gemini.
  amplifier-agent tracks main; the development lock records the tested revision.
- Remote services and adapters beyond the optional [MCP review adapter](mcp-app.v1.md).
  The stdio/MCP Apps adapter preserves public library semantics and compiles the
  native review frontend rather than maintaining a reduced second UI. Provider
  setup has durable public jobs and exact request receipts; narrated-video transfer
  is path-free, bounded and uses retained audio only. Acceptance is caller-reported,
  not identity authentication. Browser parity evidence is distinct from live
  provider and narration quality evidence;
  unsupported features and unauthenticated attribution remain explicit.
- Autonomous source connectors — promote when a source-specific permission and
  failure contract is proposed; this version does not require those connectors.

## Stories acceptance checks

These are Stories-specific checks, not claims about the upstream kit's coverage.
Run and report the upstream kit separately for descriptor, manifest and CLI probes;
it does not install the tool or establish library parity, truth or visual quality.
Report skips as skips, never as passes.

- Clauses 1–3: Git installation outside the checkout exposes both surfaces and the
  same capability set; descriptor, manifest and package metadata agree.
- Clauses 4–5: provider-scrubbed deterministic calls succeed without an engine boot;
  configured smart execution reaches the embedded runtime without a host session.
- Clause 6: a direct content payload works without access to its original file.
- Clause 7: invalid input and missing credentials fail nonzero with remedies;
  stdout parses as documented and stdin-closed calls terminate.
- Clause 8: output, process, dependency and repository snapshots show no unrequested
  changes, publication, service startup or overwrites.

Missing evidence is not a pass.
