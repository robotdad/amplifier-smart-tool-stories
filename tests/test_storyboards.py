import asyncio
import base64
import copy
import io
import json
import zipfile

import pytest
from PIL import Image

from amplifier_smart_tool_stories import Stories, StoriesError
from amplifier_smart_tool_stories.quality import render
from amplifier_smart_tool_stories.storyboards import checked, render_storyboard


def board(name="Follow the request"):
    return {
        "name": name,
        "approach": "Follow one fictional request through its journey.",
        "tradeoff": "Less architectural detail",
        "panels": [
            {
                "id": "arrival",
                "title": "A request arrives",
                "action": "A fictional team receives a request.",
                "visual": "A request card moving into an inbox",
                "asset_id": "",
                "narration": "Start with the need.",
                "notes": "Conceptual illustration, not observed behavior.",
                "evidence_ids": [],
            },
            {
                "id": "handoff",
                "title": "The next person can act",
                "action": "The request passes to a teammate.",
                "visual": "",
                "asset_id": "",
                "narration": "",
                "notes": "",
                "evidence_ids": [],
            },
        ],
    }


def candidate(value=None):
    return {
        "storyboard": value or board(),
        "evidence": [],
        "limitations": [],
        "calculations": [],
        "changes": {
            "summary": "Developed the sequence",
            "material_changes": [],
            "omissions": [],
            "assumptions": [],
        },
    }


def result(count=1):
    return {
        "action": "revise",
        "message": "Draft available",
        "brief": {
            "intent": "Explain a fictional handoff",
            "assumptions": ["Fictional scenario"],
            "open_questions": [],
        },
        "candidates": [
            candidate(board("Journey" if i == 0 else "Reveal the mechanism")) for i in range(count)
        ],
    }


def generate(api, explore=False, request_id="generate"):
    return api.generate_storyboard(
        "Handoff", "Explain a fictional handoff", "New team members", {}, request_id, explore=explore
    )


def ingest(api):
    image = io.BytesIO()
    Image.new("RGB", (400, 200), "#307565").save(image, format="PNG")
    data = image.getvalue()
    return api.import_media(
        "Supplied concept sketch", "image/png", "asset", data_base64=base64.b64encode(data).decode()
    )["asset"], data


def test_import_reorder_stable_text_anchors_and_no_acceptance_inheritance(tmp_path):
    api = Stories(tmp_path)
    initial = api.create_storyboard("Handoff", board(), "create")
    sid, rid = initial["story_id"], initial["revision_id"]
    assert api.get_story(sid)["selected_direction"] is None
    anchor = {"kind": "text", "element": "d-panel-handoff-action", "start": 0, "end": 3, "quote": "The"}
    comment = api.add_comment(sid, rid, "Keep this beat", "note", anchor=anchor, author="agent")
    api.save_draft(sid, rid, "draft", 1, "Unsaved idea", anchor)
    api.accept_revision(sid, rid, "accept")
    edited = board()
    edited["panels"].reverse()
    revised = api.revise_storyboard(sid, rid, edited, "edit")
    new = api.get_revision(sid, revised["revision_id"])
    assert new["direction_id"] == initial["direction_id"]
    assert new["review"]["visual"] == "not_performed"
    state = api.get_story(sid)
    assert state["annotations"][0]["id"] == comment["annotation_id"]
    assert state["annotations"][0]["revision_id"] == rid
    assert all(a["revision_id"] != new["id"] for a in state["acceptances"])
    assert any(
        e["element"] == anchor["element"] and e["text"].startswith("The")
        for e in api.get_preview(sid, new["id"])["elements"]
    )
    with pytest.raises(StoriesError, match="newer revision"):
        api.revise_storyboard(sid, rid, edited, "stale")
    branch = api.revise_storyboard(sid, rid, board("Other"), "branch", new_direction=True)
    assert branch["direction_id"] != initial["direction_id"]
    before = api.get_story(sid)
    comparison = api.get_comparison(sid)
    assert len(comparison["items"]) == 2
    assert api.get_story(sid) == before
    choice = api.select_direction(sid, branch["revision_id"], "choice")
    assert api.select_direction(sid, branch["revision_id"], "choice") == choice
    assert api.get_story(sid)["selected_direction"] == branch["direction_id"]
    assert len(api.get_story(sid)["acceptances"]) == 1


