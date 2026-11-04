"""Composition-stage regression checks; stubs exercise execution, not live quality."""

import asyncio
import copy
import json
import time
from types import SimpleNamespace

import pytest

from amplifier_smart_tool_stories import Stories, StoriesError, intelligence
from amplifier_smart_tool_stories.artifacts import digest
from amplifier_smart_tool_stories.quality import validate_record

HTML = '<html><body><section class="slide"><h1>Qualified finding</h1></section></body></html>'


def candidate(html=HTML, **fields):
    return {
        "action": "revise",
        **({} if "document" in fields else {"html": html}),
        "message": "Draft composition; export and playback not performed.",
        "limitations": [],
        "changes": {"summary": "Draft", "material_changes": [], "omissions": [], "assumptions": []},
        "calculations": [],
        **fields,
    }


def verdict(issue=None):
    return {
        "semantic": {"status": "failed" if issue else "passed", "findings": [issue] if issue else []},
        "visual": {"status": "passed", "findings": []},
        "warnings": [],
    }


def document(text="Qualified finding"):
    return {
        "title": "Brief",
        "subtitle": "",
        "blocks": [
            {
                "id": "finding",
                "kind": "paragraph",
                "text": text,
                "items": [],
                "rows": [],
                "evidence_ids": [],
                "marks": [],
            }
        ],
    }


def harness(monkeypatch, answers, *, findings=(), pages=1, render_error=None):
    """Only provider and render I/O are stubbed; real validation/gates execute."""
    queued = [
        {"evidence": [], "plan": "Qualified finding", "expertise": ["general"], "limitations": []},
        *answers,
    ]
    requests, rendered = [], []

    class Session:
        coordinator = SimpleNamespace(get=lambda _: {"stub": object()})

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    async def create_session():
        return Session()

    async def prepared(config):
        return SimpleNamespace(create_session=create_session)

    async def complete(provider, config, messages, max_tokens, timeout, schema):
        content = messages[1]["content"]
        payload = json.loads(content if isinstance(content, str) else content[0]["text"])
        requests.append({"instruction": messages[0]["content"], "payload": payload, "schema": schema})
        answer = queued.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return json.dumps(answer), {"provider": "stub", "model": f"call-{len(requests)}", "usage": {}}

    async def render(html, timeout, media=None):
        rendered.append(html)
        if render_error:
            raise render_error
        return {
            "images": [{"sha256": digest(f"{html}-{i}"), "data": "stub-page"} for i in range(pages)],
            "findings": list(findings),
            "rendered_text": "Qualified finding",
            "renderer": "test stub (not visual evidence)",
        }

    monkeypatch.setattr(intelligence, "prepared", prepared)
    monkeypatch.setattr(intelligence, "complete", complete)
    monkeypatch.setattr(intelligence, "render", render)
    story = {
        "kind": "presentation",
        "title": "Test",
        "purpose": "Explain",
        "audience": "Reader",
        "sources": [],
        "annotations": [],
        "revisions": [],
        "assets": [],
        "_media_images": {"private-render-only": {"data": "private-media-sentinel"}},
    }
    operation = {
        "kind": "generate",
        "provider": {"provider": "openai"},
        "annotation_id": None,
        "revision_id": None,
        "deadline": time.time() + 30,
        "grant": {"max_output_tokens": 1000},
    }
    return SimpleNamespace(
        story=story,
        operation=operation,
        requests=requests,
        rendered=rendered,
        queued=queued,
        run=lambda: intelligence.execute(story, operation, lambda: False),
    )


