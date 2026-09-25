"use strict";
const $ = (id) => document.getElementById(id),
  frame = $("material");
const transport = window.StoriesTransport;
let story,
  revision,
  channel,
  bridge,
  documentBridge,
  documentKind = false,
  documentView = { mode: "continuous", zoom: 1, fit: false },
  commentIndex = -1,
  anchorRect = null,
  selection = { kind: "story" },
  active = null,
  candidate = null,
  visible = true,
  agentIndex = -1,
  slideElements = null,
  slide = 0;
let loadRequest = 0, loadingRevision = false;
let draftId,
  sequence = Date.now(),
  saveTimer,
  polling = false,
  submission = null;
// One retained shared review identity, not a claim of authenticated personhood.
const editor = "shared";
let retainedView = null, contextState = {}, viewQueue = Promise.resolve(), viewTimer;
let restoring = false, typing = 0, scope = 0, viewBusy = 0, viewConflict = false;
let draftQueue = Promise.resolve(), adoption = 0;
let commentToRestore = null;
const draftVersions = new Map();
const draftCommits = new Map();
function commentContext(id) {
  const saved = contextState.revision_comments?.[id];
  if (saved) return structuredClone(saved);
  // A legacy view describes only its identified revision, not a similar index
  // in the next revision. Capture this before asynchronous view writes arrive.
  if (retainedView?.revision_id !== id) return null;
  return {
    anchor: retainedView.anchor, draft_id: contextState.draft_id || null,
    active_annotation: contextState.active_annotation || null,
    composer_open: contextState.composer_open ??
      (retainedView.panel_open && !contextState.details_open && !retainedView.sections.length),
  };
}
function readContext(state) {
  const value = structuredClone(state.native_context || {});
  value.comparison_open = Boolean(state.comparison_revision);
  if (state.comparison_revision && value.comparison_ids?.at(-1) !== state.comparison_revision)
    value.comparison_ids = [state.revision_id, state.comparison_revision];
  return value;
}
const sameAnchor = (a, b) =>
  a.kind === b.kind &&
  a.element === b.element &&
  (a.kind !== "text" || (a.start === b.start && a.end === b.end));
const requestId = () => typeof crypto.randomUUID === "function" ? crypto.randomUUID()
  : [...crypto.getRandomValues(new Uint8Array(16))].map(b => b.toString(16).padStart(2, "0")).join("");
