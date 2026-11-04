import asyncio
import copy

import pytest

from amplifier_smart_tool_stories import StoriesError
from amplifier_smart_tool_stories.quality import record, render, validate_record

HTML = '<html><body><section class="slide"><h1 style="font-size:48px">A qualified result</h1></section></body></html>'


def test_rendered_pages_are_identifiable_and_content_is_present():
    result = asyncio.run(render(HTML, 30))
    assert result["page_count"] == 1 and not result["findings"]
    assert "A qualified result" in result["rendered_text"]
    assert len(result["images"][0]["sha256"]) == 64
    assert len(result["images"][0]["data"]) > 100


def test_renderer_blocks_resource_fetches_and_detects_overflow():
    html = HTML.replace(
        "<html>",
        '<html><head><style>@import url("https://example.invalid/a.css");'
        "h1 {position:absolute;left:1400px}</style></head>",
    )
    result = asyncio.run(render(html, 30))
    assert any("blocked external" in issue for issue in result["findings"])
    assert any("outside the canvas" in issue for issue in result["findings"])


def test_renderer_rejects_page_count_beyond_allowance():
    html = "<html><body>" + '<section class="slide"><h1>One</h1></section>' * 13 + "</body></html>"
    with pytest.raises(StoriesError, match="12 slides"):
        asyncio.run(render(html, 30))


def checked():
    return record(
        HTML,
        {"images": [{"sha256": "a" * 64}], "findings": []},
        {"semantic": {"status": "passed", "findings": []}, "visual": {"status": "passed", "findings": []}},
        {"provider": "test"},
    )


def test_review_is_bound_to_exact_artifact():
    review = checked()
    assert validate_record(HTML, review) is review
    with pytest.raises(StoriesError) as exc:
        validate_record(HTML.replace("qualified", "unqualified"), review)
    assert exc.value.code == "stale_review"


def test_model_cannot_override_mechanical_findings():
    review = record(
        HTML,
        {"images": [{"sha256": "a" * 64}], "findings": ["Text clipped"]},
        {"semantic": {"status": "passed", "findings": []}, "visual": {"status": "passed", "findings": []}},
        {},
    )
    assert not review["passed"]
    with pytest.raises(StoriesError):
        validate_record(HTML, review)


def test_review_cannot_pass_with_findings_or_missing_images():
    review = checked()
    review["semantic"]["findings"] = ["Unsupported metric"]
    with pytest.raises(StoriesError):
        validate_record(HTML, review)
    review = checked()
    review["pages"] = []
    with pytest.raises(StoriesError):
        validate_record(HTML, review)


def test_runtime_repairs_once_and_reviews_new_artifact(monkeypatch):
    from types import SimpleNamespace

    from amplifier_smart_tool_stories import intelligence

    class Session:
        coordinator = SimpleNamespace(get=lambda _: {"test": object()})

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    async def session():
        return Session()

    async def prepared(config):
        return SimpleNamespace(create_session=session)

    revised = HTML.replace("qualified", "bounded")
    answers = [
        {"evidence": [], "plan": "Be precise", "expertise": ["case-study"], "limitations": []},
        {
            "changes": {
                "summary": "Requested change",
                "material_changes": [],
                "omissions": [],
                "assumptions": [],
            },
            "calculations": [],
            "action": "revise",
            "html": HTML,
            "message": "Draft",
            "limitations": [],
        },
        {
            "semantic": {"status": "failed", "findings": ["Qualify result"]},
            "visual": {"status": "passed", "findings": []},
            "warnings": [],
        },
        {
            "changes": {
                "summary": "Requested change",
                "material_changes": [],
                "omissions": [],
                "assumptions": [],
            },
            "calculations": [],
            "action": "revise",
            "html": revised,
            "message": "Revised",
            "limitations": [],
        },
        {
            "semantic": {"status": "passed", "findings": []},
            "visual": {"status": "passed", "findings": []},
            "warnings": [],
        },
    ]
    payloads, rendered = [], []

    async def complete(provider, config, messages, *args, **kwargs):
        import json

        payloads.append(messages)
        answer = answers.pop(0)
        if "action" in answer:
            answer.setdefault(
                "changes",
                {"summary": "Requested revision", "material_changes": [], "omissions": [], "assumptions": []},
            )
            answer.setdefault("calculations", [])
        return json.dumps(answer), {"provider": "test"}

    async def render_stub(html, timeout, media=None):
        rendered.append(html)
        return {"images": [{"sha256": "a" * 64, "data": "png"}], "findings": [], "rendered_text": "Result"}

    monkeypatch.setattr(intelligence, "prepared", prepared)
    monkeypatch.setattr(intelligence, "complete", complete)
    monkeypatch.setattr(intelligence, "render", render_stub)
    import time

    story = {
        "sources": [],
        "purpose": "Explain",
        "audience": "Reader",
        "title": "Test",
        "revisions": [],
        "annotations": [
            {
                "id": "note",
                "text": "Turn this into a case study.",
                "revision_id": None,
                "anchor": {"kind": "story"},
            }
        ],
    }
    operation = {
        "provider": {"provider": "openai"},
        "revision_id": None,
        "annotation_id": "note",
        "deadline": time.time() + 30,
        "grant": {"max_output_tokens": 1000},
    }
    result = intelligence.execute(story, operation, lambda: False)
    assert rendered == [HTML, revised]
    assert result["provenance"]["model_calls"] == 5
    assert len(result["review_attempts"]) == 2
    assert validate_record(revised, result["quality_review"])
    assert "Turn this into a case study." in payloads[0][1]["content"]
    assert payloads[2][1]["content"][1]["type"] == "image"
    assert result["provenance"]["expertise"][0]["id"] == "case-study"
    for index in (1, 2, 3, 4):
        assert "Case study and feature journey guidance:" in payloads[index][0]["content"]
        assert "Community spotlight and digest guidance:" not in payloads[index][0]["content"]

    # Persistent failure cannot trigger a second repair or produce an accepted artifact.
    answers.extend(
        [
            {"evidence": [], "expertise": ["general"], "plan": "Be precise", "limitations": []},
            {
                "changes": {
                    "summary": "Requested change",
                    "material_changes": [],
                    "omissions": [],
                    "assumptions": [],
                },
                "calculations": [],
                "action": "revise",
                "html": HTML,
                "message": "Draft",
                "limitations": [],
            },
            {
                "semantic": {"status": "failed", "findings": ["Unsupported"]},
                "visual": {"status": "passed", "findings": []},
                "warnings": [],
            },
            {
                "changes": {
                    "summary": "Requested change",
                    "material_changes": [],
                    "omissions": [],
                    "assumptions": [],
                },
                "calculations": [],
                "action": "revise",
                "html": revised,
                "message": "Repair",
                "limitations": [],
            },
            {
                "semantic": {"status": "failed", "findings": ["Still unsupported"]},
                "visual": {"status": "passed", "findings": []},
                "warnings": [],
            },
        ]
    )
    with pytest.raises(StoriesError) as exc:
        intelligence.execute(copy.deepcopy(story), operation, lambda: False)
    assert exc.value.code == "quality_review_failed"
    assert exc.value.candidate["html"] == revised
    assert len(exc.value.candidate["reviews"]) == 2
    assert not answers