def test_review_sees_exact_composition_instructions_and_unperformed_delivery(monkeypatch):
    html = HTML.replace(
        "</section>", '<video controls src="asset:clip" poster="asset:poster"></video></section>'
    )
    h = harness(monkeypatch, [candidate(html), verdict()])
    h.story["assets"] = [
        {"id": "clip", "mime_type": "video/mp4", "sha256": "a" * 64},
        {"id": "poster", "mime_type": "image/png", "sha256": "b" * 64},
    ]
    h.story["purpose"] = "Keep the clip, export HTML and separate MP4; pause when leaving the panel."
    result = h.run()
    context = h.requests[2]["payload"]["composition_context"]
    assert context["composition_instructions"] == h.requests[1]["instruction"]
    assert context["composition_instruction_sha256"] == digest(h.requests[1]["instruction"])
    assert "No JavaScript" in context["composition_instructions"]
    assert "Do not demand an exported ZIP" in h.requests[2]["instruction"]
    assert context["stage"] == "composition"
    assert context["asset_bindings"] == {"status": "passed", "used_asset_ids": ["clip", "poster"]}
    assert h.requests[2]["payload"]["request"]["purpose"] == h.story["purpose"]
    assert "private-media-sentinel" not in json.dumps(h.requests)
    review = result["quality_review"]
    assert review["stage"] == "composition"
    assert review["unperformed_checks"] == ["media_playback", "export", "player_interaction"]
    assert "not inspected" in review["limits"][-1]
    assert validate_record(html, review)
    assert [c["stage"] for c in result["provenance"]["calls"]] == ["evidence", "composition", "review"]
    assert not h.queued


def test_repair_has_fresh_constraints_and_review_identity(monkeypatch):
    fixed = HTML.replace("Qualified", "Carefully qualified")
    h = harness(monkeypatch, [candidate(), verdict("Preserve qualifier"), candidate(fixed), verdict()])
    result = h.run()
    first, second = result["review_attempts"]
    assert not first["passed"] and second["passed"]
    assert first["artifact_sha256"] == digest(HTML)
    assert second["artifact_sha256"] == digest(fixed)
    assert first["pages"] != second["pages"]
    assert (
        h.requests[4]["payload"]["composition_context"]["composition_instructions"]
        == h.requests[3]["instruction"]
    )
    assert first["composition_instruction_sha256"] != second["composition_instruction_sha256"]
    assert result["provenance"]["model_calls"] == 5
    assert h.rendered == [HTML, fixed]


@pytest.mark.parametrize("mechanical", [True, False])
def test_failure_retains_both_candidates_and_provenance_without_duplicate_findings(monkeypatch, mechanical):
    fixed = HTML.replace("Qualified", "Revised")
    issue = "Text clipped"
    answers = [
        candidate(),
        verdict(None if mechanical else "Unsupported source claim"),
        candidate(fixed),
        verdict(None if mechanical else "Still unsupported"),
    ]
    h = harness(monkeypatch, answers, findings=[issue] if mechanical else [])
    with pytest.raises(StoriesError) as caught:
        h.run()
    assert caught.value.code == "quality_review_failed"
    saved = caught.value.candidate
    assert saved["html"] == fixed
    assert saved["review_completed"] is True
    assert [c["submission"]["html"] for c in saved["candidates"]] == [HTML, fixed]
    assert [c["artifact_sha256"] for c in saved["candidates"]] == [digest(HTML), digest(fixed)]
    assert [c["composition_call"] for c in saved["candidates"]] == [2, 4]
    assert [c["stage"] for c in saved["provenance"]["calls"]] == [
        "evidence",
        "composition",
        "review",
        "repair",
        "review",
    ]
    assert saved["provenance"]["model_calls"] == 5
    for review in saved["reviews"]:
        assert not review["passed"]
        if mechanical:
            assert review["visual"]["findings"] == [issue]
        with pytest.raises(StoriesError):
            validate_record(fixed, review)
    assert "private-media-sentinel" not in json.dumps(saved)
    assert len(saved["reviews"]) == 2 and not h.queued


