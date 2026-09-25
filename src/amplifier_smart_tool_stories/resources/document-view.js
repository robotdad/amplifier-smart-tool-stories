// Document layout is entirely inside the isolated material frame. No credentials.
(() => {
  const root = document.querySelector(".stories-document");
  if (!root) return;
  // Storyboards are responsive articles, not fixed-width document paper. Capture
  // their authored cap before the preview overrides max-width.
  const storyboard = root.classList.contains("stories-storyboard");
  const storyboardWidth = parseFloat(getComputedStyle(root).maxWidth);
  const blocks = [...root.children];
  let mode = "continuous",
    zoom = 1,
    fit = false,
    tracked = null;
  const emit = (type, data = {}) =>
    parent.postMessage({ channel: __CHANNEL__, type, ...data }, "*");
  const style = document.createElement("style");
  style.textContent = `html{background:#eeefed!important}body{padding:64px 20px 100px!important;min-width:0}.stories-document{max-width:none!important;transform-origin:top left;margin:0!important;position:relative}.stories-document.paginated{padding:0!important;background:transparent!important}.document-page{background:white;width:816px;min-height:1056px;height:auto;padding:64px;margin-bottom:28px;display:flow-root}.document-page>*:first-child{margin-top:0!important}.stories-document>h2,.document-page>h2{break-after:avoid}`;
  document.head.append(style);
  const target = (id) =>
    [root, ...root.querySelectorAll("[data-stories-id]")].find(
      (n) => n.dataset.storiesId === id,
    );
  function reading() {
    const el =
      blocks.find((n) => n.getBoundingClientRect().bottom > 85) ||
      blocks.at(-1);
    const r = el.getBoundingClientRect();
    return {
      id: el.dataset.storiesId,
      fraction: Math.max(0, Math.min(1, (85 - r.top) / r.height)),
    };
  }
  function restore(a) {
    const n = target(a?.id);
    if (!n) return;
    const r = n.getBoundingClientRect();
    scrollBy(0, r.top + r.height * a.fraction - 85);
  }
  const availableWidth = () => document.documentElement.clientWidth - 40;
  const paperWidth = () =>
    storyboard && mode === "continuous"
      ? Math.min(storyboardWidth, availableWidth())
      : 816;
  function metrics() {
    const width = paperWidth();
    const w = width * zoom;
    // Explicit width prevents body min-width/zoom from feeding back into an
    // auto-sized article. Position and scroll extent use that same actual paper.
    root.style.width = width + "px";
    root.style.zoom = zoom;
    root.style.left = Math.max(0, (availableWidth() - w) / 2) / zoom + "px";
    document.body.style.minWidth = Math.max(document.documentElement.clientWidth, w + 40) + "px";
  }
  function layout(next = {}) {
    const passage = next.passage || reading();
    mode = next.mode || mode;
    if (next.zoom !== undefined) {
      zoom = next.zoom;
      fit = false;
    }
    if (next.fit !== undefined) fit = next.fit;
    if (fit) zoom = Math.min(2, Math.max(0.35, availableWidth() / paperWidth()));
    zoom = Math.min(2, Math.max(0.35, zoom));
    root.replaceChildren(...blocks);
    root.classList.toggle("paginated", mode === "paginated");
    if (mode === "paginated") {
      let page;
      const addPage = () => {
        page = document.createElement("div");
        page.className = "document-page";
        root.append(page);
      };
      addPage();
      for (let i = 0; i < blocks.length; i++) {
        const b = blocks[i];
        page.append(b);
        // Keep a heading with its next block when it fits; move the same nodes, never rewrite text.
        const tail = b.offsetTop + b.offsetHeight - page.offsetTop;
        if (tail > 992 && page.children.length > 1) {
          const previous = b.previousElementSibling;
          const heading = previous?.tagName === "H2" ? previous : null;
          addPage();
          if (heading) page.append(heading);
          page.append(b);
        }
      }
    }
    metrics();
    restore(passage);
    if (tracked?.kind === "text" && CSS.highlights && window.storiesTextRange) {
      const range = window.storiesTextRange(tracked);
      if (range) CSS.highlights.set("selectionTarget", new Highlight(range));
    }
    publish();
    emit("document-layout", {
      mode,
      zoom,
      fit,
      passage: reading(),
      missingPassage: !!passage?.id && !target(passage.id),
      pages: root.querySelectorAll(".document-page").length,
    });
  }
  function rect(anchor) {
    const el = target(anchor?.element);
    if (!el) return null;
    let r = el.getBoundingClientRect();
    // A precise selected range is preferable to the containing paragraph.
    if (anchor.kind === "text" && window.storiesTextRange) {
      const range = window.storiesTextRange(anchor);
      if (range) r = range.getBoundingClientRect();
    }
    const paper = (
      el.closest(".document-page") || root
    ).getBoundingClientRect();
    return {
      x: r.x,
      y: r.y,
      width: r.width,
      height: r.height,
      paperLeft: paper.left,
      paperRight: paper.right,
      visible: r.bottom > 65 && r.top < innerHeight - 30,
    };
  }
  function publish() {
    emit("document-position", {
      passage: reading(),
      anchor: tracked,
      rect: rect(tracked),
    });
  }
  let pending = false;
  addEventListener(
    "scroll",
    () => {
      if (!pending) {
        pending = true;
        requestAnimationFrame(() => {
          pending = false;
          publish();
        });
      }
    },
    { passive: true },
  );
  addEventListener("resize", () => layout());
  addEventListener("message", (e) => {
    if (e.source !== parent || e.data?.channel !== __CHANNEL__) return;
    const m = e.data;
    if (m.type === "document-view") layout(m);
    if (m.type === "track-anchor") {
      tracked = m.anchor;
      publish();
    }
  });
  layout();
})();
