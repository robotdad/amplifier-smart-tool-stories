"""Storyboard planning, composition and review inside the existing bounded Agent session."""

import copy
import time
from importlib.resources import files

from .accountability import disclosure_hash, validate_disclosures
from .artifacts import revision_evidence, selected_evidence, source_excerpts
from .errors import StoriesError, require
from .quality import record, render
from .storyboards import BOARD, BRIEF, checked_brief, render_storyboard
from .submissions import CALCULATIONS, CHANGES, EVIDENCE, REVIEW, SECTION, TEXT, TEXTS, obj

STORYBOARD_EVIDENCE = copy.deepcopy(EVIDENCE)
STORYBOARD_EVIDENCE["properties"]["evidence"]["maxItems"] = 12

CANDIDATE = obj({"storyboard": BOARD, "changes": CHANGES, "calculations": CALCULATIONS, "limitations": TEXTS})
RESULT = obj(
    {
        "action": {"type": "string", "enum": ["revise", "answer", "clarify"]},
        "message": TEXT,
        "brief": BRIEF,
        "candidates": {"type": "array", "items": CANDIDATE, "maxItems": 2},
    }
)


def narration_metrics(board):
    """Supply measured text counts, not model-estimated timings or audio duration."""
    counts = [len(panel["narration"].split()) for panel in board["panels"]]
    total = sum(counts)
    return {
        "method": "whitespace-delimited narration words; planning estimate, not measured audio",
        "panel_word_counts": counts,
        "total_words": total,
        "spoken_seconds_at_150_wpm": round(total * 60 / 150, 1),
        "spoken_seconds_at_120_wpm": round(total * 60 / 120, 1),
        "note": "These estimates exclude pauses, visual holds and reading on-screen text; do not add them to the brief as source facts.",
    }