def test_repair_provider_failure_preserves_original_candidate_and_review(monkeypatch):
    h = harness(
        monkeypatch, [candidate(), verdict("Unsupported"), StoriesError("provider_failed", "Stopped")]
    )
    with pytest.raises(StoriesError) as caught:
        h.run()
    saved = caught.value.candidate
    assert saved["html"] == HTML
    assert saved["candidates"][0]["submission"]["html"] == HTML
    assert len(saved["candidates"]) == len(saved["reviews"]) == 1
    assert not saved["reviews"][0]["passed"]
    assert saved["provenance"]["calls"][-1] == {"stage": "repair", "status": "started"}
    assert len(h.requests) == 4


def test_render_failure_preserves_unreviewed_candidate(monkeypatch):
    h = harness(monkeypatch, [candidate()], render_error=StoriesError("render_failed", "Renderer stopped"))
    with pytest.raises(StoriesError) as caught:
        h.run()
    saved = caught.value.candidate
    assert not saved["review_completed"]
    assert not saved["reviews"]
    assert saved["candidates"][0]["artifact_sha256"] == digest(HTML)
    assert saved["provenance"]["model_calls"] == 2


def test_second_review_error_retains_both_candidates_without_inheriting_first_review(monkeypatch):
    fixed = HTML.replace("Qualified", "Revised")
    h = harness(
        monkeypatch,
        [candidate(), verdict("Unsupported"), candidate(fixed), StoriesError("provider_failed", "Stopped")],
    )
    with pytest.raises(StoriesError) as caught:
        h.run()
    saved = caught.value.candidate
    assert [c["submission"]["html"] for c in saved["candidates"]] == [HTML, fixed]
    assert saved["html"] == fixed and not saved["review_completed"]
    assert len(saved["reviews"]) == 1
    assert saved["reviews"][0]["artifact_sha256"] == digest(HTML)
    assert saved["provenance"]["calls"][-1] == {"stage": "review", "status": "started"}
    assert len(h.requests) == 5


def test_inconsistent_reviewer_verdict_is_rejected_without_content_repair(monkeypatch):
    invalid = verdict()
    invalid["semantic"]["findings"] = ["Unsupported even though labelled passed"]
    h = harness(monkeypatch, [candidate(), invalid])
    with pytest.raises(StoriesError) as caught:
        h.run()
    assert caught.value.code == "invalid_review"
    assert not caught.value.candidate["review_completed"]
    assert len(h.requests) == 3
    observed = caught.value.candidate["candidates"][0]["review_submissions"][0]
    assert observed["verdict"] == invalid
    assert observed["artifact_sha256"] == digest(HTML)
    assert observed["pages"] == [digest(f"{HTML}-0")]
    assert observed["call"] == 3 and observed["attempt"] == 1
    assert observed["reviewer"]["model"] == "call-3"
    assert observed["validation"]["status"] == "failed"
    assert observed["validation"]["error"]["code"] == "invalid_review"


@pytest.mark.parametrize("reference", ["asset:invented", "asset:wrongtype"])
def test_binding_failure_cannot_be_overridden_by_model_or_hidden_until_commit(monkeypatch, reference):
    html = HTML.replace("</section>", f'<video src="{reference}"></video></section>')
    h = harness(monkeypatch, [candidate(html)])
    h.story["assets"] = [{"id": "wrongtype", "mime_type": "image/png"}]
    with pytest.raises(StoriesError) as caught:
        h.run()
    assert not caught.value.candidate["review_completed"]
    assert len(h.requests) == 2
    assert not h.rendered


def test_empty_render_is_not_a_review_pass(monkeypatch):
    h = harness(monkeypatch, [candidate()], pages=0)
    with pytest.raises(StoriesError, match="no rendered pages"):
        h.run()
    assert len(h.requests) == 2


