// Host-owned controls; provider credentials never enter this page.
(() => {
  const dialog = $("providerDialog");
  let settings,
    timer,
    busy = false;
  const names = {
    anthropic: "Anthropic",
    openai: "OpenAI",
    gemini: "Gemini",
    chatgpt: "ChatGPT",
    copilot: "GitHub Copilot",
  };
  const input = () => ({
    provider: $("providerChoice").value,
    model: $("providerModel").value.trim() || null,
  });
  function status() {
    const row = settings?.providers.find((p) => p.name === input().provider);
    if (!row) return;
    $("providerStatus").textContent =
      `${row.configured ? "Credentials available" : "Not signed in / configured"} · ${row.runtime_ready ? "Runtime ready" : "Runtime needs preparation"}`;
    $("providerSetup").textContent = row.setup;
    $("providerLogin").hidden = !["chatgpt", "copilot"].includes(row.name);
    $("providerPrepare").textContent = row.runtime_ready
      ? "Prepare runtime again"
      : "Prepare runtime";
    $("providerPrepare").title =
      "Downloads and installs provider runtime modules. No story is generated.";
    for (const id of [
      "providerDiscover",
      "providerTest",
      "providerLogin",
      "providerPrepare",
    ]) {
      $(id).disabled = busy || !settings.model_access;
    }
    $("providerApply").disabled = busy;
    $("providerChoice").disabled = busy;
    $("providerModel").disabled = busy;
    if (!settings.model_access)
      $("providerSetup").textContent +=
        " This viewer has no model access; reopen it with model_env enabled for setup and testing.";
    const effective = settings.effective;
    $("providerApplied").textContent =
      `Current: ${names[effective.provider]} · ${effective.model || "provider default"}`;
  }
  async function load(reset = false) {
    settings = await api("provider-settings");
    if (reset) {
      $("providerChoice").value = settings.effective.provider;
      $("providerModel").value = settings.effective.model || "";
      $("providerModels").replaceChildren();
    }
    status();
  }
  function failure(e) {
    $("providerResult").textContent = e.message;
  }
  async function poll() {
    clearTimeout(timer);
    try {
      const job = await api("provider-job");
      busy = ["running", "cancelling", "timing_out"].includes(job.status);
      const lines = [...(job.messages || [])];
      if (busy)
        lines.push(
          `${names[job.provider]}: ${job.kind === "login" ? "Waiting for sign-in…" : job.kind === "prepare" ? "Preparing runtime…" : job.kind === "models" ? "Discovering models…" : "Testing connection…"}`,
        );
      if (job.error) lines.push(`${names[job.provider]}: ${job.error.message}`, job.error.remedy || "");
      if (job.result) {
        const result = job.result;
        if (result.models) {
          lines.push(`${result.models.length} models found. ${result.notice}`);
          if (job.provider === input().provider) {
            $("providerModels").replaceChildren(
              ...result.models.map((m) => {
                const option = document.createElement("option");
                option.value = m.id;
                option.label = m.name;
                return option;
              }),
            );
          }
        } else if (job.kind === "test")
          lines.push(
            `Connected to ${names[job.provider]} · ${result.model || "provider default"}.`,
          );
        else if (job.kind === "prepare")
          lines.push(`${names[job.provider]} runtime is ready.`);
        else
          lines.push(
            result.notice ||
              "Sign-in finished. Prepare the runtime, then test the connection.",
          );
      }
      if (job.status !== "idle")
        $("providerResult").textContent = lines.filter(Boolean).join("\n");
      if (busy) {
        status();
        if (dialog.open) timer = setTimeout(poll, 1000);
      } else await load();
    } catch (e) {
      busy = false;
      failure(e);
      status();
    }
  }
  async function open() {
    dialog.showModal();
    try {
      await load(true);
      await poll();
    } catch (e) {
      failure(e);
    }
  }
  $("providerSettingsOpen").onclick = open;
  $("documentSettings").onclick = open;
  $("providerClose").onclick = () => dialog.close();
  dialog.addEventListener("close", () => clearTimeout(timer));
  $("providerChoice").onchange = () => {
    $("providerModel").value = "";
    $("providerModels").replaceChildren();
    $("providerResult").textContent = "";
    status();
  };
  $("providerApply").onclick = async () => {
    try {
      await api("configure-provider", input());
      await load();
      $("providerResult").textContent =
        "Applied to future work in this session. Existing operations keep their original provider.";
    } catch (e) {
      failure(e);
    }
  };
  async function action(kind) {
    busy = true;
    status();
    $("providerResult").textContent = "Starting…";
    try {
      await retainedMutation("start-provider-job", { kind, ...input() });
      await poll();
    } catch (e) {
      busy = false;
      status();
      failure(e);
    }
  }
  $("providerDiscover").onclick = () => action("models");
  $("providerTest").onclick = () => action("test");
  $("providerLogin").onclick = () => action("login");
  $("providerPrepare").onclick = () => action("prepare");
})();