async def compose(story, operation, ask, calls):
    prompt = files("amplifier_smart_tool_stories").joinpath("resources/storyboarding.md").read_text()
    catalog, excerpts = source_excerpts(story["sources"])
    base = next((r for r in story["revisions"] if r["id"] == operation["revision_id"]), None)
    brief = next(b for b in story["briefs"] if b["id"] == story["brief_id"])
    note = next((n for n in story["annotations"] if n["id"] == operation["annotation_id"]), None)
    count = operation.get("direction_count", 1)
    assets = base.get("assets", []) if base else story["assets"]
    payload = {
        "title": story["title"],
        "audience": story["audience"],
        "brief": brief,
        "fidelity": story["fidelity"],
        "requested_direction_count": count,
        "base": base,
        "comment": note,
        "assets": assets,
        "continuation": operation.get("continuation", []),
        "related_comments": [
            n
            for n in story["annotations"]
            if note and n["revision_id"] == note["revision_id"] and n["anchor"] == note["anchor"]
        ],
    }
    extracted = await ask(
        prompt
        + "\nExtract evidence before factual composition. Select at most 12 evidence references, using only supplied excerpt IDs; "
        "return empty evidence if no factual sources. Select general expertise and plan an audience-appropriate sequence.",
        {**payload, "sources": catalog},
        schema=STORYBOARD_EVIDENCE,
    )
    evidence = selected_evidence(extracted.get("evidence", []), excerpts, story["sources"])
    if base:
        evidence = revision_evidence(base.get("evidence", []), evidence)
    payload.update(
        evidence=evidence, plan=extracted.get("plan"), limitations=extracted.get("limitations", [])
    )
    result_schema = copy.deepcopy(RESULT)
    result_schema["properties"]["candidates"]["maxItems"] = count
    if operation["kind"] == "generate":
        result_schema["properties"]["action"]["enum"] = ["revise", "clarify"]
    result = await ask(
        prompt
        + "\nSubmit candidates only for revise; answers and focused questions use an empty candidates array. "
        "Generation must revise or clarify. Refinement returns one candidate containing the entire storyboard, "
        "not one candidate per panel. Include change disclosures and calculations.",
        payload,
        schema=result_schema,
    )
    checked_brief(result.get("brief"))
    require(
        (result["action"] == "revise" and 0 < len(result["candidates"]) <= count)
        or (result["action"] in {"answer", "clarify"} and not result["candidates"]),
        "Revise must supply the requested whole storyboards; answer/clarify must have no candidates.",
        "invalid_model_result",
    )
    attempts, completed, failures = [], [], []
    if result.get("action") == "revise":
        for index, candidate in enumerate(result["candidates"]):
            reviews = []
            try:
                for attempt in range(2):
                    candidate.update(action="revise", evidence=evidence)
                    try:
                        validate_disclosures(candidate, story, operation)
                        candidate["html"] = render_storyboard(
                            candidate.get("storyboard"), evidence, assets, story["fidelity"]
                        )
                        rendered = await render(
                            candidate["html"],
                            operation["deadline"] - time.time(),
                            media=story.get("_media_images"),
                        )
                        verdict = await ask(
                            prompt + "\nReview the actual storyboard sheets and sources. "
                            "Fail unsupported claims, lost qualifiers, unclear sequencing, unreadable layout, "
                            "and edits outside the requested scope. Planned imagery is valid at outline/mixed fidelity. "
                            "A static review does not establish audience understanding or produced video. "
                            "Findings are BLOCKING defects only: a passed section MUST have an empty findings array. "
                            "Put nonblocking caveats in warnings; omit positive observations. "
                            "Use the supplied computed narration_metrics, not an estimated word count. "
                            "Compare spoken time plus visual holds against the requested runtime. "
                            "You are reviewing one candidate; the sibling direction is checked separately.",
                            {
                                "request": payload,
                                "candidate": candidate,
                                "sources": story["sources"],
                                "rendered_text": rendered["rendered_text"],
                                "findings": rendered["findings"],
                                "narration_metrics": narration_metrics(candidate["storyboard"]),
                            },
                            rendered["images"],
                            schema=REVIEW,
                        )
                        review = record(candidate["html"], rendered, verdict, calls[-1])
                    except StoriesError as exc:
                        if exc.code in {
                            "cancelled",
                            "execution_timeout",
                            "execution_limit",
                            "markup_resource_limit",
                            "render_resource_limit",
                            "render_timeout",
                        }:
                            raise
                        review = {"passed": False, "error": exc.public()["error"]}
                    reviews.append(review)
                    if review["passed"]:
                        review["disclosure_sha256"] = disclosure_hash(candidate)
                        review["narration_metrics"] = narration_metrics(candidate["storyboard"])
                        candidate["quality_review"] = review
                        completed.append(candidate)
                        break
                    if attempt == 1:
                        raise StoriesError(
                            "quality_review_failed", "Storyboard still has findings after one repair."
                        )
                    candidate = await ask(
                        prompt
                        + "\nRepair this candidate using the findings. Keep its direction and panel IDs. "
                        "You control content, not the renderer or CSS. For overflow, shorten redundant copy "
                        "and requirements; never claim to move renderer-owned blocks.",
                        {"request": payload, "candidate": candidate, "review": review},
                        schema=CANDIDATE,
                    )
            except StoriesError as exc:
                if exc.code == "cancelled":
                    raise
                failures.append({"candidate": index + 1, **exc.public()["error"], "submission": candidate})
            attempts.append({"candidate": index + 1, "reviews": reviews})
        if len(completed) == 2:
            try:
                diversity = await ask(
                    "Judge whether these are substantively different narrative/visual approaches to the same brief. "
                    "Different styles, labels or feature slices alone fail. This is a model judgment, not human proof.",
                    {"brief": brief, "candidates": [c["storyboard"] for c in completed]},
                    schema=SECTION,
                )
                attempts.append({"comparison": diversity, "reviewer": calls[-1]})
                require(
                    diversity.get("status") == "passed",
                    "Alternative directions are not substantively distinct.",
                    "comparison_review_failed",
                )
            except StoriesError as exc:
                if exc.code == "cancelled":
                    raise
                failures.append({"candidate": 2, **exc.public()["error"], "submission": completed.pop()})
        if len(completed) < count and not failures:
            failures.append({"code": "incomplete_comparison", "message": "Missing requested direction."})
        result.update(candidates=completed, failures=failures)
    result["review_attempts"] = attempts
    result["provenance"] = {
        "runtime": "amplifier-core+foundation",
        "calls": calls,
        "model_calls": len(calls),
        "plan": extracted.get("plan"),
        "expertise": ["shared-storyboarding"],
    }
    return result
