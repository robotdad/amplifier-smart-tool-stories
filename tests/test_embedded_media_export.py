"""Portable media export is exact, bounded, explicit and provider-free."""

import base64
import hashlib
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import zipfile

import pytest
from bs4 import BeautifulSoup
from PIL import Image

from amplifier_smart_tool_stories import Stories, exports
from amplifier_smart_tool_stories.errors import StoriesError


@pytest.fixture(autouse=True)
def no_provider(monkeypatch):
    # Deterministic public paths must not import/boot the embedded agent.
    monkeypatch.setitem(sys.modules, "amplifier_agent", None)
    for name in list(os.environ):
        if any(part in name for part in ("API_KEY", "ACCESS_TOKEN", "AUTH_TOKEN")):
            monkeypatch.delenv(name)


def make_clip(extension, tmp_path_factory):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("Real media fixtures require ffmpeg and ffprobe")
    path = tmp_path_factory.mktemp("embedded-clips") / ("clip." + extension)
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=blue:s=64x64:r=10:d=0.3",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:duration=0.3",
            "-c:v",
            "libx264" if extension == "mp4" else "libvpx-vp9",
            "-c:a",
            "aac" if extension == "mp4" else "libopus",
            "-pix_fmt",
            "yuv420p",
            "-shortest",
            str(path),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    return "video/" + extension, path.read_bytes()


@pytest.fixture(scope="module", params=["mp4", "webm"])
def clip(request, tmp_path_factory):
    return make_clip(request.param, tmp_path_factory)


@pytest.fixture(scope="module")
def mp4_clip(tmp_path_factory):
    return make_clip("mp4", tmp_path_factory)


def imported(api, name, mime, data):
    return api.import_media(
        name,
        mime,
        name,
        data_base64=base64.b64encode(data).decode(),
        attribution="Test fixture, generated locally; not factual evidence.",
    )["asset"]


def media_story(tmp_path, clip, source_child=False):
    api = Stories(tmp_path / "store", model_env=False)
    mime, data = clip
    video = imported(api, "Clip", mime, data)
    png = io.BytesIO()
    Image.new("RGB", (64, 64), "blue").save(png, format="PNG")
    poster = imported(api, "Poster", "image/png", png.getvalue())
    vtt = b"WEBVTT\n\n00:00.000 --> 00:00.300\nA blue test frame.\n"
    captions = imported(api, "Captions", "text/vtt", vtt)
    video_src = "" if source_child else f'src="asset:{video["id"]}"'
    source = f'<source src="asset:{video["id"]}" type="{mime}">' if source_child else ""
    html = (
        '<html><body><section class="slide"><h1>Demo</h1>'
        f'<img src="asset:{poster["id"]}" alt="Blue poster">'
        f'<video controls {video_src} poster="asset:{poster["id"]}">'
        f'{source}<track kind="captions" srclang="en" default src="asset:{captions["id"]}">'
        "A blue test frame with a tone.</video></section>"
        '<section class="slide"><h1>End</h1></section></body></html>'
    )
    assets = [video, poster, captions]
    result = api.create_story("Demo", html, "create", asset_ids=[a["id"] for a in assets])
    raw = {video["id"]: data, poster["id"]: png.getvalue(), captions["id"]: vtt}
    return api, result["story_id"], result["revision_id"], assets, raw


