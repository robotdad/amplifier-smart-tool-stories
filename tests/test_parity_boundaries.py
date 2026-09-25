"""Shared adapter prerequisites: durable setup, inert view context, bounded video."""

import base64
import json
from pathlib import Path

import pytest

from amplifier_smart_tool_stories import Stories
from amplifier_smart_tool_stories.errors import StoriesError
from amplifier_smart_tool_stories.provider_jobs import run


def test_setup_receipt_survives_reconnect_without_replay_or_authority(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(
        "amplifier_smart_tool_stories.provider_jobs.subprocess.Popen", lambda *a, **k: calls.append(a)
    )
    api = Stories(tmp_path, model_env=True)
    receipt = api.start_provider_job("test", "setup", provider="anthropic")
    assert len(calls) == 1
    reopened = Stories(tmp_path, model_env=False)
    assert reopened.start_provider_job("test", "setup", provider="anthropic") == receipt
    assert len(calls) == 1
    with pytest.raises(StoriesError, match="already used"):
        reopened.start_provider_job("models", "setup", provider="anthropic")
    with pytest.raises(StoriesError, match="Enable model_env"):
        reopened.start_provider_job("models", "new", provider="anthropic")
    with pytest.raises(StoriesError, match="Wait for provider"):
        api.configure_provider("gemini")
    with pytest.raises(StoriesError, match="Another provider"):
        api.start_provider_job("models", "another", provider="anthropic")
    assert api.cancel_provider_job(receipt["job_id"])["status"] == "cancelled"
    assert api.start_provider_job("test", "setup", provider="anthropic") == receipt
    assert len(calls) == 1
    assert api.get_provider_job(receipt["job_id"])["status"] == "cancelled"


def test_setup_worker_progress_claim_and_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr("amplifier_smart_tool_stories.provider_jobs.subprocess.Popen", lambda *a, **k: None)
    api = Stories(tmp_path, model_env=True)
    receipt = api.start_provider_job("login", "login", provider="chatgpt")
    calls = []

    def login(self, provider=None, timeout_seconds=300, on_progress=None):
        calls.append(self.config.provider)
        for n in range(50):
            on_progress(str(n) + "x" * 2500)
        return {"status": "succeeded", "notice": "Synthetic fixture, no login"}

    monkeypatch.setattr(Stories, "provider_login", login)
    run(str(tmp_path), receipt["job_id"])
    run(str(tmp_path), receipt["job_id"])
    job = api.get_provider_job(receipt["job_id"])
    assert calls == ["chatgpt"]
    assert job["status"] == "succeeded"
    assert len(job["messages"]) == 30 and all(len(m) == 2000 for m in job["messages"])
    expired = api.start_provider_job("test", "expiry")
    with api.store.transaction() as db:
        row = api.store.get(db, "provider_jobs", expired["job_id"])
        row["deadline"] = 0
        api.store.put(db, "provider_jobs", row)
    assert api.get_provider_job(expired["job_id"])["error"]["code"] == "setup_timeout"


def test_setup_refuses_active_work_and_disabled_prepare(tmp_path, monkeypatch):
    api = Stories(tmp_path)
    with pytest.raises(StoriesError, match="Enable model_env"):
        api.prepare_runtime()
    r = api.create_story("Test", "<html><body><p>Work</p></body></html>", "create")
    api.grant_feedback(r["story_id"], {}, "grant")
    api.add_comment(r["story_id"], r["revision_id"], "Work", "comment")
    api.model_env = True
    with pytest.raises(StoriesError, match="Wait for current work"):
        api.start_provider_job("test", "setup")
    assert api.get_provider_job()["status"] == "idle"


def test_setup_cancellation_ack_is_separate_from_owned_cleanup(tmp_path, monkeypatch):
    import asyncio
    import threading

    from amplifier_smart_tool_stories.providers import _run_provider

    monkeypatch.setattr("amplifier_smart_tool_stories.provider_jobs.subprocess.Popen", lambda *a, **k: None)
    api = Stories(tmp_path, model_env=True)
    receipt = api.start_provider_job("login", "cancel-login", provider="chatgpt")
    entered, cleaned = threading.Event(), threading.Event()

    async def login():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            cleaned.set()

    monkeypatch.setattr(Stories, "provider_login", lambda self, **kwargs: _run_provider(login(), 5))
    worker = threading.Thread(target=run, args=(str(tmp_path), receipt["job_id"]))
    worker.start()
    assert entered.wait(3)
    assert api.cancel_provider_job(receipt["job_id"])["status"] == "cancelling"
    worker.join(3)
    assert not worker.is_alive() and cleaned.is_set()
    assert api.get_provider_job(receipt["job_id"])["status"] == "cancelled"


def test_native_context_is_cas_inert_and_scope_checked(tmp_path):
    api = Stories(tmp_path)
    r = api.create_story("Test", "<html><body><p>Work</p></body></html>", "create")
    payload = {"story_id": r["story_id"], "revision_id": r["revision_id"], "text": "Draft only"}
    context = {
        "document_view": {"mode": "paginated", "zoom": 1.25, "fit": False},
        "pending": {"comment": {"request_id": "future", "payload": payload}},
    }
    result = api.update_review_view(r["story_id"], 0, "view", native_context=context)
    assert Stories(tmp_path).get_review_view(r["story_id"]) == result
    assert api.get_story(r["story_id"])["annotations"] == []
    assert api.update_review_view(r["story_id"], 0, "view", native_context=context) == result
    with pytest.raises(StoriesError, match="Review view changed"):
        api.update_review_view(r["story_id"], 0, "stale", native_context={})
    with pytest.raises(StoriesError, match="Invalid document"):
        api.update_review_view(
            r["story_id"], 1, "invalid", native_context={"document_view": {"mode": "invented"}}
        )


def test_path_free_video_cleans_owned_output_and_checks_transfer_limit(tmp_path, monkeypatch):
    api = Stories(tmp_path)
    targets = []

    def export(story_id, revision_id, output_path, **options):
        path = Path(output_path)
        targets.append(path)
        path.write_bytes(b"retained-video")
        return {"path": str(path), "mime_type": "video/mp4", "story_id": story_id, "revision_id": revision_id}

    monkeypatch.setattr(api, "_export_video", export)
    result = api.get_video_export("story", "revision", "narration")
    assert base64.b64decode(result["data_base64"]) == b"retained-video"
    assert "path" not in result and not targets[-1].parent.exists()
    assert str(tmp_path) not in json.dumps(result)

    def oversize(story_id, revision_id, output_path, **options):
        with open(output_path, "wb") as file:
            file.truncate(128 * 1024 * 1024 + 1)
        targets.append(Path(output_path))
        return {"path": output_path}

    monkeypatch.setattr(api, "_export_video", oversize)
    with pytest.raises(StoriesError, match="128 MiB"):
        api.get_video_export("story", "revision", "narration")
    assert not targets[-1].parent.exists()