def test_document_batches_keep_failed_page_verdict_and_reviewer_identity(monkeypatch):
    doc = document()
    h = harness(
        monkeypatch,
        [
            candidate(document=doc),
            verdict("First pages unsupported"),
            verdict(),
            candidate(document=doc),
            verdict("Still unsupported"),
            verdict(),
        ],
        pages=4,
    )
    h.story["kind"] = "document"
    with pytest.raises(StoriesError) as caught:
        h.run()
    saved = caught.value.candidate
    review = saved["reviews"][-1]
    assert not review["passed"]
    assert review["semantic"]["findings"] == ["Still unsupported"]
    assert review["reviewer"] == {"method": "batch_aggregation", "model_calls": 2}
    assert [r["reviewer"]["model"] for r in review["batches"]] == ["call-6", "call-7"]
    assert review["batches"][0]["semantic"]["status"] == "failed"
    assert review["batches"][1]["semantic"]["status"] == "passed"
    assert [h.requests[i]["payload"]["page_numbers"] for i in (2, 3)] == [[1, 2, 3], [4]]
    assert (
        "Submit document structure"
        in h.requests[2]["payload"]["composition_context"]["composition_instructions"]
    )
    assert saved["document"] == doc
    assert saved["candidates"][0]["document_sha256"] == digest(json.dumps(doc, sort_keys=True))
    assert saved["provenance"]["model_calls"] == 7


def test_document_later_batch_error_keeps_earlier_completed_review(monkeypatch):
    h = harness(
        monkeypatch,
        [candidate(document=document()), verdict("Unsupported"), StoriesError("provider_failed", "Stopped")],
        pages=4,
    )
    h.story["kind"] = "document"
    with pytest.raises(StoriesError) as caught:
        h.run()
    saved = caught.value.candidate
    assert not saved["review_completed"]
    assert not saved["reviews"]
    assert saved["review_batches"][0]["semantic"]["findings"] == ["Unsupported"]
    assert saved["review_batches"][0]["reviewer"]["model"] == "call-3"
    assert len(saved["review_batches"][0]["pages"]) == 3


def test_invalid_document_repair_retains_each_structure_without_claiming_render(monkeypatch):
    first = document()
    first["blocks"][0]["id"] = "unsafe id"
    second = copy.deepcopy(first)
    second["title"] = "Changed but still invalid"
    h = harness(monkeypatch, [candidate(html="", document=first), candidate(html="", document=second)])
    h.story["kind"] = "document"
    with pytest.raises(StoriesError) as caught:
        h.run()
    saved = caught.value.candidate
    assert [c["submission"]["document"] for c in saved["candidates"]] == [first, second]
    assert len(saved["reviews"]) == 2
    assert all(
        r["stage"] == "document_structure" and r["visual"] == "not_performed" for r in saved["reviews"]
    )
    assert not saved["review_completed"]
    assert not h.rendered
    assert len(h.requests) == 3


def test_document_structure_repair_can_succeed_but_only_after_new_render_and_review(monkeypatch):
    first = document()
    first["blocks"][0]["id"] = "unsafe id"
    fixed = document()
    h = harness(monkeypatch, [candidate(html="", document=first), candidate(document=fixed), verdict()])
    h.story["kind"] = "document"
    result = h.run()
    assert result["review_attempts"][0]["stage"] == "document_structure"
    assert not result["review_attempts"][0]["passed"]
    assert result["review_attempts"][0]["candidate"]["submission"]["document"] == first
    assert result["review_attempts"][0]["candidate"]["review_submissions"] == []
    assert result["quality_review"]["passed"]
    assert result["document"] == fixed
    assert result["review_attempts"][1]["candidate"]["submission"]["document"] == fixed
    assert len(h.rendered) == 1
    assert len(h.requests) == 4
    assert (
        h.requests[3]["payload"]["composition_context"]["composition_instructions"]
        == h.requests[2]["instruction"]
    )


