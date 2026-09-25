"""Paired native HTTP and real SDK/AppBridge review, without provider calls."""

import asyncio
import importlib.resources
import subprocess
import threading
from pathlib import Path

import pytest

pytest.importorskip("mcp")
pytest.importorskip("playwright")
from mcp import Client
from playwright.async_api import async_playwright, expect
from test_mcp import fixture

from amplifier_smart_tool_stories import Stories
from amplifier_smart_tool_stories.dashboard import Dashboard
from amplifier_smart_tool_stories.mcp import create_server

ROOT = Path(__file__).parents[1]


@pytest.mark.parametrize("surface", ["http", "mcp"])
def test_narration_settings_exact_feedback_and_acknowledgement(tmp_path, surface):
    """Real transports: shared form copy, server rejection, and lost committed ack."""
    api = Stories(tmp_path / "store")
    ids = api.create_story(
        "Settings", '<html><body><section class="slide"><p>Review</p></section></body></html>', "create"
    )
    host = subprocess.run(
        [
            str(ROOT / "mcp-app/node_modules/.bin/esbuild"),
            str(ROOT / "mcp-app/test-host.js"),
            "--bundle",
            "--format=iife",
            "--log-level=error",
        ],
        check=True,
        text=True,
        capture_output=True,
    ).stdout
    html = (
        importlib.resources.files("amplifier_smart_tool_stories")
        .joinpath("resources/mcp_app.html")
        .read_text()
    )

    async def run():
        server = Dashboard(api, ids["story_id"])
        worker = threading.Thread(target=server.serve)
        worker.start()
        attempts = []
        lose_ack = False
        try:
            async with Client(create_server(api)) as client, async_playwright() as pw:
                browser = await pw.chromium.launch()
                try:
                    page = await browser.new_page(viewport={"width": 1100, "height": 900})
                    errors = []
                    page.on("pageerror", lambda e: errors.append(str(e)))

                    async def http_call(route):
                        nonlocal lose_ack
                        attempts.append(route.request.post_data_json)
                        response = await route.fetch()
                        if lose_ack:
                            lose_ack = False
                            assert response.ok  # Mutation committed before the acknowledgement is lost.
                            await route.abort("failed")
                        else:
                            await route.fulfill(response=response)

                    async def tool(args):
                        nonlocal lose_ack
                        configuring = args["name"] == "stories_configure_narration"
                        if configuring:
                            attempts.append(args["arguments"])
                        result = (await client.call_tool(args["name"], args.get("arguments", {}))).model_dump(
                            by_alias=True, exclude_none=True
                        )
                        if configuring and lose_ack:
                            lose_ack = False
                            assert not result.get("isError")
                            raise RuntimeError("Acknowledgement lost after commit")
                        return result

                    async def read(args):
                        return (await client.read_resource(args["uri"])).model_dump(
                            by_alias=True, exclude_none=True
                        )

                    if surface == "http":
                        await page.route("**/api/configure-narration", http_call)

                        async def mount():
                            if page.url.startswith("http://127.0.0.1:"):
                                await page.reload()
                            else:
                                await page.goto(
                                    f"http://127.0.0.1:{server.server.server_port}/#{server.token}"
                                )
                            return page, page

                    else:
                        await page.expose_function("hostCall", tool)
                        await page.expose_function("hostRead", read)
                        await page.route(
                            "https://stories-host.test/**",
                            lambda route: route.fulfill(body="<body></body>", content_type="text/html"),
                        )
                        await page.goto("https://stories-host.test/")
                        await page.add_script_tag(content=host)

                        async def mount():
                            initial = await client.call_tool(
                                "stories_get_story", {"story_id": ids["story_id"]}
                            )
                            await page.evaluate(
                                "([html,result])=>mountStories(html,result)",
                                [html, initial.model_dump(by_alias=True, exclude_none=True)],
                            )
                            frame = next(f for f in page.frames if f.parent_frame == page.main_frame)
                            return page.frame_locator("#app"), frame

                    ui, frame = await mount()

                    async def open_settings():
                        await expect(ui.locator("#versions")).to_have_value(ids["revision_id"])
                        if not await ui.locator("#details").is_visible():
                            await ui.locator("#more").click()
                        await ui.locator("#narrationOpen").click()
                        await expect(ui.locator("#speechApply")).to_be_enabled()

                    def pending():
                        return api.get_review_view(ids["story_id"])["native_context"].get("pending", {})

                    await open_settings()
                    message = "Model and voice must be nonempty strings up to 200 characters."
                    for field, value, expected in [
                        ("speechVoice", "x" * 201, message),
                        ("speechVoice", "", message),
                        ("speechVoice", "   ", message),
                        ("speechModel", "x" * 201, message),
                        ("speechModel", "", message),
                        ("speechModel", "   ", message),
                        ("speechVoice", "\U0001f600" * 201, message),
                        (
                            "speechInstructions",
                            "x" * 2001,
                            "Delivery instructions must be at most 2000 characters.",
                        ),
                    ]:
                        await ui.locator("#speechModel").fill("gpt-4o-mini-tts")
                        await ui.locator("#speechVoice").fill("marin")
                        await ui.locator("#speechInstructions").fill("")
                        await ui.locator("#" + field).fill(value)
                        await ui.locator("#speechApply").click()
                        await expect(ui.locator("#speechStatus")).to_have_text(expected)
                        assert not pending() and not attempts
                        assert api.narration_settings()["effective"] is None
                    # Generate uses the same preflight before saving scripts or admitting speech.
                    await ui.locator("#speechGenerate").click()
                    await expect(ui.locator("#speechStatus")).to_have_text(
                        "Delivery instructions must be at most 2000 characters."
                    )
                    assert not attempts and not pending()
                    assert not api.list_narration_scripts(ids["story_id"], ids["revision_id"])["scripts"]
                    await page.screenshot(path=str(tmp_path / f"{surface}-validation.png"))

                    # Exact inclusive limits, including non-BMP characters, agree with Python.
                    await ui.locator("#speechModel").fill("\U0001f600" * 200)
                    await ui.locator("#speechVoice").fill("\U0001f600" * 200)
                    await ui.locator("#speechInstructions").fill("\U0001f600" * 2000)
                    await ui.locator("#speechApply").click()
                    saved = "Narration settings saved. No speech generated."
                    await expect(ui.locator("#speechApply")).to_be_enabled()
                    await expect(ui.locator("#speechStatus")).to_have_text(saved)
                    assert api.narration_settings()["effective"]["voice"] == "\U0001f600" * 200
                    assert not pending()

                    # Bypass only the form, not transport/server validation. MCP's actual SDK
                    # schema error must remain definite; HTTP's domain rejection must too.
                    rejection = await frame.evaluate(
                        """async () => {
                          try {
                            await StoriesReview.mutation('configure-narration',
                              {provider:'openai',model:'gpt-4o-mini-tts',voice:'x'.repeat(201),instructions:''});
                            return {unexpectedSuccess:true};
                          } catch (e) { return {message:e.message,definite:e.definite}; }
                        }"""
                    )
                    assert rejection["definite"] is True
                    assert ("validation error" if surface == "mcp" else "Model and voice") in rejection[
                        "message"
                    ]
                    assert not pending()
                    assert api.narration_settings()["effective"]["voice"] == "\U0001f600" * 200

                    await ui.locator("#speechModel").fill("gpt-4o-mini-tts")
                    await ui.locator("#speechVoice").fill("marin")
                    await ui.locator("#speechInstructions").fill("")
                    await ui.locator("#speechApply").click()
                    await expect(ui.locator("#speechApply")).to_be_enabled()
                    await expect(ui.locator("#speechStatus")).to_have_text(saved)
                    assert api.narration_settings()["effective"]["voice"] == "marin" and not pending()

                    # Commit real settings then discard their actual transport acknowledgement.
                    await ui.locator("#speechInstructions").fill("A retained delivery choice")
                    lose_ack = True
                    await ui.locator("#speechApply").click()
                    await expect(ui.locator("#speechStatus")).not_to_have_text(saved)
                    await expect(ui.locator("#speechApply")).to_be_enabled()
                    original = pending()["configure-narration"]
                    lost_attempt = attempts[-1]
                    assert (
                        api.narration_settings()["effective"]["instructions"] == "A retained delivery choice"
                    )
                    ui, frame = await mount()  # Durable unknown intent survives reload/iframe destruction.
                    await open_settings()
                    assert pending()["configure-narration"] == original
                    count = len(attempts)
                    await ui.locator("#speechVoice").fill("x" * 201)
                    await ui.locator("#speechApply").click()
                    await expect(ui.locator("#speechStatus")).to_have_text(message)
                    assert pending()["configure-narration"] == original and len(attempts) == count
                    await ui.locator("#speechVoice").fill("coral")
                    await ui.locator("#speechApply").click()
                    await expect(ui.locator("#speechStatus")).to_contain_text("unknown acknowledgement")
                    assert pending()["configure-narration"] == original and len(attempts) == count
                    await ui.locator("#speechVoice").fill("marin")
                    await ui.locator("#speechApply").click()
                    await expect(ui.locator("#speechStatus")).to_have_text(saved)
                    assert attempts[-1] == lost_attempt and len(attempts) == count + 1
                    assert not pending() and not errors
                    await page.screenshot(path=str(tmp_path / f"{surface}-recovered.png"))
                finally:
                    await browser.close()
        finally:
            server.server.shutdown()
            worker.join(5)

    asyncio.run(run())