@pytest.mark.parametrize("source_child", [False, True])
def test_html_and_zip_preserve_exact_media_and_independent_originals(tmp_path, clip, source_child):
    api, sid, rid, assets, raw = media_story(tmp_path, clip, source_child)
    before = api.get_revision(sid, rid)
    api.add_comment(sid, rid, "PRIVATE REVIEW", "comment", author="agent")
    result = api.get_export(sid, rid, format="html")
    html = base64.b64decode(result["data_base64"])
    soup = BeautifulSoup(html, "html.parser")
    expected = {(a["mime_type"], raw[a["id"]]) for a in assets}
    found = set()
    for node in soup.select("img,video,source,track"):
        for attr in ("src", "poster"):
            if attr in node.attrs:
                header, encoded = node[attr].split(",", 1)
                assert header.endswith(";base64")
                found.add((header[5:-7], base64.b64decode(encoded, validate=True)))
    assert found == expected
    assert soup.video.has_attr("controls")
    assert soup.track["kind"] == "captions"
    assert soup.select_one("script[data-stories-presentation]")
    assert b"asset:" not in html and b"PRIVATE REVIEW" not in html
    assert str(tmp_path).encode() not in html
    assert result["mime_type"] == "text/html"
    assert result["size_bytes"] == len(html)
    assert result["sha256"] == hashlib.sha256(html).hexdigest()
    assert result["assets"] == assets
    assert assets[0]["has_audio"]  # Audio remains in the unchanged video container.
    assert result["media_size_bytes"] == sum(map(len, raw.values()))
    assert result["embedded_media_size_bytes"] == sum(map(len, raw.values())) + len(raw[assets[1]["id"]])
    assert result["checks"]["media_playback"] == "not_performed"
    assert result["checks"]["visual"] == "not_performed"
    assert "caption synchronization" in " ".join(result["limitations"])
    assert api.get_export(sid, rid, "html") == result
    assert api.get_revision(sid, rid) == before
    package = api.get_export(sid, rid, "zip")
    assert package == api.get_export(sid, rid, "zip")
    assert package["embedded_media_size_bytes"] == 0
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(package["data_base64"]))) as archive:
        packaged_html = archive.read("index.html")
        assert b"data:video/" not in packaged_html
        assert b"asset:" not in packaged_html
        assert json.loads(archive.read("manifest.json"))["assets"] == assets
        for asset in assets:
            path = f"assets/{asset['id']}.{exports_extension(asset)}"
            assert archive.read(path) == raw[asset["id"]]
            assert path.encode() in packaged_html
    for asset in assets:
        retained = api.get_media(sid, rid, asset["id"])
        assert retained["asset"] == asset
        assert base64.b64decode(retained["data_base64"]) == raw[asset["id"]]


def exports_extension(asset):
    from amplifier_smart_tool_stories.media import EXTENSIONS

    return EXTENSIONS[asset["mime_type"]]


def run_cli(store, command, payload, cwd):
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "amplifier_smart_tool_stories",
            "--store",
            str(store),
            command,
            "--input",
            json.dumps(payload),
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
        timeout=40,
    )


@pytest.mark.parametrize("format", ["html", "zip"])
def test_explicit_library_and_cli_destinations_no_overwrite_or_extra_files(tmp_path, clip, format):
    api, sid, rid, assets, raw = media_story(tmp_path, clip)
    directory = tmp_path / "delivery"
    directory.mkdir()
    library_path = directory / f"library.{format}"
    library = api.export(sid, rid, str(library_path), format=format)
    cli_path = directory / f"cli.{format}"
    command = run_cli(
        tmp_path / "store",
        "export",
        {
            "story_id": sid,
            "revision_id": rid,
            "format": format,
            "output_path": str(cli_path),
        },
        directory,
    )
    assert command.returncode == 0, command.stdout + command.stderr
    cli = json.loads(command.stdout)
    assert cli["status"] == library["status"] == "succeeded"
    assert cli["sha256"] == library["sha256"]
    assert cli["assets"] == assets
    assert cli_path.read_bytes() == library_path.read_bytes()
    assert {p.name for p in directory.iterdir()} == {f"cli.{format}", f"library.{format}"}
    with pytest.raises(StoriesError) as error:
        api.export(sid, rid, str(library_path), format=format)
    assert error.value.code == "output_exists"
    duplicate = run_cli(
        tmp_path / "store",
        "export",
        {
            "story_id": sid,
            "revision_id": rid,
            "format": format,
            "output_path": str(cli_path),
        },
        directory,
    )
    assert duplicate.returncode != 0
    assert json.loads(duplicate.stdout)["error"]["code"] == "output_exists"
    assert hashlib.sha256(cli_path.read_bytes()).hexdigest() == cli["sha256"]