def test_public_failed_operation_keeps_serialized_candidates_without_committing(monkeypatch, tmp_path):
    h = harness(
        monkeypatch,
        [
            candidate(),
            verdict("Unsupported"),
            candidate(HTML.replace("Qualified", "Still qualified")),
            verdict("Still unsupported"),
        ],
    )
    api = Stories(tmp_path, model_env=True, provider="openai")
    imported = api.create_story("Trial", HTML, "import")
    api.grant_feedback(imported["story_id"], {"max_operations": 1}, "grant")
    receipt = api.add_comment(imported["story_id"], imported["revision_id"], "Qualify the claim", "comment")
    result = api.run_operation(receipt["operation_id"])
    assert result["state"] == "failed"
    assert result["error"]["code"] == "quality_review_failed"
    saved = api.get_operation(receipt["operation_id"])["candidate"]
    assert saved == result["candidate"]
    assert saved["candidates"][0]["submission"]["html"] == HTML
    assert saved["candidates"][0]["artifact_sha256"] == digest(HTML)
    assert saved["provenance"]["model_calls"] == 5
    assert len(api.get_story(imported["story_id"])["revisions"]) == 1
    assert api.run_operation(receipt["operation_id"]) == result
    assert len(h.requests) == 5
    assert not h.queued


@pytest.mark.parametrize("stage", ["evidence", "composition", "document", "review"])
@pytest.mark.parametrize("defect", ["missing", "type", "additional"])
def test_every_stage_schema_is_checked_and_corrected_locally(monkeypatch, stage, defect):
    composed = candidate(document=document()) if stage == "document" else candidate()
    h = harness(monkeypatch, [composed, verdict()])
    if stage == "document":
        h.story["kind"] = "document"
    index = {"evidence": 0, "composition": 1, "document": 1, "review": 2}[stage]
    correct = copy.deepcopy(h.queued[index])
    invalid = copy.deepcopy(correct)
    key = "warnings" if stage == "review" else "limitations"
    if defect == "missing":
        del invalid[key]
    elif defect == "type":
        invalid[key] = "not an array"
    else:
        invalid["invented_pass"] = True
    h.queued[index : index + 1] = [invalid, correct]
    result = h.run()
    assert result["quality_review"]["passed"]
    assert result["provenance"]["model_calls"] == 4
    assert len(h.rendered) == 1
    saved = result["provenance"]["invalid_submissions"]
    assert len(saved) == 1 and saved[0]["submission"] == invalid
    assert saved[0]["call"] == index + 1
    assert h.requests[index + 1]["payload"]["validation_errors"] == saved[0]["validation_errors"]
    assert h.requests[index + 1]["payload"]["invalid_submission"] == invalid
    assert h.requests[index + 1]["schema"] == h.requests[index]["schema"]
    assert result["provenance"]["calls"][index + 1]["schema_correction"] is True
    if stage in {"composition", "document"}:
        assert (
            h.requests[3]["payload"]["composition_context"]["composition_instructions"]
            == h.requests[2]["instruction"]
        )
    if stage == "review":
        assert h.requests[3]["payload"]["request"]["candidate"] == h.requests[2]["payload"]["candidate"]
    assert not h.queued


@pytest.mark.parametrize("stage", ["evidence", "composition", "document", "review"])
def test_schema_correction_exhaustion_retains_invalid_submissions(monkeypatch, stage):
    h = harness(
        monkeypatch, [candidate(document=document()) if stage == "document" else candidate(), verdict()]
    )
    if stage == "document":
        h.story["kind"] = "document"
    index = {"evidence": 0, "composition": 1, "document": 1, "review": 2}[stage]
    invalid = copy.deepcopy(h.queued[index])
    invalid["unexpected"] = "must not be accepted"
    h.queued[index : index + 1] = [invalid, invalid]
    with pytest.raises(StoriesError) as caught:
        h.run()
    assert caught.value.code == "invalid_model_result"
    saved = caught.value.candidate
    assert [r["submission"] for r in saved["invalid_submissions"]] == [invalid, invalid]
    assert saved["review_completed"] is False
    assert len(h.requests) == index + 2
    assert saved["provenance"]["model_calls"] == index + 2
    assert len(h.rendered) == (1 if stage == "review" else 0)