def test_two_browser_transports_keep_stale_clock_skewed_typing(tmp_path):
    api = Stories(tmp_path)
    ids = api.create_story(
        "CAS review", '<html><body><section class="slide"><p>Review</p></section></body></html>', "create"
    )
    draft_id = "review-shared-" + ids["revision_id"] + '-["story",null,null,null]'
    api.save_draft(ids["story_id"], ids["revision_id"], draft_id, 1, "Original", expected_version=0)
    api.update_review_view(
        ids["story_id"],
        0,
        "view",
        native_context={
            "composer_open": True,
            "draft_id": draft_id,
            "document_view": {"mode": "continuous", "zoom": 1, "fit": False},
        },
    )
    host = subprocess.run(
        [
            str(ROOT / "mcp-app/node_modules/.bin/esbuild"),
            str(ROOT / "mcp-app/test-host.js"),
            "--bundle",
            "--format=iife",
            "--log-level=error",
        ],
        check=True,
        text=True,
        capture_output=True,
    ).stdout

    async def run():
        server = Dashboard(api, ids["story_id"])
        worker = threading.Thread(target=server.serve)
        worker.start()
        try:
            async with Client(create_server(api)) as client, async_playwright() as pw:
                browser = await pw.chromium.launch()
                stale = await browser.new_page()
                await stale.add_init_script("Date.now = () => 9000000000000")
                saves = []
                frozen_read = None

                async def tool(args):
                    if args["name"] == "stories_save_draft":
                        saves.append(args["arguments"])
                    result = (await client.call_tool(args["name"], args.get("arguments", {}))).model_dump(
                        by_alias=True, exclude_none=True
                    )
                    if frozen_read is not None and args["name"] == "stories_get_review_view":
                        result["structuredContent"]["result"] = frozen_read
                    return result

                async def read(args):
                    return (await client.read_resource(args["uri"])).model_dump(
                        by_alias=True, exclude_none=True
                    )

                await stale.expose_function("hostCall", tool)
                await stale.expose_function("hostRead", read)
                await stale.route(
                    "https://stories-host.test/**",
                    lambda route: route.fulfill(body="<body></body>", content_type="text/html"),
                )
                await stale.goto("https://stories-host.test/")
                await stale.add_script_tag(content=host)
                initial = await client.call_tool("stories_get_story", {"story_id": ids["story_id"]})
                html = (ROOT / "src/amplifier_smart_tool_stories/resources/mcp_app.html").read_text()
                await stale.evaluate(
                    "([html,result])=>mountStories(html,result)",
                    [html, initial.model_dump(by_alias=True, exclude_none=True)],
                )
                b = stale.frame_locator("#app")
                await expect(b.locator("#comment")).to_have_value("Original")
                await expect(b.locator("#saved")).to_have_text("Draft saved")
                app_frame = next(f for f in stale.frames if f.parent_frame == stale.main_frame)
                await app_frame.evaluate("window.StoriesReview.save()")
                frozen_read = api.get_review_view(ids["story_id"])
                native = await browser.new_page()
                await native.goto(f"http://127.0.0.1:{server.server.server_port}/#{server.token}")
                await expect(native.locator("#comment")).to_have_value("Original")
                await native.locator("#comment").fill("Acknowledged A")
                await expect(native.locator("#saved")).to_contain_text("Draft saved")
                a_version = api.get_story(ids["story_id"])["drafts"][draft_id]["version"]
                await b.locator("#comment").fill("Stale B must stay available")
                await expect(b.locator("#error")).to_contain_text("Draft changed in another view")
                await expect(b.locator("#comment")).to_have_value("Stale B must stay available")
                assert saves[-1]["expected_version"] < a_version
                assert saves[-1]["sequence"] >= 9000000000000
                assert api.get_story(ids["story_id"])["drafts"][draft_id]["text"] == "Acknowledged A"
                # Failed save must not dismiss the only remaining copy of B's typing.
                await b.locator("#close").click()
                await expect(b.locator("#composer")).to_be_visible()
                await expect(b.locator("#comment")).to_have_value("Stale B must stay available")
                await browser.close()
        finally:
            server.server.shutdown()
            worker.join(5)

    asyncio.run(run())


