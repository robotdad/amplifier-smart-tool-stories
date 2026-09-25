import json
import threading
import urllib.error
import urllib.request

import pytest

from amplifier_smart_tool_stories import Stories
from amplifier_smart_tool_stories.dashboard import Dashboard


@pytest.fixture
def server(tmp_path):
    api = Stories(tmp_path)
    r = api.create_story("Test", "<html><body><p>Hello world</p></body></html>", "s")
    other = api.create_story("Other", "<html><body><p>Private</p></body></html>", "o")
    api.grant_feedback(other["story_id"], {}, "g")
    op = api.add_comment(other["story_id"], other["revision_id"], "Private", "c")["operation_id"]
    server = Dashboard(api, r["story_id"])
    thread = threading.Thread(target=server.serve)
    thread.start()
    yield server, r, op
    server.server.shutdown()
    thread.join(5)


def post(server, name, data, token=None, origin=None):
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + (token or server.token)}
    if origin:
        headers["Origin"] = origin
    req = urllib.request.Request(
        f"http://127.0.0.1:{server.server.server_port}/api/{name}",
        data=json.dumps(data).encode(),
        headers=headers,
    )
    return urllib.request.urlopen(req)


def test_auth_origin_scope_and_no_arbitrary_capabilities(server):
    s, r, other_op = server
    for name, data, token, origin in [
        ("get-story", {}, "bad", None),
        ("get-story", {}, None, "null"),
        ("get-story", {}, None, "https://evil.test"),
        ("export", {"output_path": "/tmp/no"}, None, None),
        ("get-operation", {"operation_id": other_op}, None, None),
    ]:
        with pytest.raises(urllib.error.HTTPError):
            post(s, name, data, token, origin)
    with post(s, "get-story", {}) as response:
        assert json.load(response)["id"] == r["story_id"]


def test_dashboard_library_parity(server):
    s, r, _ = server
    with post(
        s, "add-comment", {"revision_id": r["revision_id"], "text": "Question", "request_id": "review"}
    ) as response:
        result = json.load(response)
    story = s.api.get_story(r["story_id"])
    assert story["annotations"][0]["id"] == result["annotation_id"]
    assert story["annotations"][0]["author"] == "user"
    with post(s, "download", {"revision_id": r["revision_id"]}) as response:
        assert response.read().decode() == "<html><body><p>Hello world</p></body></html>"


def test_owned_process_lifecycle_and_retention(tmp_path):
    api = Stories(tmp_path)
    created = api.create_story("Owned viewer", "<html><body><p>Retain me</p></body></html>", "create")
    viewer = api.start_dashboard(created["story_id"], created["revision_id"])
    assert viewer["url"].startswith("http://127.0.0.1:") and "#" in viewer["url"]
    assert api.stop_dashboard(viewer["service_id"])["status"] == "stopped"
    assert api.get_revision(created["story_id"], created["revision_id"])["html"].endswith("</html>")


def test_document_binary_downloads_use_exact_format_and_scope(tmp_path):
    import io
    import zipfile

    api = Stories(tmp_path)
    document = {
        "title": "Portable brief",
        "subtitle": "",
        "blocks": [
            {
                "id": "body",
                "kind": "paragraph",
                "text": "Retain this text.",
                "items": [],
                "rows": [],
                "evidence_ids": [],
            }
        ],
    }
    r = api.create_document("Brief", document, "doc")
    server = Dashboard(api, r["story_id"])
    thread = threading.Thread(target=server.serve)
    thread.start()
    try:
        with post(server, "download", {"revision_id": r["revision_id"], "format": "docx"}) as response:
            assert "story.docx" in response.headers["Content-Disposition"]
            assert "wordprocessingml" in response.headers["Content-Type"]
            with zipfile.ZipFile(io.BytesIO(response.read())) as archive:
                assert b"Retain this text" in archive.read("word/document.xml")
        with post(server, "download", {"revision_id": r["revision_id"], "format": "pdf"}) as response:
            assert response.read().startswith(b"%PDF")
            assert "story.pdf" in response.headers["Content-Disposition"]
        with pytest.raises(urllib.error.HTTPError):
            post(server, "download", {"revision_id": r["revision_id"], "format": "pptx"})
    finally:
        server.server.shutdown()
        thread.join(5)


def test_dashboard_control_bindings_have_unique_elements():
    import re
    from importlib.resources import files

    from bs4 import BeautifulSoup

    resources = files("amplifier_smart_tool_stories").joinpath("resources")
    html = BeautifulSoup(resources.joinpath("dashboard.html").read_text(), "html.parser")
    ids = [n["id"] for n in html.select("[id]")]
    assert len(ids) == len(set(ids))
    required = set(
        re.findall(
            r'\$\("([^"\n]+)"\)',
            resources.joinpath("dashboard.js").read_text()
            + resources.joinpath("provider-settings.js").read_text(),
        )
    )
    assert required <= set(ids), required - set(ids)