def test_non_object_json_is_corrected_and_original_response_retained(monkeypatch):
    h = harness(monkeypatch, [[], candidate(), verdict()])
    result = h.run()
    assert result["quality_review"]["passed"]
    assert result["provenance"]["invalid_submissions"][0]["submission"] == "[]"
    assert result["provenance"]["model_calls"] == 4


def test_schema_correction_consumes_allowance_never_skips_final_quality_review(monkeypatch):
    invalid = candidate()
    del invalid["limitations"]
    fixed = HTML.replace("Qualified", "Revised")
    h = harness(monkeypatch, [invalid, candidate(), verdict("Unsupported"), candidate(fixed)])
    with pytest.raises(StoriesError) as caught:
        h.run()
    assert caught.value.code == "execution_limit"
    saved = caught.value.candidate
    assert saved["provenance"]["model_calls"] == 5
    assert len(h.requests) == 5
    assert saved["html"] == fixed
    assert not saved["review_completed"]
    assert len(saved["reviews"]) == 1 and not saved["reviews"][0]["passed"]
    assert saved["invalid_submissions"][0]["submission"] == invalid
    assert len(saved["candidates"]) == 2 and len(h.rendered) == 2
    assert not h.queued


def test_invalid_final_review_cannot_get_sixth_call_or_inherit_old_pass(monkeypatch):
    invalid = verdict()
    del invalid["warnings"]
    h = harness(monkeypatch, [candidate(), verdict("Unsupported"), candidate(), invalid])
    with pytest.raises(StoriesError) as caught:
        h.run()
    assert caught.value.code == "execution_limit"
    saved = caught.value.candidate
    assert not saved["review_completed"]
    assert saved["invalid_submissions"][-1]["stage"] == "review"
    assert saved["invalid_submissions"][-1]["call"] == 5
    assert len(saved["reviews"]) == 1 and len(h.requests) == 5


def test_document_correction_and_batches_share_eleven_call_allowance(monkeypatch):
    invalid = candidate(document=document())
    del invalid["document"]["blocks"][0]["marks"]
    h = harness(
        monkeypatch,
        [
            invalid,
            candidate(document=document()),
            verdict("Unsupported"),
            verdict(),
            verdict(),
            verdict(),
            candidate(document=document()),
            verdict(),
            verdict(),
            verdict(),
        ],
        pages=12,
    )
    h.story["kind"] = "document"
    with pytest.raises(StoriesError) as caught:
        h.run()
    assert caught.value.code == "execution_limit"
    saved = caught.value.candidate
    assert len(h.requests) == saved["provenance"]["model_calls"] == 11
    assert not saved["review_completed"]
    assert len(saved["review_batches"]) == 3
    assert len(saved["reviews"]) == 1 and not saved["reviews"][0]["passed"]
    assert not h.queued


def test_schema_invalid_repair_is_retained_and_cannot_become_committed_artifact(monkeypatch, tmp_path):
    invalid = candidate()
    invalid["action"] = "answer"  # Legal in comment composition, illegal in REPAIR.
    h = harness(monkeypatch, [candidate(), verdict("Unsupported"), invalid, invalid])
    api = Stories(tmp_path, model_env=True, provider="openai")
    imported = api.create_story("Trial", HTML, "import")
    api.grant_feedback(imported["story_id"], {"max_operations": 1}, "grant")
    receipt = api.add_comment(imported["story_id"], imported["revision_id"], "Revise", "comment")
    outcome = api.run_operation(receipt["operation_id"])
    assert outcome["state"] == "failed" and outcome["error"]["code"] == "invalid_model_result"
    saved = outcome["candidate"]
    assert [i["stage"] for i in saved["invalid_submissions"]] == ["repair", "repair"]
    assert saved["reviews"][0]["passed"] is False
    assert saved["candidates"][0]["submission"]["html"] == HTML
    assert len(api.get_story(imported["story_id"])["revisions"]) == 1
    assert api.get_operation(receipt["operation_id"]) == outcome
    assert api.run_operation(receipt["operation_id"]) == outcome
    assert len(h.requests) == 5