def test_media_zip_portable_exact_structure_and_layout(tmp_path):
    api = Stories(tmp_path)
    asset, data = ingest(api)
    value = board()
    value["panels"][0]["asset_id"] = asset["id"]
    initial = api.create_storyboard("Handoff", value, "create", asset_ids=[asset["id"]])
    sid, rid = initial["story_id"], initial["revision_id"]
    api.add_comment(sid, rid, "PRIVATE REVIEW NOTE", "note", author="agent")
    exported = api.get_export(sid, rid, "zip")
    archive = zipfile.ZipFile(io.BytesIO(base64.b64decode(exported["data_base64"])))
    structured = json.loads(archive.read("storyboard.json"))
    assert structured["storyboard"] == value
    assert structured["direction_id"] == initial["direction_id"]
    assert structured["brief"]["id"] == structured["brief_id"]
    assert structured["audience"] == api.get_story(sid)["audience"]
    api.update_storyboard_brief(
        sid, {"intent": "A new intent", "assumptions": [], "open_questions": []}, "new-brief"
    )
    assert api.get_revision(sid, rid)["brief"] == structured["brief"]
    assert archive.read(structured["asset_paths"][asset["id"]]) == data
    html = archive.read("index.html").decode()
    assert "PRIVATE REVIEW NOTE" not in html and "asset:" not in html
    assert exported == api.get_export(sid, rid, "zip")
    assert any("Review-only" in item for item in api.get_export(sid, rid, "html")["limitations"])
    with pytest.raises(StoriesError):
        api.get_export(sid, rid, "pdf")
    rev = api.get_revision(sid, rid)
    rendered = asyncio.run(
        render(
            rev["html"],
            40,
            media={
                "asset:" + asset["id"]: {"mime_type": "image/png", "data": base64.b64encode(data).decode()}
            },
        )
    )
    assert rendered["page_count"] == 3
    assert not rendered["findings"]
    with pytest.raises(StoriesError):
        api.revise_media(sid, rid, [asset["id"]], "wrong-surface")


@pytest.mark.parametrize("change", ["duplicate", "missing_asset", "evidence", "unsafe_id", "illustrated"])
def test_invalid_structure_never_commits(tmp_path, change):
    api = Stories(tmp_path)
    value = board()
    if change == "duplicate":
        value["panels"][1]["id"] = value["panels"][0]["id"]
    if change == "missing_asset":
        value["panels"][0]["asset_id"] = "absent"
    if change == "evidence":
        value["panels"][0]["evidence_ids"] = ["invented"]
    if change == "unsafe_id":
        value["panels"][0]["id"] = '../bad"'
    with pytest.raises(StoriesError):
        api.create_storyboard(
            "Invalid", value, "invalid", fidelity="illustrated" if change == "illustrated" else "mixed"
        )
    assert api.list_stories() == []


def test_defaults_explicit_exploration_retry_and_partial(tmp_path):
    observed = []

    def intelligence(story, op):
        observed.append(op["direction_count"])
        return result(op["direction_count"])

    api = Stories(tmp_path, execution="in_process", intelligence=intelligence)
    receipt = generate(api)
    assert generate(api) == receipt and observed == [1]
    assert len(api.get_story(receipt["story_id"])["directions"]) == 1
    explored = generate(api, True, "explore")
    assert observed == [1, 2]
    assert len(api.get_story(explored["story_id"])["directions"]) == 2
    assert api.get_story(explored["story_id"])["selected_direction"] is None
    api.intelligence = lambda story, op: result(1)
    partial = generate(api, True, "partial")
    op = api.get_operation(partial["operation_id"])
    assert op["state"] == "partial" and len(op["result"]["revision_ids"]) == 1
    assert op["result"]["failures"]