def test_provider_settings_are_authenticated_session_only(server, monkeypatch):
    s, r, _ = server
    monkeypatch.setenv("ANTHROPIC_API_KEY", "private-provider-secret")
    with pytest.raises(urllib.error.HTTPError):
        post(s, "provider-settings", {}, token="invalid")
    with post(s, "provider-settings", {}) as response:
        data = json.load(response)
    assert {p["name"] for p in data["providers"]} == {"anthropic", "openai", "gemini", "chatgpt", "copilot"}
    assert "private-provider-secret" not in json.dumps(data)
    before = s.api.get_story(r["story_id"])
    with post(s, "configure-provider", {"provider": "gemini", "model": "test-model"}) as response:
        assert json.load(response) == {"provider": "gemini", "model": "test-model"}
    assert s.api.get_story(r["story_id"]) == before
    with pytest.raises(urllib.error.HTTPError):
        post(s, "start-provider-job", {"provider": "gemini", "kind": "test"})


def test_provider_jobs_keep_dashboard_responsive_and_reject_overlap(server, monkeypatch):
    import time

    s, r, _ = server
    s.api.model_env = True
    entered, release = threading.Event(), threading.Event()

    def test(api, timeout_seconds=60):
        assert api.config.provider == "anthropic"
        entered.set()
        assert release.wait(5)
        return {"status": "succeeded", "model": "test-model"}

    monkeypatch.setattr(Stories, "test_provider", test)
    from amplifier_smart_tool_stories import provider_jobs

    s.api.cancel_operation(server[2])

    def launch(argv, **kwargs):
        worker = threading.Thread(target=provider_jobs.run, args=(argv[3], argv[4]), daemon=True)
        worker.start()
        return worker

    monkeypatch.setattr(provider_jobs.subprocess, "Popen", launch)
    try:
        with post(
            s, "start-provider-job", {"kind": "test", "provider": "anthropic", "request_id": "setup-1"}
        ) as response:
            assert json.load(response)["status"] == "running"
        assert entered.wait(2)
        with post(s, "get-story", {}) as response:
            assert json.load(response)["id"] == r["story_id"]
        for route, data in [
            ("configure-provider", {"provider": "gemini"}),
            ("start-provider-job", {"kind": "test", "provider": "openai", "request_id": "setup-2"}),
        ]:
            with pytest.raises(urllib.error.HTTPError):
                post(s, route, data)
    finally:
        release.set()
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        with post(s, "provider-job", {}) as response:
            job = json.load(response)
        if job["status"] != "running":
            break
        time.sleep(0.02)
    assert job["status"] == "succeeded"
    assert s.api.config.provider == "openai"  # Testing is not applying.


def test_acceptance_route_is_scoped_and_retained(server):
    s, r, _ = server
    result = json.load(post(s, "accept-revision", {"revision_id": r["revision_id"], "request_id": "accept"}))
    assert result["acceptance"]["revision_id"] == r["revision_id"]
    assert json.load(post(s, "get-story", {}))["acceptances"] == [result["acceptance"]]
    with pytest.raises(urllib.error.HTTPError):
        post(s, "accept-revision", {"revision_id": "other", "request_id": "bad-accept"})


def test_narration_dashboard_scope_and_no_path_input(server):
    s, r, other_op = server
    with post(s, "configure-narration", {"provider": "openai", "request_id": "speech-settings"}) as response:
        assert json.load(response)["effective"]["provider"] == "openai"
    with post(s, "narration-settings", {}) as response:
        assert json.load(response)["model_access"] is False
    with post(s, "get-speaker-notes", {"revision_id": r["revision_id"]}) as response:
        assert json.load(response)["notes"] == []
    for name, data in [
        ("cancel-operation", {"operation_id": other_op}),
        (
            "narrated-download",
            {"revision_id": r["revision_id"], "narration_id": "x", "output_path": "/tmp/unowned.mp4"},
        ),
        ("get-speaker-notes", {"revision_id": s.api.get_operation(other_op)["revision_id"]}),
    ]:
        with pytest.raises(urllib.error.HTTPError):
            post(s, name, data)


def test_script_routes_are_scoped_and_preparation_is_not_speech(server):
    s, r, other_op = server
    with post(s, "list-narration-scripts", {"revision_id": r["revision_id"]}) as response:
        assert json.load(response) == {"scripts": []}
    other_revision = s.api.get_operation(other_op)["revision_id"]
    for name, data in [
        ("prepare-narration", {"revision_id": other_revision, "grant": {}, "request_id": "wrong-script"}),
        (
            "save-narration-script",
            {"revision_id": other_revision, "notes": ["Private"], "request_id": "wrong-script-save"},
        ),
        ("list-narration-scripts", {"revision_id": other_revision}),
    ]:
        with pytest.raises(urllib.error.HTTPError):
            post(s, name, data)
    assert s.api.narration_settings()["effective"] is None
