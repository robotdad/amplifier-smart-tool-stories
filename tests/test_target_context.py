"""Exact-target regressions for retained narration and revision comment recovery.

Synthetic queued operations never run. Only legacy fixtures bypass admission, to
represent stores written by the previous release. Both real UI transports run.
"""

import asyncio
import copy
import importlib.resources
import json
import subprocess
import threading
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
from mcp import Client
from playwright.async_api import async_playwright, expect

from amplifier_smart_tool_stories import Stories, StoriesError
from amplifier_smart_tool_stories.dashboard import Dashboard
from amplifier_smart_tool_stories.mcp import create_server

ROOT = Path(__file__).parents[1]
HTML = '<html><body><section class="slide"><h1>Original</h1><p>Exact passage</p></section></body></html>'


def seed(api):
    a = api.create_story("A", HTML, "a")
    a2 = api.revise_media(a["story_id"], a["revision_id"], [], "a2", html=HTML.replace("Original", "New"))
    b = api.create_story("B", HTML, "b")
    api.configure_narration("openai", "gpt-4o-mini-tts", "marin", "config")
    return a, a2, b


def reference(api, owner, field):
    sid, rid = owner["story_id"], owner["revision_id"]
    if field == "script_id":
        return api.save_narration_script(sid, rid, ["Retained script"], "script-" + rid)["script_id"]
    if field == "writing_operation":
        return api.prepare_narration(sid, rid, {}, "writing-" + rid)["operation_id"]
    return api.generate_narration(sid, rid, {}, "speech-" + rid, notes=["Retained speech"])["operation_id"]


@pytest.mark.parametrize("field", ["operation", "writing_operation", "script_id"])
@pytest.mark.parametrize("bad", ["foreign", "revision", "kind", "missing", "malformed"])
def test_reference_admission_is_exact_and_atomic(tmp_path, field, bad):
    api = Stories(tmp_path, model_env=False, execution="queued")
    a, a2, b = seed(api)
    owner = b if bad == "foreign" else a2 if bad == "revision" else a
    actual_field = (
        ("writing_operation" if field != "writing_operation" else "operation") if bad == "kind" else field
    )
    ref = reference(api, owner, actual_field)
    if bad == "missing":
        ref = "missing-reference"
    if bad == "malformed":
        ref = {"id": ref}
    before = api.get_review_view(a["story_id"])
    with pytest.raises(StoriesError):
        api.update_review_view(
            a["story_id"],
            before["version"],
            "bad",
            native_context={"narration": {a["revision_id"]: {field: ref}}},
        )
    assert api.get_review_view(a["story_id"]) == before
    # Null references and genuine same-target references stay supported.
    valid = reference(api, a, field) if bad in {"foreign", "revision"} else None
    context = {"narration": {a["revision_id"]: {field: valid, "notes": ["Unsent work"]}}}
    assert (
        api.update_review_view(a["story_id"], before["version"], "valid", native_context=context)[
            "native_context"
        ]
        == context
    )