def test_shared_native_mcp_review_and_retained_recovery(tmp_path):
    node = ROOT / "mcp-app/node_modules"
    if not node.exists():
        pytest.skip("Run npm ci --prefix mcp-app for the SDK host fixture.")
    host = subprocess.run(
        [
            str(node / ".bin/esbuild"),
            str(ROOT / "mcp-app/test-host.js"),
            "--bundle",
            "--format=iife",
            "--log-level=error",
        ],
        check=True,
        text=True,
        capture_output=True,
    ).stdout

    async def run():
        ids = fixture.seed(tmp_path)
        api = Stories(tmp_path, execution="background")  # provider-disabled submissions never spend
        dashboard = Dashboard(api, ids["story_id"])
        worker = threading.Thread(target=dashboard.serve)
        worker.start()
        try:
            async with Client(create_server(api)) as client, async_playwright() as pw:
                browser = await pw.chromium.launch()
                native = await browser.new_page(viewport={"width": 1100, "height": 900})
                errors = []
                native.on("pageerror", lambda e: errors.append(str(e)))
                await native.goto(f"http://127.0.0.1:{dashboard.server.server_port}/#{dashboard.token}")
                await expect(native.locator("#versions")).to_have_value(ids["revision_id"])
                await expect(native.frame_locator("#material").locator("img").first).to_have_js_property(
                    "naturalWidth", 360
                )
                await native.locator("#revealTools").click()
                await native.locator("#documentMode").select_option("paginated")
                await native.locator("#zoomIn").click()
                await expect(native.locator("#zoomLabel")).to_have_text("110%")
                controls = await native.locator("button,input,select,textarea").evaluate_all(
                    "nodes=>nodes.map(n=>[n.id,n.tagName,n.type,n.textContent])"
                )
                await native.locator("#revealTools").click()
                await native.locator("#documentOverall").click()
                bounds = await native.locator("#material").bounding_box()
                await native.locator("#comment").fill("Carry this draft across transports")
                await expect(native.locator("#saved")).to_have_text("Draft saved")
                await native.evaluate("window.StoriesReview.save()")
                assert api.get_review_view(ids["story_id"])["native_context"]["draft_id"]
                assert await native.locator("#material").bounding_box() == bounds
                # Close without shared browser storage; the server's acknowledged draft/view is sufficient.
                await native.close()
                page = await browser.new_page(viewport={"width": 1100, "height": 900})
                page.on("pageerror", lambda e: errors.append(str(e)))
                await page.route(
                    "https://stories-host.test/**",
                    lambda route: route.fulfill(
                        body="<!doctype html><body></body>", content_type="text/html"
                    ),
                )
                await page.goto("https://stories-host.test/")
                entered, release = asyncio.Event(), asyncio.Event()
                delayed = False
                lose_ack = True
                attempts = []
                views = []
                calls = []

                async def tool(args):
                    nonlocal delayed, lose_ack
                    calls.append(args["name"])
                    if args["name"] == "stories_update_review_view":
                        views.append(args["arguments"])
                    if args["name"] == "stories_add_comment":
                        attempts.append(args["arguments"])
                        if not delayed:
                            delayed = True
                            entered.set()
                            await release.wait()
                    result = (await client.call_tool(args["name"], args.get("arguments", {}))).model_dump(
                        by_alias=True, exclude_none=True
                    )
                    if args["name"] == "stories_add_comment" and lose_ack:
                        lose_ack = False
                        raise RuntimeError("Acknowledgement lost after commit")
                    return result

                async def read(args):
                    return (await client.read_resource(args["uri"])).model_dump(
                        by_alias=True, exclude_none=True
                    )

                await page.expose_function("hostCall", tool)
                await page.expose_function("hostRead", read)
                await page.add_script_tag(content=host)
                html = (ROOT / "src/amplifier_smart_tool_stories/resources/mcp_app.html").read_text()

                async def mount():
                    initial = await client.call_tool("stories_get_story", {"story_id": ids["story_id"]})
                    await page.evaluate(
                        "([html,result])=>mountStories(html,result)",
                        [html, initial.model_dump(by_alias=True, exclude_none=True)],
                    )

                await mount()
                app = page.frame_locator("#app")
                await expect(app.locator("#versions")).to_have_value(ids["revision_id"], timeout=15000)
                await expect(app.locator("#comment")).to_have_value("Carry this draft across transports")
                await expect(app.locator("#documentMode")).to_have_value("paginated")
                await expect(app.locator("#zoomLabel")).to_have_text("110%")
                assert (
                    await app.locator("button,input,select,textarea").evaluate_all(
                        "nodes=>nodes.map(n=>[n.id,n.tagName,n.type,n.textContent])"
                    )
                    == controls
                )
                await expect(app.frame_locator("#material").locator("img").first).to_have_js_property(
                    "naturalWidth", 360
                )
                await app.locator("#send").click()
                await asyncio.wait_for(entered.wait(), 5)
                await app.locator("#comment").fill("A newer thought must survive")
                release.set()
                await expect(app.locator("#error")).to_contain_text("Acknowledgement lost")
                await expect(app.locator("#comment")).to_have_value("A newer thought must survive")
                await expect(app.locator("#saved")).to_have_text("Draft saved")
                assert (
                    api.get_review_view(ids["story_id"])["native_context"]
                    .get("pending", {})
                    .get("comment", {})
                    .get("request_id")
                    == attempts[0]["request_id"]
                ), views
                await mount()  # retry receipt survives iframe destruction
                await expect(app.locator("#comment")).to_have_value("A newer thought must survive")
                await app.locator("#comment").fill("Carry this draft across transports")
                await app.locator("#send").click()
                await expect(app.locator("#comment")).to_have_value("")
                assert attempts[0] == attempts[1]
                notes = api.get_story(ids["story_id"])["annotations"]
                assert len(notes) == 1 and notes[0]["revision_id"] == ids["revision_id"]
                # Per-direction comparison uses exactly the native controls and semantics.
                await app.locator("#revealTools").click()
                await app.locator("#documentCompare").click()
                await expect(app.locator(".comparison-card")).to_have_count(2)
                assert api.get_story(ids["story_id"])["selected_direction"] is None
                await app.get_by_role("button", name="Focus & comment").last.click()
                await expect(app.locator("#versions")).to_have_value(ids["comparison_revision"])
                await app.locator("#revealTools").click()
                await app.locator("#documentCompare").click()
                await app.get_by_role("button", name="Continue with this direction").last.click()
                await expect(app.locator("#comparison")).to_be_hidden()
                assert api.get_story(ids["story_id"])["selected_revision"] == ids["comparison_revision"]
                await app.locator("#revealTools").click()
                await app.locator("#documentDetails").click()
                await app.locator("#acceptRevision").click()
                await expect(app.locator("#acceptanceStatus")).to_contain_text("not authenticated")
                await app.locator("#narrationOpen").click()
                await expect(app.locator("#speechNotes textarea")).to_have_count(2)
                await expect(app.locator("#speechNotes textarea").first).to_have_value("Begin with the need.")
                await expect(app.locator("#speechGenerateExport")).to_be_disabled()
                await app.locator("#narrationClose").click()
                await app.locator("#revealTools").click()
                await app.locator("#documentSettings").click()
                await expect(app.locator("#providerTest")).to_be_disabled()
                await app.locator("#providerChoice").select_option("gemini")
                await app.locator("#providerApply").click()
                await expect(app.locator("#providerApplied")).to_contain_text("Gemini")
                await app.locator("#providerClose").click()
                # Untrusted nested material cannot read the parent or call its MCP bridge.
                child = page.frames[-1]
                assert (
                    await child.evaluate(
                        "(()=>{try{return parent.document.body.innerText}catch{return 'isolated'}})()"
                    )
                    == "isolated"
                )
                count = calls.count("stories_cancel_operation")
                await child.evaluate(
                    "parent.postMessage({jsonrpc:'2.0',id:999,method:'tools/call',params:{name:'stories_cancel_operation',arguments:{operation_id:'forged'}}},'*')"
                )
                app_frame = next(frame for frame in page.frames if frame.parent_frame == page.main_frame)
                await app_frame.evaluate("window.StoriesReview.api('get-story')")
                assert calls.count("stories_cancel_operation") == count
                # Legacy/public CAS navigation remains authoritative; native
                # context must not erase an agent's comparison on reconnect.
                current = api.get_review_view(ids["story_id"])
                api.update_review_view(
                    ids["story_id"],
                    current["version"],
                    "agent-comparison",
                    revision_id=ids["revision_id"],
                    comparison_revision=ids["comparison_revision"],
                )
                await mount()
                await expect(app.locator("#comparison")).to_be_visible()
                await expect(app.locator(".comparison-card")).to_have_count(2)
                assert not errors, errors
                await browser.close()
        finally:
            dashboard.server.shutdown()
            worker.join(5)

    asyncio.run(run())