@pytest.mark.parametrize("mutation", ["missing", "corrupt"])
def test_retained_media_failure_precedes_destination_write(tmp_path, clip, mutation):
    api, sid, rid, assets, raw = media_story(tmp_path, clip)
    with api.store.transaction() as db:
        if mutation == "missing":
            db.execute("DELETE FROM media WHERE id=?", (assets[0]["id"],))
        else:
            db.execute("UPDATE media SET content=? WHERE id=?", (b"changed", assets[0]["id"]))
    target = tmp_path / "must-not-exist.html"
    with pytest.raises(StoriesError):
        api.export(sid, rid, str(target), "html")
    assert not target.exists()
    cli = run_cli(
        tmp_path / "store",
        "export",
        {
            "story_id": sid,
            "revision_id": rid,
            "format": "html",
            "output_path": str(target),
        },
        tmp_path,
    )
    assert cli.returncode != 0
    assert json.loads(cli.stdout)["error"]["code"] in {"missing_asset", "invalid_media"}
    assert not target.exists()


@pytest.mark.parametrize(
    "reference",
    [
        "asset:not-attached",
        "file:///secret.mp4",
        "https://example.invalid/clip.mp4",
        "../clip.mp4",
        "data:video/mp4;base64,AAAA",
    ],
)
def test_zip_rejects_unretained_references_without_attached_assets(tmp_path, reference):
    api = Stories(tmp_path / "store")
    created = api.create_story(
        "Unretained",
        f'<html><body><h1>Clip</h1><video src="{reference}"></video></body></html>',
        "create",
    )
    target = tmp_path / "must-not-exist.zip"
    with pytest.raises(StoriesError) as error:
        api.export(created["story_id"], created["revision_id"], str(target), "zip")
    assert error.value.code == "missing_asset"
    assert not target.exists()


def test_asset_in_store_is_not_authority_for_another_revision(tmp_path, clip):
    api, sid, rid, assets, raw = media_story(tmp_path, clip)
    other = api.create_story(
        "Other",
        f'<html><body><h1>Clip</h1><video src="asset:{assets[0]["id"]}"></video></body></html>',
        "other",
    )
    with pytest.raises(StoriesError, match="retained asset"):
        api.get_export(other["story_id"], other["revision_id"], "html")


@pytest.mark.parametrize(
    "dependency",
    [
        "<script>alert(1)</script>",
        '<iframe src="https://example.invalid"></iframe>',
        '<link rel="stylesheet" href="https://example.invalid/style.css">',
        "<style>body{background:url(file:///secret)}</style>",
        '<p onclick="alert(1)">Click</p>',
        '<img srcset="https://example.invalid/a.png 2x">',
        '<base href="https://example.invalid/">',
    ],
)
def test_embedding_does_not_relax_portable_markup_security(tmp_path, clip, dependency):
    api, sid, rid, assets, raw = media_story(tmp_path, clip)
    revision = api.get_revision(sid, rid)
    changed = api.revise_media(
        sid,
        rid,
        [a["id"] for a in assets],
        "unsafe",
        html=revision["html"].replace("</body>", dependency + "</body>"),
    )
    target = tmp_path / "must-not-exist.html"
    with pytest.raises(StoriesError) as error:
        api.export(sid, changed["revision_id"], str(target), "html")
    assert error.value.code == "external_dependency"
    assert not target.exists()


def test_embedding_budget_counts_repeated_uses_before_encoding(tmp_path, clip, monkeypatch):
    api, sid, rid, assets, raw = media_story(tmp_path, clip)
    # One poster is used twice. Unique-asset accounting alone would miss this.
    monkeypatch.setattr(exports, "MAX_EMBEDDED_MEDIA_BYTES", sum(map(len, raw.values())))
    target = tmp_path / "must-not-exist.html"
    with pytest.raises(StoriesError, match="Choose ZIP") as error:
        api.export(sid, rid, str(target), "html")
    assert error.value.code == "resource_limit"
    assert not target.exists()
    assert api.get_export(sid, rid, "zip")["format"] == "zip"


