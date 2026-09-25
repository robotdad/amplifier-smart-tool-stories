// Every asynchronous continuation belongs to one dialog opening and exact target.
(() => {
  let session = null, generation = 0, audioKey = null, players = new Map();
  const current = s => session === s && s.generation === generation && story?.id === s.story_id && revision === s.revision_id;
  const retained = s => contextState.narration?.[s.revision_id] || {};
  const fields = () => [...$('speechNotes').querySelectorAll('textarea')];
  const text = () => JSON.stringify(fields().map(e => e.value));
  const report = (s, id, value) => { if (current(s)) $(id).textContent = value; };
  const call = (s, name, args = {}) => api(name, {story_id: s.story_id, ...args});
  async function checkedReference(s, id, field) {
    const message = 'Retained narration reference ' + field + ' does not match this story, revision and kind. Reconcile the saved context before using it.';
    if (typeof id !== 'string' || !id) throw Error(message);
    let record;
    try {
      record = await call(s, field === 'script_id' ? 'get-narration-script' : 'get-operation',
        field === 'script_id' ? {script_id: id} : {operation_id: id});
    } catch (_) { throw Error(message); }
    if (record.id !== id || record.story_id !== s.story_id || record.revision_id !== s.revision_id ||
        (field !== 'script_id' && record.kind !== (field === 'operation' ? 'narration' : 'prepare_narration')))
      throw Error(message);
    return record;
  }
  function releaseAudio() {
    for (const {player, url} of players.values()) { player.pause(); URL.revokeObjectURL(url); }
    players.clear(); audioKey = null; $('speechAudio').replaceChildren();
  }
  function close() {
    generation++; session = null;
    $('speechAudio').querySelectorAll('audio').forEach(a => a.pause());
  }
  window.addEventListener('stories-workspace', () => { close(); releaseAudio(); });
  // Escape's cancel event is synchronous with the old opening. A queued close
  // event can arrive after a rapid reopen and must not invalidate that new one.
  $('narrationDialog').addEventListener('cancel', close);
  $('narrationClose').onclick = () => { close(); $('narrationDialog').close(); };
  async function saveDraft(s) {
    if (!current(s) || !s.ready) return;
    contextState.narration = {...contextState.narration, [s.revision_id]: {
      ...retained(s), notes: JSON.parse(text()), script_id: s.scriptId,
      guidance: $('scriptGuidance').value, duration: $('scriptDuration').value,
    }};
    await persistView();
  }
  function controls(s) {
    if (!current(s)) return;
    $('scriptPrepare').disabled = !s.ready || s.panel || Boolean(s.writingOperation) || s.preparing;
    $('scriptSave').disabled = !s.ready || s.panel || s.saving;
    $('scriptVersions').disabled = !s.ready || s.panel || Boolean(s.writingOperation);
    $('scriptCancel').disabled = !s.writingOperation;
    $('speechGenerate').disabled = !s.ready || Boolean(s.operation) || s.generating;
    $('speechGenerateExport').disabled = $('speechGenerate').disabled || s.panel;
    $('speechCancel').disabled = !s.operation;
    $('speechApply').disabled = !s.ready || s.applying;
    $('speechDelivery').disabled = $('speechPause').disabled = s.panel;
    const n = s.records.find(n => n.id === $('speechVersions').value);
    $('speechExport').disabled = s.panel || s.exporting || !n || n.state !== 'succeeded';
  }
  function availability(s) {
    if (!current(s) || !s.configuration) return;
    const p = s.configuration.providers.find(p => p.provider === $('speechProvider').value);
    $('speechAvailability').textContent = (p.credential_present ? 'API key present; speech access has not been tested.' : 'Missing API key: ' + p.credential_env.join(' or ')) + (!s.configuration.model_access ? ' This viewer has no provider-use authority.' : '');
  }
  const settings = () => ({provider: $('speechProvider').value, model: $('speechModel').value, voice: $('speechVoice').value, instructions: $('speechInstructions').value});
  function validateSettings(payload) {
    // Shared form feedback precedes either transport and creates no pending intent.
    // Count Unicode code points, like the Python domain/schema, not UTF-16 units.
    if (!['openai', 'gemini'].includes(payload.provider))
      throw Error('Choose openai or gemini for speech; chat sign-in is not a speech API key.');
    if ([payload.model, payload.voice].some(value => !value.trim() || [...value].length > 200))
      throw Error('Model and voice must be nonempty strings up to 200 characters.');
    if ([...payload.instructions].length > 2000)
      throw Error('Delivery instructions must be at most 2000 characters.');
  }
  async function apply(s, payload = settings()) {
    if (!current(s)) return;
    validateSettings(payload);
    await retainedMutation('configure-narration', {story_id: s.story_id, ...payload});
  }
  function scriptInfo(s, script) {
    report(s, 'scriptDetails', script ? `${script.throughline} · Rough estimate ${script.estimated_seconds} seconds, not measured audio. ${script.review.method === 'model_review' ? 'Model reviewed; not human approval.' : 'Not reviewed.'} ${script.limitations.join(' ')}` : '');
  }
  function loadScript(s, script) {
    if (!current(s) || !script) return;
    s.scriptId = script.id;
    script.slides.forEach((row, i) => { fields()[i].value = row.text; });
    $('scriptVersions').value = script.id; scriptInfo(s, script);
    saveDraft(s).catch(e => report(s, 'scriptStatus', e.message));
  }
  async function refreshScripts(s, selected, autoLoad = false) {
    const request = ++s.scriptsRequest;
    const result = await call(s, 'list-narration-scripts', {revision_id: s.revision_id});
    if (!current(s) || request !== s.scriptsRequest) return;
    s.scripts = result.scripts;
    const empty = document.createElement('option'); empty.value = ''; empty.textContent = 'Current text / speaker notes';
    $('scriptVersions').replaceChildren(empty);
    s.scripts.forEach((script, i) => {
      const o = document.createElement('option'); o.value = script.id;
      o.textContent = `Version ${i + 1} · ${script.origin === 'model' ? 'Prepared' : 'Edited'} · ~${script.estimated_seconds}s`;
      $('scriptVersions').append(o);
    });
    $('scriptVersions').value = selected || s.scriptId || '';
    scriptInfo(s, s.scripts.find(script => script.id === s.scriptId));
    if (autoLoad && !s.scriptId && !retained(s).notes && s.scripts.length) loadScript(s, s.scripts.at(-1));
  }
  async function audio(s) {
    const request = ++s.audioRequest;
    const n = s.records.find(n => n.id === $('speechVersions').value);
    const key = n ? [s.story_id, s.revision_id, n.id].join(':') : null;
    if (key !== audioKey) { releaseAudio(); audioKey = key; }
    controls(s);
    if (!n) return;
    let label = $('speechAudio').querySelector('[data-narration-status]');
    if (!label) { label = document.createElement('p'); label.dataset.narrationStatus = ''; $('speechAudio').append(label); }
    label.textContent = `${n.settings.provider} · ${n.settings.model} · ${n.settings.voice} · ${n.state}`;
    // Stable clip nodes survive completion, metadata refresh and same-target reopen.
    // Only missing immutable clips are fetched; an older load cannot attach a node.
    for (const clip of n.clips) {
      const clipKey = clip.panel_id || String(clip.slide);
      if (players.has(clipKey)) continue;
      const r = await call(s, 'get-narration-audio', {narration_id: n.id, ...(n.source === 'storyboard_panels' ? {panel_id: clip.panel_id} : {slide: clip.slide})});
      if (!current(s) || request !== s.audioRequest || key !== audioKey || $('speechVersions').value !== n.id) return;
      if (players.has(clipKey)) continue;
      const bytes = Uint8Array.from(atob(r.data_base64), c => c.charCodeAt(0));
      const url = URL.createObjectURL(new Blob([bytes], {type: 'audio/wav'}));
      const position = clip.position || clip.slide;
      const p = document.createElement('p');
      p.textContent = `${n.source === 'storyboard_panels' ? 'Panel' : 'Slide'} ${position} · ${clip.duration_seconds.toFixed(1)} seconds · AI-generated voice: ${n.notes[position - 1]}`;
      const player = document.createElement('audio'); player.controls = true; player.src = url; player.preload = 'none';
      players.set(clipKey, {player, url}); $('speechAudio').append(p, player);
    }
  }
  async function refresh(s, selected) {
    const request = ++s.recordsRequest;
    const r = await call(s, 'list-narrations', {revision_id: s.revision_id});
    if (!current(s) || request !== s.recordsRequest) return;
    s.records = r.narrations;
    const keep = selected || $('speechVersions').value;
    $('speechVersions').replaceChildren();
    for (const n of s.records) {
      const o = document.createElement('option'); o.value = n.id;
      o.textContent = `${n.id.slice(-8)} · ${n.state} · ${n.clips.length}/${n.notes.length} ${s.panel ? 'panels' : 'slides'}`;
      $('speechVersions').append(o);
    }
    if (s.records.some(n => n.id === keep)) $('speechVersions').value = keep;
    else if (s.records.length) $('speechVersions').value = s.records.at(-1).id;
    const running = s.records.find(n => ['queued', 'running'].includes(n.state));
    if (running && !s.operation) s.operation = running.operation_id;
    await audio(s);
  }
  $('narrationOpen').onclick = async () => {
    const s = {story_id: story.id, revision_id: revision, generation: ++generation,
      ready: false, records: [], scripts: [], scriptId: null, operation: null, writingOperation: null,
      audioRequest: 0, recordsRequest: 0, scriptsRequest: 0, pollBusy: false, writePollBusy: false};
    session = s;
    if (audioKey && !audioKey.startsWith(s.story_id + ':' + s.revision_id + ':')) releaseAudio();
    $('narrationRevision').textContent = 'Revision ' + s.revision_id;
    controls(s);
    try {
      const rev = await call(s, 'get-revision', {revision_id: s.revision_id});
      if (!current(s)) return;
      if (rev.kind === 'document') { report(s, 'speechStatus', 'Narration requires a presentation or retained storyboard panel text.'); return; }
      s.panel = rev.kind === 'storyboard';
      const config = await call(s, 'narration-settings');
      if (!current(s)) return;
      s.configuration = config;
      const c = config.effective || {provider: 'openai', ...config.providers[0], instructions: ''};
      $('speechProvider').value = c.provider; $('speechModel').value = c.model; $('speechVoice').value = c.voice; $('speechInstructions').value = c.instructions || ''; availability(s);
      const r = s.panel ? {notes: rev.storyboard.panels.map(p => p.narration)} : await call(s, 'get-speaker-notes', {revision_id: s.revision_id});
      if (!current(s)) return;
      const saved = retained(s), notes = s.panel ? r.notes : saved.notes || r.notes;
      const referenceErrors = [];
      for (const [field, local, status] of [
        ['script_id', 'scriptId', 'scriptStatus'],
        ['operation', 'operation', 'speechStatus'],
        ['writing_operation', 'writingOperation', 'scriptStatus'],
      ]) {
        if (saved[field] == null) continue;
        try {
          await checkedReference(s, saved[field], field);
          if (!current(s)) return;
          s[local] = saved[field];
        } catch (e) { referenceErrors.push([status, e.message]); }
      }
      if (!current(s)) return;
      s.writingDraft = saved.writing_draft || null;
      $('scriptGuidance').value = saved.guidance || ''; $('scriptDuration').value = saved.duration || '';
      $('speechNotes').replaceChildren();
      notes.forEach((value, i) => {
        const label = document.createElement('label'), field = document.createElement('textarea');
        label.textContent = `${s.panel ? 'Panel' : 'Slide'} ${i + 1}`;
        field.rows = 3; field.value = value; field.readOnly = s.panel;
        field.setAttribute('aria-label', `Narration for ${s.panel ? 'panel' : 'slide'} ${i + 1}`);
        field.oninput = () => { if (!current(s)) return; saveDraft(s).catch(e => report(s, 'scriptStatus', e.message)); report(s, 'scriptStatus', 'Unsaved script edits; previous script review does not apply to this text.'); };
        label.append(field); $('speechNotes').append(label);
      });
      s.ready = true; controls(s);
      report(s, 'scriptStatus', ''); scriptInfo(s, null);
      report(s, 'speechStatus', '');
      referenceErrors.forEach(([status, message]) => report(s, status, message));
      report(s, 'speechExportStatus', s.panel ? 'Storyboard narration speaks exact retained panel text. Video production and script adaptation require a presentation.' : '');
      $('narrationDialog').showModal();
      await refresh(s);
      if (!current(s)) return;
      if (!s.panel) await refreshScripts(s, null, true);
      if (!current(s)) return;
      const writing = await call(s, 'provider-settings');
      report(s, 'scriptWritingProvider', 'Writing provider: ' + (writing.effective?.provider || 'configured provider') + '. Preparing a script sends the deck, notes and retained sources to this provider; it does not generate audio.');
    } catch (e) { if (current(s)) error(e); }
  };
  async function saveScript(s) {
    const captured = text(), old = s.scripts.find(script => script.id === s.scriptId);
    if (old && JSON.stringify(old.slides.map(row => row.text)) === captured) return;
    const r = await retainedMutation('save-narration-script', {story_id: s.story_id, revision_id: s.revision_id, notes: JSON.parse(captured), base_script_id: s.scriptId});
    if (!current(s)) return;
    if (text() !== captured) throw Error('Script retained; newer typing was preserved. Select the saved version explicitly.');
    s.scriptId = r.script_id;
    await saveDraft(s);
    if (!current(s)) return;
    await refreshScripts(s, s.scriptId);
  }
  $('scriptVersions').onchange = () => {
    const s = session; if (!s?.ready) return;
    const script = s.scripts.find(item => item.id === $('scriptVersions').value);
    if (script) loadScript(s, script);
    else { s.scriptId = null; scriptInfo(s, null); saveDraft(s).catch(e => report(s, 'scriptStatus', e.message)); }
  };
  $('scriptSave').onclick = async () => {
    const s = session; if (!s?.ready) return;
    s.saving = true; controls(s);
    try { await saveScript(s); report(s, 'scriptStatus', 'Script saved. No model or speech request.'); }
    catch (e) { report(s, 'scriptStatus', e.message); }
    finally { s.saving = false; controls(s); }
  };
  $('scriptPrepare').onclick = async () => {
    const s = session; if (!s?.ready) return;
    s.preparing = true; s.writingDraft = text(); controls(s);
    const payload = {story_id: s.story_id, revision_id: s.revision_id, base_script_id: s.scriptId,
      draft_notes: JSON.parse(s.writingDraft), guidance: $('scriptGuidance').value,
      target_seconds: $('scriptDuration').value ? Number($('scriptDuration').value) : null,
      grant: {max_operations: 1, timeout_seconds: 180, max_output_tokens: 12000}};
    try {
      await saveDraft(s); if (!current(s)) return;
      const r = await retainedMutation('prepare-narration', payload);
      if (!current(s)) return; // receipt already retained against the original target
      s.writingOperation = r.operation_id; report(s, 'scriptStatus', 'Writing queued. No speech synthesis.');
    } catch (e) { report(s, 'scriptStatus', e.message); }
    finally { s.preparing = false; controls(s); }
  };
  $('speechProvider').onchange = () => {
    const s = session; if (!s?.configuration) return;
    const p = s.configuration.providers.find(p => p.provider === $('speechProvider').value);
    $('speechModel').value = p.model; $('speechVoice').value = p.voice; availability(s);
  };
  $('speechApply').onclick = async () => {
    const s = session; if (!s?.ready) return;
    s.applying = true; controls(s);
    try { await apply(s); report(s, 'speechStatus', 'Narration settings saved. No speech generated.'); }
    catch (e) { report(s, 'speechStatus', e.message); }
    finally { s.applying = false; controls(s); }
  };
  $('speechVersions').onchange = () => { const s = session; if (s?.ready) audio(s).catch(e => report(s, 'speechStatus', e.message)); };
  async function generate(andExport) {
    const s = session; if (!s?.ready) return;
    const captured = text(), retry = $('speechRetry').checked, config = settings();
    s.generating = true; controls(s);
    try {
      validateSettings(config);
      await saveDraft(s); if (!current(s)) return;
      if (!s.panel) await saveScript(s);
      if (!current(s)) return;
      await apply(s, config);
      if (!current(s)) return;
      if (text() !== captured) throw Error('Narration text changed; no speech submitted.');
      const r = await retainedMutation('generate-narration', {story_id: s.story_id, revision_id: s.revision_id,
        ...(s.panel ? {source: 'storyboard_panels'} : {script_id: s.scriptId}),
        grant: {max_requests: 12, max_characters: 48000, timeout_seconds: 300}, retry_uncertain: retry});
      if (!current(s)) return; // including A -> B -> A: an opening is not a revision ID
      s.operation = r.operation_id; s.exportAfter = andExport;
      report(s, 'speechStatus', 'Narration queued.'); await refresh(s, r.narration_id);
    } catch (e) { report(s, 'speechStatus', e.message); }
    finally { s.generating = false; controls(s); }
  }
  $('speechGenerate').onclick = () => generate(false);
  $('speechGenerateExport').onclick = () => generate(true);
  async function cancel(writing) {
    const s = session; if (!s?.ready) return;
    const field = writing ? 'writingOperation' : 'operation', id = s[field]; if (!id) return;
    // Invalidate any observation that began before this cancellation intent.
    s.pollEpoch = (s.pollEpoch || 0) + 1;
    try {
      await checkedReference(s, id, writing ? 'writing_operation' : 'operation');
      if (!current(s) || s[field] !== id) return;
      await call(s, 'cancel-operation', {operation_id: id});
      if (current(s) && s[field] === id) report(s, writing ? 'scriptStatus' : 'speechStatus', 'Cancellation requested; retained results are preserved.');
    } catch (e) { report(s, writing ? 'scriptStatus' : 'speechStatus', e.message); }
  }
  $('scriptCancel').onclick = () => cancel(true);
  $('speechCancel').onclick = () => cancel(false);
  async function poll(writing) {
    const s = session; if (!s?.ready) return;
    const field = writing ? 'writingOperation' : 'operation', savedField = writing ? 'writing_operation' : 'operation';
    const busy = writing ? 'writePollBusy' : 'pollBusy', statusId = writing ? 'scriptStatus' : 'speechStatus';
    // Late receipts may arrive after reopening A -> B -> A. Validate them before
    // adopting a local operation or enabling Cancel, just like persisted context.
    const id = s[field] || retained(s)[savedField], epoch = s.pollEpoch || 0;
    if (!id || s[busy]) return;
    s[busy] = true;
    try {
      const o = await checkedReference(s, id, savedField);
      if (!current(s) || (s[field] && s[field] !== id) || epoch !== (s.pollEpoch || 0)) return;
      s[field] = id;
      controls(s);
      const unit = s.panel ? 'panels' : 'slides', progress = o.progress;
      report(s, statusId, o.state + (progress ? ` · ${progress['completed_' + unit]}/${progress['total_' + unit]} ${unit}` : '') + (o.error ? ' · ' + o.error.message : ''));
      if (['queued', 'running'].includes(o.state)) return;
      s[field] = null;
      if (retained(s)[savedField] === id) {
        contextState.narration[s.revision_id] = {...retained(s), [savedField]: null};
        await persistView();
      }
      if (!current(s)) return;
      controls(s);
      if (writing) {
        await refreshScripts(s);
        if (!current(s)) return;
        if (o.state === 'succeeded') {
          const script = s.scripts.find(item => item.id === o.result.script_id);
          if ((s.writingDraft || retained(s).writing_draft) === text()) { loadScript(s, script); report(s, statusId, 'Script ready to review, edit, or synthesize. No audio generated.'); }
          else report(s, statusId, 'New script retained in the version list. Your newer text edits were preserved.');
        }
      } else {
        await refresh(s, o.result?.narration_id);
        if (!current(s)) return;
        if (s.exportAfter && o.state === 'succeeded') $('speechExport').click();
        s.exportAfter = false;
      }
    } catch (e) { report(s, statusId, e.message); }
    finally { s[busy] = false; }
  }
  setInterval(() => poll(true), 1500);
  setInterval(() => poll(false), 1500);
  $('speechExport').onclick = async () => {
    const s = session; if (!s?.ready) return;
    const n = s.records.find(n => n.id === $('speechVersions').value); if (!n) return;
    const delivery = $('speechDelivery').value, pause_seconds = Number($('speechPause').value);
    s.exporting = true; controls(s); report(s, 'speechExportStatus', 'Encoding from retained audio…');
    try {
      const blob = await transport.binary('narrated-download', {story_id: s.story_id, revision_id: s.revision_id, narration_id: n.id, delivery, pause_seconds});
      if (!current(s)) return;
      const url = URL.createObjectURL(blob), a = document.createElement('a'); a.href = url; a.download = 'narrated-story.' + (delivery === 'separate' ? 'zip' : 'mp4'); a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      report(s, 'speechExportStatus', 'Export complete. No new speech synthesis.');
    } catch (e) { report(s, 'speechExportStatus', e.message); }
    finally { s.exporting = false; controls(s); }
  };
})();
