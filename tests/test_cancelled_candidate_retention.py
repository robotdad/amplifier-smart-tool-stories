"""Public cancellation retains diagnostics, never authority or committed output."""

import asyncio
import copy
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from test_review_stage_contract import HTML, candidate, harness, verdict

from amplifier_smart_tool_stories import Stories, StoriesError, intelligence
from amplifier_smart_tool_stories.cli import main


def queued(tmp_path, *, model_env=False):
    api = Stories(tmp_path / "store", model_env=model_env)
    base = api.create_story("Retained base", HTML, "import")
    api.grant_feedback(base["story_id"], {"max_operations": 1}, "grant")
    receipt = api.add_comment(base["story_id"], base["revision_id"], "Revise", "edit")
    return api, base, receipt["operation_id"]


def assert_cancelled(api, base, operation_id, before, saved):
    """Read/retry/cancel are inert; original artifacts and spent grant survive."""
    assert saved["state"] == "cancelled"
    assert saved["cleanup"] == "complete"
    assert saved["finished_at"] >= saved["started_at"]
    assert saved["grant"] == before["operation"]["grant"]
    assert saved["result"] is None
    assert api.get_operation(operation_id) == saved
    assert api.run_operation(operation_id) == saved
    api.cancel_operation(operation_id)
    assert api.get_operation(operation_id) == saved
    # Reopen the public API to prove diagnostics were committed, not only returned.
    reopened = Stories(api.store.path)
    assert reopened.get_operation(operation_id) == saved
    story = reopened.get_story(base["story_id"])
    assert story["revisions"] == before["story"]["revisions"]
    assert story["selected_revision"] == base["revision_id"]
    assert story["feedback_grant"] == before["story"]["feedback_grant"]
    assert story["feedback_grant"]["used"] == 1
    assert story["annotations"][0]["status"] == "cancelled"
    assert story["annotations"][0]["responses"] == []
    events = api.read_changes(base["story_id"])["changes"]
    assert sum(e["kind"] == "operation_cancelled" for e in events) == 1
    assert not any(e["kind"] in {"operation_completed", "operation_failed"} for e in events)
    assert (
        api.add_comment(base["story_id"], base["revision_id"], "Again", "again")["status"]
        == "awaiting_authority"
    )


def snapshot(api, base, operation_id):
    return {
        "story": api.get_story(base["story_id"]),
        "operation": api.get_operation(operation_id),
    }


@pytest.mark.parametrize("boundary", ["render", "review", "repair", "second_review"])
def test_public_watchdog_retains_composed_candidate_and_observed_calls(tmp_path, monkeypatch, boundary):
    fixed = HTML.replace("Qualified", "Repaired")
    h = harness(monkeypatch, [candidate(), verdict("Unsupported"), candidate(fixed), verdict()])
    api, base, operation_id = queued(tmp_path, model_env=True)
    before = snapshot(api, base, operation_id)
    entered, settled = Event(), Event()
    original_render, original_complete = intelligence.render, intelligence.complete
    call_number = 0
    blocked_call = {"review": 3, "repair": 4, "second_review": 5}.get(boundary)

    async def block():
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            settled.set()

    async def render(*args, **kwargs):
        if boundary == "render":
            await block()
        return await original_render(*args, **kwargs)

    async def complete(*args, **kwargs):
        nonlocal call_number
        call_number += 1
        if call_number == blocked_call:
            await block()
        return await original_complete(*args, **kwargs)

    monkeypatch.setattr(intelligence, "render", render)
    monkeypatch.setattr(intelligence, "complete", complete)
    # Different API instances/SQLite connections model caller and worker threads.
    caller = Stories(api.store.path)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(api.run_operation, operation_id)
        try:
            assert entered.wait(5), "Execution never reached the selected boundary"
        finally:
            caller.cancel_operation(operation_id)
        pending = caller.get_operation(operation_id)
        assert pending["state"] == "cancelled"
        saved = future.result(timeout=5)
    assert settled.is_set(), "Owned async work must settle before cleanup completes"
    assert_cancelled(caller, base, operation_id, before, saved)
    retained = saved["candidate"]
    assert retained["html"] == (fixed if boundary == "second_review" else HTML)
    assert retained["candidates"][0]["submission"]["html"] == HTML
    calls = retained["provenance"]["calls"]
    expected = {"render": 2, "review": 3, "repair": 4, "second_review": 5}[boundary]
    assert retained["provenance"]["model_calls"] == expected
    assert len(calls) == call_number == expected
    if blocked_call:
        stage = "repair" if boundary == "repair" else "review"
        assert calls[-1] == {"stage": stage, "status": "started"}
        completed = calls[:-1]
    else:
        completed = calls
    assert len(completed) == len(h.requests)
    assert all(c["provider"] == "stub" and c["model"].startswith("call-") for c in completed)
    if boundary in {"repair", "second_review"}:
        assert retained["reviews"][0]["semantic"]["findings"] == ["Unsupported"]
        assert retained["reviews"][0]["passed"] is False
    if boundary == "second_review":
        assert [c["submission"]["html"] for c in retained["candidates"]] == [HTML, fixed]
        assert retained["review_completed"] is False