def test_missing_model_question_continuation_and_cancellation(tmp_path):
    api = Stories(tmp_path, execution="in_process")
    receipt = generate(api)
    assert api.get_operation(receipt["operation_id"])["error"]["code"] == "model_access_required"
    api.intelligence = lambda story, op: {"action": "clarify", "message": "Which audience?", "candidates": []}
    question = generate(api, True, "question")
    api.execution = "queued"
    answer = api.answer_question(question["operation_id"], "New employees", {}, "answer")
    op = api.get_operation(answer["operation_id"])
    assert op["direction_count"] == 2 and op["continuation"][0]["answer"] == "New employees"
    api.intelligence = lambda story, op: api.cancel_operation(op["id"]) and result(2)
    assert api.run_operation(op["id"])["state"] == "cancelled"
    assert api.get_story(question["story_id"])["revisions"] == []


def test_shared_brief_correction_fences_inflight_work_and_supersedes(tmp_path):
    api = Stories(tmp_path, execution="in_process", intelligence=lambda story, op: result())
    initial = generate(api)
    sid = initial["story_id"]
    rid = api.get_operation(initial["operation_id"])["result"]["revision_id"]
    api.grant_feedback(sid, {}, "grant")
    api.execution = "queued"
    comment = api.add_comment(sid, rid, "Revise this beat", "comment")
    api.update_storyboard_brief(
        sid, {"intent": "For experienced readers", "assumptions": [], "open_questions": []}, "brief"
    )
    assert api.run_operation(comment["operation_id"])["error"]["code"] == "brief_conflict"
    assert api.get_comparison(sid)["items"][0]["superseded"]
    with pytest.raises(StoriesError):
        api.select_direction(sid, rid, "stale-choice")
    briefs = api.get_story(sid)["briefs"]
    assert len(briefs) == 3  # Original idea, model-developed brief, explicit correction.
    assert briefs[0]["assumptions"] == []
    assert briefs[1]["assumptions"] == ["Fictional scenario"]


def test_comparison_supports_existing_formats_without_generating(tmp_path):
    api = Stories(tmp_path)
    story = api.create_story("Slides", "<html><body><h1>Original</h1></body></html>", "create")
    assert api.get_comparison(story["story_id"])["items"][0]["preview"]["kind"] == "presentation"
    from amplifier_smart_tool_stories.help import VALUES

    document = api.create_document("Doc", VALUES["document"], "doc")
    assert api.get_comparison(document["story_id"])["items"][0]["preview"]["kind"] == "document"
    with pytest.raises(StoriesError):
        api.get_comparison(story["story_id"], [document["revision_id"]])


def test_renderer_escapes_and_changes_identity_for_direction_metadata():
    original = board()
    html = render_storyboard(original)
    changed = copy.deepcopy(original)
    changed["tradeoff"] = "<script>alert(1)</script>"
    assert render_storyboard(changed) != html
    assert "<script>alert" not in render_storyboard(changed)
    assert checked(original)["panels"][0]["id"] == "arrival"


