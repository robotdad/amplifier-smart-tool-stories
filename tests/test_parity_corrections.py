"""Regressions for independently reproduced parity acceptance failures."""

import asyncio
import json
import threading
from pathlib import Path

import pytest
from mcp import Client
from test_dashboard import post

from amplifier_smart_tool_stories import Stories, StoriesError
from amplifier_smart_tool_stories.dashboard import Dashboard
from amplifier_smart_tool_stories.mcp import create_server
from amplifier_smart_tool_stories.provider_jobs import run
from amplifier_smart_tool_stories.providers import _run_provider

HTML = '<html><body><section class="slide"><p>Exact retained content</p></section></body></html>'


def test_clock_skewed_stale_mcp_cannot_overwrite_http_draft(tmp_path):
    api = Stories(tmp_path)
    ids = api.create_story("Shared draft", HTML, "create")
    args = {key: ids[key] for key in ("story_id", "revision_id")}
    initial = api.save_draft(**args, draft_id="shared", sequence=10, text="Original", expected_version=0)
    a = api.get_story(ids["story_id"])["drafts"]["shared"]
    b = Stories(tmp_path).get_story(ids["story_id"])["drafts"]["shared"]
    server = Dashboard(api, ids["story_id"])
    worker = threading.Thread(target=server.serve)
    worker.start()
    try:
        saved = json.load(
            post(
                server,
                "save-draft",
                {
                    **args,
                    "draft_id": "shared",
                    "sequence": 11,
                    "text": "Acknowledged A",
                    "expected_version": a["version"],
                },
            )
        )
        assert saved["version"] == initial["version"] + 1

        async def check():
            async with Client(create_server(Stories(tmp_path))) as client:
                result = await client.call_tool(
                    "stories_save_draft",
                    {
                        **args,
                        "draft_id": "shared",
                        "sequence": 9999999999999,
                        "text": "Stale B",
                        "expected_version": b["version"],
                    },
                )
                assert result.is_error and result.structured_content["error"]["code"] == "draft_conflict"

        asyncio.run(check())
        assert api.get_story(ids["story_id"])["drafts"]["shared"]["text"] == "Acknowledged A"
        # A lost acknowledgement can retry exactly without advancing again.
        assert (
            api.save_draft(
                **args, draft_id="shared", sequence=11, text="Acknowledged A", expected_version=a["version"]
            )
            == saved
        )
        with pytest.raises(StoriesError, match="requires its observed version"):
            api.save_draft(**args, draft_id="shared", sequence=99999999999999, text="Legacy bypass")
        # Legacy isolated draft identities retain their documented ordering.
        assert api.save_draft(**args, draft_id="legacy", sequence=2, text="Legacy")["status"] == "saved"
        assert api.save_draft(**args, draft_id="legacy", sequence=1, text="Older")["status"] == "stale"
    finally:
        server.server.shutdown()
        worker.join(5)


def test_timeout_keeps_exclusion_until_cleanup_settles(tmp_path, monkeypatch):
    launches = []
    monkeypatch.setattr(
        "amplifier_smart_tool_stories.provider_jobs.subprocess.Popen", lambda *a, **kw: launches.append(a)
    )
    entered, cleaning, release = threading.Event(), threading.Event(), threading.Event()

    async def login():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaning.set()
            while not release.is_set():
                await asyncio.sleep(0.01)

    monkeypatch.setattr(Stories, "provider_login", lambda self, **kw: _run_provider(login(), 10))
    api = Stories(tmp_path, model_env=True)
    receipt = api.start_provider_job("login", "first")
    worker = threading.Thread(target=run, args=(tmp_path, receipt["job_id"]))
    worker.start()
    try:
        assert entered.wait(3)
        with api.store.transaction() as db:
            job = api.store.get(db, "provider_jobs", receipt["job_id"])
            job["deadline"] = 0
            api.store.put(db, "provider_jobs", job)
        assert api.get_provider_job(receipt["job_id"])["status"] == "timing_out"
        assert cleaning.wait(3)
        with pytest.raises(StoriesError) as e:
            api.configure_provider("gemini")
        assert e.value.code == "provider_busy"
        with pytest.raises(StoriesError) as e:
            api.start_provider_job("test", "second")
        assert e.value.code == "provider_busy"
        assert api.start_provider_job("login", "first") == receipt and len(launches) == 1
    finally:
        release.set()
        worker.join(3)
    assert not worker.is_alive()
    assert api.get_provider_job(receipt["job_id"])["status"] == "failed"
    api.configure_provider("gemini")
    api.start_provider_job("test", "second")
    assert len(launches) == 2


def test_dead_owner_unclaimed_admission_and_fake_intelligence(tmp_path, monkeypatch):
    launches = []
    monkeypatch.setattr(
        "amplifier_smart_tool_stories.provider_jobs.subprocess.Popen", lambda *a, **kw: launches.append(a)
    )
    api = Stories(tmp_path, model_env=True)
    receipt = api.start_provider_job("test", "lost")
    # Claimed but no kernel lease: owner is demonstrably gone, even if PID was reused.
    with api.store.transaction() as db:
        job = api.store.get(db, "provider_jobs", receipt["job_id"])
        job.update(owner_claimed=True, pid=__import__("os").getpid())
        api.store.put(db, "provider_jobs", job)
    assert api.get_provider_job(receipt["job_id"])["error"]["code"] == "setup_owner_lost"
    assert api.start_provider_job("test", "lost") == receipt and len(launches) == 1
    pending = api.start_provider_job("test", "pre-dispatch")
    with pytest.raises(StoriesError):
        api.configure_provider("gemini")
    with api.store.transaction() as db:
        job = api.store.get(db, "provider_jobs", pending["job_id"])
        job["deadline"] = 0
        api.store.put(db, "provider_jobs", job)
    assert api.get_provider_job(pending["job_id"])["status"] == "failed"
    monkeypatch.setattr(Stories, "test_provider", lambda self: pytest.fail("expired worker replay"))
    run(tmp_path, pending["job_id"])
    disabled = Stories(tmp_path, intelligence=object())
    for kind in ("login", "prepare", "models", "test"):
        with pytest.raises(StoriesError) as e:
            disabled.start_provider_job(kind, kind)
        assert e.value.code == "model_access_required"
    assert len(launches) == 2


def test_path_free_video_descriptor_and_events_omit_temporary_path(tmp_path, monkeypatch):
    api = Stories(tmp_path)
    ids = api.create_story("Video", HTML, "create")
    monkeypatch.setattr(api, "get_narration", lambda story_id, narration_id: {"id": "synthetic"})

    def encode(api, revision, media, narration, output_path, *args):
        Path(output_path).write_bytes(b"synthetic-video")
        return {"path": output_path, "mime_type": "video/mp4", "status": "succeeded"}

    monkeypatch.setattr("amplifier_smart_tool_stories.narrated_video.export", encode)

    async def check():
        async with Client(create_server(api)) as client:
            result = await client.call_tool(
                "stories_get_video_export",
                {
                    "story_id": ids["story_id"],
                    "revision_id": ids["revision_id"],
                    "narration_id": "synthetic",
                },
            )
            assert not result.is_error
            events = await client.call_tool("stories_read_changes", {"story_id": ids["story_id"]})
            for value in (result.structured_content, events.structured_content):
                assert str(tmp_path) not in json.dumps(value)
                assert '"path":' not in json.dumps(value)

    asyncio.run(check())
    destination = tmp_path / "explicit.mp4"
    api.export_video(ids["story_id"], ids["revision_id"], str(destination), narration_id="synthetic")
    assert str(destination) in json.dumps(api.read_changes(ids["story_id"]))