@pytest.mark.parametrize("outcome", ["return", "exception", "bare_exception"])
def test_cancel_wins_before_worker_commit_without_losing_diagnostics(tmp_path, outcome):
    api, base, operation_id = queued(tmp_path)
    before = snapshot(api, base, operation_id)
    payload = {
        **candidate(),
        "evidence": [],
        "provenance": {
            "model_calls": 2,
            "calls": [
                {"stage": "composition", "model": "observed"},
                {"stage": "review", "status": "started"},
            ],
        },
    }
    original = copy.deepcopy(payload)
    entered, release = Event(), Event()
    executions = []

    def execute(story, operation):
        executions.append(operation["id"])
        entered.set()
        assert release.wait(5)
        if outcome == "return":
            return payload
        error = StoriesError("cancelled", "Stopped")
        if outcome == "exception":
            error.candidate = payload
        raise error

    api.intelligence = execute
    caller = Stories(api.store.path)
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(api.run_operation, operation_id)
        try:
            assert entered.wait(5)
            assert caller.cancel_operation(operation_id)["cleanup"] == "pending"
            # A duplicate runner must not own execution or mark cleanup complete.
            duplicate = pool.submit(api.run_operation, operation_id).result(timeout=5)
            assert duplicate["state"] == "cancelled" and duplicate["cleanup"] == "pending"
        finally:
            release.set()
        saved = future.result(timeout=5)
    assert_cancelled(api, base, operation_id, before, saved)
    assert executions == [operation_id]
    assert payload == original
    if outcome == "bare_exception":
        assert "candidate" not in saved
    else:
        assert saved["candidate"] == original


def test_queued_cancellation_never_executes_or_fabricates_diagnostics(tmp_path):
    api, base, operation_id = queued(tmp_path)
    before = snapshot(api, base, operation_id)

    def forbidden(*_):
        pytest.fail("Cancelled work was replayed")

    api.intelligence = forbidden
    assert api.cancel_operation(operation_id)["cleanup"] == "complete"
    saved = api.run_operation(operation_id)
    assert saved["state"] == "cancelled"
    assert "candidate" not in saved and "finished_at" not in saved
    assert api.get_operation(operation_id) == saved
    assert api.get_story(base["story_id"])["feedback_grant"] == before["story"]["feedback_grant"]


def test_completed_operation_is_unchanged_by_cancel_or_duplicate_runner(tmp_path):
    api, base, operation_id = queued(tmp_path)
    executions = []

    def execute(*_):
        executions.append(True)
        return {**candidate(), "evidence": []}

    api.intelligence = execute
    saved = api.run_operation(operation_id)
    assert saved["state"] == "succeeded"
    story = api.get_story(base["story_id"])
    assert len(story["revisions"]) == 2
    assert api.cancel_operation(operation_id)["status"] == "succeeded"
    assert api.run_operation(operation_id) == saved
    assert api.get_operation(operation_id) == saved
    assert api.get_story(base["story_id"]) == story
    assert executions == [True]


def test_cli_get_operation_reads_cancelled_diagnostics_without_execution(tmp_path, monkeypatch, capsys):
    api, _, operation_id = queued(tmp_path)
    payload = {**candidate(), "provenance": {"calls": [{"status": "started", "stage": "review"}]}}

    def execute(*_):
        api.cancel_operation(operation_id)
        error = StoriesError("cancelled", "Stopped")
        error.candidate = payload
        raise error

    api.intelligence = execute
    saved = api.run_operation(operation_id)
    assert saved["candidate"] == payload
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "stories",
            "--store",
            str(api.store.path),
            "get-operation",
            "--input",
            json.dumps({"operation_id": operation_id}),
        ],
    )
    main()
    assert json.loads(capsys.readouterr().out) == saved
    assert api.get_operation(operation_id) == saved