@pytest.mark.parametrize("revisit", [False, True])
def test_delayed_synthesis_receipt_never_retargets_dialog(tmp_path, revisit):
    ids = fixture.seed(tmp_path)
    api = Stories(tmp_path, model_env=True)  # queued only; no speech provider invoked
    api.configure_narration("openai", "settings")
    # Populate all required exact panel text without changing either revision identity.
    # Use a new imported board derived through public APIs instead of storage edits.
    board = api.get_revision(ids["story_id"], ids["revision_id"])["storyboard"]
    for panel in board["panels"]:
        panel["narration"] = "Synthetic retained words."
    a = api.create_storyboard("Delayed receipt", board, "delayed-board", asset_ids=[ids["asset_id"]])
    b = api.revise_storyboard(a["story_id"], a["revision_id"], board, "other-revision")
    host = subprocess.run(
        [
            str(ROOT / "mcp-app/node_modules/.bin/esbuild"),
            str(ROOT / "mcp-app/test-host.js"),
            "--bundle",
            "--format=iife",
            "--log-level=error",
        ],
        check=True,
        text=True,
        capture_output=True,
    ).stdout

    async def run():
        async with Client(create_server(api)) as client, async_playwright() as pw:
            browser = await pw.chromium.launch()
            page = await browser.new_page(viewport={"width": 1200, "height": 900})
            entered, release = asyncio.Event(), asyncio.Event()
            poll_entered, poll_release = asyncio.Event(), asyncio.Event()
            delay_poll = False
            receipt = {}

            async def tool(args):
                result = (await client.call_tool(args["name"], args.get("arguments", {}))).model_dump(
                    by_alias=True, exclude_none=True
                )
                if args["name"] == "stories_generate_narration":
                    receipt.update(result["structuredContent"]["result"])
                    entered.set()
                    await release.wait()
                if args["name"] == "stories_get_operation" and receipt:
                    result["structuredContent"]["result"]["progress"] = {
                        "completed_panels": 1,
                        "total_panels": 2,
                    }
                    if delay_poll and not poll_entered.is_set():
                        poll_entered.set()
                        await poll_release.wait()
                return result

            async def read(args):
                return (await client.read_resource(args["uri"])).model_dump(by_alias=True, exclude_none=True)

            try:
                await page.expose_function("hostCall", tool)
                await page.expose_function("hostRead", read)
                await page.route(
                    "https://stories-host.test/**",
                    lambda route: route.fulfill(body="<body></body>", content_type="text/html"),
                )
                await page.goto("https://stories-host.test/")
                await page.add_script_tag(content=host)
                initial = await client.call_tool("stories_get_story", {"story_id": a["story_id"]})
                html = (ROOT / "src/amplifier_smart_tool_stories/resources/mcp_app.html").read_text()
                await page.evaluate(
                    "([html,result])=>mountStories(html,result)",
                    [html, initial.model_dump(by_alias=True, exclude_none=True)],
                )
                ui = page.frame_locator("#app")
                await expect(ui.locator("#versions")).to_have_value(a["revision_id"])
                await ui.locator("#revealTools").click()
                await ui.locator("#documentDetails").click()
                await ui.locator("#narrationOpen").click()
                await expect(ui.locator("#speechNotes textarea")).to_have_count(2)
                await ui.locator("#speechGenerate").click()
                await asyncio.wait_for(entered.wait(), 5)
                await ui.locator("#narrationClose").click()
                await ui.locator("#versions").select_option(b["revision_id"])
                await expect(ui.locator("#versions")).to_have_value(b["revision_id"])
                await ui.locator("#narrationOpen").click()
                await expect(ui.locator("#narrationRevision")).to_have_text("Revision " + b["revision_id"])
                await expect(ui.locator("#speechCancel")).to_be_disabled()
                if revisit:
                    await ui.locator("#narrationClose").click()
                    await ui.locator("#versions").select_option(a["revision_id"])
                    await ui.locator("#narrationOpen").click()
                    await expect(ui.locator("#narrationRevision")).to_have_text(
                        "Revision " + a["revision_id"]
                    )
                release.set()
                # Await a real server observation, not an arbitrary sleep.
                for _ in range(100):
                    view = api.get_review_view(a["story_id"])["native_context"]
                    if (
                        view.get("narration", {}).get(a["revision_id"], {}).get("operation")
                        == receipt["operation_id"]
                    ):
                        break
                    await asyncio.sleep(0.05)
                assert view["narration"][a["revision_id"]]["operation"] == receipt["operation_id"]
                assert not view.get("narration", {}).get(b["revision_id"], {}).get("operation")
                if not revisit:
                    await expect(ui.locator("#speechCancel")).to_be_disabled()
                    await expect(ui.locator("#speechStatus")).not_to_contain_text("queued")
                else:
                    await expect(ui.locator("#speechCancel")).to_be_enabled()
                    await expect(ui.locator("#speechStatus")).to_contain_text("1/2 panels", timeout=8000)
                    delay_poll = True
                    await asyncio.wait_for(poll_entered.wait(), 5)
                    await ui.locator("#speechCancel").click()
                    await expect(ui.locator("#speechStatus")).to_contain_text("Cancellation requested")
                    assert api.get_operation(receipt["operation_id"])["state"] == "cancelled"
                    poll_release.set()
                    frame = next(f for f in page.frames if f.parent_frame == page.main_frame)
                    await frame.evaluate("window.StoriesReview.api('get-story')")
                    await expect(ui.locator("#speechStatus")).not_to_contain_text("queued")
                    await expect(ui.locator("#speechStatus")).to_contain_text("cancelled", timeout=8000)
            finally:
                release.set()
                poll_release.set()
                await browser.close()

    asyncio.run(run())


