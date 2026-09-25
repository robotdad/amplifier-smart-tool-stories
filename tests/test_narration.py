"""Narration retention, spending boundaries and actual synchronized media delivery."""

import asyncio
import base64
import io
import json
import math
import shutil
import struct
import threading
import wave
import zipfile

import pytest

from amplifier_smart_tool_stories import Stories, StoriesError
from amplifier_smart_tool_stories.speech import wav

HTML = '<html><head><style>body{margin:0}.slide{width:1280px;height:720px;page-break-after:always}.slide:last-child{page-break-after:auto}.notes{display:none}</style></head><body><section class="slide">First<aside class="notes">First note.</aside></section><section class="slide">Second<aside class="notes">Second note.</aside></section></body></html>'


def fixture(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-secret")
    api = Stories(tmp_path / "store", model_env=True, execution="in_process")
    r = api.create_story("Narrated test", HTML, "create")
    api.configure_narration("openai", "config")
    calls = []

    async def speak(text, config, timeout):
        calls.append((text, config.copy()))
        hz = 440 if text.startswith("First") else 880
        pcm = b"".join(
            struct.pack("<h", int(10000 * math.sin(2 * math.pi * hz * i / 24000))) for i in range(4800)
        )
        return wav(pcm)

    monkeypatch.setattr("amplifier_smart_tool_stories.speech.synthesize", speak)
    return api, r, calls


def generate(api, r, request_id="speech", **kwargs):
    receipt = api.generate_narration(
        r["story_id"], r["revision_id"], {"max_requests": 2}, request_id, **kwargs
    )
    return receipt, api.get_operation(receipt["operation_id"])


def test_gemini_narration_defaults(tmp_path):
    api = Stories(tmp_path / "store")
    settings = api.narration_settings()
    assert settings["effective"] is None
    gemini = next(p for p in settings["providers"] if p["provider"] == "gemini")
    assert gemini["model"] == "gemini-3.1-flash-tts-preview"
    assert gemini["voice"] == "Kore"
    assert gemini["speech_access"] == "not_tested"
    result = api.configure_narration("gemini", "config")
    assert result["effective"] == {
        "provider": "gemini",
        "model": "gemini-3.1-flash-tts-preview",
        "voice": "Kore",
        "instructions": "",
    }
    assert Stories(tmp_path / "store").narration_settings()["effective"] == result["effective"]


@pytest.mark.parametrize("model", ["gemini-2.5-flash-preview-tts", "custom-speech-model"])
def test_gemini_explicit_model_and_saved_settings_survive_reopen(tmp_path, model):
    api = Stories(tmp_path / "store")
    result = api.configure_narration(
        "gemini", "config", model=model, voice="Puck", instructions="Speak calmly."
    )
    expected = {
        "provider": "gemini",
        "model": model,
        "voice": "Puck",
        "instructions": "Speak calmly.",
    }
    assert result["effective"] == expected
    reopened = Stories(tmp_path / "store")
    settings = reopened.narration_settings()
    assert settings["effective"] == expected
    gemini = next(p for p in settings["providers"] if p["provider"] == "gemini")
    assert gemini["model"] == "gemini-3.1-flash-tts-preview"
    assert (
        reopened.configure_narration(
            "gemini", "config", model=model, voice="Puck", instructions="Speak calmly."
        )
        == result
    )
    # Queuing uses the retained settings, not the new provider default; no synthesis runs.
    story = reopened.create_story("Saved speech settings", HTML, "create")
    receipt = reopened.generate_narration(story["story_id"], story["revision_id"], {}, "speech")
    narration = reopened.get_narration(story["story_id"], receipt["narration_id"])
    assert narration["settings"] == expected
    assert reopened.get_operation(receipt["operation_id"])["state"] == "queued"


def test_reuse_notes_settings_and_exact_retry(tmp_path, monkeypatch):
    api, r, calls = fixture(tmp_path, monkeypatch)
    receipt, op = generate(api, r)
    assert op["state"] == "succeeded"
    assert [c[0] for c in calls] == ["First note.", "Second note."]
    assert generate(api, r)[0] == receipt
    assert len(calls) == 2
    # Re-encoding/reusing completed audio requires neither credentials nor model access.
    monkeypatch.delenv("OPENAI_API_KEY")
    api.model_env = False
    reused, reused_op = generate(api, r, "reuse")
    assert reused_op["state"] == "succeeded" and reused_op["requests_used"] == 0
    assert (
        api.get_narration(r["story_id"], reused["narration_id"])["clips"]
        == api.get_narration(r["story_id"], receipt["narration_id"])["clips"]
    )
    assert len(calls) == 2
    assert api.get_speaker_notes(r["story_id"], r["revision_id"])["notes"] == ["First note.", "Second note."]


def test_only_changed_slide_synthesizes_and_settings_are_frozen(tmp_path, monkeypatch):
    api, r, calls = fixture(tmp_path, monkeypatch)
    generate(api, r)
    _, op = generate(api, r, "changed", notes=["First note.", "A revised second note."])
    assert op["state"] == "succeeded" and len(calls) == 3
    api.execution = "queued"
    pending, _ = generate(api, r, "snapshot", notes=["New first.", "New second."])
    api.configure_narration("openai", "new-voice", voice="cedar")
    api.run_operation(pending["operation_id"])
    assert calls[-1][1]["voice"] == "marin"
    api.execution = "in_process"
    generate(api, r, "voice-change")
    assert calls[-1][1]["voice"] == "cedar"


def test_missing_notes_and_grant_fail_before_spending(tmp_path, monkeypatch):
    api, r, calls = fixture(tmp_path, monkeypatch)
    with pytest.raises(StoriesError, match="nonempty"):
        generate(api, r, notes=["", "Second"])
    with pytest.raises(StoriesError, match="exceeds"):
        api.generate_narration(r["story_id"], r["revision_id"], {"max_requests": 1}, "too-small")
    assert not calls


def test_partial_failure_uncertainty_and_explicit_retry(tmp_path, monkeypatch):
    api, r, calls = fixture(tmp_path, monkeypatch)
    good = __import__("amplifier_smart_tool_stories.speech", fromlist=["synthesize"]).synthesize

    async def fail(text, config, timeout):
        if text.startswith("Second"):
            raise RuntimeError("Do not expose test-secret")
        return await good(text, config, timeout)

    monkeypatch.setattr("amplifier_smart_tool_stories.speech.synthesize", fail)
    receipt, op = generate(api, r)
    assert op["state"] == "failed" and op["error"]["code"] == "speech_completion_uncertain"
    assert "test-secret" not in json.dumps(op)
    audio = api.get_narration_audio(r["story_id"], receipt["narration_id"], 1)
    assert base64.b64decode(audio["data_base64"]).startswith(b"RIFF")
    monkeypatch.setattr("amplifier_smart_tool_stories.speech.synthesize", good)
    _, op = generate(api, r, "no-blind-retry")
    assert op["state"] == "failed" and op["error"]["code"] == "speech_completion_uncertain"
    _, op = generate(api, r, "explicit-retry", retry_uncertain=True)
    assert op["state"] == "succeeded" and len(calls) == 2


def test_cancel_prevents_late_audio_commit(tmp_path, monkeypatch):
    api, r, calls = fixture(tmp_path, monkeypatch)
    api.execution = "queued"
    rec, _ = generate(api, r)
    started = threading.Event()

    async def blocked(*args):
        started.set()
        await asyncio.sleep(60)

    monkeypatch.setattr("amplifier_smart_tool_stories.speech.synthesize", blocked)
    thread = threading.Thread(target=api.run_operation, args=(rec["operation_id"],))
    thread.start()
    assert started.wait(3)
    api.cancel_operation(rec["operation_id"])
    thread.join(3)
    assert not thread.is_alive()
    assert api.get_operation(rec["operation_id"])["state"] == "cancelled"
    assert api.get_narration(r["story_id"], rec["narration_id"])["clips"] == []


def test_both_deliveries_share_retained_audio_and_timeline(tmp_path, monkeypatch):
    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg required for real media encoding")
    api, r, calls = fixture(tmp_path, monkeypatch)
    rec, op = generate(api, r)
    assert op["state"] == "succeeded"
    kwargs = dict(
        story_id=r["story_id"],
        revision_id=r["revision_id"],
        narration_id=rec["narration_id"],
        pause_seconds=0.1,
    )
    embedded = api.export_video(output_path=str(tmp_path / "embedded.mp4"), **kwargs)
    separate = api.export_video(output_path=str(tmp_path / "separate.zip"), delivery="separate", **kwargs)
    assert len(calls) == 2
    assert embedded["duration_seconds"] == 0.6
    assert embedded["plan_id"] == separate["plan_id"]
    with zipfile.ZipFile(tmp_path / "separate.zip") as z:
        plan = json.loads(z.read("manifest.json"))
        assert plan["timeline"][1]["audio_start_sample"] == 7200
        with wave.open(io.BytesIO(z.read("narration.wav")), "rb") as w:
            pcm = w.readframes(w.getnframes())
            assert w.getnframes() == 14400
        assert pcm[4800 * 2 : 7200 * 2] == b"\0" * (2400 * 2)
        for i in [1, 2]:
            raw = api.get_narration_audio(r["story_id"], rec["narration_id"], i)
            assert z.read(f"slides/slide-{i:03}.wav") == base64.b64decode(raw["data_base64"])
    with pytest.raises(StoriesError, match="truncate"):
        api.export_video(output_path=str(tmp_path / "short.mp4"), slide_seconds=[0.1, 0.1], **kwargs)
    assert not (tmp_path / "short.mp4").exists()
    assert not list(tmp_path.glob(".stories-narrated-*"))


def test_missing_authority_and_queued_cancellation_do_not_spend(tmp_path, monkeypatch):
    api, r, calls = fixture(tmp_path, monkeypatch)
    api.model_env = False
    _, op = generate(api, r)
    assert op["error"]["code"] == "model_access_required"
    api.model_env = True
    monkeypatch.delenv("OPENAI_API_KEY")
    _, op = generate(api, r, "missing-key")
    assert op["error"]["code"] == "speech_unavailable"
    api.execution = "queued"
    rec, _ = generate(api, r, "cancel-before-start")
    api.cancel_operation(rec["operation_id"])
    api.run_operation(rec["operation_id"])
    assert api.list_narrations(r["story_id"])["narrations"][-1]["state"] == "cancelled"
    assert not calls


def test_wrong_revision_narration_cannot_export(tmp_path, monkeypatch):
    api, r, _ = fixture(tmp_path, monkeypatch)
    rec, _ = generate(api, r)
    other = api.create_story("Other", HTML, "other")
    with pytest.raises(StoriesError, match="another story"):
        api.export_video(
            other["story_id"],
            other["revision_id"],
            str(tmp_path / "bad.mp4"),
            narration_id=rec["narration_id"],
        )
    assert not (tmp_path / "bad.mp4").exists()


@pytest.mark.parametrize("provider", ["openai", "gemini"])
def test_direct_adapters_bound_requests_and_disable_retries(monkeypatch, provider):
    from types import SimpleNamespace

    from amplifier_smart_tool_stories.speech import DEFAULTS, synthesize

    captured = {}
    pcm = b"\0\0" * 100

    async def request(**kwargs):
        captured["request"] = kwargs
        if provider == "openai":
            return SimpleNamespace(content=pcm)
        return SimpleNamespace(
            candidates=[
                SimpleNamespace(
                    content=SimpleNamespace(
                        parts=[
                            SimpleNamespace(
                                inline_data=SimpleNamespace(
                                    mime_type="audio/L16;codec=pcm;rate=24000", data=pcm
                                )
                            )
                        ]
                    )
                )
            ]
        )

    class Client:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.aio = self
            self.audio = SimpleNamespace(speech=SimpleNamespace(create=request))
            self.models = SimpleNamespace(generate_content=request)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    monkeypatch.setenv("OPENAI_API_KEY", "test-only")
    monkeypatch.setenv("GOOGLE_API_KEY", "test-only")
    monkeypatch.setattr("openai.AsyncOpenAI" if provider == "openai" else "google.genai.Client", Client)
    result = asyncio.run(
        synthesize(
            "Exact notes.", {"provider": provider, **DEFAULTS[provider], "instructions": "Speak calmly."}, 7
        )
    )
    with wave.open(io.BytesIO(result)) as w:
        assert w.getnframes() == 100 and w.getframerate() == 24000
    if provider == "openai":
        assert captured["client"]["max_retries"] == 0
        assert captured["client"]["timeout"] == 7
        assert captured["request"]["input"] == "Exact notes."
    else:
        assert captured["client"]["http_options"].retry_options.attempts == 1
        assert captured["client"]["http_options"].timeout == 7000
        assert captured["request"]["model"] == "gemini-3.1-flash-tts-preview"
        voice_config = captured["request"]["config"].speech_config.voice_config
        assert voice_config.prebuilt_voice_config.voice_name == "Kore"
        assert captured["request"]["config"].automatic_function_calling.disable
        assert captured["request"]["contents"].endswith("Exact notes.")


@pytest.mark.parametrize(
    ("mime_type", "accepted"),
    [
        ("audio/L16;codec=pcm;rate=24000", True),
        # Observed from gemini-3.1-flash-tts-preview via google-genai 2.25.0.
        ("audio/l16; rate=24000; channels=1", True),
        ("audio/wav; rate=24000", False),
        ("audio/l16; rate=16000", False),
    ],
)
def test_gemini_pcm_mime_type_is_case_insensitive(monkeypatch, mime_type, accepted):
    from types import SimpleNamespace

    from amplifier_smart_tool_stories.speech import DEFAULTS, synthesize

    pcm = b"\0\0" * 100

    async def request(**kwargs):
        part = SimpleNamespace(inline_data=SimpleNamespace(mime_type=mime_type, data=pcm))
        return SimpleNamespace(candidates=[SimpleNamespace(content=SimpleNamespace(parts=[part]))])

    class Client:
        def __init__(self, **kwargs):
            self.aio = self
            self.models = SimpleNamespace(generate_content=request)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    monkeypatch.setenv("GOOGLE_API_KEY", "test-only")
    monkeypatch.setattr("google.genai.Client", Client)
    call = synthesize("Exact notes.", {"provider": "gemini", **DEFAULTS["gemini"], "instructions": ""}, 7)
    if accepted:
        with wave.open(io.BytesIO(asyncio.run(call))) as w:
            assert w.getnframes() == 100 and w.getframerate() == 24000
    else:
        with pytest.raises(StoriesError) as error:
            asyncio.run(call)
        assert error.value.code == "invalid_audio"


def test_parallel_bound_out_of_order_partial_and_duplicate_inputs(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test")
    api = Stories(tmp_path / "parallel", model_env=True, execution="in_process")
    html = (
        "<html><body>" + "".join(f'<section class="slide">{i}</section>' for i in range(6)) + "</body></html>"
    )
    r = api.create_story("Parallel", html, "create")
    api.configure_narration("openai", "config")
    active = peak = 0
    calls = []

    async def speak(text, config, timeout):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        calls.append(text)
        try:
            await asyncio.sleep(0.08 if text == "slow" else 0.01)
            if text == "fail":
                raise RuntimeError("Provider failed")
            return wav(b"\0\0" * 2400)
        finally:
            active -= 1

    monkeypatch.setattr("amplifier_smart_tool_stories.speech.synthesize", speak)
    rec = api.generate_narration(
        r["story_id"],
        r["revision_id"],
        {"max_requests": 5},
        "parallel",
        notes=["slow", "fail", "third", "same", "same", "last"],
        concurrency=3,
    )
    op = api.get_operation(rec["operation_id"])
    nar = api.get_narration(r["story_id"], rec["narration_id"])
    assert peak == 3 and active == 0 and len(calls) == 5 and calls.count("same") == 1
    assert op["state"] == "failed" and op["requests_used"] == 5
    assert [c["slide"] for c in nar["clips"]] == [1, 3, 4, 5, 6]
    assert op["progress"]["completed_slides"] == 5
    assert api.get_narration_audio(r["story_id"], rec["narration_id"], 6)["audio"]["text"] == "last"
    with pytest.raises(StoriesError):
        api.get_narration_audio(r["story_id"], rec["narration_id"], 2)
    assert nar["clips"][2]["audio_id"] == nar["clips"][3]["audio_id"]


def test_parallel_cancel_stops_all_inflight_requests(tmp_path, monkeypatch):
    api, r, _ = fixture(tmp_path, monkeypatch)
    api.execution = "queued"
    rec, _ = generate(api, r)
    ready = threading.Event()
    active = 0
    stopped = 0

    async def blocked(*args):
        nonlocal active, stopped
        active += 1
        if active == 2:
            ready.set()
        try:
            await asyncio.sleep(60)
        finally:
            stopped += 1

    monkeypatch.setattr("amplifier_smart_tool_stories.speech.synthesize", blocked)
    t = threading.Thread(target=api.run_operation, args=(rec["operation_id"],))
    t.start()
    assert ready.wait(3)
    api.cancel_operation(rec["operation_id"])
    t.join(3)
    assert not t.is_alive() and stopped == 2
    assert api.get_narration(r["story_id"], rec["narration_id"])["clips"] == []


def test_rate_limit_has_actionable_error_without_exposing_provider_text(tmp_path, monkeypatch):
    api, r, _ = fixture(tmp_path, monkeypatch)

    class Limited(Exception):
        code = 429

    async def limited(*args):
        raise Limited("private provider response must not leak")

    monkeypatch.setattr("amplifier_smart_tool_stories.speech.synthesize", limited)
    rec, op = generate(api, r)
    assert op["error"]["code"] == "speech_rate_limited"
    assert "private provider" not in json.dumps(op)
    assert [e["http_status"] for e in op["slide_errors"]] == [429, 429]

    # Known rejected requests don't require acknowledging uncertain synthesis.
    async def good(*args):
        return wav(b"\0\0" * 2400)

    monkeypatch.setattr("amplifier_smart_tool_stories.speech.synthesize", good)
    _, next_op = generate(api, r, "after-limit-reset")
    assert next_op["state"] == "succeeded"