function error(e) {
  $("error").textContent = e.message || String(e);
  $("error").hidden = false;
}
async function api(name, data = {}) {
  const generation = scope;
  const result = await transport.api(name, {story_id: story?.id, ...data});
  if (generation !== scope) throw Error("Reply belongs to an earlier review workspace; retained result is unchanged.");
  return result;
}
function send(type, data = {}) {
  frame.contentWindow.postMessage({ channel, type, ...data }, "*");
}
const notes = () => story.annotations.filter((n) => n.revision_id === revision);
function view() {
  clearTimeout(viewTimer);
  if (!restoring) viewTimer = setTimeout(() => persistView().catch(error), 200);
}
function persistView() {
  if (!story || !retainedView || restoring) return Promise.resolve();
  if (viewConflict) return Promise.reject(Error("Shared review changed concurrently. Reopen to reconcile retained context; current typing remains in this open view."));
  const targetStory = story.id, targetScope = scope;
  if (revision && !commentToRestore) contextState.revision_comments = {
    ...contextState.revision_comments, [revision]: {
      anchor: structuredClone(selection), draft_id: draftId || null,
      active_annotation: active, composer_open: !$("composer").hidden,
    },
  };
  const changes = {
    revision_id: revision, slide: slide + 1,
    panel_open: !$("details").hidden || !$("composer").hidden, anchor: structuredClone(selection),
    comparison_revision: contextState.comparison_open ? contextState.comparison_ids?.at(-1) || "" : "",
    export_format: $("exportFormat").value,
    native_context: {...structuredClone(contextState), document_view: structuredClone(documentView),
      composer_open: !$("composer").hidden, draft_id: draftId || null,
      active_annotation: active, review_visible: visible, details_open: !$("details").hidden},
  };
  // A newly opened thread has a UI identity before its first save completes.
  // Wait only for drafts this view actually references, not unrelated work.
  // Capture the dependency with the view: later typing/retries cannot substitute
  // a different save for a failed first acknowledgement.
  const draftIds = new Set([
    changes.native_context.draft_id,
    ...Object.values(changes.native_context.revision_comments || {}).map(c => c.draft_id),
  ].filter(Boolean));
  const dependencies = [...draftIds].filter(id => !story.drafts[id])
    .map(id => draftCommits.get(targetStory + ":" + id));
  const run = async () => {
    for (const commit of dependencies) {
      if (!commit) throw Error("Comment draft is not saved yet; retry saving before retaining its review context.");
      await commit;
    }
    if (scope !== targetScope) return;
    if (viewConflict) throw Error("Shared review conflict: reopen before another submission.");
    if (Object.entries(changes).every(([key, value]) => JSON.stringify(value) === JSON.stringify(retainedView[key]))) return;
    const input = {...changes, story_id: targetStory, expected_version: retainedView.version, request_id: requestId()};
    try {
      const result = await api("update-review-view", input);
      if (scope !== targetScope) return;
      retainedView = result;
      transport.context({story_id: targetStory, ...result});
    } catch (e) {
      if (e.code === "view_conflict" && scope === targetScope)
        viewConflict = true;
      throw e;
    }
  };
  viewBusy++;
  const result = viewQueue.then(run).finally(() => { viewBusy--; });
  viewQueue = result.catch(() => {});
  return result;
}
async function retainedMutation(name, payload, key = name) {
  if (restoring || !retainedView) throw Error("Review context is updating; retry this action when the workspace is ready.");
  const targetScope = scope;
  payload = {story_id: story.id, ...structuredClone(payload)};
  const old = contextState.pending?.[key];
  if (old && JSON.stringify(old.payload) !== JSON.stringify(payload))
    throw Error("An earlier " + name + " has an unknown acknowledgement. Restore its exact input to retry; do not create another request.");
  const intent = old || {payload, request_id: requestId()};
  contextState.pending = {...contextState.pending, [key]: intent};
  await persistView();
  try {
    const result = await transport.api(name, {...intent.payload, request_id: intent.request_id});
    const recordReceipt = context => {
      if (["generate-narration", "prepare-narration"].includes(name)) {
        const rev = intent.payload.revision_id;
        context.narration = {...context.narration, [rev]: {
          ...context.narration?.[rev],
          [name === "generate-narration" ? "operation" : "writing_operation"]: result.operation_id,
          ...(name === "prepare-narration" ? {writing_draft: JSON.stringify(intent.payload.draft_notes)} : {}),
        }};
      }
      if (context.pending?.[key]?.request_id === intent.request_id) delete context.pending[key];
    };
    if (scope === targetScope) {
      recordReceipt(contextState);
      await persistView();
    } else {
      // Keep the acknowledged operation on its original story/revision, even
      // when another workspace has since been adopted. CAS refuses interference.
      const original = await transport.api("get-review-view", {story_id: intent.payload.story_id});
      const context = structuredClone(original.native_context || {});
      recordReceipt(context);
      await transport.api("update-review-view", {
        story_id: intent.payload.story_id, expected_version: original.version,
        request_id: requestId(), native_context: context,
      });
    }
    return result;
  } catch (e) {
    if (e.definite && scope === targetScope) {
      delete contextState.pending[key];
      await persistView().catch(error);
    }
    throw e;
  }
}
function draftIdentity() {
  const { kind, element, start, end } = selection;
  return (
    "review-" +
    editor +
    "-" +
    revision +
    "-" +
    JSON.stringify([kind, element, start, end])
  );
}
async function closeComment() {
  clearTimeout(saveTimer);
  const edit = typing, id = draftId, targetScope = scope;
  await saveDraft();
  if (edit !== typing || id !== draftId || targetScope !== scope) return;
  $("composer").hidden = true;
  $("quick").hidden = true;
  send("track-anchor", { anchor: null });
  return persistView();
}
function saveDraft() {
  if (!draftId) return;
  const id = draftId,
    text = $("comment").value,
    anchor = structuredClone(selection),
    rev = revision,
    seq = ++sequence;
  const targetStory = story.id, edit = typing, targetScope = scope;
  const key = targetStory + ":" + id;
  if (!draftVersions.has(key)) draftVersions.set(key, story.drafts[id]?.version || 0);
  $("saved").textContent = "Saving…";
  const run = async () => {
  let committed = false;
  try {
    const result = await transport.api("save-draft", {
      story_id: targetStory,
      revision_id: rev,
      draft_id: id,
      sequence: seq,
      text,
      anchor,
      expected_version: draftVersions.get(key),
    });
    draftVersions.set(key, result.version);
    committed = result.status === "saved";
    if (scope === targetScope && result.status === "saved")
      story.drafts[id] = {revision_id: rev, anchor, text, sequence: seq, version: result.version};
    if (scope === targetScope && draftId === id && sequence === seq && typing === edit)
      $("saved").textContent =
        result.status === "saved" ? "Draft saved" : "Newer draft retained";
  } catch (e) {
    if (scope === targetScope) {
      $("saved").textContent = committed ? "Draft saved · review context not saved" : "Not saved to Stories";
      error(e);
    }
    throw e;
  }
  };
  const result = draftQueue.then(run);
  draftCommits.set(key, result);
  draftQueue = result.catch(() => {});
  // Keep view persistence OUTSIDE the draft commit queue: an older save may
  // finish while the current view references a newer first save. Waiting for
  // that view inside this queue would deadlock the newer draft behind itself.
  return result.then(async () => {
    if (scope !== targetScope) return;
    try { await persistView(); }
    catch (e) {
      if (scope === targetScope) error(e);
      throw e;
    }
  });
}
async function openComment(anchor, note = null) {
  if (!$("composer").hidden) await saveDraft();
  selection = anchor;
  $("composer").dataset.anchor = JSON.stringify(anchor);
  active = note?.id || null;
  anchorRect = null;
  draftId = draftIdentity();
  $("composer").hidden = false;
  $("quick").hidden = true;
  $("author").textContent =
    note?.author === "agent" ? "From your agent" : "Your comment";
  const saved = story.drafts[draftId];
  const entry = saved?.revision_id === revision && sameAnchor(saved.anchor, anchor) ? saved : null;
  draftVersions.set(story.id + ":" + draftId, entry?.version || 0);
  $("comment").value = entry?.text || "";
  sequence = Math.max(sequence, entry?.sequence || 0);
  typing++;
  $("target").textContent =
    anchor.quote ||
    note?.anchor.quote ||
    (anchor.kind === "story" ? "Whole story" : "Selected element");
  $("outcome").textContent = "";
  renderMessages();
  send("track-anchor", { anchor });
  $("comment").focus({ preventScroll: true });
  await saveDraft();
}
function renderMessages() {
  const group = notes().filter((n) => sameAnchor(n.anchor, selection));
  const n = group.at(-1);
  const messages = group.flatMap((n) => [
    { author: n.author, text: n.text },
    ...n.responses,
  ]);
  const key = JSON.stringify(messages);
  if ($("messages").dataset.messages !== key) {
    $("messages").dataset.messages = key;
    $("messages").replaceChildren();
    for (const m of messages) {
      const row = document.createElement("div");
      row.className = "message";
      const a = document.createElement("strong");
      a.textContent =
        m.author === "agent"
          ? "Agent"
          : m.author === "stories"
            ? "Stories"
            : "You";
      row.append(a, document.createTextNode(m.text));
      $("messages").append(row);
    }
  }
  if (n)
    $("outcome").textContent =
      n.status.replaceAll("_", " ") +
      (n.result_revision ? " · revision available" : "") +
      (n.error ? " · " + n.error.message + " " + n.error.remedy : "");
}
function update() {
  const allNotes = notes();
  if (documentKind && !$("composer").hidden)
    send("track-anchor", { anchor: selection });
  $("previousComment").disabled = $("nextComment").disabled = !allNotes.length;
  $("commentPosition").textContent = allNotes.length
    ? commentIndex >= 0 && allNotes[commentIndex]
      ? `${commentIndex + 1} / ${allNotes.length} · ${allNotes[commentIndex].author === "agent" ? "Agent" : "You"}`
      : `${allNotes.length} comment${allNotes.length === 1 ? "" : "s"}`
    : "No comments";
  const agents = notes().filter((n) => n.author === "agent");
  $("agent").hidden = !agents.length;
  $("agent").textContent = `Agent highlights · ${agents.length}`;
  const direction = story.directions?.find(d => d.id === story.revisions.find(r => r.id === revision)?.direction_id);
  const newest = direction?.latest_revision || story.latest_revision;
  $("available").dataset.revision = newest || "";
  $("available").hidden = !newest || newest === revision;
  send("annotations", { annotations: notes() });
  renderMessages();
  $("threads").replaceChildren();
  for (const n of notes()) {
    const b = document.createElement("button");
    b.textContent = (n.author === "agent" ? "Agent: " : "You: ") + n.text;
    b.onclick = () => {
      send("reveal", { anchor: n.anchor });
      openComment(n.anchor, n).catch(error);
    };
    $("threads").append(b);
  }
  const current = story.revisions.find((r) => r.id === revision);
  const accepted = (story.acceptances || []).find(a => a.revision_id === revision);
  $("acceptRevision").disabled = !current || Boolean(accepted);
  $("acceptanceStatus").textContent = accepted ? "Acceptance reported · this revision only (not authenticated)" : "Acceptance is caller-reported, separate from model checks, and does not authorize publication.";
  $("sources").textContent =
    (current
      ? Object.entries(current.review)
          .map(([k, v]) => k + ": " + v)
          .join("\n")
      : "No revision") +
    (current?.quality_review
      ? "\n\nModel review of " +
        current.quality_review.pages.length +
        " rendered pages\n" +
        [
          ...current.quality_review.warnings,
          ...current.quality_review.limits,
        ].join("\n")
      : "") +
    "\n\n" +
    story.sources.map((s) => s.name + " · " + (s.kind || "source") + "\n" + (s.attribution || "") + "\n" + s.content).join("\n\n");
  if (current?.changes) $("sources").textContent += "\n\nChanges, omissions & assumptions\n" + [current.changes.summary, ...["material_changes", "omissions", "assumptions"].map(key => key.replaceAll("_", " ") + ":\n" + ((current.changes[key] || []).map(text => "• " + text).join("\n") || "None reported"))].join("\n\n");
  if (current?.calculations?.length) $("sources").textContent += "\n\nCalculations\n" + current.calculations.map(c => `${c.operation.replaceAll("_", " ")}: ${c.inputs.map(i => i.value + " [" + i.evidence_id + "]").join(", ")} → ${c.result} ${c.unit}\nRounded to ${c.decimal_places} decimal places. Arithmetic checked; interpretation reviewed by model.`).join("\n\n");
  const versions = $("versions");
  if (JSON.stringify([...versions.options].map(o => o.value)) !== JSON.stringify(story.revisions.map(r => r.id))) {
    versions.replaceChildren();
    for (const [i, r] of story.revisions.entries()) {
      const option = document.createElement("option");
      option.value = r.id;
      option.textContent = `Version ${i + 1}${r.id === story.latest_revision ? " · newest" : ""}`;
      versions.append(option);
    }
  }
  versions.value = revision;
  $("narrationOpen").disabled = loadingRevision || current?.kind === "document";
  $("narrationOpen").title = current?.kind === "document"
    ? "Narration is available for presentations and retained storyboard panel text, not documents." : "";
  $("narrationLimit").textContent = current?.kind === "document" ? $("narrationOpen").title : "";
  $("narrationLimit").hidden = current?.kind !== "document";
}
async function loadRevision(id, initialSlide = 0) {
  const request = ++loadRequest;
  loadingRevision = true;
  $("narrationOpen").disabled = true;
  const targetScope = scope, targetStory = story.id;
  try {
  if (!$("composer").hidden) await saveDraft();
  const p = await api("get-preview", {story_id: targetStory, revision_id: id });
  if (request !== loadRequest || scope !== targetScope) return;
  const nonce = requestId();
  const csp = `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data: blob:; media-src blob:; script-src 'nonce-${nonce}'; connect-src 'none'; form-action 'none'; base-uri 'none'">`;
  const parsed = new DOMParser().parseFromString(p.html, "text/html");
  const mediaPayload = [];
  for (const asset of p.assets || []) {
    const nodes = [...parsed.querySelectorAll("img,video,source,track")].filter(node =>
      ["src", "poster"].some(attr => node.getAttribute(attr) === "asset:" + asset.id));
    if (!nodes.length) continue;
    const response = await transport.binary("media", {story_id: targetStory, revision_id: id, asset_id: asset.id});
    mediaPayload.push({id: asset.id, mime_type: asset.mime_type, bytes: await response.arrayBuffer()});
    for (const node of nodes) for (const attr of ["src", "poster"])
      if (node.getAttribute(attr) === "asset:" + asset.id) {
        node.setAttribute("data-stories-media-" + attr, asset.id);
        node.removeAttribute(attr);
      }
  }
  if (request !== loadRequest || scope !== targetScope) return;
  documentKind = ["document", "storyboard"].includes(p.kind);
  document.body.classList.toggle("document-review", documentKind);
  $("documentTools").hidden = !documentKind;
  commentIndex = -1;
  $("exportFormat").hidden = false;
  for (const option of $("exportFormat").options) {
    option.hidden = p.kind === "document" ? option.value === "zip" : ["pdf", "docx"].includes(option.value);
  }
  $("exportFormat").value = p.kind === "storyboard" ? "zip" : (p.assets || []).some(a => a.mime_type.startsWith("video/")) ? "zip" : "html";
  $("exportLimit").textContent = "";
  commentToRestore = commentContext(id);
  revision = id;
  loadingRevision = false;
  slide = initialSlide;
  channel = requestId();
  $("composer").hidden = true;
  $("quick").hidden = true;
  active = null;
  draftId = null;
  candidate = null;
  slideElements = null;
  selection = { kind: "story" };
  frame.addEventListener("load", () => {
    if (request === loadRequest) send("media", {assets: mediaPayload});
  }, {once: true});
  $("mediaDetails").textContent = (p.assets || []).map(a =>
    `${a.name} · ${(a.size_bytes / 1024 / 1024).toFixed(2)} MiB${a.width ? ` · ${a.width}×${a.height}` : ""}`
  ).join("\n") + "\n" + (p.media_warnings || []).map(w => w.message).join("\n");
  let html = parsed.documentElement.outerHTML.replace(/<head[^>]*>/i, (m) => m + csp);
  if (!/<head/i.test(html))
    html = html.replace(/<html[^>]*>/i, (m) => m + "<head>" + csp + "</head>");
  const code = (bridge + (documentKind ? documentBridge : ""))
    .replaceAll("__CHANNEL__", JSON.stringify(channel))
    .replace("__SLIDE__", String(slide));
  html = html.replace(
    /<\/body>/i,
    `<script nonce="${nonce}">${code}</script></body>`,
  );
  frame.srcdoc = html;
  view();
  update();
  } finally {
    if (request === loadRequest && scope === targetScope) {
      loadingRevision = false;
      $("narrationOpen").disabled = story.revisions.find(r => r.id === revision)?.kind === "document";
    }
  }
}
async function choose(id) {
  if (story.kind !== "storyboard") await retainedMutation("select-revision", { revision_id: id });
  await loadRevision(id, slide);
}
window.addEventListener("message", (e) => {
  if (e.source !== frame.contentWindow || e.data?.channel !== channel) return;
  const m = e.data;
  if (m.type === "open-link") {
    try {
      const url = new URL(m.href);
      if (["http:", "https:"].includes(url.protocol) && !url.username && !url.password)
        transport.openLink(url.href);
    } catch (_) { /* Invalid links never navigate the review surface. */ }
    return;
  }
  if (m.type === "document-layout") {
    send("annotations", { annotations: notes() });
    if (m.missingPassage) {
      $("connection").textContent =
        "Previous passage is absent in this version";
    }
    documentView = {
      mode: m.mode,
      zoom: m.zoom,
      fit: m.fit,
      passage: m.passage,
    };
    $("documentMode").value = m.mode;
    $("zoomLabel").textContent = Math.round(m.zoom * 100) + "%";
    view();
  }
  if (m.type === "document-position") {
    documentView.passage = m.passage;
    anchorRect = m.rect;
    if (m.anchor && sameAnchor(m.anchor, selection)) placeComment();
    view();
  }
  if (m.type === "dismiss-selection") {
    $("quick").hidden = true;
    candidate = null;
  }
  if (m.type === "selection" && visible) {
    candidate = m.anchor;
    const existing = notes().find((n) => sameAnchor(n.anchor, candidate));
    const r = m.rect;
    $("quick").style.left =
      Math.max(10, Math.min(innerWidth - 200, r.x + r.width / 2)) + "px";
    $("quick").style.top =
      Math.max(85, Math.min(innerHeight - 80, r.y + r.height + 8)) + "px";
    $("quick").hidden = false;
    $("quick").textContent = existing ? "Open comment" : "Comment on selection";
  }
  if (m.type === "open-thread") {
    const n = notes().find((n) => n.id === m.id);
    if (n) openComment(n.anchor, n).catch(error);
  }
  if (m.type === "position") {
    slideElements = m.elements;
    if (m.slide !== slide) {
      $("quick").hidden = true;
      candidate = null;
      if (
        !$("composer").hidden &&
        selection.kind !== "story" &&
        !m.elements?.includes(selection.element)
      )
        closeComment().catch(error);
    }
    slide = m.slide;
    $("position").textContent = `${m.slide + 1} / ${m.total}`;
    view();
  }
  if (m.type === "ready") {
    send("overlay", { visible, annotations: notes() });
    if (documentKind) send("document-view", documentView);
    const cached = commentToRestore;
    commentToRestore = null;
    const draft = cached?.draft_id ? story.drafts[cached.draft_id] : null;
    const note = notes().find(n => n.id === cached?.active_annotation);
    if (cached?.composer_open && cached.anchor &&
        (!cached.draft_id || (draft?.revision_id === revision && sameAnchor(draft.anchor, cached.anchor))) &&
        (!cached.active_annotation || (note && sameAnchor(note.anchor, cached.anchor)))) {
      send("reveal", {anchor: cached.anchor});
      openComment(cached.anchor, note).catch(error);
    }
  }
});
$("quick").onpointerdown = (e) => e.preventDefault();
$("quick").onclick = () =>
  openComment(
    candidate,
    notes().find((n) => sameAnchor(n.anchor, candidate)),
  ).catch(error);
