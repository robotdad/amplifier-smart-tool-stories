"use strict";
// Comparison is observation. Only the explicit choice button changes direction.
(() => {
  const review = window.StoriesReview;
  const dialog = document.createElement("dialog");
  dialog.id = "comparison";
  dialog.setAttribute("aria-label", "Compare directions or versions");
  dialog.innerHTML = `<div class="comparison-top"><div><h2>Compare possibilities</h2>
    <p>Inspect either version, then choose a direction when you are ready.</p></div>
    <button id="closeComparison">Back to review</button></div>
    <div id="comparisonChoices"></div><p id="comparisonStatus" role="status"></p>
    <div id="comparisonCards"></div>`;
  document.body.append(dialog);
  let urls = [], generation = 0;
  function imageData(blob) {
    return new Promise((resolve, reject) => {
      const reader = new FileReader();
      reader.onload = () => resolve(reader.result);
      reader.onerror = () => reject(Error("Unable to read retained comparison image."));
      reader.readAsDataURL(blob);
    });
  }
  function release() { urls.forEach(URL.revokeObjectURL); urls = []; }
  dialog.addEventListener("close", () => {
    generation++; release();
    review.retain({comparison_open: false}).catch(review.error);
  });
  document.getElementById("closeComparison").onclick = () => dialog.close();
  async function show(ids) {
    const run = ++generation;
    document.getElementById("comparisonStatus").textContent = "Loading retained versions…";
    const result = await review.api("get-comparison", ids ? {revision_ids: ids} : {});
    if (run !== generation) return;
    release();
    const cards = document.getElementById("comparisonCards");
    cards.replaceChildren();
    for (const item of result.items) {
      const card = document.createElement("section");
      card.className = "comparison-card";
      const heading = document.createElement("h3");
      heading.textContent = item.name;
      const rationale = document.createElement("p");
      rationale.textContent = [item.approach, item.tradeoff,
        item.superseded ? "Earlier brief · superseded" : "",
        item.direction_id && item.direction_id === result.selected_direction ? "Chosen direction" : ""].filter(Boolean).join(" · ");
      const actions = document.createElement("div");
      const focus = document.createElement("button");
      focus.textContent = "Focus & comment";
      focus.onclick = async () => {
        try { await review.focus(item.revision_id); dialog.close(); }
        catch (e) { review.error(e); }
      };
      actions.append(focus);
      if (item.direction_id) {
        const choose = document.createElement("button");
        choose.textContent = "Continue with this direction";
        choose.disabled = item.superseded;
        choose.onclick = async () => {
          try {
            await review.mutation("select-direction", {revision_id: item.revision_id});
            await review.refresh();
            await review.focus(item.revision_id);
            dialog.close();
          } catch (e) { review.error(e); }
        };
        actions.append(choose);
      }
      const frame = document.createElement("iframe");
      frame.title = item.name + " comparison preview";
      frame.setAttribute("sandbox", "");
      const parsed = new DOMParser().parseFromString(item.preview.html, "text/html");
      const security = document.createElement("meta");
      security.httpEquiv = "Content-Security-Policy";
      security.content = "default-src 'none'; style-src 'unsafe-inline'; img-src blob: data:; media-src blob:; script-src 'none'; connect-src 'none'; form-action 'none'; base-uri 'none'";
      parsed.head.prepend(security);
      const styles = parsed.createElement("style");
      styles.textContent = "html,body{margin:0;overflow:auto!important} .slide{display:block!important;position:relative!important;transform:none!important;opacity:1!important;visibility:visible!important;width:100%!important;height:auto!important;min-height:70vh!important;margin-bottom:24px} .storyboard-panel{padding:22px} h2{font-size:24px} nav{display:none!important}";
      parsed.head.append(styles);
      for (const asset of item.preview.assets || []) {
        const nodes = [...parsed.querySelectorAll("img,video,source,track")];
        if (!nodes.some(n => ["src", "poster"].some(a => n.getAttribute(a) === "asset:" + asset.id))) continue;
        const blob = await review.media(item.revision_id, asset.id);
        if (run !== generation) return;
        // The script-free sandbox has an opaque origin: parent-created blob URLs
        // cannot reliably load there. Embed authenticated image bytes instead.
        const isImage = asset.mime_type.startsWith("image/");
        const url = isImage ? await imageData(blob) : URL.createObjectURL(blob);
        if (run !== generation) {
          if (!isImage) URL.revokeObjectURL(url);
          return;
        }
        if (!isImage) urls.push(url);
        for (const n of nodes) for (const attr of ["src", "poster"])
          if (n.getAttribute(attr) === "asset:" + asset.id) n.setAttribute(attr, url);
      }
      frame.srcdoc = parsed.documentElement.outerHTML;
      card.append(heading, rationale, actions, frame); cards.append(card);
    }
    document.getElementById("comparisonStatus").textContent = "Independent previews · focus does not select or generate. Presentation layout may adapt to the narrower preview.";
  }
  async function open(suppliedIds) {
    try {
      await review.save();
      await review.refresh();
      const story = review.story();
      if (!story.revisions.length) throw Error("No completed versions to compare yet.");
      const choices = document.getElementById("comparisonChoices");
      choices.replaceChildren();
      const defaults = Array.isArray(suppliedIds) ? suppliedIds : review.context().comparison_ids || (story.directions?.length ? story.directions.map(d => d.latest_revision).slice(-2)
        : story.revisions.slice(-2).map(r => r.id));
      const selectors = [0, 1].map(index => {
        const label = document.createElement("label"); label.textContent = index ? "Right version " : "Left version ";
        const select = document.createElement("select");
        for (const [i, rev] of story.revisions.entries()) {
          const option = document.createElement("option"); option.value = rev.id;
          const direction = story.directions?.find(d => d.id === rev.direction_id);
          option.textContent = `${direction?.name || story.title} · version ${i + 1}`;
          select.append(option);
        }
        select.value = defaults[index] || defaults[0]; label.append(select); choices.append(label);
        return select;
      });
      for (const select of selectors) select.onchange = async () => {
        const ids = [...new Set(selectors.map(s => s.value))];
        try { await review.retain({comparison_ids: ids, comparison_open: true}); await show(ids); }
        catch (e) { review.error(e); }
      };
      if (!dialog.open) dialog.showModal();
      await review.retain({comparison_ids: selectors.map(s => s.value), comparison_open: true});
      await show([...new Set(selectors.map(s => s.value))]);
    } catch (e) {
      document.getElementById("comparisonStatus").textContent = e.message;
      review.error(e);
    }
  }
  document.getElementById("compare").onclick = open;
  document.getElementById("documentCompare").onclick = open;
  window.addEventListener("stories-ready", () => {
    const story = review.story();
    if (review.context().comparison_open) open();
    else if (story.explore && story.directions?.length > 1 && !story.selected_direction
        && !review.context().comparison_ids) open();
  });
  window.addEventListener("stories-external-view", event => {
    if (event.detail.comparison_revision && !dialog.open)
      open([event.detail.revision_id, event.detail.comparison_revision]);
    else if (!event.detail.comparison_revision && dialog.open) dialog.close();
  });
})();