@asynccontextmanager
async def workspace(api, ids, surface, observe=None):
    host = subprocess.check_output(
        [
            str(ROOT / "mcp-app/node_modules/.bin/esbuild"),
            str(ROOT / "mcp-app/test-host.js"),
            "--bundle",
            "--format=iife",
            "--log-level=error",
        ],
        text=True,
    )
    html = (
        importlib.resources.files("amplifier_smart_tool_stories")
        .joinpath("resources/mcp_app.html")
        .read_text()
    )
    server = Dashboard(api, ids["story_id"])
    worker = threading.Thread(target=server.serve)
    worker.start()
    calls, errors = [], []
    try:
        async with Client(create_server(api)) as client, async_playwright() as pw:
            browser = await pw.chromium.launch()
            try:
                page = await browser.new_page(viewport={"width": 1200, "height": 950})
                page.on("pageerror", lambda e: errors.append(str(e)))
                if surface == "http":

                    async def route(r):
                        calls.append(
                            {"name": r.request.url.rsplit("/", 1)[-1], "arguments": r.request.post_data_json}
                        )
                        if observe:
                            observe(calls[-1])
                        await r.continue_()

                    await page.route("**/api/**", route)
                    await page.goto(f"http://127.0.0.1:{server.server.server_port}/#{server.token}")
                    ui, frame = page, page.main_frame
                else:

                    async def tool(args):
                        calls.append(
                            {
                                "name": args["name"].removeprefix("stories_").replace("_", "-"),
                                "arguments": args.get("arguments", {}),
                            }
                        )
                        if observe:
                            observe(calls[-1])
                        return (await client.call_tool(args["name"], args.get("arguments", {}))).model_dump(
                            by_alias=True, exclude_none=True
                        )

                    async def read(args):
                        return (await client.read_resource(args["uri"])).model_dump(
                            by_alias=True, exclude_none=True
                        )

                    await page.expose_function("hostCall", tool)
                    await page.expose_function("hostRead", read)
                    await page.route(
                        "https://target.test/**",
                        lambda r: r.fulfill(body="<body></body>", content_type="text/html"),
                    )
                    await page.goto("https://target.test/")
                    await page.add_script_tag(content=host)
                    initial = await client.call_tool("stories_get_story", {"story_id": ids["story_id"]})
                    await page.evaluate(
                        "([h,r])=>mountStories(h,r)",
                        [html, initial.model_dump(by_alias=True, exclude_none=True)],
                    )
                    ui = page.frame_locator("#app")
                    frame = next(f for f in page.frames if f.parent_frame == page.main_frame)
                await expect(ui.locator("#versions")).to_have_value(ids["revision_id"])
                await expect(ui.frame_locator("#material").locator("h1").first).to_be_attached()
                yield page, ui, frame, calls
                assert not errors
            finally:
                await browser.close()
    finally:
        server.server.shutdown()
        worker.join(5)
        assert not worker.is_alive()


@pytest.mark.parametrize("surface", ["http", "mcp"])
@pytest.mark.parametrize("field", ["operation", "writing_operation", "script_id"])
@pytest.mark.parametrize("bad", ["foreign", "revision", "kind", "malformed"])
def test_legacy_reference_never_controls_wrong_work(tmp_path, surface, field, bad):
    api = Stories(tmp_path, model_env=False, execution="queued")
    a, a2, b = seed(api)
    owner = b if bad in {"foreign", "malformed"} else a2 if bad == "revision" else a
    actual_field = (
        ("writing_operation" if field != "writing_operation" else "operation") if bad == "kind" else field
    )
    ref = reference(api, owner, actual_field)
    before = (
        api.get_operation(ref)
        if actual_field != "script_id"
        else api.get_narration_script(owner["story_id"], ref)
    )
    view = api.update_review_view(a["story_id"], 0, "focus", revision_id=a["revision_id"])
    # Simulate an existing pre-fix store; public admission is tested separately.
    with api.store.transaction() as db:
        record = api.store.get(db, "stories", a["story_id"])
        view["native_context"] = {
            "narration": {
                a["revision_id"]: {
                    field: ref if bad != "malformed" else {"id": ref},
                    "notes": ["Keep my unsent narration"],
                }
            }
        }
        record["review_views"]["shared"] = view
        api.store.put(db, "stories", record)

    async def run():
        async with workspace(api, a, surface) as (_, ui, frame, calls):
            await ui.locator("#more").click()
            await ui.locator("#narrationOpen").click()
            await expect(ui.locator("#narrationDialog")).to_be_visible()
            status = "#speechStatus" if field == "operation" else "#scriptStatus"
            await expect(ui.locator(status)).to_contain_text("Retained narration reference")
            button = "speechCancel" if field == "operation" else "scriptCancel"
            await expect(ui.locator("#" + button)).to_be_disabled()
            # Even a direct handler invocation must not dispatch cancellation.
            await frame.evaluate("id => document.getElementById(id).onclick()", button)
            assert not [c for c in calls if c["name"] == "cancel-operation"]
            assert "queued" not in await ui.locator(status).inner_text()
            await expect(ui.locator("#speechNotes textarea")).to_have_value("Keep my unsent narration")

    asyncio.run(run())
    after = (
        api.get_operation(ref)
        if actual_field != "script_id"
        else api.get_narration_script(owner["story_id"], ref)
    )
    assert after == before
    assert (
        api.get_review_view(a["story_id"])["native_context"]["narration"]
        == view["native_context"]["narration"]
    )