@pytest.mark.parametrize("surface", ["http", "mcp"])
def test_phone_document_limit_and_story_adoption(tmp_path, surface):
    api = Stories(tmp_path)
    a = api.create_story(
        "Story A", '<html><body><section class="slide"><h1>A</h1></section></body></html>', "a"
    )
    document = {
        "title": "Document B",
        "subtitle": "",
        "blocks": [
            {
                "id": "body",
                "kind": "paragraph",
                "text": "Retained context",
                "items": [],
                "rows": [],
                "evidence_ids": [],
            },
        ],
    }
    b = api.create_document("Story B", document, "b")
    c = api.create_document("Story C", {**document, "title": "Document C"}, "c")
    host = subprocess.run(
        [
            str(ROOT / "mcp-app/node_modules/.bin/esbuild"),
            str(ROOT / "mcp-app/test-host.js"),
            "--bundle",
            "--format=iife",
            "--log-level=error",
        ],
        check=True,
        text=True,
        capture_output=True,
    ).stdout

    async def run():
        server = Dashboard(api, b["story_id"])
        worker = threading.Thread(target=server.serve)
        worker.start()
        try:
            async with Client(create_server(api)) as client, async_playwright() as pw:
                browser = await pw.chromium.launch()
                page = await browser.new_page(viewport={"width": 390, "height": 844})
                if surface == "http":
                    await page.goto(f"http://127.0.0.1:{server.server.server_port}/#{server.token}")
                    ui = page
                else:
                    delayed, release = asyncio.Event(), asyncio.Event()
                    delay_b = False

                    async def tool(args):
                        result = (await client.call_tool(args["name"], args.get("arguments", {}))).model_dump(
                            by_alias=True, exclude_none=True
                        )
                        if (
                            delay_b
                            and args["name"] == "stories_get_story"
                            and args.get("arguments", {}).get("story_id") == b["story_id"]
                        ):
                            delayed.set()
                            await release.wait()
                        return result

                    async def read(args):
                        return (await client.read_resource(args["uri"])).model_dump(
                            by_alias=True, exclude_none=True
                        )

                    await page.expose_function("hostCall", tool)
                    await page.expose_function("hostRead", read)
                    await page.route(
                        "https://stories-host.test/**",
                        lambda route: route.fulfill(body="<body></body>", content_type="text/html"),
                    )
                    await page.goto("https://stories-host.test/")
                    await page.add_script_tag(content=host)
                    initial = await client.call_tool("stories_get_story", {"story_id": a["story_id"]})
                    html = (ROOT / "src/amplifier_smart_tool_stories/resources/mcp_app.html").read_text()
                    await page.evaluate(
                        "([html,result])=>mountStories(html,result)",
                        [html, initial.model_dump(by_alias=True, exclude_none=True)],
                    )
                    ui = page.frame_locator("#app")
                    await expect(ui.locator("#versions")).to_have_value(a["revision_id"])

                    async def notify(ids):
                        result = await client.call_tool("stories_get_story", {"story_id": ids["story_id"]})
                        await page.evaluate(
                            "result=>window.storiesBridge.sendToolResult(result)",
                            result.model_dump(by_alias=True, exclude_none=True),
                        )

                    await notify(b)
                    await expect(ui.locator("#versions")).to_have_value(b["revision_id"])
                    assert await ui.locator("#versions option").evaluate_all(
                        "nodes=>nodes.map(n=>n.value)"
                    ) == [b["revision_id"]]
                    # Overlapping actual notifications: a delayed B load cannot replace C.
                    await notify(a)
                    await expect(ui.locator("#versions")).to_have_value(a["revision_id"])
                    delay_b = True
                    await notify(b)
                    await asyncio.wait_for(delayed.wait(), 5)
                    await notify(c)
                    await expect(ui.locator("#versions")).to_have_value(c["revision_id"])
                    release.set()
                    # Read barrier after delayed response, then verify latest identity.
                    frame = next(f for f in page.frames if f.parent_frame == page.main_frame)
                    await frame.evaluate("window.StoriesReview.api('get-story')")
                    await expect(ui.locator("#versions")).to_have_value(c["revision_id"])
                await ui.locator("#revealTools").click()
                await ui.locator("#documentDetails").click()
                await expect(ui.locator("#narrationOpen")).to_be_disabled()
                await expect(ui.locator("#narrationLimit")).to_contain_text("not documents")
                assert await ui.locator("#closeDetails").evaluate(
                    "(e)=>{const r=e.getBoundingClientRect();return e.ownerDocument.elementFromPoint(r.x+r.width/2,r.y+r.height/2)===e}"
                )
                await ui.locator("#closeDetails").click()
                await expect(ui.locator("#details")).to_be_hidden()
                await ui.locator("#revealTools").click()
                await ui.locator("#documentSettings").click()
                await expect(ui.locator("#providerDialog")).to_be_visible()
                await browser.close()
        finally:
            server.server.shutdown()
            worker.join(5)

    asyncio.run(run())