$("overall").onclick = () => openComment({ kind: "story" }).catch(error);
$("close").onclick = () => closeComment().catch(error);
$("comment").oninput = () => {
  typing++;
  clearTimeout(saveTimer);
  $("saved").textContent = "Unsaved";
  saveTimer = setTimeout(() => saveDraft().catch(error), 250);
};
$("send").onclick = async () => {
  if (restoring || !retainedView) {
    error(Error("Review context is updating; your text remains unsubmitted."));
    return;
  }
  const text = $("comment").value;
  if (!text.trim()) return;
  $("send").disabled = true;
  clearTimeout(saveTimer);
  // Capture all mutable target/payload state before any await. An uncertain
  // acknowledgement retains this exact intent, even if the user types elsewhere.
  const target = {story_id: story.id, revision_id: revision, text,
    anchor: structuredClone(selection)};
  const edit = typing, targetDraft = draftId, targetScope = scope;
  const pending = contextState.pending?.comment;
  if (pending && JSON.stringify(pending.payload) !== JSON.stringify(target)) {
    $("send").disabled = false;
    error(Error("A previous submission has an unknown acknowledgement. Retry its original revision and text before submitting changed intent."));
    return;
  }
  submission = pending || {payload: target, request_id: requestId()};
  const intent = structuredClone(submission);
  try {
    await saveDraft();
    contextState.pending = {...contextState.pending, comment: intent};
    await persistView();
    const result = await api("add-comment", {
      ...intent.payload, request_id: intent.request_id,
    });
    if (scope !== targetScope) return;
    delete contextState.pending.comment;
    await persistView();
    if (revision !== target.revision_id || draftId !== targetDraft || typing !== edit) return;
    active = result.annotation_id;
    submission = null;
    $("comment").value = "";
    await saveDraft();
    story = await api("get-story");
    update();
    $("outcome").textContent =
      result.status === "awaiting_authority"
        ? "Saved · waiting for model authority"
        : result.status.replaceAll("_", " ");
  } catch (e) {
    if (e.definite && scope === targetScope) {
      delete contextState.pending?.comment;
      submission = null;
      await persistView().catch(error);
    }
    error(e);
  } finally {
    $("send").disabled = false;
  }
};
$("agent").onclick = () => {
  const a = notes().filter((n) => n.author === "agent");
  if (!a.length) return;
  const n = a[++agentIndex % a.length];
  send("reveal", { anchor: n.anchor });
  openComment(n.anchor, n).catch(error);
};
$("overlay").onclick = async () => {
  visible = !visible;
  document.body.classList.toggle("review-hidden", !visible);
  $("overlay").textContent = visible ? "Hide review" : "Show review";
  $("documentOverlay").textContent = $("overlay").textContent;
  if (!visible) {
    await saveDraft();
    $("composer").hidden = true;
    $("quick").hidden = true;
  }
  send("overlay", { visible, annotations: notes() });
  view();
};
$("previous").onclick = () => send("navigate", { delta: -1 });
$("next").onclick = () => send("navigate", { delta: 1 });
$("more").onclick = () => {
  $("details").hidden = !$("details").hidden;
  view();
};
$("closeDetails").onclick = () => {
  $("details").hidden = true;
  view();
};
$("available").onclick = () => choose($("available").dataset.revision).catch(error);
$("versions").onchange = (e) => choose(e.target.value).catch(error);
$("exportFormat").onchange = () => {
  view();
  $("exportLimit").textContent =
    $("exportFormat").value === "docx"
      ? "Editable Word. Page breaks may differ; inspect in Word before delivery."
      : $("exportFormat").value === "pdf"
        ? "Letter PDF. Browser page breaks are approximate; inspect the exported PDF."
        : $("exportFormat").value === "zip"
          ? "Extract the ZIP and open index.html. Keep its assets folder alongside it."
          : "Single HTML with embedded images. Video requires ZIP. Images are not resized.";
};
$("export").onclick = async () => {
  const exportFormat = $("exportFormat").value;
  const exportTitle = story.title;
  $("export").disabled = true;
  $("export").textContent = "Exporting…";
  try {
    const url = URL.createObjectURL(await transport.binary("download", {
      story_id: story.id, revision_id: revision, format: exportFormat,
    }));
    const a = document.createElement("a");
    a.href = url;
    a.download = exportTitle.replace(/[^a-z0-9 -]/gi, "") + "." + exportFormat;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  } catch (e) {
    error(e);
  } finally {
    $("export").disabled = false;
    $("export").textContent = "Export this version";
  }
};
async function openWorkspace(initial, acceptedAdoption = adoption) {
  if (acceptedAdoption !== adoption) return;
  restoring = true;
  viewConflict = false;
  scope++;
  loadRequest++;
  clearTimeout(viewTimer);
  clearTimeout(saveTimer);
  revision = null; draftId = null; active = null; commentToRestore = null; selection = {kind: "story"};
  documentView = {mode: "continuous", zoom: 1, fit: false};
  $("composer").hidden = true;
  $("quick").hidden = true;
  for (const dialog of document.querySelectorAll("dialog[open]")) dialog.close();
  window.dispatchEvent(new Event("stories-workspace"));
  bridge = initial.bridge;
  documentBridge = initial.documentBridge;
  story = initial.story;
  const workspaceScope = scope;
  const incomingView = await transport.api("get-review-view", {story_id: story.id});
  if (scope !== workspaceScope || acceptedAdoption !== adoption) return;
  retainedView = incomingView;
  contextState = readContext(retainedView);
  $("title").textContent = story.title;
  if (contextState.document_view) documentView = contextState.document_view;
  const id = story.revisions.some((r) => r.id === retainedView.revision_id)
    ? retainedView.revision_id
    : initial.revision_id || story.selected_revision;
  restoring = true;
  if (id) await loadRevision(id, retainedView.revision_id === id ? retainedView.slide - 1 : 0);
  if (scope !== workspaceScope || acceptedAdoption !== adoption) return;
  $("details").hidden = !(contextState.details_open ?? (retainedView.panel_open && retainedView.sections.length > 0));
  visible = contextState.review_visible !== false;
  document.body.classList.toggle("review-hidden", !visible);
  $("overlay").textContent = $("documentOverlay").textContent = visible ? "Hide review" : "Show review";
  if ([...$("exportFormat").options].some(o => o.value === retainedView.export_format && !o.hidden))
    $("exportFormat").value = retainedView.export_format;
  restoring = false;
  if (!id) $("connection").textContent = "Waiting for first artifact";
  window.dispatchEvent(new Event("stories-ready"));
}
async function boot() {
  await openWorkspace(await transport.bootstrap());
  setInterval(async () => {
    if (polling) return;
    polling = true;
    const pollingScope = scope;
    try {
      const targetScope = scope;
      const refreshed = await api("get-story");
      if (scope !== targetScope) return;
      story = refreshed;
      if (!revision && story.latest_revision)
        await loadRevision(story.latest_revision);
      else update();
      if (!viewBusy && !viewConflict && $("saved").textContent !== "Unsaved" && $("saved").textContent !== "Saving…") {
        const external = await api("get-review-view");
        if (scope === targetScope && !viewBusy && external.version > retainedView.version) {
          restoring = true;
          retainedView = external;
          contextState = readContext(external);
          if (contextState.document_view) documentView = contextState.document_view;
          if (external.revision_id && external.revision_id !== revision)
            await loadRevision(external.revision_id, external.slide - 1);
          else if (external.slide - 1 !== slide) send("navigate", {delta: external.slide - 1 - slide});
          if (!sameAnchor(selection, external.anchor)) {
            if (!$("composer").hidden) await saveDraft();
            $("composer").hidden = true;
            draftId = null;
            active = null;
            selection = structuredClone(external.anchor);
            send("reveal", {anchor: selection});
          }
          $("details").hidden = !(contextState.details_open ?? (external.panel_open && external.sections.length > 0));
          if (external.panel_open && !contextState.details_open) {
            send("reveal", {anchor: external.anchor});
            await openComment(external.anchor);
          }
          visible = contextState.review_visible !== false;
          document.body.classList.toggle("review-hidden", !visible);
          send("overlay", {visible, annotations: notes()});
          if (documentKind) send("document-view", documentView);
          if ([...$("exportFormat").options].some(o => o.value === external.export_format && !o.hidden))
            $("exportFormat").value = external.export_format;
          restoring = false;
          window.dispatchEvent(new CustomEvent("stories-external-view", {detail: external}));
        }
      }
      $("connection").textContent = "Connected";
    } catch {
      $("connection").textContent = "Disconnected · unsaved typing remains in this open view";
    } finally {
      polling = false;
      if (scope === pollingScope) restoring = false;
    }
  }, 1500);
}
window.addEventListener("stories-target", async event => {
  const request = ++adoption;
  try {
    await saveDraft();
    await viewQueue;
    if (request !== adoption) return;
    const next = await transport.api("get-story", {story_id: event.detail.story_id});
    if (request !== adoption) return;
    await openWorkspace({story: next, revision_id: event.detail.revision_id, bridge, documentBridge}, request);
  } catch (e) { error(e); }
});
function placeComment() {
  if (!documentKind || $("composer").hidden) return;
  const box = $("composer"),
    r = anchorRect;
  if (selection.kind !== "story" && r && !r.visible) {
    closeComment().catch(error);
    return;
  }
  const width = box.offsetWidth,
    height = box.offsetHeight;
  // Use existing whitespace only. The document iframe and its width never change.
  let left = innerWidth - width - 18;
  if (r && innerWidth - r.paperRight > width + 28) left = r.paperRight + 14;
  else if (r && r.paperLeft > width + 28) left = r.paperLeft - width - 14;
  box.style.left = Math.max(12, Math.min(innerWidth - width - 12, left)) + "px";
  box.style.right = "auto";
  box.style.bottom = "auto";
  box.style.top =
    Math.max(70, Math.min(innerHeight - height - 18, r?.y || 110)) + "px";
}
new ResizeObserver(placeComment).observe($("composer"));
let toolbarTimer,
  suppressReveal = false;