@pytest.mark.parametrize("surface", ["http", "mcp"])
@pytest.mark.parametrize("field", ["operation", "writing_operation"])
def test_valid_reference_still_polls_cancels_and_global_mcp_is_unchanged(tmp_path, surface, field):
    api = Stories(tmp_path, model_env=False, execution="queued")
    a, _, b = seed(api)
    ref = reference(api, a, field)
    foreign = reference(api, b, field)
    api.update_review_view(
        a["story_id"],
        0,
        "focus",
        revision_id=a["revision_id"],
        native_context={"narration": {a["revision_id"]: {field: ref}}},
    )

    async def run():
        async with workspace(api, a, surface) as (_, ui, frame, _calls):
            # Both transports expose the same definite admission rejection. This
            # tests the adapter, not just direct library validation.
            rejected = await frame.evaluate(
                """async ([sid, rid, field, id]) => {
                const view = await StoriesReview.api('get-review-view');
                try {
                    await StoriesReview.api('update-review-view', {
                        expected_version: view.version, request_id: 'bad-transport',
                        native_context: {narration: {[rid]: {[field]: id}}}
                    });
                    return null;
                } catch(e) { return {message: e.message, definite: e.definite}; }
            }""",
                [a["story_id"], a["revision_id"], field, foreign],
            )
            assert rejected["definite"] and "exact story, revision and kind" in rejected["message"]
            await ui.locator("#more").click()
            await ui.locator("#narrationOpen").click()
            status, button = (
                ("#speechStatus", "#speechCancel")
                if field == "operation"
                else ("#scriptStatus", "#scriptCancel")
            )
            await expect(ui.locator(status)).to_contain_text("queued")
            await expect(ui.locator(button)).to_be_enabled()
            await ui.locator(button).click()
            await expect(ui.locator(status)).to_contain_text("Cancellation requested")
            assert api.get_operation(ref)["state"] == "cancelled"
            assert api.get_operation(foreign)["state"] == "queued"
        # Deliberate store-wide MCP capability remains available; no tenant auth
        # restrictions were added to fix the contextual UI error.
        async with Client(create_server(api)) as client:
            result = await client.call_tool("stories_get_operation", {"operation_id": foreign})
            assert not result.is_error
            result = await client.call_tool("stories_cancel_operation", {"operation_id": foreign})
            assert not result.is_error
            assert api.get_operation(foreign)["state"] == "cancelled"

    asyncio.run(run())


def document(tag, removed=False):
    return {
        "title": tag + " field guide",
        "subtitle": "Retained review",
        "blocks": [
            {
                "id": key,
                "kind": "paragraph",
                "text": tag + " passage " + key + ". Review retained material.",
                "items": [],
                "rows": [],
                "evidence_ids": [],
            }
            for key in (["p4", "replacement"] if removed else ["p4", "p12"])
        ],
    }