@pytest.mark.parametrize("invalid", ["encoded", "wrong_action"])
def test_real_pipeline_with_scripted_provider_reviews_both_directions(tmp_path, monkeypatch, invalid):
    from types import SimpleNamespace

    from amplifier_smart_tool_stories import intelligence

    class Session:
        coordinator = {"providers": {"scripted": object()}}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    async def create_session():
        return Session()

    async def prepared(config):
        return SimpleNamespace(create_session=create_session)

    composed = result(2)
    for value in composed["candidates"]:
        value.pop("evidence")
        for panel in value["storyboard"]["panels"]:
            panel["production_requirements"] = []
    composed["candidates"][1]["storyboard"]["approach"] = (
        "Reveal the coordination mechanism before following a request."
    )
    verdict = {
        "semantic": {"status": "passed", "findings": []},
        "visual": {"status": "passed", "findings": []},
        "warnings": [],
    }
    answers = [
        {
            "evidence": [],
            "expertise": ["general"],
            "plan": "Compare journey and mechanism",
            "limitations": [],
        },
        (
            {**composed, "candidates": '[{"storyboard": "unescaped "quote""}]'}
            if invalid == "encoded"
            else {**composed, "action": "answer"}
        ),
        composed,
        verdict,
        verdict,
        {"status": "passed", "findings": []},
    ]
    calls = []

    async def complete(provider, config, messages, tokens, timeout, schema=None):
        calls.append({"schema": schema, "messages": messages})
        # Some providers encode tool-argument containers as JSON strings.
        answer = answers.pop(0)
        answer = {k: json.dumps(v) if isinstance(v, (list, dict)) else v for k, v in answer.items()}
        return json.dumps(answer), {"provider": "scripted", "model": "test"}

    monkeypatch.setattr(intelligence, "prepared", prepared)
    monkeypatch.setattr(intelligence, "complete", complete)
    api = Stories(tmp_path, model_env=True, execution="in_process")
    receipt = generate(api, True)
    op = api.get_operation(receipt["operation_id"])
    assert op["state"] == "succeeded", op
    assert op["result"]["provenance"]["model_calls"] == 6
    assert calls[0]["schema"]["properties"]["evidence"]["maxItems"] == 12
    assert "answer" not in calls[1]["schema"]["properties"]["action"]["enum"]
    assert len(op["result"]["revision_ids"]) == 2
    for rid in op["result"]["revision_ids"]:
        rev = api.get_revision(receipt["story_id"], rid)
        assert rev["quality_review"]["artifact_sha256"] == rev["sha256"]
        assert len(rev["quality_review"]["pages"]) == 3
    assert isinstance(calls[3]["messages"][1]["content"], list)
    review_payload = json.loads(calls[3]["messages"][1]["content"][0]["text"])
    assert review_payload["narration_metrics"]["total_words"] == 4
    assert not answers


@pytest.mark.parametrize("failure_stage", ["semantic", "comparison"])
def test_review_failure_repairs_once_and_preserves_successful_sibling(tmp_path, monkeypatch, failure_stage):
    from amplifier_smart_tool_stories import storyboard_intelligence
    from amplifier_smart_tool_stories.storyboard_intelligence import compose

    api = Stories(tmp_path)
    receipt = generate(api, True)
    with api.store.transaction() as db:
        story = api.store.get(db, "stories", receipt["story_id"])
    import time

    operation = api.get_operation(receipt["operation_id"])
    operation["deadline"] = time.time() + 60
    passed = {
        "semantic": {"status": "passed", "findings": []},
        "visual": {"status": "passed", "findings": []},
    }
    failed = {
        "semantic": {"status": "failed", "findings": ["Unsupported causal claim"]},
        "visual": {"status": "passed", "findings": []},
    }
    answers = [
        {"evidence": [], "plan": "Plan", "expertise": ["general"]},
        result(2),
        passed,
        failed,
        candidate(board("Repair")),
        failed,
    ]
    if failure_stage == "comparison":
        answers = answers[:2] + [
            passed,
            passed,
            {"status": "failed", "findings": ["Same narrative structure"]},
        ]
    calls = []

    async def ask(*args, **kwargs):
        calls.append({"provider": "scripted"})
        return copy.deepcopy(answers.pop(0))

    async def rendered(*args, **kwargs):
        return {"images": [{"sha256": "a" * 64}], "findings": [], "rendered_text": "Panels"}

    monkeypatch.setattr(storyboard_intelligence, "render", rendered)
    outcome = asyncio.run(compose(story, operation, ask, calls))
    assert len(outcome["candidates"]) == 1
    if failure_stage == "semantic":
        assert outcome["failures"][0]["code"] == "quality_review_failed"
        assert len(outcome["review_attempts"][1]["reviews"]) == 2
    else:
        assert outcome["failures"][0]["code"] == "comparison_review_failed"
        assert outcome["review_attempts"][-1]["comparison"]["findings"] == ["Same narrative structure"]
    assert not answers
    api.intelligence = lambda story, op: outcome
    op = api.run_operation(operation["id"])
    assert op["state"] == "partial", op
    assert len(api.get_story(receipt["story_id"])["revisions"]) == 1


