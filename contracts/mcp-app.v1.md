# Portable MCP review adapter — v1 (DRAFT)

**Who builds against this:** MCP hosts, agents and authors of collaborative presenters.
This optional adapter follows the [invocation](invocation.v1.md),
[caller interaction](caller-interaction.v1.md) and [dashboard](dashboard.v1.md)
contracts. Its supported scope is recorded in [the adapter guide](../docs/MCP.md).

1. The library owns business behavior. Typed MCP tools adapt public calls and return
   their identified outcomes; the App calls the same tools on the same store.
2. Discovery, help and retained review are provider-free. Generation needs explicit
   environment access and bounded authority. The adapter never implies host sampling,
   MCP Tasks, elicitation, authentication, notifications or caller wake-up.
3. Catalog/schema/UI metadata describes capability, not installation or execution
   authority. An App is optional. Any App-only capability is explicitly described;
   visibility does not itself authenticate a human or grant execution authority.
4. Requests preserve library idempotency, revision targets, draft ordering and grants.
   Drafts remain distinguishable from submissions. Provider-free user-comment
   submissions are retained awaiting model access without consuming a grant or
   dispatching guaranteed-failed work. Reads do not dispatch work.
5. Author labels are caller-reported. The protocol does not authenticate human intent;
   an explicit acceptance record must not claim verified human identity. Direction choice does not imply
   acceptance, generation permission or publication.
6. Actual retained previews use an opaque nested frame, without credentials, arbitrary
   network access or access to the MCP App bridge. Shared annotations do not change
   export bytes. Opening review controls does not move the material.
7. Scoped resource URIs identify retained media or a bounded transfer snapshot, not
   host paths or private web-service URLs. Binary chunks retain exact order and bytes.
   Export snapshots are immutable for the declared process lifetime; expiration or
   capacity exhaustion is explicit and never silently replaces an existing transfer.
8. Closing a viewer or transport preserves retained work and does not claim cancellation.
   Explicit cancellation remains a library operation; uncertain completion is not replayed.
9. The implementation uses MCP/MCP Apps SDKs and a self-contained resource, with no
   named-host dependencies. A separate fixture host exercises the wire contract.

Acceptance checks cover reconnects, exact-target drafts/comments, no accidental model
access, independent host rendering, retained media, immutable chunked exports, and
attempted nested-frame bridge access. They also require complete built-in dashboard
experience parity through the shared frontend and transport adapters, as specified
in the dashboard contract. Live provider quality and remote multi-user identity
remain separate checks. This requirement is not a claim that parity has passed.

Shared navigation MUST use public `get_review_view` / `update_review_view` library
capabilities. The state includes exact revision focus, one-based slide, comparison,
selected target, review panel, expanded sections and export format. Updates require
an exact version and idempotency identity; conflicts do not overwrite another
participant. The App follows explicit view changes and restores them on reopen.
Navigation MUST NOT imply direction selection, acceptance or model authority.
Draft content writes enforce their own observed-version CAS, not a later view
update. Clock skew cannot turn a stale editor into permission to replace a newer
acknowledged draft. Exact retries preserve the accepted draft version. Narration
replies retain their original story/revision and dialog-opening identity, including
when the same revision is reopened before an earlier reply returns.
Media playback and browser download handling may remain local presentation state;
acknowledged review position and saved drafts must be recoverable across the two
surfaces through public state, without depending on shared browser storage. Unsent
typing remains distinct from a saved draft or submission, and conflicts never
silently overwrite newer edits. Underlying domain actions are public capabilities.

Story-scoped MCP results include optional `_meta["amplifier/presentationId"]`
metadata with value `stories:story:<story_id>`. Hosts can reuse the same dashboard
across review methods while retaining exact revision links. Independent stories
have distinct identities; global status and failed calls do not invent one. This
metadata does not open a viewer, select a revision or grant execution authority.