def test_large_retained_video_does_not_spend_markup_budget(tmp_path, mp4_clip):
    mime, data = mp4_clip
    # The MP4 free box supplies legal, deterministic container padding.
    padding_size = 25 * 1024 * 1024
    data += struct.pack(">I4s", padding_size, b"free") + b"\0" * (padding_size - 8)
    api = Stories(tmp_path / "store")
    asset = imported(api, "Large clip", mime, data)
    created = api.create_story(
        "Large",
        '<html><body><section class="slide">'
        f'<video controls src="asset:{asset["id"]}">Blue frame</video>'
        "</section></body></html>",
        "create",
        asset_ids=[asset["id"]],
    )
    result = api.export(created["story_id"], created["revision_id"], str(tmp_path / "large.html"), "html")
    output = (tmp_path / "large.html").read_bytes()
    assert len(output) == result["size_bytes"] > 32 * 1024 * 1024
    encoded = output.split(b"data:video/mp4;base64,", 1)[1].split(b'"', 1)[0]
    assert base64.b64decode(encoded) == data
    assert result["assets"][0]["sha256"] == hashlib.sha256(data).hexdigest()
    assert (
        base64.b64decode(
            api.get_media(
                created["story_id"],
                created["revision_id"],
                asset["id"],
            )["data_base64"]
        )
        == data
    )


@pytest.mark.parametrize("format", ["html", "zip", "docx", "pdf"])
def test_export_preserves_attributed_source_qualifications(tmp_path, format):
    from test_documents import document

    api = Stories(tmp_path / "store")
    created = api.create_story("Qualifications", "", "create", document=document())
    sid, rid = created["story_id"], created["revision_id"]
    # Seed a retained model-review record without running a provider.
    with api.store.transaction() as db:
        story = api.store.get(db, "stories", sid)
        revision = api._revision(story, rid)
        revision["limitations"] = ["Source figures are estimates."]
        revision["quality_review"] = {
            "method": "model_review",
            "warnings": ["The cost estimate lacks independent confirmation."],
            "limits": ["Static review did not inspect playback."],
        }
        api.store.put(db, "stories", story)
    before = api.get_revision(sid, rid)
    result = api.get_export(sid, rid, format)
    expected = [
        "Source revision limitation (not an export check): Source figures are estimates.",
        "Source model review warning (not an export check): The cost estimate lacks independent confirmation.",
        "Source model review scope limit (not an export check): Static review did not inspect playback.",
    ]
    assert all(value in result["limitations"] for value in expected)
    assert "estimate" not in json.dumps(result["checks"])
    assert result["checks"]["visual"] == "not_performed"
    assert api.get_revision(sid, rid) == before
    cli = run_cli(
        tmp_path / "store",
        "get-export",
        {
            "story_id": sid,
            "revision_id": rid,
            "format": format,
        },
        tmp_path,
    )
    assert cli.returncode == 0, cli.stdout + cli.stderr
    assert all(value in json.loads(cli.stdout)["limitations"] for value in expected)


