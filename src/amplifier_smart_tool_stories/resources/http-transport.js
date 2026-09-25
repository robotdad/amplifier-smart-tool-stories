"use strict";
// HTTP owns authentication and URLs; shared controllers own presentation.
window.StoriesTransport = (() => {
  let token = location.hash.slice(1);
  try {
    token ||= sessionStorage.getItem("stories-token");
    if (token) sessionStorage.setItem("stories-token", token);
  } catch {}
  if (location.hash) history.replaceState(null, "", location.pathname);
  async function response(name, data) {
    if (!token) throw Error("Open the private viewer URL returned by start-dashboard.");
    const r = await fetch("/api/" + name, {
      method: "POST",
      headers: {Authorization: "Bearer " + token, "Content-Type": "application/json"},
      body: JSON.stringify(data),
    });
    if (!r.ok) {
      const v = await r.json();
      throw Object.assign(Error(v.error?.message || v.error || "Request failed"), {definite: true, code: v.error?.code});
    }
    return r;
  }
  return {
    api: async (name, data = {}) => (await response(name, data)).json(),
    binary: async (name, data) => (await response(name, data)).blob(),
    bootstrap: async () => {
      const [initial, bridge, documentBridge] = await Promise.all([
        (await response("bootstrap", {})).json(),
        fetch("/bridge.js").then(r => r.text()),
        fetch("/document-view.js").then(r => r.text()),
      ]);
      return {...initial, bridge, documentBridge};
    },
    openLink: url => window.open(url, "_blank", "noopener,noreferrer"),
    context: () => {},
  };
})();