@pytest.mark.parametrize("surface", ["http", "mcp"])
@pytest.mark.parametrize("reject_first", [False, True])
def test_first_draft_commit_precedes_view_reference(tmp_path, surface, reject_first):
    api = Stories(tmp_path, model_env=False)
    ids = api.create_document("Ordering", document("OLD"), "create")
    sid, rid = ids["story_id"], ids["revision_id"]
    for element in ("d-p4", "d-p12"):
        api.add_comment(
            sid, rid, element + " thread", element, {"kind": "element", "element": element}, author="agent"
        )
    premature = []

    def references(call):
        context = call["arguments"].get("native_context", {})
        return [
            context.get("draft_id"),
            *(c.get("draft_id") for c in context.get("revision_comments", {}).values()),
        ]

    def observe(call):
        if call["name"] == "update-review-view":
            committed = api.get_story(sid)["drafts"]
            premature.extend(d for d in references(call) if d and d not in committed)

    async def run():
        async with workspace(api, ids, surface, observe) as (_, ui, frame, calls):
            await ui.locator("#revealTools").click()
            await ui.locator("#nextComment").click()
            await expect(ui.locator("#target")).to_contain_text("OLD passage p4")
            await ui.locator("#comment").fill("Retain earlier draft")
            await expect(ui.locator("#saved")).to_have_text("Draft saved")
            await frame.evaluate("() => StoriesReview.save()")
            await frame.evaluate(
                """reject => {
                const original = StoriesTransport.api.bind(StoriesTransport);
                window.firstDraft = {};
                const gate = new Promise(resolve => firstDraft.release = resolve);
                StoriesTransport.api = async (name, args) => {
                    if (name === 'save-draft' && args.anchor?.element === 'd-p12' && !firstDraft.started) {
                        firstDraft.started = true;
                        firstDraft.id = args.draft_id;
                        await gate;
                        // Exercise a real server rejection, not a fake successful
                        // save or fabricated error response.
                        if (reject) args = {...args, expected_version: 999};
                    }
                    return original(name, args);
                };
            }""",
                reject_first,
            )
            await ui.locator("#nextComment").click()
            await frame.wait_for_function("() => firstDraft.started")
            await expect(ui.locator("#target")).to_contain_text("OLD passage p12")
            draft_id = await frame.evaluate("firstDraft.id")
            try:
                # Real preview layout/position events plus an explicit view save
                # while the FIRST save cannot reach either backend yet.
                await ui.locator("#zoomIn").click()
                await frame.evaluate("""() => {
                    window.referenceSave = StoriesReview.retain({}).then(
                        () => ({saved:true}), e => ({error:e.message}));
                }""")
                # An unrelated actual read completes while the draft is blocked.
                await frame.evaluate("() => StoriesReview.api('get-story')")
                assert draft_id not in api.get_story(sid)["drafts"]

                def referencing():
                    return [
                        c for c in calls if c["name"] == "update-review-view" and draft_id in references(c)
                    ]

                assert not referencing(), referencing()
                await expect(ui.locator("#error")).to_be_hidden()
                if not reject_first:
                    await ui.locator("#comment").fill("New typing during first save")
                await frame.evaluate("firstDraft.release()")
                if reject_first:
                    await expect(ui.locator("#error")).to_contain_text("Draft changed")
                    await expect(ui.locator("#saved")).to_have_text("Not saved to Stories")
                    assert draft_id not in api.get_story(sid)["drafts"]
                    assert not referencing(), referencing()
                    outcome = await frame.evaluate("referenceSave")
                    assert "Draft changed" in outcome["error"]
                    await expect(ui.locator("#composer")).to_be_visible()
                    await expect(ui.locator("#target")).to_contain_text("OLD passage p12")
                    # Explicit retry is allowed and cannot deadlock behind a
                    # view waiting on the failed first-save dependency.
                    await ui.locator("#comment").fill("Explicit retry text")
                await frame.evaluate("() => StoriesReview.save()")
                text = "Explicit retry text" if reject_first else "New typing during first save"
                await expect(ui.locator("#comment")).to_have_value(text)
                if not reject_first:
                    await expect(ui.locator("#error")).to_be_hidden()
                    assert await frame.evaluate("referenceSave") == {"saved": True}
                stored = api.get_story(sid)
                assert stored["drafts"][draft_id]["text"] == text
                assert stored["drafts"][draft_id]["anchor"]["element"] == "d-p12"
                assert any(d["text"] == "Retain earlier draft" for d in stored["drafts"].values())
                assert api.get_review_view(sid)["native_context"]["draft_id"] == draft_id
                assert referencing()
                assert not premature, premature
            finally:
                await frame.evaluate("firstDraft.release()")

    asyncio.run(run())