@pytest.mark.parametrize("cause", ["cancelled", "execution_timeout"])
def test_watchdog_retains_current_candidate_after_settling_owned_task(monkeypatch, cause):
    h = harness(monkeypatch, [candidate()])
    stopped = []

    async def blocked_render(html, timeout, media=None):
        h.rendered.append(html)
        if cause == "execution_timeout":
            h.operation["deadline"] = time.time() - 1
        try:
            await asyncio.Event().wait()
        finally:
            stopped.append(True)

    monkeypatch.setattr(intelligence, "render", blocked_render)
    with pytest.raises(StoriesError) as caught:
        intelligence.execute(
            h.story,
            h.operation,
            lambda: cause == "cancelled" and bool(h.rendered),
        )
    assert caught.value.code == cause
    assert stopped == [True]
    saved = caught.value.candidate
    assert saved["html"] == HTML
    assert saved["candidates"][0]["artifact_sha256"] == digest(HTML)
    assert not saved["reviews"] and not saved["review_completed"]
    assert len(h.requests) == 2


def test_expired_deadline_never_admits_schema_correction(monkeypatch):
    invalid = candidate()
    del invalid["limitations"]
    h = harness(monkeypatch, [invalid])
    original = intelligence.complete

    async def expire_after_invalid(*args, **kwargs):
        response = await original(*args, **kwargs)
        if len(h.requests) == 2:
            h.operation["deadline"] = time.time() - 1
        return response

    monkeypatch.setattr(intelligence, "complete", expire_after_invalid)
    with pytest.raises(StoriesError) as caught:
        h.run()
    assert caught.value.code == "execution_timeout"
    assert caught.value.candidate["invalid_submissions"][0]["submission"] == invalid
    assert len(h.requests) == 2


def test_schema_valid_invented_evidence_still_fails_reference_validation(monkeypatch):
    h = harness(monkeypatch, [])
    h.queued[0]["evidence"] = [{"id": "fact1", "excerpt_id": "invented", "claim": "Unobserved result"}]
    with pytest.raises(StoriesError) as caught:
        h.run()
    assert caught.value.code == "invalid_model_result"
    assert "unavailable excerpt" in str(caught.value)
    assert not caught.value.candidate["invalid_submissions"]
    assert len(h.requests) == 1
    assert not h.rendered


