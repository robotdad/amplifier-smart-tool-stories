"""Storyboard geometry in the native dashboard and the packaged MCP App.

Uses the same retained mixed/illustrated fixture as the actual-host trial, but
in a fresh provider-disabled store. No access to the live host or its store.
"""

import asyncio
import importlib.resources
import json
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
GEOMETRY = """() => {
  const root = document.querySelector('.stories-storyboard');
  const box = n => {
    const r = n.getBoundingClientRect();
    return {left:r.left + scrollX, right:r.right + scrollX, width:r.width};
  };
  const nodes = [...root.querySelectorAll(
    '.document-page,.storyboard-direction,.storyboard-panel,.visual,img,.panel-copy,p,h1,h2,strong,.planned')];
  const text = [...root.querySelectorAll('p,h1,h2,strong,.planned')].flatMap(n => {
    const range = document.createRange();
    range.selectNodeContents(n);
    return [...range.getClientRects()].map(r => ({
      tag:'text', id:n.id, left:r.left + scrollX, right:r.right + scrollX, width:r.width
    }));
  });
  return {
    viewport:document.documentElement.clientWidth,
    client:document.documentElement.clientWidth,
    scroll:document.documentElement.scrollWidth,
    bodyClient:document.body.clientWidth,
    bodyScroll:document.body.scrollWidth,
    zoom:Number(getComputedStyle(root).zoom),
    root:box(root),
    boxes:[...nodes.map(n => ({tag:n.tagName, id:n.id, ...box(n)})), ...text],
    hidden:[document.documentElement,document.body,root].some(
      n => ['hidden','clip'].includes(getComputedStyle(n).overflowX)),
    pages:root.querySelectorAll('.document-page').length,
    imageReady:[...root.querySelectorAll('img')].every(n => n.complete && n.naturalWidth > 0)
  };
}"""


def assert_geometry(g, *, fitted):
    """A centered fitting paper, or reachable overflow at explicitly chosen zoom."""
    assert not g["hidden"], g
    assert g["imageReady"], g
    paper = g["root"]
    assert paper["left"] >= -1, g
    for box in g["boxes"]:
        assert box["left"] >= paper["left"] - 1, (box, g)
        assert box["right"] <= paper["right"] + 1, (box, g)
    if fitted:
        assert paper["right"] <= g["client"] + 1, g
        assert abs(paper["left"] - (g["client"] - paper["right"])) <= 1, g
        assert g["scroll"] <= g["client"] + 1, g
        assert g["bodyScroll"] <= g["bodyClient"] + 1, g
    else:
        assert paper["right"] <= g["scroll"] + 1, g
        # Overflow starts at the left gutter, never at an inaccessible negative X.
        if paper["width"] > g["viewport"] - 40:
            assert abs(paper["left"] - 20) <= 1, g
        else:
            assert abs(paper["left"] - (g["client"] - paper["right"])) <= 1, g