@pytest.mark.parametrize("surface", ["http", "mcp"])
def test_shared_script_speech_audio_and_real_video_download(tmp_path, monkeypatch, surface):
    from test_narration import fixture as narration_fixture

    api, ids, speech_calls = narration_fixture(tmp_path, monkeypatch)
    node = ROOT / "mcp-app/node_modules"
    if surface == "mcp" and not node.exists():
        pytest.skip("Install the local SDK build dependencies.")
    host = (
        subprocess.run(
            [
                str(node / ".bin/esbuild"),
                str(ROOT / "mcp-app/test-host.js"),
                "--bundle",
                "--format=iife",
                "--log-level=error",
            ],
            check=True,
            text=True,
            capture_output=True,
        ).stdout
        if surface == "mcp"
        else None
    )

    async def run():
        dashboard = Dashboard(api, ids["story_id"])
        worker = threading.Thread(target=dashboard.serve)
        worker.start()
        try:
            async with Client(create_server(api)) as client, async_playwright() as pw:
                browser = await pw.chromium.launch()
                page = await browser.new_page(viewport={"width": 1100, "height": 900})
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                if surface == "http":
                    await page.goto(f"http://127.0.0.1:{dashboard.server.server_port}/#{dashboard.token}")
                    ui = page
                else:

                    async def tool(args):
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
                        "https://stories-host.test/**",
                        lambda route: route.fulfill(
                            body="<!doctype html><body></body>", content_type="text/html"
                        ),
                    )
                    await page.goto("https://stories-host.test/")
                    await page.add_script_tag(content=host)
                    initial = await client.call_tool("stories_get_story", {"story_id": ids["story_id"]})
                    html = (ROOT / "src/amplifier_smart_tool_stories/resources/mcp_app.html").read_text()
                    await page.evaluate(
                        "([html,result])=>mountStories(html,result)",
                        [html, initial.model_dump(by_alias=True, exclude_none=True)],
                    )
                    ui = page.frame_locator("#app")
                await expect(ui.locator("#versions")).to_have_value(ids["revision_id"])
                await ui.locator("#next").click()
                await expect(ui.locator("#position")).to_have_text("2 / 2")
                await ui.locator("#more").click()
                await ui.locator("#narrationOpen").click()
                await expect(ui.locator("#speechNotes textarea")).to_have_count(2)
                await ui.locator("#speechVoice").fill("x" * 201)
                await ui.locator("#speechApply").click()
                await expect(ui.locator("#speechStatus")).to_have_text(
                    "Model and voice must be nonempty strings up to 200 characters."
                )
                await ui.locator("#speechVoice").fill("marin")
                await ui.locator("#speechApply").click()
                await expect(ui.locator("#speechStatus")).to_have_text(
                    "Narration settings saved. No speech generated."
                )
                assert not api.get_review_view(ids["story_id"])["native_context"]["pending"]
                await ui.locator("#speechNotes textarea").first.fill("First adapted passage.")
                await ui.locator("#scriptSave").click()
                await expect(ui.locator("#scriptStatus")).to_contain_text("Script saved")
                assert len(api.list_narration_scripts(ids["story_id"], ids["revision_id"])["scripts"]) == 1
                assert not speech_calls
                await ui.locator("#speechGenerate").click()
                await expect(ui.locator("#speechStatus")).to_contain_text("succeeded", timeout=15000)
                await expect(ui.locator("#speechAudio audio")).to_have_count(2)
                original_audio = await ui.locator("#speechAudio audio").first.element_handle()
                await original_audio.evaluate("a=>{a.dataset.original='retained'; a.play()}")
                await ui.locator("#narrationClose").click()
                await ui.locator("#narrationOpen").click()
                await expect(ui.locator("#speechAudio audio").first).to_have_attribute(
                    "data-original", "retained"
                )
                await expect(ui.locator("#speechVersions")).not_to_be_empty()
                assert await original_audio.evaluate("a=>a.isConnected")
                await original_audio.evaluate("a=>{a.currentTime=0; return a.play()}")
                await expect(ui.locator("#speechAudio audio").first).to_have_js_property("ended", True)
                assert [call[0] for call in speech_calls] == ["First adapted passage.", "Second note."]
                async with page.expect_download(timeout=30000) as download:
                    await ui.locator("#speechExport").click()
                downloaded = await download.value
                path = await downloaded.path()
                assert b"ftyp" in Path(path).read_bytes()[:32]
                await expect(ui.locator("#speechExportStatus")).to_contain_text("No new speech synthesis")
                assert len(speech_calls) == 2
                assert not errors, errors
                await browser.close()
        finally:
            dashboard.server.shutdown()
            worker.join(5)

    asyncio.run(run())
