"""Media survives review, revisions and portable exports without hidden transformation."""

import asyncio
import base64
import io
import json
import shutil
import subprocess
import zipfile

import pytest
from PIL import Image

from amplifier_smart_tool_stories import Stories
from amplifier_smart_tool_stories.errors import StoriesError
from amplifier_smart_tool_stories.quality import render


def image_bytes(size=(320, 180)):
    output = io.BytesIO()
    Image.new("RGB", size, "red").save(output, format="PNG")
    return output.getvalue()


def ingest(api, data=None, request_id="image", **kwargs):
    return api.import_media(
        "Poster",
        "image/png",
        request_id,
        data_base64=base64.b64encode(data or image_bytes()).decode(),
        **kwargs,
    )["asset"]


def markup(asset):
    return f'<html><body><section class="slide"><h1>Demo</h1><img src="asset:{asset["id"]}" alt="Demo poster"></section></body></html>'


def test_original_preview_export_and_revision_identity(tmp_path):
    api = Stories(tmp_path / "store")
    data = image_bytes((3000, 1500))
    receipt = api.import_media("Large", "image/png", "large", data_base64=base64.b64encode(data).decode())
    assert receipt["warnings"]
    asset = receipt["asset"]
    created = api.create_story("Demo", markup(asset), "create", asset_ids=[asset["id"]])
    story, rev = created["story_id"], created["revision_id"]
    preview = api.get_preview(story, rev)
    assert 'src="asset:' in preview["html"] and preview["media_warnings"]
    assert base64.b64decode(api.get_media(story, rev, asset["id"])["data_base64"]) == data
    resized = api.resize_media(asset["id"], 640, 360, "resize")["asset"]
    assert resized["width"] == 640 and resized["height"] == 320
    assert resized["derived_from"] == asset["id"]
    newer = api.revise_media(story, rev, [resized["id"]], "revision", html=markup(resized))
    assert api.get_revision(story, rev)["assets"] == [asset]
    assert (
        api.get_revision(story, newer["revision_id"])["delivery_sha256"]
        != api.get_revision(story, rev)["delivery_sha256"]
    )
    exported = api.get_export(story, rev)
    assert base64.b64encode(data).decode() in base64.b64decode(exported["data_base64"]).decode()
    with pytest.raises(StoriesError, match="not attached"):
        api.get_media(story, rev, resized["id"])
    assert (
        api.import_media("Large", "image/png", "large", data_base64=base64.b64encode(data).decode())
        == receipt
    )


def test_packaged_media_exact_and_no_paths_or_comments(tmp_path):
    api = Stories(tmp_path / "store")
    asset = ingest(api)
    created = api.create_story("Demo", markup(asset), "create", asset_ids=[asset["id"]])
    api.add_comment(created["story_id"], created["revision_id"], "PRIVATE REVIEW", "comment", author="agent")
    package = api.get_export(created["story_id"], created["revision_id"], "zip")
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(package["data_base64"]))) as archive:
        html = archive.read("index.html").decode()
        assert "asset:" not in html and "PRIVATE REVIEW" not in html and str(tmp_path) not in html
        path = "assets/" + asset["id"] + ".png"
        assert path in html and archive.read(path) == image_bytes()
        assert json.loads(archive.read("manifest.json"))["assets"] == [asset]


def test_static_renderer_reads_only_registered_images(tmp_path):
    api = Stories(tmp_path / "store")
    asset = ingest(api)
    from amplifier_smart_tool_stories.media import image_payload

    with api.store.transaction() as db:
        media = image_payload(db, [asset])
    result = asyncio.run(render(markup(asset), 40, media=media))
    assert result["images"] and not result["findings"]
    without = asyncio.run(render(markup(asset), 40))
    assert result["images"][0]["sha256"] != without["images"][0]["sha256"]


def test_unregistered_refs_and_limits(tmp_path):
    api = Stories(tmp_path / "store")
    asset = ingest(api)
    html = '<html><body><h1>Unsafe</h1><video src="file:///secret.mp4" poster="https://example.com/tracker.png"></video></body></html>'
    created = api.create_story("Unsafe", html, "create")
    preview = api.get_preview(created["story_id"], created["revision_id"])["html"]
    assert "file:" not in preview and "https:" not in preview and "unavailable" in preview
    with pytest.raises(StoriesError):
        api.get_export(created["story_id"], created["revision_id"], "zip")
    with pytest.raises(StoriesError):
        api.create_story("Unsafe", html, "create-bound", asset_ids=[asset["id"]])
    with pytest.raises(StoriesError):
        api.import_media("Bad", "image/png", "bad", data_base64=base64.b64encode(b"not png").decode())
    with pytest.raises(StoriesError):
        api.create_story("Missing", markup(asset), "missing", asset_ids=["unknown"])
    # The previous blanket 2 MB rejection no longer applies to markup.
    api.create_story("Long", "<html><body><p>" + "x" * 2_000_100 + "</p></body></html>", "long")


@pytest.fixture
def video(tmp_path):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg unavailable")
    path = tmp_path / "demo.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=320x180:r=10:d=1",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ],
        check=True,
    )
    return path