@pytest.mark.parametrize("kind", ["presentation", "document"])
def test_public_successful_repair_retains_exact_attempt_ledger(monkeypatch, tmp_path, kind):
    from amplifier_smart_tool_stories.documents import render_document

    first_doc, fixed_doc = document(), document("Repaired finding")
    first_html = render_document(first_doc) if kind == "document" else HTML
    fixed_html = render_document(fixed_doc) if kind == "document" else HTML.replace("Qualified", "Repaired")
    first = candidate(document=first_doc) if kind == "document" else candidate(first_html)
    fixed = candidate(document=fixed_doc) if kind == "document" else candidate(fixed_html)
    h = harness(monkeypatch, [first, verdict("Unsupported"), fixed, verdict()])
    api = Stories(tmp_path, model_env=True, provider="openai")
    imported = api.create_story(
        "Trial", first_html, "import", **({"document": first_doc} if kind == "document" else {})
    )
    api.grant_feedback(imported["story_id"], {"max_operations": 1}, "grant")
    receipt = api.add_comment(imported["story_id"], imported["revision_id"], "Revise", "comment")
    outcome = api.run_operation(receipt["operation_id"])
    assert outcome["state"] == "succeeded", outcome
    # A fresh library caller must get identical evidence without provider access.
    saved = Stories(tmp_path).get_operation(receipt["operation_id"])
    assert saved == outcome
    attempts = saved["result"]["review_attempts"]
    assert len(attempts) == 2
    assert [attempt["passed"] for attempt in attempts] == [False, True]
    assert [attempt["candidate"]["submission"]["html"] for attempt in attempts] == [first_html, fixed_html]
    assert [attempt["candidate"]["composition_call"] for attempt in attempts] == [2, 4]
    for index, (attempt, html) in enumerate(zip(attempts, [first_html, fixed_html])):
        snapshot = attempt["candidate"]
        assert snapshot["artifact_sha256"] == attempt["artifact_sha256"] == digest(html)
        observed = snapshot["review_submissions"][0]
        assert observed["artifact_sha256"] == digest(html)
        assert observed["pages"] == attempt["pages"]
        assert observed["call"] == (3 if index == 0 else 5)
        assert observed["verdict"] == verdict("Unsupported" if index == 0 else None)
        assert observed["validation"] == {"status": "passed"}  # Valid verdict, not artifact approval.
        if kind == "document":
            expected = first_doc if index == 0 else fixed_doc
            assert snapshot["submission"]["document"] == expected
            assert snapshot["document_sha256"] == digest(json.dumps(expected, sort_keys=True))
    revision = api.get_revision(imported["story_id"], saved["result"]["revision_id"])
    assert revision["html"] == fixed_html
    assert revision["quality_review"]["artifact_sha256"] == digest(fixed_html)
    with pytest.raises(StoriesError, match="does not match"):
        validate_record(first_html, revision["quality_review"])
    assert len(api.get_story(imported["story_id"])["revisions"]) == 2
    assert saved["result"]["provenance"]["model_calls"] == 5
    assert api.run_operation(receipt["operation_id"]) == saved
    assert len(h.requests) == 5 and not h.queued


@pytest.mark.parametrize("section", ["semantic", "visual"])
def test_public_invalid_review_retains_raw_verdict_and_validation_failure(monkeypatch, tmp_path, section):
    invalid = verdict()
    invalid[section]["findings"] = ["EXACT_BLOCKING_FINDING_SENTINEL"]
    h = harness(monkeypatch, [candidate(), invalid])
    api = Stories(tmp_path, model_env=True, provider="openai")
    imported = api.create_story("Trial", HTML, "import")
    api.grant_feedback(imported["story_id"], {"max_operations": 1}, "grant")
    receipt = api.add_comment(imported["story_id"], imported["revision_id"], "Revise", "comment")
    outcome = api.run_operation(receipt["operation_id"])
    assert outcome["state"] == "failed" and outcome["error"]["code"] == "invalid_review"
    saved = Stories(tmp_path).get_operation(receipt["operation_id"])["candidate"]
    observed = saved["candidates"][0]["review_submissions"][0]
    assert observed["verdict"] == invalid
    assert observed["artifact_sha256"] == digest(HTML)
    assert observed["pages"] == [digest(f"{HTML}-0")]
    assert observed["page_batch"] == observed["attempt"] == 1
    assert observed["call"] == 3
    assert observed["reviewer"] == saved["provenance"]["calls"][2]
    assert observed["validation"]["status"] == "failed"
    assert observed["validation"]["error"]["code"] == "invalid_review"
    assert "Blocking findings cannot pass" in observed["validation"]["error"]["message"]
    assert not saved["review_completed"] and not saved["reviews"] and not saved["review_batches"]
    assert not saved["invalid_submissions"]  # Schema-valid; semantic consistency failed separately.
    assert len(api.get_story(imported["story_id"])["revisions"]) == 1
    assert api.run_operation(receipt["operation_id"]) == outcome
    assert len(h.requests) == 3 and not h.queued