def test_optional_production_requirements_portable_without_tracking(tmp_path):
    api = Stories(tmp_path)
    old = api.create_storyboard("Handoff", board(), "old")
    revised = board()
    revised["panels"][0]["production_requirements"] = [
        "Capture the request entering the queue; hold 3 seconds.",
        "Animate <request> moving to the owner; transparent background.",
    ]
    new = api.revise_storyboard(old["story_id"], old["revision_id"], revised, "production")
    rev = api.get_revision(old["story_id"], new["revision_id"])
    assert "Production requirements" in rev["html"]
    assert "Animate &lt;request&gt;" in rev["html"]
    assert rev["sha256"] != api.get_revision(old["story_id"], old["revision_id"])["sha256"]
    assert (
        "production_requirements"
        not in api.get_revision(old["story_id"], old["revision_id"])["storyboard"]["panels"][0]
    )
    export = api.get_export(old["story_id"], new["revision_id"], "zip")
    with zipfile.ZipFile(io.BytesIO(base64.b64decode(export["data_base64"]))) as archive:
        assert json.loads(archive.read("storyboard.json"))["storyboard"] == revised
    for invalid in ("text", [""], ["x" * 501], ["x"] * 5, [{"status": "done"}]):
        revised["panels"][0]["production_requirements"] = invalid
        with pytest.raises(StoriesError):
            checked(revised)


def test_direction_overview_does_not_orphan_production_panel_copy():
    from bs4 import BeautifulSoup

    value = board()
    value["approach"] = "Follow the request, then explain the mechanism and its limits. " * 7
    value["tradeoff"] = (
        "The visual explanation needs room for a clear example and a careful qualification. " * 5
    )
    panel = value["panels"][0]
    panel["visual"] = "A conceptual client and service diagram with a keyed result store. " * 3
    panel["narration"] = "The same request returns its recorded result within this demonstration. " * 4
    panel["production_requirements"] = [
        "Draw the client, service and keyed result store; label this as an illustration, not a capture.",
        "Record the request and repeat request in a real demo; retain the matching result and visible key.",
        "Keep the retention limit legible while the result appears, synchronized with narration.",
        "Use a labeled planned capture frame until the recording exists; do not fabricate product evidence.",
    ]
    rendered_html = render_storyboard(value)
    soup = BeautifulSoup(rendered_html, "html.parser")
    assert soup.select_one("#direction-approach").find_parent(class_="storyboard-panel") is None
    rendered = asyncio.run(render(rendered_html, 40))
    assert rendered["page_count"] == 3  # Intentional overview plus two complete panel sheets.
    assert not rendered["findings"]


def test_narration_counts_are_computed_not_model_estimates():
    from amplifier_smart_tool_stories.storyboard_intelligence import narration_metrics

    value = board()
    value["panels"][0]["narration"] = "One two three four five."
    value["panels"][1]["narration"] = "Six seven eight nine ten."
    metrics = narration_metrics(value)
    assert metrics["panel_word_counts"] == [5, 5]
    assert metrics["total_words"] == 10
    assert metrics["spoken_seconds_at_150_wpm"] == 4
    assert metrics["spoken_seconds_at_120_wpm"] == 5
    for panel in value["panels"]:
        panel["narration"] = ""
    assert narration_metrics(value)["total_words"] == 0