def test_video_embeds_or_packages_and_retains_original(tmp_path, video):
    api = Stories(tmp_path / "store")
    asset = api.import_media("Clip", "video/mp4", "clip", path=str(video))["asset"]
    assert asset["duration_seconds"] == pytest.approx(1)
    poster = ingest(api)
    html = f'<html><body><h1>Demo clip</h1><video controls src="asset:{asset["id"]}" poster="asset:{poster["id"]}"></video></body></html>'
    created = api.create_story("Demo", html, "create", asset_ids=[asset["id"], poster["id"]])
    standalone = api.get_export(created["story_id"], created["revision_id"], "html")
    assert b"data:video/mp4;base64," + base64.b64encode(video.read_bytes()) in base64.b64decode(
        standalone["data_base64"]
    )
    package = api.get_export(created["story_id"], created["revision_id"], "zip")
    original = video.read_bytes()
    video.unlink()
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(package["data_base64"]))) as archive:
        assert archive.read("assets/" + asset["id"] + ".mp4") == original
    preview = api.get_preview(created["story_id"], created["revision_id"])["html"]
    assert "controls" in preview and "poster=" in preview and "asset:" in preview


def test_authenticated_media_route_is_revision_scoped(tmp_path):
    import threading
    import urllib.error

    from test_dashboard import post

    from amplifier_smart_tool_stories.dashboard import Dashboard

    api = Stories(tmp_path / "store")
    asset = ingest(api)
    r = api.create_story("Demo", markup(asset), "create", asset_ids=[asset["id"]])
    other = api.create_story("Other", markup(asset), "other", asset_ids=[asset["id"]])
    server = Dashboard(api, r["story_id"])
    thread = threading.Thread(target=server.serve)
    thread.start()
    try:
        data = {"revision_id": r["revision_id"], "asset_id": asset["id"]}
        with post(server, "media", data) as response:
            assert response.read() == image_bytes()
        for bad, token, origin in [
            (data, "bad", None),
            (data, None, "null"),
            ({**data, "revision_id": other["revision_id"]}, None, None),
            ({**data, "asset_id": "/etc/passwd"}, None, None),
        ]:
            with pytest.raises(urllib.error.HTTPError):
                post(server, "media", bad, token=token, origin=origin)
        with post(server, "download", {"revision_id": r["revision_id"], "format": "zip"}) as response:
            assert 'filename="story.zip"' in response.headers["Content-Disposition"]
            assert zipfile.is_zipfile(io.BytesIO(response.read()))
    finally:
        server.server.shutdown()
        thread.join(5)


def test_zip_rejects_hidden_dependencies_and_is_reproducible(tmp_path):
    api = Stories(tmp_path / "store")
    asset = ingest(api)
    r = api.create_story("Demo", markup(asset), "create", asset_ids=[asset["id"]])
    one = api.get_export(r["story_id"], r["revision_id"], "zip")
    two = api.get_export(r["story_id"], r["revision_id"], "zip")
    assert one["sha256"] == two["sha256"]
    for i, dependency in enumerate(
        [
            '<script>fetch("https://example.com")</script>',
            "<style>body {background:url(https://example.com/x)}</style>",
        ]
    ):
        bad = api.create_story("Bad", "<html><body><p>Demo</p>" + dependency + "</body></html>", f"bad-{i}")
        with pytest.raises(StoriesError, match="Portable media export"):
            api.get_export(bad["story_id"], bad["revision_id"], "zip")


def test_text_anchor_after_media_remains_valid_in_submission(tmp_path):
    api = Stories(tmp_path)
    asset = ingest(api)
    html = markup(asset).replace("</section>", "<p>Caption selected for comment.</p></section>")
    r = api.create_story("Demo", html, "create", asset_ids=[asset["id"]])
    preview = api.get_preview(r["story_id"], r["revision_id"])
    target = next(e for e in preview["elements"] if e["tag"] == "p")
    anchor = {"kind": "text", "element": target["element"], "start": 0, "end": 7, "quote": "Caption"}
    receipt = api.add_comment(
        r["story_id"], r["revision_id"], "Check caption", "comment", anchor=anchor, author="agent"
    )
    assert receipt["annotation_id"]
    api.save_draft(r["story_id"], r["revision_id"], "draft", 1, "Keep it", anchor=anchor)


def test_portable_deck_keeps_navigation_and_media(tmp_path):
    """Both delivery modes include a player, without modifying the retained revision."""
    import zipfile

    api = Stories(tmp_path / "store")
    html = (
        '<html><body><section class="slide">One</section><section class="slide">Two</section></body></html>'
    )
    created = api.create_story("Deck", html, "deck")
    sid, rid = created["story_id"], created["revision_id"]
    standalone = base64.b64decode(api.get_export(sid, rid)["data_base64"]).decode()
    package = base64.b64decode(api.get_export(sid, rid, "zip")["data_base64"])
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        assert archive.read("index.html").decode() == standalone
    assert 'data-stories-presentation="1"' in standalone
    assert "Presentation navigation" in standalone
    assert "ArrowRight" in standalone
    assert api.get_revision(sid, rid)["html"] == html