def test_library_rejects_stale_review_without_committing(tmp_path):
    from amplifier_smart_tool_stories import Stories

    def adapter(story, operation):
        return {
            "changes": {
                "summary": "Requested change",
                "material_changes": [],
                "omissions": [],
                "assumptions": [],
            },
            "calculations": [],
            "action": "revise",
            "html": HTML.replace("qualified", "changed"),
            "message": "Updated",
            "quality_review": checked(),
        }

    api = Stories(tmp_path, intelligence=adapter)
    imported = api.create_story("Test", HTML, "import")
    api.grant_feedback(imported["story_id"], {"max_operations": 1}, "grant")
    receipt = api.add_comment(imported["story_id"], imported["revision_id"], "Revise", "comment")
    outcome = api.run_operation(receipt["operation_id"])
    assert outcome["state"] == "failed" and outcome["error"]["code"] == "stale_review"
    assert len(api.get_story(imported["story_id"])["revisions"]) == 1


def test_text_coverage_allows_css_case_transforms_but_detects_hidden_content():
    html = HTML.replace("<h1 ", '<h1 class="caps" ').replace(
        "<body>", "<head><style>.caps{text-transform:uppercase}</style></head><body>"
    )
    result = asyncio.run(render(html, 30))
    assert not any("missing" in x for x in result["findings"])
    hidden = html.replace("</section>", '<p style="display:none">Omitted evidence</p></section>')
    result = asyncio.run(render(hidden, 30))
    assert any("missing" in x for x in result["findings"])


def test_excerpt_selection_preserves_exact_markdown_and_rejects_invented_references():
    from amplifier_smart_tool_stories.artifacts import selected_evidence, source_excerpts

    sources = [
        {
            "id": "source",
            "name": "Report",
            "content": "# Report\n\n**Count:** 11  \n**Date:** January 2026\n\n| A | B |\n| 1 | 2 |",
        }
    ]
    catalog, index = source_excerpts(sources)
    key = catalog[0]["excerpts"][1]["excerpt_id"]
    evidence = selected_evidence(
        [{"id": "fact1", "excerpt_id": key, "claim": "Reported 11 in January 2026"}], index, sources
    )
    assert evidence[0]["quote"] == "**Count:** 11  \n**Date:** January 2026"
    assert evidence[0]["quote"] in sources[0]["content"]
    with pytest.raises(StoriesError):
        selected_evidence([{"id": "fact1", "excerpt_id": "made-up", "claim": "Anything"}], index, sources)


def test_renderer_preserves_block_flow_instead_of_forcing_flex():
    html = (
        '<html><body><section class="slide" style="display:block;padding:48px;font-size:24px">'
        + "<h1>Heading</h1><p>First paragraph stays below the heading.</p><p>Second paragraph.</p></section></body></html>"
    )
    result = asyncio.run(render(html, 30))
    assert not result["findings"]
    assert "First paragraph" in result["rendered_text"]