@pytest.mark.parametrize("scripted", [False, True])
@pytest.mark.parametrize("reference", ["data", "relative", "remote", "empty-video"])
def test_imported_original_media_html_passthrough_with_caveats(tmp_path, scripted, reference):
    api = Stories(tmp_path / "store")
    png = io.BytesIO()
    Image.new("RGB", (2, 2), "blue").save(png, format="PNG")
    data_uri = "data:image/png;base64," + base64.b64encode(png.getvalue()).decode()
    media = {
        "data": f'<img src="{data_uri}">',
        "relative": '<img src="picture.png">',
        "remote": '<img src="https://example.invalid/picture.png">',
        "empty-video": "<video controls></video>",
    }[reference]
    script = '<script>console.log("retained controls")</script>' if scripted else ""
    html = '<html><body><section class="slide"><h1>Import</h1>' + media + script + "</section></body></html>"
    created = api.create_story("Import", html, "create")
    sid, rid = created["story_id"], created["revision_id"]
    exported = api.get_export(sid, rid, "html")
    assert base64.b64decode(exported["data_base64"]) == html.encode()
    assert exported["assets"] == []
    assert exported["embedded_media_size_bytes"] == 0
    assert any("not validated as a portable package" in v for v in exported["limitations"])
    if reference != "empty-video":
        assert any("unretained media references" in v for v in exported["limitations"])
    cli = run_cli(
        tmp_path / "store",
        "export",
        {
            "story_id": sid,
            "revision_id": rid,
            "format": "html",
            "output_path": str(tmp_path / "original.html"),
        },
        tmp_path,
    )
    assert cli.returncode == 0, cli.stdout
    assert (tmp_path / "original.html").read_bytes() == html.encode()
    assert api.get_revision(sid, rid)["html"] == html


@pytest.mark.parametrize("format", ["html", "zip"])
@pytest.mark.parametrize(
    "dependency",
    [
        '<svg><image href="https://example.invalid/private.png"/></svg>',
        '<svg><image xlink:href="https://example.invalid/private.png"/></svg>',
        '<svg><use href="https://example.invalid/icons.svg#icon"/></svg>',
        '<svg><use xlink:href="../icons.svg#icon"/></svg>',
        '<svg><image href="data:image/svg+xml,unsafe"/></svg>',
        '<svg><rect fill="url(https://example.invalid/paint.svg#p)"/></svg>',
        r'<svg><rect fill="u\72l(https://example.invalid/paint.svg#p)"/></svg>',
        '<svg><rect filter="url(&quot;https://example.invalid/f.svg#f&quot;)"/></svg>',
        '<svg><rect style="fill:url(https://example.invalid/p.svg#p)"/></svg>',
        '<svg><image href="#absent"/></svg>',
        '<svg><use href="#icon"/><g id="icon" xml:base="https://example.invalid/"/></svg>',
        '<svg><animate attributeName="href" values="https://example.invalid/a"/></svg>',
        '<svg><set attributeName="href" to="javascript:alert(1)"/></svg>',
        "<svg><foreignObject><p>Foreign HTML</p></foreignObject></svg>",
        '<svg><filter><feImage href="https://example.invalid/a"/></filter></svg>',
        '<a href="javascript:alert(document.domain)">Link</a>',
        '<a href="JaVaScRiPt:alert(1)">Link</a>',
        '<a href="java&#x09;script:alert(1)">Link</a>',
        '<a href="&#x0a;javascript:alert(1)">Link</a>',
        '<svg><a xlink:href="javascript:alert(1)"><text>Link</text></a></svg>',
        '<a href="data:text/html,unsafe">Link</a>',
        '<a href="https://example.invalid" ping="https://example.invalid/track">Link</a>',
        '<input type="image" src="https://example.invalid/button.png">',
        '<form action="https://example.invalid/submit"><button>Submit</button></form>',
        '<style>body{background:image-set("https://example.invalid/a.png" 1x)}</style>',
        '<frame src="https://example.invalid/frame">',
        '<applet code="https://example.invalid/App.class"></applet>',
    ],
)
def test_portable_boundary_rejects_active_links_and_svg_resources(tmp_path, format, dependency):
    api = Stories(tmp_path / "store")
    captions = imported(api, "Captions", "text/vtt", b"WEBVTT\n")
    html = (
        "<html><body><h1>Clip</h1><video controls>"
        f'<track src="asset:{captions["id"]}"></video>' + dependency + "</body></html>"
    )
    result = api.create_story("Probe", html, "create", asset_ids=[captions["id"]])
    destination = tmp_path / ("unsafe." + format)
    with pytest.raises(StoriesError) as error:
        api.export(result["story_id"], result["revision_id"], str(destination), format)
    assert error.value.code == "external_dependency"
    assert not destination.exists()
    assert api.get_revision(result["story_id"], result["revision_id"])["html"] == html
    if dependency in {
        '<svg><image href="https://example.invalid/private.png"/></svg>',
        '<a href="javascript:alert(document.domain)">Link</a>',
    }:
        cli = run_cli(
            tmp_path / "store",
            "export",
            {
                "story_id": result["story_id"],
                "revision_id": result["revision_id"],
                "format": format,
                "output_path": str(destination),
            },
            tmp_path,
        )
        assert cli.returncode != 0
        assert json.loads(cli.stdout)["error"]["code"] == "external_dependency"
        assert not destination.exists()