const tools = $("documentTools"),
  panel = $("viewTools");
function revealToolbar() {
  if (suppressReveal) return;
  clearTimeout(toolbarTimer);
  panel.hidden = false;
  $("revealTools").setAttribute("aria-expanded", "true");
}
function hideToolbar() {
  panel.hidden = true;
  $("revealTools").setAttribute("aria-expanded", "false");
}
function scheduleHide() {
  clearTimeout(toolbarTimer);
  toolbarTimer = setTimeout(() => {
    if (!tools.matches(":hover") && !tools.contains(document.activeElement))
      hideToolbar();
  }, 650);
}
tools.onpointerenter = revealToolbar;
tools.onpointerleave = () => {
  suppressReveal = false;
  scheduleHide();
};
tools.onfocusin = revealToolbar;
tools.onfocusout = scheduleHide;
$("revealTools").onclick = () => {
  suppressReveal = false;
  revealToolbar();
};
$("hideTools").onclick = () => {
  suppressReveal = true;
  hideToolbar();
  $("revealTools").focus({ preventScroll: true });
};
document.addEventListener("pointerdown", (e) => {
  if (!e.target.closest("#quick")) {
    $("quick").hidden = true;
    candidate = null;
    send("dismiss-selection");
  }
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    $("quick").hidden = true;
    candidate = null;
    send("dismiss-selection");
  }
  if (e.key === "Escape" && !panel.hidden) {
    suppressReveal = true;
    hideToolbar();
    $("revealTools").focus({ preventScroll: true });
  }
});
$("documentMode").onchange = (e) =>
  send("document-view", { mode: e.target.value });