@pytest.mark.parametrize("surface", ["http", "mcp"])
@pytest.mark.parametrize("width", [390, 574, 575, 576, 1280])
def test_storyboard_width_modes_zoom_and_comparison(tmp_path, surface, width):
    ids = fixture.seed(tmp_path / "store")
    api = Stories(tmp_path / "store", model_env=False)
    originals = {
        rid: api.get_revision(ids["story_id"], rid)["html"]
        for rid in [ids["revision_id"], ids["comparison_revision"]]
    }
    html = (
        importlib.resources.files("amplifier_smart_tool_stories")
        .joinpath("resources/mcp_app.html")
        .read_text()
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
    observations = []

    async def run():
        server = Dashboard(api, ids["story_id"])
        worker = threading.Thread(target=server.serve)
        worker.start()
        try:
            async with Client(create_server(api)) as client, async_playwright() as pw:
                browser = await pw.chromium.launch()
                try:
                    page = await browser.new_page(viewport={"width": width, "height": 900})
                    errors = []
                    page.on("pageerror", lambda e: errors.append(str(e)))
                    if surface == "http":
                        await page.goto(f"http://127.0.0.1:{server.server.server_port}/#{server.token}")
                        ui = page
                    else:

                        async def tool(args):
                            return (
                                await client.call_tool(args["name"], args.get("arguments", {}))
                            ).model_dump(by_alias=True, exclude_none=True)

                        async def read(args):
                            return (await client.read_resource(args["uri"])).model_dump(
                                by_alias=True, exclude_none=True
                            )

                        await page.expose_function("hostCall", tool)
                        await page.expose_function("hostRead", read)
                        await page.route(
                            "https://stories-host.test/**",
                            lambda r: r.fulfill(
                                body="<body style='margin:0'></body>", content_type="text/html"
                            ),
                        )
                        await page.goto("https://stories-host.test/")
                        await page.add_script_tag(content=host)
                        initial = await client.call_tool("stories_get_story", {"story_id": ids["story_id"]})
                        await page.evaluate(
                            "([html,result])=>mountStories(html,result)",
                            [html, initial.model_dump(by_alias=True, exclude_none=True)],
                        )
                        ui = page.frame_locator("#app")

                    await expect(ui.locator("body.document-review")).to_be_attached()
                    material = await (await ui.locator("#material").element_handle()).content_frame()
                    await material.wait_for_function(
                        "() => document.querySelector('.stories-storyboard')?.style.zoom === '1'"
                        " && [...document.images].every(i => i.complete && i.naturalWidth)"
                    )

                    async def check(label, *, fitted=True, pages=False):
                        g = await material.evaluate(GEOMETRY)
                        observations.append({"state": label, **g})
                        (tmp_path / "geometry.json").write_text(json.dumps(observations, indent=2))
                        await page.screenshot(path=str(tmp_path / f"{label}.png"))
                        assert g["viewport"] == width, g  # Never widen the containing pane.
                        assert bool(g["pages"]) == pages, g
                        assert_geometry(g, fitted=fitted)
                        return g

                    baseline = await check("continuous-default")
                    assert baseline["zoom"] == 1
                    resized = 575 if width != 575 else 390
                    for pane_width in [resized, width]:
                        await page.set_viewport_size({"width": pane_width, "height": 900})
                        await material.wait_for_function(
                            "() => Math.abs(document.querySelector('.stories-storyboard')"
                            ".getBoundingClientRect().width - Math.min(900, innerWidth - 40)) < 1"
                        )
                        g = await material.evaluate(GEOMETRY)
                        observations.append({"state": f"resized-default-{pane_width}", **g})
                        assert g["zoom"] == 1
                        assert_geometry(g, fitted=True)
                    await ui.locator("#revealTools").click()
                    await ui.locator("#zoomIn").click()
                    await expect(ui.locator("#zoomLabel")).to_have_text("110%")
                    enlarged = await check("continuous-zoom", fitted=False)
                    assert enlarged["zoom"] == pytest.approx(1.1)
                    assert enlarged["root"]["width"] == pytest.approx(baseline["root"]["width"] * 1.1, abs=1)
                    await ui.locator("#zoomOut").click()
                    await expect(ui.locator("#zoomLabel")).to_have_text("100%")
                    await check("continuous-restored")
                    await ui.locator("#documentMode").select_option("paginated")
                    await material.wait_for_selector(".document-page")
                    paginated = await check("paginated-100", fitted=False, pages=True)
                    assert paginated["zoom"] == 1 and paginated["root"]["width"] == 816
                    await ui.locator("#documentMode").select_option("continuous")
                    await material.wait_for_selector(".document-page", state="detached")
                    await check("continuous-from-pages")
                    await ui.locator("#fitWidth").click()
                    await material.wait_for_function(
                        "() => Math.abs(document.querySelector('.stories-storyboard')"
                        ".getBoundingClientRect().width - (innerWidth - 40)) < 1"
                    )
                    await check("continuous-fit")
                    await ui.locator("#documentMode").select_option("paginated")
                    await material.wait_for_selector(".document-page")
                    fitted_page = await check("paginated-fit", pages=True)
                    # Explicit zoom is honored even when a fixed page needs horizontal scroll.
                    await ui.locator("#zoomIn").click()
                    await material.wait_for_function(
                        "expected => Math.abs(Number(getComputedStyle(document.querySelector("
                        "'.stories-storyboard')).zoom) - expected) < 0.00001",
                        arg=fitted_page["zoom"] + 0.1,
                    )
                    zoomed = await check("paginated-zoom", fitted=False, pages=True)
                    assert zoomed["zoom"] == pytest.approx(fitted_page["zoom"] + 0.1, abs=0.00001)
                    assert zoomed["root"]["width"] == pytest.approx(816 * zoomed["zoom"], abs=1)
                    await material.evaluate("scrollTo(100000, scrollY)")
                    edge = await material.evaluate(
                        "() => ({right:document.querySelector('.document-page')"
                        ".getBoundingClientRect().right, viewport:innerWidth})"
                    )
                    assert edge["right"] <= edge["viewport"] + 1, edge
                    await ui.locator("#fitWidth").click()
                    await material.wait_for_function(
                        "() => Math.abs(document.querySelector('.stories-storyboard')"
                        ".getBoundingClientRect().width - (innerWidth - 40)) < 1"
                    )
                    await check("paginated-refit", pages=True)
                    await ui.locator("#documentMode").select_option("continuous")
                    await material.wait_for_selector(".document-page", state="detached")
                    await check("continuous-return")
                    # Resize the actual pane with Fit still active, not the material itself.
                    await page.set_viewport_size({"width": resized, "height": 900})
                    await material.wait_for_function(
                        "() => Math.abs(document.querySelector('.stories-storyboard')"
                        ".getBoundingClientRect().width - (innerWidth - 40)) < 1"
                    )
                    g = await material.evaluate(GEOMETRY)
                    observations.append({"state": "resized-fit", **g})
                    assert g["viewport"] == resized
                    assert_geometry(g, fitted=True)
                    await page.set_viewport_size({"width": width, "height": 900})
                    await ui.locator("#documentCompare").click()
                    await expect(ui.locator(".comparison-card")).to_have_count(2)
                    for i in range(2):
                        comparison = await (
                            await ui.locator(".comparison-card iframe").nth(i).element_handle()
                        ).content_frame()
                        await comparison.wait_for_function(
                            "() => !!document.querySelector('.stories-storyboard')"
                            " && [...document.images].every(i => i.complete && i.naturalWidth)"
                        )
                        g = await comparison.evaluate(GEOMETRY)
                        observations.append({"state": f"comparison-{i}", **g})
                        assert_geometry(g, fitted=True)
                    (tmp_path / "geometry.json").write_text(json.dumps(observations, indent=2))
                    assert not errors, errors
                finally:
                    await browser.close()
        finally:
            server.server.shutdown()
            worker.join(5)

    asyncio.run(run())
    for rid, original in originals.items():
        assert api.get_revision(ids["story_id"], rid)["html"] == original