@pytest.mark.parametrize("surface", ["http", "mcp"])
@pytest.mark.parametrize("anchor_kind", ["text", "removed"])
def test_new_revision_and_back_restore_only_exact_comment(tmp_path, surface, anchor_kind):
    api = Stories(tmp_path, model_env=False)
    a = api.create_document("Review", document("OLD"), "create")
    sid, rid = a["story_id"], a["revision_id"]
    anchor = (
        {"kind": "element", "element": "d-p12"}
        if anchor_kind == "removed"
        else {"kind": "text", "element": "d-p4", "start": 0, "end": 14, "quote": "OLD passage p4"}
    )
    note = api.add_comment(sid, rid, "Original thread", "comment", anchor, author="agent")
    anchor = next(n["anchor"] for n in api.get_story(sid)["annotations"] if n["id"] == note["annotation_id"])
    new_document = document("NEW", removed=True)

    async def run():
        async with workspace(api, a, surface) as (_, ui, frame, _calls):
            await ui.locator("#revealTools").click()
            await ui.locator("#nextComment").click()
            await expect(ui.locator("#composer")).to_be_visible()
            await ui.locator("#comment").fill("NEWER_UNSENT_PASSAGE_TEXT")
            await frame.evaluate("() => StoriesReview.save()")
            before = copy.deepcopy(api.get_story(sid))
            draft_id = next(
                k for k, d in before["drafts"].items() if d["text"] == "NEWER_UNSENT_PASSAGE_TEXT"
            )
            # Deterministic injected intelligence creates a real background revision.
            from amplifier_smart_tool_stories.documents import render_document

            api.intelligence = lambda *_: {
                "action": "revise",
                "message": "Fixture revision",
                "document": new_document,
                "html": render_document(new_document),
                "evidence": [],
                "changes": {
                    "summary": "Changed and removed targets",
                    "material_changes": [],
                    "omissions": [],
                    "assumptions": [],
                },
                "calculations": [],
            }
            api.grant_feedback(sid, {"max_operations": 1}, "grant")
            result = api.add_comment(sid, rid, "Create new revision", "background")
            new = api.run_operation(result["operation_id"])["result"]["revision_id"]
            await expect(ui.locator("#available")).to_be_visible()
            await expect(ui.locator("#comment")).to_have_value("NEWER_UNSENT_PASSAGE_TEXT")
            await frame.evaluate("""() => {
                window.targetReady = false;
                window.addEventListener('message', e => {
                    if (e.source === document.querySelector('#material').contentWindow && e.data?.type === 'ready')
                        window.targetReady = true;
                });
            }""")
            await ui.locator("#available").click()
            await expect(ui.frame_locator("#material").locator("h1")).to_have_text("NEW field guide")
            await frame.wait_for_function("() => window.targetReady")
            await expect(ui.locator("#composer")).to_be_hidden()
            await expect(ui.locator("#error")).to_be_hidden()
            await frame.evaluate("() => StoriesReview.retain({})")
            assert api.get_review_view(sid)["revision_id"] == new
            assert api.get_story(sid)["drafts"][draft_id]["text"] == "NEWER_UNSENT_PASSAGE_TEXT"
            await ui.locator("#revealTools").click()
            await ui.locator("#documentDetails").click()
            await ui.locator("#versions").select_option(rid)
            await expect(ui.frame_locator("#material").locator("h1")).to_have_text("OLD field guide")
            await expect(ui.locator("#composer")).to_be_visible()
            await expect(ui.locator("#comment")).to_have_value("NEWER_UNSENT_PASSAGE_TEXT")
            await expect(ui.locator("#composer")).to_have_attribute(
                "data-anchor", json.dumps(anchor, separators=(",", ":"))
            )
            await expect(ui.locator("#messages")).to_contain_text("Original thread")
            await expect(ui.locator("#error")).to_be_hidden()
            retained = api.get_story(sid)
            original = next(n for n in retained["annotations"] if n["id"] == note["annotation_id"])
            assert original["revision_id"] == rid and original["anchor"] == anchor
            assert not [d for d in retained["drafts"].values() if d["revision_id"] == new]
            await frame.evaluate("() => StoriesReview.save()")
        # Recovery is durable across a fresh browser context and the OTHER
        # transport, not merely an in-memory per-revision cache.
        async with workspace(api, a, "mcp" if surface == "http" else "http") as (_, ui, _frame, _calls):
            await expect(ui.locator("#composer")).to_be_visible()
            await expect(ui.locator("#comment")).to_have_value("NEWER_UNSENT_PASSAGE_TEXT")
            await expect(ui.locator("#composer")).to_have_attribute(
                "data-anchor", json.dumps(anchor, separators=(",", ":"))
            )
            await expect(ui.locator("#messages")).to_contain_text("Original thread")
            await expect(ui.locator("#error")).to_be_hidden()

    asyncio.run(run())