$("zoomOut").onclick = () =>
  send("document-view", { zoom: Math.max(0.35, documentView.zoom - 0.1) });
$("zoomIn").onclick = () =>
  send("document-view", { zoom: Math.min(2, documentView.zoom + 0.1) });
$("fitWidth").onclick = () => send("document-view", { fit: true });
$("documentOverall").onclick = () =>
  openComment({ kind: "story" }).catch(error);
$("documentOverlay").onclick = () => $("overlay").click();
$("documentDetails").onclick = () => {
  $("details").hidden = !$("details").hidden;
  view();
};
function nextComment(delta) {
  const all = notes();
  if (!all.length) return;
  commentIndex = (commentIndex + delta + all.length) % all.length;
  const n = all[commentIndex];
  send("reveal", { anchor: n.anchor });
  openComment(n.anchor, n).catch(error);
  update();
}
$("previousComment").onclick = () => nextComment(-1);
$("nextComment").onclick = () => nextComment(1);
boot().catch(error);

$("acceptRevision").onclick = async () => {
  const target = revision;
  try {
    await retainedMutation("accept-revision", {revision_id: target});
    story = await api("get-story", {});
    update();
  } catch (e) { error(e); }
};

window.StoriesReview = {
  api, error, mutation: retainedMutation, story: () => story, focus: id => loadRevision(id, 0),
  context: () => contextState,
  retain: async patch => { contextState = {...contextState, ...patch}; await persistView(); },
  save: async () => { if (!$("composer").hidden) await saveDraft(); },
  refresh: async () => { story = await api("get-story"); update(); },
  media: async (revision_id, asset_id) => {
    return transport.binary("media", {story_id: story.id, revision_id, asset_id});
  }
};