@pytest.mark.parametrize("format", ["html", "zip"])
def test_portable_static_inline_svg_and_explicit_evidence_navigation(tmp_path, format):
    api = Stories(tmp_path / "store")
    captions = imported(api, "Captions", "text/vtt", b"WEBVTT\n")
    svg = (
        '<svg viewBox="0 0 20 20"><title>Static icon</title><defs>'
        '<linearGradient id="paint"><stop offset="0" stop-color="blue"/></linearGradient>'
        '<symbol id="icon"><path d="M0 0L10 10"/></symbol></defs>'
        '<rect width="20" height="20" fill="url(#paint)"/>'
        '<circle r="2" fill="url(&quot;#paint&quot;)"/>'
        '<use href="#icon"/><use xlink:href="#icon"/>'
        '<a href="https://example.invalid/evidence"><text>Evidence</text></a></svg>'
    )
    html = (
        '<html><body><h1 id="heading">Clip</h1>'
        '<a href="https://example.invalid/source">Source</a>'
        '<a href="http://example.invalid/source">Other source</a>'
        '<a href="#heading">Heading</a><video controls>'
        f'<track src="asset:{captions["id"]}"></video>' + svg + "</body></html>"
    )
    created = api.create_story("Static SVG", html, "create", asset_ids=[captions["id"]])
    exported = api.get_export(created["story_id"], created["revision_id"], format)
    data = base64.b64decode(exported["data_base64"])
    if format == "zip":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            data = archive.read("index.html")
    soup = BeautifulSoup(data, "html.parser")
    assert soup.svg and soup.svg.path and len(soup.select("use")) == 2
    assert soup.rect["fill"] == "url(#paint)"
    assert soup.circle["fill"] == 'url("#paint")'
    assert soup.select_one('a[href="https://example.invalid/source"]')
    assert soup.select_one('a[href="http://example.invalid/source"]')
    assert api.get_revision(created["story_id"], created["revision_id"])["html"] == html


def test_generated_html_without_assets_still_uses_strict_boundary(tmp_path):
    api = Stories(tmp_path / "store")
    result = api.create_story(
        "Generated",
        '<html><body><h1>Generated</h1><a href="javascript:alert(1)">Unsafe</a></body></html>',
        "create",
    )
    with api.store.transaction() as db:
        story = api.store.get(db, "stories", result["story_id"])
        api._revision(story, result["revision_id"])["origin"] = "model"
        api.store.put(db, "stories", story)
    with pytest.raises(StoriesError) as error:
        api.get_export(result["story_id"], result["revision_id"], "html")
    assert error.value.code == "external_dependency"


@pytest.mark.parametrize("format", ["html", "zip"])
def test_source_type_hint_must_match_retained_container(tmp_path, clip, format):
    api, sid, rid, assets, raw = media_story(tmp_path, clip, source_child=True)
    html = api.get_revision(sid, rid)["html"]
    bad = api.revise_media(
        sid,
        rid,
        [a["id"] for a in assets],
        "bad-type",
        html=html.replace(f'type="{clip[0]}"', 'type="application/not-supported"'),
    )
    destination = tmp_path / ("bad-type." + format)
    with pytest.raises(StoriesError, match="Source type hint"):
        api.export(sid, bad["revision_id"], str(destination), format)
    assert not destination.exists()
